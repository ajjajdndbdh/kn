#!/usr/bin/env python3
"""INV-REF-04 — **MENGHAPUS DOKUMEN WAJIB MENYAPU TAUTAN BALIKNYA**.

KELAS BUG YANG DICEGAH (terukur 2026-08-21, bukan dugaan)
=========================================================
`doc_refs_service.link()` menulis relasi **DUA ARAH** — itu keputusan yang benar
(jejak bisa dibaca dari dokumen mana pun). Tetapi ia melahirkan kewajiban yang
tidak pernah ditulis di mana pun: **siapa pun yang MENGHAPUS dokumen wajib
menyapu ref yang menunjuk dokumen itu.** Kalau tidak, dokumen yang MASIH HIDUP
memegang tautan ke dokumen yang sudah tidak ada, dan layar "Relasi Dokumen"
dengan tenang menawarkan tautan yang menuju 404.

Ditemukan begini: POC FASE E-7 hijau 58/58, `verify_data_integrity` 237/0/0 —
tetapi `audit_doc_refs --strict` MERAH:

    internal_request KSC/PIN-00003 --fulfilled_by--> interco_transaction KSC/IC-00007
    internal_request KSC/PIN-00003 --fulfilled_by--> interco_transaction KANDA/IC-00007

Kedua targetnya dihapus oleh pembersih POC; permintaannya tertinggal. Dan bukan
cuma POC — audit yang sama menemukan **empat jalur PRODUKSI** dengan lubang
identik: amandemen PO menghapus inbound `wms_tasks` (doc_type `grn`) yang sudah
bertaut ke PO-nya; hapus retur beli draf; hapus kontrak supplier; rollback
transfer antar-gudang saat SO gagal di tengah jalan.

Kenapa penjaga ini STATIK dan bukan runtime: tautan hantu di basis data memang
sudah dijaga runtime (`audit_doc_refs --strict` §C dan `gate_residue --check`),
tetapi keduanya hanya berteriak SESUDAH kerusakan terjadi — dan hanya kalau data
demo kebetulan melewati jalur itu. Penjaga ini menutup **sumbernya**: jalur
penghapusan baru tidak bisa lahir tanpa sapuan, bahkan bila tidak ada satu pun
dokumen demo yang melewatinya.

APA YANG DIPERIKSA
------------------
S1. Setiap pemanggilan `db.<koleksi>.delete_one/delete_many` (atau
    `db[KONSTANTA].delete_*`) di kode PRODUKSI backend, yang koleksinya
    **ber-refs** (terdaftar di `doc_refs_service.DOC_TYPES`), WAJIB berada di
    fungsi yang juga memanggil `unlink_all(` / `safe_unlink_all(`.
S2. Nama koleksi wajib bisa DIPASTIKAN secara statik (literal, atau konstanta
    modul — termasuk lintas-modul seperti `db[cs.COLL]`). Yang tidak bisa
    dipastikan harus terdaftar eksplisit di `DYNAMIC_OK` beserta alasannya,
    supaya "tidak bisa dibaca mesin" tidak menjadi tempat sembunyi.
S3. `doc_refs_service` sendiri WAJIB menyediakan `unlink_all` **dan**
    `safe_unlink_all` — penjaga yang menuntut pemakaian fungsi yang tidak ada
    hanya akan membuat orang mematikan penjaganya.

Sumber kebenaran koleksi: `backend/services/doc_refs_service.py::DOC_TYPES`.
Menambah jenis dokumen di registry otomatis memperluas jangkauan penjaga ini.

Usage:
    python scripts/guardrails/verify_ref_unlink.py
    python scripts/guardrails/verify_ref_unlink.py -v
    python scripts/guardrails/verify_ref_unlink.py --self-test   # bukti-merah dua arah
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parents[2]
BE = ROOT / "backend"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import B, C, G, R, X, Y, Guard  # noqa: E402

#: Token yang membuktikan sapuan tautan dilakukan.
UNLINK_TOKENS = ("unlink_all", "safe_unlink_all")

#: Berkas yang BUKAN kode produksi (uji/seed/skrip sekali pakai).
SKIP_PARTS = ("__pycache__", "/tests/", "test_", "backend_test", "_smoke", "seed_",
              "_fase_t_snapshot", "/scripts/")

#: Koleksi yang namanya tidak bisa dipastikan statik — WAJIB berikut alasannya.
#: Bukan pembebasan buta: tiap baris menyatakan kenapa koleksinya mustahil ber-refs.
DYNAMIC_OK: Dict[str, str] = {
    "poc_stock_guard.py":
        "restore STOK: `db[c]` berputar pada inventory_rolls/lots/balances/movements — "
        "koleksi kuantitas, bukan dokumen bernomor, jadi tidak pernah ber-`refs`.",
    "services/entity_master_service.py":
        "`db[s.collection]` = koleksi MASTER dari registry (produk, kategori, UOM, warna). "
        "Master data bukan surat; tidak ada doc_type yang menautnya lewat `refs`.",
}

#: Pembebasan per (berkas, koleksi) — kosong itu bagus. Isi HANYA dengan alasan
#: yang bisa dibaca orang lain, bukan "sudah dicek manual".
EXEMPT: Dict[str, str] = {}


# ── util AST ────────────────────────────────────────────────────────────────
def _module_str_consts(tree: ast.AST) -> Dict[str, str]:
    """Konstanta modul bernilai string (`COLL = "purchase_returns"`)."""
    out: Dict[str, str] = {}
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node.value.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str) and isinstance(node.target, ast.Name):
            out[node.target.id] = node.value.value
    return out


def _import_aliases(tree: ast.AST) -> Dict[str, str]:
    """alias → modul backend, mis. `cs` → `services.contract_service`."""
    out: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for a in node.names:
                out[a.asname or a.name] = f"{node.module}.{a.name}"
        elif isinstance(node, ast.Import):
            for a in node.names:
                out[a.asname or a.name] = a.name
    return out


_XMOD_CACHE: Dict[str, Dict[str, str]] = {}


def _consts_of_module(dotted: str) -> Dict[str, str]:
    """Konstanta string modul backend lain (untuk `db[cs.COLL]`)."""
    if dotted in _XMOD_CACHE:
        return _XMOD_CACHE[dotted]
    path = BE / (dotted.replace(".", "/") + ".py")
    consts: Dict[str, str] = {}
    if path.exists():
        try:
            consts = _module_str_consts(ast.parse(path.read_text(encoding="utf-8")))
        except SyntaxError:
            consts = {}
    _XMOD_CACHE[dotted] = consts
    return consts


def _resolve_collection(node: ast.AST, consts: Dict[str, str],
                        aliases: Dict[str, str]) -> Tuple[Optional[str], str]:
    """`db.foo` / `db["foo"]` / `db[COLL]` / `db[cs.COLL]` → nama koleksi.

    Return `(nama, teks_asal)`; `nama=None` berarti tidak bisa dipastikan statik.
    """
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
            and node.value.id == "db":
        return node.attr, f"db.{node.attr}"
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) \
            and node.value.id == "db":
        key = node.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            return key.value, f'db["{key.value}"]'
        if isinstance(key, ast.Name):
            return consts.get(key.id), f"db[{key.id}]"
        if isinstance(key, ast.Attribute) and isinstance(key.value, ast.Name):
            dotted = aliases.get(key.value.id)
            txt = f"db[{key.value.id}.{key.attr}]"
            if dotted:
                return _consts_of_module(dotted).get(key.attr), txt
            return None, txt
    return "", ""  # bukan operasi pada `db` sama sekali


def _has_unlink(fn: ast.AST) -> bool:
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
            if name in UNLINK_TOKENS:
                return True
    return False


def scan_source(label: str, src: str, ref_colls: Set[str],
                verbose: bool = False) -> List[str]:
    """Kembalikan daftar pelanggaran INV-REF-04 pada satu berkas."""
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return [f"{label}: tidak bisa di-parse ({exc})"]
    consts = _module_str_consts(tree)
    aliases = _import_aliases(tree)

    # peta anak → induk supaya bisa mencari fungsi pembungkus
    parent: Dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[id(child)] = node

    def enclosing_functions(node: ast.AST) -> List[ast.AST]:
        out, cur = [], parent.get(id(node))
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append(cur)
            cur = parent.get(id(cur))
        return out

    bad: List[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("delete_one", "delete_many")):
            continue
        coll, txt = _resolve_collection(node.func.value, consts, aliases)
        if coll == "":
            continue                      # bukan `db.*`
        if coll is None:
            if label in DYNAMIC_OK:
                continue
            bad.append(f"{label}:{node.lineno} — koleksi `{txt}` tidak bisa dipastikan "
                       f"statik; pakai nama literal/konstanta modul, atau daftarkan di "
                       f"DYNAMIC_OK beserta alasannya (S2)")
            continue
        if coll not in ref_colls:
            continue                      # koleksi tanpa `refs` — tidak dijaga
        if EXEMPT.get(f"{label}:{coll}"):
            continue
        fns = enclosing_functions(node)
        if any(_has_unlink(f) for f in fns):
            if verbose:
                print(f"  {G}·{X} {label}:{node.lineno} {txt}.{node.func.attr} — sapuan ada")
            continue
        where = fns[0].name if fns else "<tingkat modul>"
        bad.append(f"{label}:{node.lineno} — `{txt}.{node.func.attr}()` menghapus dokumen "
                   f"ber-`refs` ('{coll}') di `{where}()` TANPA memanggil "
                   f"`unlink_all`/`safe_unlink_all` → tautan balik jadi hantu (S1)")
    return bad


def _ref_collections() -> Set[str]:
    sys.path.insert(0, str(BE))
    from services import doc_refs_service as refs  # noqa: PLC0415
    return {m["collection"] for m in refs.DOC_TYPES.values()}


def _service_api_ok(g: Guard) -> None:
    """S3 — fungsi yang dituntut penjaga ini harus benar-benar ada."""
    src = (BE / "services" / "doc_refs_service.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    have = {n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for token in UNLINK_TOKENS:
        g.bump()
        if token not in have:
            g.add(f"services/doc_refs_service.py: `{token}()` TIDAK ADA — penjaga "
                  f"INV-REF-04 menuntut fungsi yang tidak disediakan (S3)")


def run(verbose: bool = False) -> int:
    g = Guard("INV-REF-04", "menghapus dokumen wajib menyapu tautan baliknya")
    ref_colls = _ref_collections()
    _service_api_ok(g)
    files = 0
    for path in sorted(BE.rglob("*.py")):
        rel = str(path.relative_to(BE))
        if any(p in f"/{rel}" for p in SKIP_PARTS):
            continue
        files += 1
        g.bump()
        for v in scan_source(rel, path.read_text(encoding="utf-8"), ref_colls, verbose):
            g.add(v)
    print(f"{C}  {files} berkas produksi dipindai · {len(ref_colls)} koleksi ber-refs "
          f"dijaga · {len(DYNAMIC_OK)} koleksi dinamis berdasar alasan tertulis{X}")
    return g.finish()


# ── bukti-merah: penjaga wajib bisa memerah DAN wajib tidak menuduh palsu ───
_CASES: List[Tuple[str, str, bool]] = [
    ("hapus retur beli tanpa sapuan",
     "from db import db\nasync def f(i):\n    await db.purchase_returns.delete_one({'id': i})\n",
     True),
    ("hapus retur beli DENGAN sapuan",
     "from db import db\nfrom services import doc_refs_service as r\n"
     "async def f(i):\n    await r.safe_unlink_all('purchase_return', i)\n"
     "    await db.purchase_returns.delete_one({'id': i})\n",
     False),
    ("hapus lewat konstanta modul tanpa sapuan",
     "from db import db\nCOLL = 'sales_returns'\n"
     "async def f(i):\n    await db[COLL].delete_many({'id': i})\n",
     True),
    ("hapus lewat konstanta modul DENGAN sapuan",
     "from db import db\nfrom services import doc_refs_service as r\nCOLL = 'sales_returns'\n"
     "async def f(i):\n    await r.unlink_all('sales_return', i)\n"
     "    await db[COLL].delete_many({'id': i})\n",
     False),
    ("koleksi TANPA refs tidak dituduh (bukti anti-tuduhan palsu)",
     "from db import db\nasync def f():\n    await db.sessions.delete_many({})\n",
     False),
    ("koleksi dinamis tak terdaftar = pelanggaran, bukan celah",
     "from db import db\nasync def f(s, i):\n    await db[s.collection].delete_one({'id': i})\n",
     True),
    ("sapuan di fungsi LAIN tidak dihitung (harus di fungsi yang menghapus)",
     "from db import db\nfrom services import doc_refs_service as r\n"
     "async def sweep(i):\n    await r.unlink_all('vendor_bill', i)\n"
     "async def f(i):\n    await db.vendor_bills.delete_one({'id': i})\n",
     True),
    ("kata 'unlink_all' hanya di KOMENTAR tidak menolong",
     "from db import db\nasync def f(i):\n    # TODO: unlink_all nanti\n"
     "    await db.shipments.delete_one({'id': i})\n",
     True),
]


def self_test() -> int:
    print(f"{C}{B}== SELF-TEST INV-REF-04 — bukti-merah DUA ARAH =={X}")
    ref_colls = _ref_collections()
    fails = 0
    for name, src, should_flag in _CASES:
        got = bool(scan_source("uji_sintetis.py", src, ref_colls))
        ok = got == should_flag
        fails += 0 if ok else 1
        tag = f"{G}OK{X}" if ok else f"{R}SALAH{X}"
        arah = "MEMERAH" if should_flag else "HIJAU"
        print(f"  [{tag}] harus {arah:7s} · {name}"
              + ("" if ok else f"  (dapat: {'MEMERAH' if got else 'HIJAU'})"))
    if fails:
        print(f"\n{R}{B}✗ SELF-TEST GAGAL: {fails} dari {len(_CASES)} kasus salah.{X}")
        return 1
    print(f"\n{G}{B}✓ SELF-TEST HIJAU: {len(_CASES)}/{len(_CASES)} kasus — penjaga "
          f"memerah saat sapuan hilang DAN tidak menuduh saat sapuan ada.{X}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="INV-REF-04 — sapuan tautan sebelum hapus")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--self-test", action="store_true", help="bukti-merah dua arah")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    return run(args.verbose)


if __name__ == "__main__":
    sys.exit(main())
