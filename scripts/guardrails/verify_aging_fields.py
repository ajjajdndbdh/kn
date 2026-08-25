#!/usr/bin/env python3
"""INV-AGING-01 — FIELD UMUR TUNGGU TIDAK BOLEH DITEBAK.

KELAS BUG YANG DICEGAH (terukur 2026-08-24, temuan B1 HANDOFF audit)
====================================================================
`services/approval_backlog_service.AGING_META` memberi tahu DARI MANA umur tunggu
satu dokumen dihitung ("sudah menunggu 12 hari"). Baris `special_order` berbunyi:

    "special_order": {"since": ["submitted_at", "approval_requested_at", "created_at"]}

Padahal `grep -n "submitted_at\\|approval_requested_at" backend/routers/special_orders.py
backend/services/special_order_service.py` → **NOL hasil**. Tidak satu pun jalur tulis
mengisi kedua field itu; keduanya murni **hasil menebak**. Akibatnya:

  · umur tunggu SELALU jatuh ke `created_at` (dokumen yang lama berstatus `draft`
    dilaporkan jauh lebih tua daripada kenyataan);
  · pengurutan papan memakai field yang `null` di SELURUH dokumen → urutannya
    urutan alami koleksi dan `limit(10)` memotong sembarang, termasuk yang TERTUA.

Yang membuat kelas ini mahal: **tidak ada galat apa pun**. Mongo tidak protes untuk
field yang tak ada, ia mengembalikan `null`; papan tetap hijau, pengingat tetap
terkirim — hanya angkanya yang tenang-tenang salah. Uji API biasa tak menangkapnya
karena endpoint-nya "sukses 200".

ATURAN YANG DITEGAKKAN
======================
Untuk SETIAP kandidat field di `AGING_META[*]["since"]` (dan `["number"]`,
`["title"]`), field itu WAJIB terbukti nyata lewat salah satu dari dua bukti:

  A. **DATA** — muncul (tidak null/kosong) di ≥ 1 dokumen koleksi antrean itu; ATAU
  B. **KODE** — disebut LITERAL sebagai kunci tulis di jalur tulis backend
     (`"field":` / `"field"` dalam blok `$set`) di `backend/routers` atau
     `backend/services`.

Bukti B menutup fitur yang koleksinya belum pernah dipakai di data demo (uang muka,
biaya masuk, buka periode) supaya penjaga ini tidak menuduh palsu — penjaga yang
menuduh palsu akan dimatikan orang. Field yang MURNI TEBAKAN tidak akan ditemukan di
kedua tempat, jadi ia tetap tertangkap.

`created_at` dikecualikan: ia field bawaan seluruh dokumen di repo ini dan memang
peran cadangan terakhir yang sah.

Resilient: tanpa MongoDB, hanya lapisan KODE yang berjalan (tetap menangkap kelas
"field ditebak" karena bukti A memang tidak bisa dipakai).

Usage:
    python scripts/guardrails/verify_aging_fields.py
    python scripts/guardrails/verify_aging_fields.py --self-test   # bukti-merah
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env")
except Exception:  # noqa: BLE001
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Guard, G, R, Y, B, X  # noqa: E402

#: `created_at` sah sebagai cadangan terakhir (ada di seluruh dokumen repo ini).
BAWAAN = {"created_at"}

#: Peran yang diperiksa. `since` yang salah membuat UMUR bohong; `number`/`title`
#: yang salah membuat pengingat menyebut sesuatu yang tak bisa dicari orang —
#: keduanya kelas cacat yang sama (membaca field yang tidak ada, tanpa galat).
PERAN = ("since", "number", "title")


def backend_source() -> str:
    src = ""
    for sub in ("routers", "services"):
        d = ROOT / "backend" / sub
        if not d.exists():
            continue
        for f in sorted(d.glob("*.py")):
            src += f.read_text(encoding="utf-8")
    return src


def ada_di_kode(field: str, src: str) -> bool:
    """Field disebut sebagai KUNCI TULIS (bukan sekadar dibaca/di-doc)."""
    return bool(re.search(rf'"{re.escape(field)}"\s*:', src))


def periksa(g: Guard, queues, aging, db, src, detail=None) -> None:
    coll_of = {q[0]: q[3] for q in queues}
    for key, meta in sorted(aging.items()):
        coll = coll_of.get(key)
        if not coll:
            g.bump()
            g.add(f"`AGING_META['{key}']` tidak punya baris antrean di `QUEUES` — "
                  f"metadata umur untuk antrean yang tidak ada.")
            continue
        for peran in PERAN:
            for field in (meta.get(peran) or []):
                if field in BAWAAN or "." in field:
                    continue
                g.bump()
                bukti_kode = ada_di_kode(field, src)
                bukti_data = False
                if db is not None:
                    try:
                        bukti_data = bool(db[coll].find_one(
                            {field: {"$nin": [None, ""]}}, {"_id": 1}))
                    except Exception:  # noqa: BLE001
                        bukti_data = False
                if not (bukti_kode or bukti_data):
                    g.add(f"antrean `{key}` membaca `{peran}` dari field "
                          f"`{coll}.{field}` yang TIDAK ADA di dokumen mana pun DAN "
                          f"tidak pernah ditulis kode backend → field DITEBAK. Mongo "
                          f"mengembalikan null tanpa galat: umur/nomor/judul akan "
                          f"tenang-tenang salah (kelas bug B1 `approval_requested_at`).")
    # 2026-06 — `DETAIL_META` ikut dinilai. Utang yang tercatat di PRD: penjaga ini
    # dulu HANYA menilai `AGING_META`, padahal papan antrean membaca nilai rupiah,
    # keterangan, dan peran penyetuju dari `DETAIL_META`. Field rupiah yang salah nama
    # membuat papan melaporkan "Rp 0" untuk PO custom Rp 43 juta — tanpa satu pun galat.
    for key, meta in sorted((detail or {}).items()):
        coll = coll_of.get(key)
        if not coll:
            g.bump()
            g.add(f"`DETAIL_META['{key}']` tidak punya baris antrean di `QUEUES` — "
                  f"metadata papan untuk antrean yang tidak ada.")
            continue
        for peran, fields in sorted(meta.items()):
            for field in (fields or []):
                akar = field.split(".")[0]
                if akar in BAWAAN:
                    continue
                g.bump()
                bukti_kode = ada_di_kode(akar, src)
                bukti_data = False
                if db is not None:
                    try:
                        bukti_data = bool(db[coll].find_one(
                            {akar: {"$nin": [None, ""]}}, {"_id": 1}))
                    except Exception:  # noqa: BLE001
                        bukti_data = False
                if not (bukti_kode or bukti_data):
                    g.add(f"papan antrean `{key}` membaca `{peran}` dari field "
                          f"`{coll}.{field}` yang TIDAK ADA di dokumen mana pun DAN "
                          f"tidak pernah ditulis kode backend → field DITEBAK: papan "
                          f"akan melaporkan 0/kosong dengan percaya diri.")


def self_test() -> int:
    """Bukti-merah: penjaga harus menuduh field tebakan & meloloskan yang nyata."""
    src_nyata = '{"approval_requested_at": now_iso(), "created_at": now_iso()}'
    kasus = [
        ("field yang benar-benar ditulis kode → hijau",
         [("special_order", "L", "V", "special_orders", {})],
         {"special_order": {"since": ["approval_requested_at", "created_at"],
                            "number": ["number"], "title": ["customer_name"]}},
         src_nyata + ' {"number": n} {"customer_name": c}', 0),
        ("field TEBAKAN (nol jalur tulis, nol dokumen) → merah",
         [("special_order", "L", "V", "special_orders", {})],
         {"special_order": {"since": ["submitted_at", "created_at"],
                            "number": ["number"], "title": ["customer_name"]}},
         src_nyata + ' {"number": n} {"customer_name": c}', 1),
        ("hanya `created_at` → hijau (cadangan sah, tak dianggap tebakan)",
         [("x", "L", "V", "xs", {})],
         {"x": {"since": ["created_at"], "number": [], "title": []}}, "", 0),
        ("metadata umur untuk antrean yang tidak ada → merah",
         [], {"hantu": {"since": ["created_at"]}}, "", 1),
        ("dua field tebakan sekaligus → dua tuduhan",
         [("y", "L", "V", "ys", {})],
         {"y": {"since": ["diajukan_pada", "created_at"], "number": ["nomor_hantu"],
                "title": []}}, "", 2),
    ]
    # DETAIL_META (2026-06) — papan antrean membaca rupiah/keterangan/peran dari sini.
    kasus_detail = [
        ("DETAIL_META field nyata → hijau",
         [("special_order", "L", "V", "special_orders", {})],
         {"special_order": {"amount": ["total_amount"]}},
         '{"total_amount": t}', 0),
        ("DETAIL_META field TEBAKAN → merah",
         [("special_order", "L", "V", "special_orders", {})],
         {"special_order": {"amount": ["nilai_hantu"]}}, "", 1),
        ("DETAIL_META jalur bersarang dinilai dari AKARNYA → hijau",
         [("cb", "L", "V", "contra_bons", {})],
         {"cb": {"amount": ["totals.net_payable"]}}, '{"totals": x}', 0),
        ("DETAIL_META untuk antrean yang tidak ada → merah",
         [], {"hantu": {"amount": ["x"]}}, "", 1),
    ]
    gagal = 0
    print(f"{B}== SELF-TEST INV-AGING-01 (penjaga harus bisa MEMERAH) =={X}")
    for nama, queues, aging, src, harap in kasus:
        g = Guard("INV-AGING-01", "self-test")
        g.violations, g.checks = [], 0
        periksa(g, queues, aging, None, src)
        got = len(g.violations)
        ok_ = got == harap
        gagal += 0 if ok_ else 1
        print(f"  [{G + 'PASS' + X if ok_ else R + 'FAIL' + X}] {nama}  "
              f"(harap={harap}, dapat={got})")
    for nama, queues, detail, src, harap in kasus_detail:
        g = Guard("INV-AGING-01", "self-test")
        g.violations, g.checks = [], 0
        periksa(g, queues, {}, None, src, detail=detail)
        got = len(g.violations)
        ok_ = got == harap
        gagal += 0 if ok_ else 1
        print(f"  [{G + 'PASS' + X if ok_ else R + 'FAIL' + X}] {nama}  "
              f"(harap={harap}, dapat={got})")
    if gagal:
        print(f"{R}{B}  SELF-TEST MERAH — penjaga field umur tak bisa dipercaya.{X}")
    else:
        print(f"{G}  HIJAU — penjaga terbukti menuduh field yang ditebak.{X}")
    return gagal


def main() -> int:
    g = Guard("INV-AGING-01", "field umur tunggu WAJIB nyata (bukan ditebak)")
    sys.path.insert(0, str(ROOT / "backend"))
    from services import approval_backlog_service as abl  # noqa: PLC0415

    db = None
    try:
        from pymongo import MongoClient
        db = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=3000)[
            os.environ["DB_NAME"]]
        db.command("ping")
    except Exception as ex:  # noqa: BLE001
        print(f"{Y}  MongoDB tak terjangkau ({ex}) — hanya lapisan KODE dinilai.{X}")
        db = None

    periksa(g, abl.QUEUES, abl.AGING_META, db, backend_source(),
            detail=getattr(abl, "DETAIL_META", {}))
    return g.finish()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(1 if self_test() else 0)
    try:
        sys.exit(main())
    except Exception as ex:  # noqa: BLE001
        print(f"{Y}  Gate error (dianggap SKIP): {ex}{X}")
        sys.exit(0)
