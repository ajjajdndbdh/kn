#!/usr/bin/env python3
"""INV-ORIG-01 — **ASAL DOKUMEN PO DITULIS DARI SATU DEFINISI** (P-0, prasyarat FASE P).

KELAS BUG YANG DICEGAH (terukur, bukan dugaan)
==============================================
Papan PO (FASE P) memuat kolom **Nama Sales**. Nama itu tidak boleh diketik: ia
dirunut `PO → PR → SO`. Sebelum P-0, keadaannya terukur begini:

    purchase_orders ber-`pr_id`  : 0 dari 14   (DRIFT D3)
    purchase_requisitions.po_ids : 1 dari 5    (satu arah saja)

Artinya kolom "Nama Sales" akan **selamanya kosong** dan tidak ada satu pun galat
yang memberi tahu siapa pun. P-0 menutupnya, tetapi PO di aplikasi ini lahir dari
**EMPAT pintu** — dan justru di situ letak bahaya jangka panjangnya:

    1. `services/pr_sourcing_service.realize_to_po`  — realisasi PR (bisa sebagian)
    2. `services/rfq_service.award_rfq`               — award penawaran
    3. `routers/purchase_orders._create_po_core`      — PO manual & call-off
    4. `services/blanket_po_service`                  — kontrak payung (blanket)

Tiga cara fitur ini membusuk — semuanya **senyap**:

  A. **Pintu ke-5 lahir tanpa asal dokumen.** Seseorang menambah jalur PO baru
     (mis. "PO dari kontrak makloon") dan tidak menulis `pr_id`/`sales_name`.
     Gejalanya bukan galat, melainkan **papan PO yang benar untuk sebagian
     dokumen saja** — kelas kerusakan yang paling sulit dipercaya orang, karena
     "kadang jalan".
  B. **Daftar field disalin, lalu menyimpang.** Tiap pintu menulis sendiri
     `{"pr_id": …, "pr_number": …, "sales_name": …}`. Begitu satu field ditambah
     (mis. `source_so_ids`), pintu yang tertinggal menghasilkan dokumen dengan
     **bentuk berbeda** — dan papan tidak bisa membedakan "tidak ada sales-nya"
     dari "field-nya tidak ada".
  C. **Nama sales DIKETIK/diturunkan dari pembuat PO.** Ini yang paling merusak
     kepercayaan: PO pembelian rutin (stok menipis) tidak punya sales, tetapi
     kolomnya terisi nama admin yang mengetik PO. Papan jadi **berbohong dengan
     tenang**; keputusan MD diambil di atas nama yang salah.

APA YANG DIPERIKSA
------------------
STATIK (tanpa basis data)
  S1. Setiap berkas backend yang MENYISIPKAN dokumen ke `purchase_orders`
      (`db.purchase_orders.insert_one/insert_many`) WAJIB memakai satu definisi
      bersama: `PO_ORIGIN_EMPTY` atau `po_origin_from_pr(`.
  S2. Definisi tunggal itu WAJIB memuat SELURUH field kanonik
      (`pr_id`, `pr_number`, `source`, `source_so_ids`, `sales_user_id`,
      `sales_name`) — dibaca lewat `ast`, bukan regex, supaya tak bisa dikelabui
      komentar.
  S3. TIDAK ADA berkas penulis PO lain yang menulis sendiri kunci `"sales_name"`
      / `"sales_user_id"` / `"source_so_ids"` (sumber KEDUA = tempat aturan mulai
      menyimpang). Satu-satunya berkas yang berhak: `pr_sourcing_service.py`.
  S4. `doc_refs_service.DOC_TYPES["purchase_order"]` WAJIB ber-`source_fk`
      memuat `pr_id`, supaya `INV-REF-01` menjaga tautannya **dan** tidak
      menuduh PO mandiri (manual/blanket) sebagai dokumen yatim.

RUNTIME (Mongo langsung — opini kedua, tidak lewat API yang sedang diuji)
  R1. PO ber-`pr_id` WAJIB punya `pr_number` **dan** PR-nya benar-benar ada.
  R2. PO ber-`source="pr"` WAJIB ber-`pr_id` (dan sebaliknya) — status "berasal
      dari PR" tidak boleh diklaim tanpa jejaknya.
  R3. `sales_name` TIDAK BOLEH terisi tanpa jejak dokumen (`pr_id` kosong) →
      inilah pagar untuk kelas bug (C) di atas.
  R4. Bila PR-nya menunjuk SO (`source="so_repeat"`), `sales_name` PO wajib
      **SAMA** dengan `sales_orders.sales_name` — dihitung ulang di sini secara
      mandiri, sehingga snapshot yang menyimpang tertangkap.
  R5. Tautan `refs` PO→PR wajib **dua arah** (PO ber-`parent`, PR ber-`child`).

KEPUTUSAN PEMILIK YANG DIHORMATI GATE INI (2026-08-21)
------------------------------------------------------
PO lama (sebelum P-0) **DIBIARKAN kosong** — tanpa backfill. Karena itu R1–R5
hanya menuntut dokumen yang MENGAKU punya asal; PO tanpa `pr_id` **tidak**
dituduh apa pun. Gate yang menuntut backfill akan memerah atas keputusan bisnis,
dan gate yang memerah karena kebijakan cepat diabaikan orang.

Resilient: tanpa MONGO_URL / basis data mati → bagian runtime SKIP (exit 0),
bagian statik tetap jalan. Exit 1 hanya bila invarian terbukti dilanggar.

Usage:
    python scripts/guardrails/verify_doc_origin.py
    python scripts/guardrails/verify_doc_origin.py -v
    python scripts/guardrails/verify_doc_origin.py --self-test   # bukti-merah, tanpa DB
"""
from __future__ import annotations

import ast
import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[2]
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env")
except Exception:  # noqa: BLE001
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import B, C, G, R, X, Y, Guard  # noqa: E402

BE = ROOT / "backend"

#: Field kanonik "PO ini asalnya dari mana & siapa sales-nya" (P-0).
CANONICAL_FIELDS = ("pr_id", "pr_number", "source", "source_so_ids",
                    "sales_user_id", "sales_name")

#: Satu-satunya berkas yang berhak MENDEFINISIKAN field di atas.
OWNER_FILE = "services/pr_sourcing_service.py"

#: Nama definisi bersama yang wajib dipakai penulis PO.
SHARED_TOKENS = ("PO_ORIGIN_EMPTY", "po_origin_from_pr")

#: Kunci yang tidak boleh ditulis tangan di berkas penulis PO lain (sumber ke-2).
HAND_WRITTEN_KEYS = ("sales_name", "sales_user_id", "source_so_ids")

INSERT_RE = re.compile(r"db\.purchase_orders\.insert_(?:one|many)\s*\(")

#: Berkas yang BUKAN kode produksi (uji/seed/skrip sekali pakai) — tidak dijaga.
SKIP_PARTS = ("__pycache__", "/tests/", "test_", "backend_test", "_smoke",
              "seed_", "/scripts/")


# ═══════════════════════════════════════════════════════════════════════════
# STATIK
# ═══════════════════════════════════════════════════════════════════════════
def po_writer_files(sources: Dict[str, str]) -> List[str]:
    """Berkas yang benar-benar MENYISIPKAN dokumen PO baru."""
    return sorted(rel for rel, text in sources.items() if INSERT_RE.search(text))


def check_shared_definition(sources: Dict[str, str]) -> List[str]:
    """S1 — penulis PO wajib memakai definisi bersama (bukan daftar field sendiri)."""
    out: List[str] = []
    for rel in po_writer_files(sources):
        text = sources[rel]
        if not any(tok in text for tok in SHARED_TOKENS):
            out.append(
                f"{rel} menyisipkan dokumen `purchase_orders` tetapi TIDAK memakai "
                f"definisi asal dokumen bersama ({' / '.join(SHARED_TOKENS)}). "
                "Papan PO tidak akan bisa membedakan 'tidak ada sales-nya' dari "
                "'field-nya tidak ada'. Tambahkan `**_pr_sourcing.PO_ORIGIN_EMPTY` "
                "(PO tanpa PR) atau `**await po_origin_from_pr(pr)` (PO dari PR).")
    return out


def check_hand_written(sources: Dict[str, str]) -> List[str]:
    """S3 — nol sumber KEDUA untuk field asal dokumen."""
    out: List[str] = []
    for rel in po_writer_files(sources):
        if rel == OWNER_FILE:
            continue
        text = sources[rel]
        for key in HAND_WRITTEN_KEYS:
            # Hanya kunci dict literal (`"sales_name":`) — penyebutan di komentar
            # atau pembacaan (`po.get("sales_name")`) BUKAN pelanggaran.
            if re.search(rf'["\']{key}["\']\s*:', text):
                out.append(
                    f"{rel} menulis sendiri kunci \"{key}\" pada dokumen PO — "
                    f"itu sumber KEDUA. Satu-satunya tempat yang berhak: {OWNER_FILE} "
                    "(`PO_ORIGIN_EMPTY` / `po_origin_from_pr`).")
    return out


def origin_keys(owner_text: str) -> List[str]:
    """S2 — baca kunci `PO_ORIGIN_EMPTY` lewat `ast` (tahan komentar & format)."""
    try:
        tree = ast.parse(owner_text)
    except SyntaxError:
        return []
    for node in ast.walk(tree):
        targets: List[Any] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        names = {t.id for t in targets if isinstance(t, ast.Name)}
        if "PO_ORIGIN_EMPTY" in names and isinstance(value, ast.Dict):
            return [k.value for k in value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)]
    return []


def check_origin_keys(owner_text: str) -> List[str]:
    keys = origin_keys(owner_text)
    if not keys:
        return [f"{OWNER_FILE}: `PO_ORIGIN_EMPTY` tidak ditemukan sebagai dict literal — "
                "definisi tunggal asal dokumen PO hilang/berubah bentuk."]
    missing = [f for f in CANONICAL_FIELDS if f not in keys]
    if missing:
        return [f"{OWNER_FILE}: `PO_ORIGIN_EMPTY` kehilangan field kanonik "
                f"{missing} — dokumen PO baru akan lahir tanpa field itu, dan papan "
                "PO tidak bisa membedakan kosong-wajar dari field yang tidak ada."]
    return []


def check_source_fk(refs_text: str) -> List[str]:
    """S4 — `DOC_TYPES["purchase_order"].source_fk` memuat `pr_id`."""
    m = re.search(r'_T\(\s*"purchase_order"\s*,', refs_text)
    if not m:
        return ['doc_refs_service: entri `_T("purchase_order", …)` tidak ditemukan — '
                "Pusat Dokumen tidak akan bisa menelusuri PO."]
    # Potong sampai entri `_T(` berikutnya supaya tidak membaca milik jenis lain.
    rest = refs_text[m.end():]
    nxt = re.search(r"\n\s*_T\(", rest)
    block = rest[: nxt.start()] if nxt else rest
    if "source_fk" not in block or '"pr_id"' not in block:
        return ['doc_refs_service: `purchase_order` tidak ber-`source_fk=["pr_id"]` → '
                "INV-REF-01 tidak akan menjaga tautan PO→PR (dan/atau akan menuduh "
                "PO mandiri sebagai dokumen yatim)."]
    return []


# ═══════════════════════════════════════════════════════════════════════════
# RUNTIME (opini kedua langsung dari Mongo)
# ═══════════════════════════════════════════════════════════════════════════
def check_docs(pos: List[Dict[str, Any]], prs: Dict[str, Dict[str, Any]],
               sos: Dict[str, Dict[str, Any]]) -> List[str]:
    """R1–R5 sebagai fungsi MURNI supaya `--self-test` bisa membuktikannya merah."""
    out: List[str] = []
    for po in pos:
        num = po.get("po_number") or po.get("id")
        pr_id = (po.get("pr_id") or "").strip()
        source = (po.get("source") or "").strip()
        sales = (po.get("sales_name") or "").strip()
        refs = po.get("refs") or []

        # R3 — nama sales tanpa jejak dokumen = nama yang diketik/dikarang.
        if sales and not pr_id:
            out.append(f"{num}: `sales_name`=\"{sales}\" terisi padahal `pr_id` kosong — "
                       "nama sales hanya boleh DIRUNUT dari pesanan, tidak diketik "
                       "(PO pembelian rutin memang tidak punya sales).")
        # R2 — klaim asal tanpa jejak (dua arah)
        if source == "pr" and not pr_id:
            out.append(f"{num}: `source=\"pr\"` tetapi `pr_id` kosong — klaim asal "
                       "dokumen tanpa jejaknya.")
        if pr_id and source not in ("pr", "rfq"):
            out.append(f"{num}: ber-`pr_id` tetapi `source=\"{source}\"` — jalur lahirnya "
                       "tidak tercatat sebagai dari PR/RFQ.")
        if not pr_id:
            continue                     # PO lama/mandiri: tidak dituduh apa pun

        # R1 — PR-nya harus ada & nomornya ikut disimpan
        pr = prs.get(pr_id)
        if not pr:
            out.append(f"{num}: `pr_id`={pr_id} menunjuk PR yang tidak ada (tautan yatim).")
            continue
        if not (po.get("pr_number") or "").strip():
            out.append(f"{num}: ber-`pr_id` tetapi `pr_number` kosong — dokumen cetak & "
                       "papan tidak bisa menyebut nomor PR-nya.")

        # R5 — refs dua arah
        po_ok = any(r.get("rel") == "parent" and r.get("doc_type") == "purchase_requisition"
                    and r.get("doc_id") == pr_id for r in refs)
        pr_ok = any(r.get("rel") == "child" and r.get("doc_type") == "purchase_order"
                    and r.get("doc_id") == po.get("id") for r in (pr.get("refs") or []))
        if not po_ok:
            out.append(f"{num}: tidak menaut PR-nya di `refs` (rel=parent) — "
                       "penelusuran dari PO ke atas buntu.")
        if not pr_ok:
            out.append(f"{pr.get('number') or pr_id}: tidak menaut {num} di `refs` "
                       "(rel=child) — arah balik hilang, panel 'menurunkan' kosong.")

        # R4 — nama sales == hitung ulang mandiri dari SO
        so_id = (pr.get("source_ref_id") or "").strip()
        if (pr.get("source") or "") in ("so_repeat", "so") and so_id:
            so = sos.get(so_id) or {}
            expect = (so.get("sales_name") or "").strip()
            if expect and sales != expect:
                out.append(f"{num}: `sales_name`=\"{sales}\" ≠ hitung-ulang mandiri dari "
                           f"{so.get('number') or so_id} (\"{expect}\") — snapshot asal "
                           "dokumen menyimpang.")
            if expect and not sales:
                out.append(f"{num}: `sales_name` kosong padahal PR-nya lahir dari "
                           f"{so.get('number') or so_id} milik \"{expect}\" — rantai "
                           "PO→PR→SO terputus di langkah terakhir.")
    return out


async def run_runtime(guard: Guard, verbose: bool = False) -> None:
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=4000)
    db = client[os.environ.get("DB_NAME", "test_database")]
    await db.command("ping")

    pos = await db.purchase_orders.find(
        {}, {"_id": 0, "id": 1, "po_number": 1, "pr_id": 1, "pr_number": 1, "source": 1,
             "source_so_ids": 1, "sales_name": 1, "sales_user_id": 1, "refs": 1}
    ).to_list(5000)
    prs = {p["id"]: p for p in await db.purchase_requisitions.find(
        {}, {"_id": 0, "id": 1, "number": 1, "source": 1, "source_ref_id": 1, "refs": 1}
    ).to_list(5000)}
    sos = {s["id"]: s for s in await db.sales_orders.find(
        {}, {"_id": 0, "id": 1, "number": 1, "sales_name": 1, "created_by": 1}
    ).to_list(5000)}

    guard.bump(len(pos))
    for v in check_docs(pos, prs, sos):
        guard.add(v)
    ber_asal = sum(1 for p in pos if (p.get("pr_id") or "").strip())
    print(f"{C}[DB]{X} {len(pos)} PO diperiksa · {ber_asal} mengaku punya asal dokumen "
          f"(PR) · {len(pos) - ber_asal} berdiri sendiri (tidak dituduh — keputusan "
          "pemilik: PO lama dibiarkan kosong).")
    if verbose:
        for p in pos:
            if (p.get("pr_id") or "").strip():
                print(f"      {p.get('po_number')} ← {p.get('pr_number')} · sales="
                      f"{p.get('sales_name') or '(kosong)'}")


# ═══════════════════════════════════════════════════════════════════════════
# SELF-TEST (bukti-merah dua arah — tanpa DB)
# ═══════════════════════════════════════════════════════════════════════════
def self_test() -> int:  # noqa: C901 — daftar kasus memang panjang & linear
    cases: List[Tuple[str, bool]] = []

    def case(label: str, cond: bool) -> None:
        cases.append((label, bool(cond)))

    OK_WRITER = ('from services import pr_sourcing_service as _pr\n'
                 'po = {"id": 1, **_pr.PO_ORIGIN_EMPTY}\n'
                 'await db.purchase_orders.insert_one(po)\n')
    BAD_WRITER = ('po = {"id": 1, "supplier_id": "s"}\n'
                  'await db.purchase_orders.insert_one(po)\n')
    NON_WRITER = 'x = await db.purchase_orders.find_one({"id": 1})\n'

    # S1
    case("S1 penulis PO yang memakai definisi bersama → bersih",
         check_shared_definition({"a.py": OK_WRITER}) == [])
    case("S1 penulis PO tanpa definisi bersama → MERAH",
         len(check_shared_definition({"a.py": BAD_WRITER})) == 1)
    case("S1 berkas yang hanya MEMBACA PO tidak dituduh",
         check_shared_definition({"a.py": NON_WRITER}) == [])
    case("S1 `insert_many` ikut terdeteksi sebagai penulis",
         len(check_shared_definition(
             {"a.py": 'await db.purchase_orders.insert_many([{"id": 1}])\n'})) == 1)

    # S2
    good_owner = ('PO_ORIGIN_EMPTY: Dict[str, Any] = {\n'
                  '    "pr_id": "", "pr_number": "", "source": "", "source_so_ids": [],\n'
                  '    "sales_user_id": "", "sales_name": "",\n}\n')
    case("S2 definisi lengkap → bersih", check_origin_keys(good_owner) == [])
    case("S2 kehilangan `source_so_ids` → MERAH",
         len(check_origin_keys(good_owner.replace('"source_so_ids": [],', ''))) == 1)
    case("S2 definisi hilang sama sekali → MERAH",
         len(check_origin_keys("X = 1\n")) == 1)
    case("S2 komentar yang menyebut nama field tidak dianggap definisi",
         len(check_origin_keys('# PO_ORIGIN_EMPTY = {"pr_id": ""}\nY = 2\n')) == 1)
    case("S2 membaca kunci lewat ast (bukan regex): urutan/format bebas",
         check_origin_keys(
             'PO_ORIGIN_EMPTY = {\n  "sales_name": "",\n  "sales_user_id": "",\n'
             '  "source_so_ids": [],\n  "source": "",\n  "pr_number": "",\n'
             '  "pr_id": "",\n}\n') == [])

    # S3
    case("S3 pemilik definisi boleh menulis kunci itu",
         check_hand_written({OWNER_FILE: 'db.purchase_orders.insert_one({"sales_name": "x"})'}) == [])
    case("S3 penulis PO lain yang menulis \"sales_name\" → MERAH",
         len(check_hand_written(
             {"z.py": 'db.purchase_orders.insert_one({"sales_name": "x", '
                      '**PO_ORIGIN_EMPTY})'})) == 1)
    case("S3 MEMBACA `po.get(\"sales_name\")` bukan pelanggaran",
         check_hand_written(
             {"z.py": 'x = po.get("sales_name")\ndb.purchase_orders.insert_one('
                      '{**PO_ORIGIN_EMPTY})'}) == [])

    # S4
    refs_ok = ('_T("purchase_order", "purchase_orders", "po_number", "PO", order=20,\n'
               '   source_fk=["pr_id"]),\n'
               '_T("grn", "wms_tasks", "id", "GRN", source_fk=["po_id"]),\n')
    case("S4 `source_fk=[\"pr_id\"]` ada → bersih", check_source_fk(refs_ok) == [])
    case("S4 `source_fk` hilang → MERAH",
         len(check_source_fk(refs_ok.replace('source_fk=["pr_id"]', ""))) == 1)
    case("S4 tidak tertipu `source_fk` milik jenis dokumen SESUDAHNYA",
         len(check_source_fk(
             '_T("purchase_order", "purchase_orders", "po_number", "PO", order=20),\n'
             '_T("grn", "wms_tasks", "id", "GRN", source_fk=["pr_id"]),\n')) == 1)

    # R1–R5
    pr_ok = {"id": "pr1", "number": "PR-1", "source": "so_repeat", "source_ref_id": "so1",
             "refs": [{"rel": "child", "doc_type": "purchase_order", "doc_id": "po1"}]}
    so_ok = {"id": "so1", "number": "SO-1", "sales_name": "Ayu"}
    po_ok = {"id": "po1", "po_number": "PO-1", "pr_id": "pr1", "pr_number": "PR-1",
             "source": "pr", "sales_name": "Ayu",
             "refs": [{"rel": "parent", "doc_type": "purchase_requisition", "doc_id": "pr1"}]}
    case("R rantai lengkap & konsisten → bersih",
         check_docs([po_ok], {"pr1": pr_ok}, {"so1": so_ok}) == [])
    case("R PO mandiri (tanpa pr_id, tanpa sales) TIDAK dituduh",
         check_docs([{"id": "po2", "po_number": "PO-2", "pr_id": "", "source": "manual",
                      "sales_name": ""}], {}, {}) == [])
    case("R3 `sales_name` terisi tanpa `pr_id` → MERAH",
         len(check_docs([{"id": "po3", "po_number": "PO-3", "pr_id": "",
                          "source": "manual", "sales_name": "Admin"}], {}, {})) == 1)
    case("R4 nama sales menyimpang dari SO → MERAH",
         any("hitung-ulang mandiri" in v for v in check_docs(
             [{**po_ok, "sales_name": "Orang Lain"}], {"pr1": pr_ok}, {"so1": so_ok})))
    case("R4 nama sales KOSONG padahal SO punya sales → MERAH",
         any("terputus di langkah terakhir" in v for v in check_docs(
             [{**po_ok, "sales_name": ""}], {"pr1": pr_ok}, {"so1": so_ok})))
    case("R5 arah balik (PR→PO) hilang → MERAH",
         any("arah balik hilang" in v for v in check_docs(
             [po_ok], {"pr1": {**pr_ok, "refs": []}}, {"so1": so_ok})))
    case("R5 PO tidak menaut PR-nya → MERAH",
         any("penelusuran dari PO ke atas buntu" in v for v in check_docs(
             [{**po_ok, "refs": []}], {"pr1": pr_ok}, {"so1": so_ok})))
    case("R1 `pr_id` menunjuk PR yang tidak ada → MERAH",
         any("tautan yatim" in v for v in check_docs([po_ok], {}, {"so1": so_ok})))
    case("R1 `pr_number` kosong → MERAH",
         any("`pr_number` kosong" in v for v in check_docs(
             [{**po_ok, "pr_number": ""}], {"pr1": pr_ok}, {"so1": so_ok})))
    case("R2 `source=\"pr\"` tanpa `pr_id` → MERAH",
         any("klaim asal" in v for v in check_docs(
             [{"id": "po4", "po_number": "PO-4", "pr_id": "", "source": "pr",
               "sales_name": ""}], {}, {})))
    case("R PR dari `reorder` (bukan dari SO) → sales kosong TIDAK dituduh",
         check_docs([{**po_ok, "sales_name": ""}],
                    {"pr1": {**pr_ok, "source": "reorder", "source_ref_id": ""}},
                    {"so1": so_ok}) == [])

    print(f"{B}== SELF-TEST INV-ORIG-01 (bukti-merah dua arah) =={X}")
    fails = 0
    for label, cond in cases:
        print(f"  {G}[OK]{X} {label}" if cond else f"  {R}[GAGAL]{X} {label}")
        fails += 0 if cond else 1
    if fails:
        print(f"{R}SELF-TEST GAGAL: {fails}/{len(cases)} — penjaga tidak bisa dipercaya.{X}")
        return 1
    print(f"{G}SELF-TEST LULUS: {len(cases)}/{len(cases)} kasus (bersih & pelanggaran).{X}")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    guard = Guard("INV-ORIG-01",
                  "Asal dokumen PO dari SATU definisi (pr_id · sales dirunut, "
                  "tidak diketik · refs dua arah)")

    sources: Dict[str, str] = {}
    for path in sorted(BE.rglob("*.py")):
        rel = str(path.relative_to(BE)).replace("\\", "/")
        probe = f"/{rel}"
        if any(part in probe for part in SKIP_PARTS) or rel.startswith("test"):
            continue
        try:
            sources[rel] = path.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            continue

    writers = po_writer_files(sources)
    guard.bump(len(writers) + 2)
    if not writers:
        guard.add("Tidak ada satu pun berkas yang menyisipkan dokumen `purchase_orders` — "
                  "pola pencarian gate ini kedaluwarsa (dulu 4 pintu). Perbaiki gate, "
                  "bukan diabaikan: gate yang tak menemukan apa pun = gate mati.")
    print(f"{C}[STATIK]{X} {len(writers)} pintu lahirnya PO ditemukan: "
          f"{', '.join(writers) or '(tidak ada)'}")
    for v in check_shared_definition(sources):
        guard.add(v)
    for v in check_hand_written(sources):
        guard.add(v)
    owner_text = sources.get(OWNER_FILE, "")
    if not owner_text:
        guard.add(f"{OWNER_FILE} tidak ditemukan — definisi tunggal asal dokumen PO hilang.")
    else:
        for v in check_origin_keys(owner_text):
            guard.add(v)
    refs_text = sources.get("services/doc_refs_service.py", "")
    if not refs_text:
        guard.add("services/doc_refs_service.py tidak ditemukan — peta jenis dokumen hilang.")
    else:
        for v in check_source_fk(refs_text):
            guard.add(v)

    if os.environ.get("MONGO_URL"):
        try:
            asyncio.run(run_runtime(guard, verbose))
        except Exception as exc:  # noqa: BLE001 — DB mati ≠ pelanggaran invarian
            print(f"{Y}[SKIP]{X} bagian runtime dilewati: {type(exc).__name__}: {exc}")
    else:
        print(f"{Y}[SKIP]{X} MONGO_URL tidak tersedia — hanya pemeriksaan statik.")
    return guard.finish()


if __name__ == "__main__":
    raise SystemExit(main())
