"""poc_stock_guard — pulihkan STOK setelah POC fase (menutup **POC-RESIDU-01**).

MASALAH NYATA (terukur 2026-07-29, ditemukan checkpoint residu FASE POC yang baru):
satu `bash scripts/gate.sh --full` dari seed bersih meninggalkan

    inventory_rolls                     53 → 75   (+22 roll)
    prod_batik_mega|wh_jakarta.reserved 50 → 173
    prod_batik_mega|wh_jakarta.available 435 → 307
    prod_batik_mega|wh_bandung.reserved  20 → 109

Akibat yang dilihat pemakai: **stok tersedia menyusut** dan muncul roll-roll
potongan tak bertuan setiap kali gate dijalankan.

AKAR MASALAH: POC G-0/G-1/G-2/G-3 mengonfirmasi Sales Order sungguhan. Konfirmasi
SO mengalokasikan roll dan **memotong** roll bila qty tidak bulat (roll cut
MELAHIRKAN roll baru). Cleanup POC lalu menghapus SO **langsung dari MongoDB**,
sehingga:
  * reservasi pada roll tidak pernah dilepas (`status` tetap reserved/committed);
  * roll hasil potongan tidak pernah digabung ulang;
  * `inventory_balances` (proyeksi dari roll) ikut bergeser permanen.

KENAPA RESTORE, BUKAN "HAPUS YANG BARU": memotong roll bukan operasi yang bisa
dibalik per-dokumen (satu roll jadi dua, nomor & sisa berubah). Satu-satunya
pemulihan yang EKSAK adalah snapshot sebelum uji lalu restore sesudahnya —
pola yang sudah dipakai `scripts/guardrails/_common.py::DbSnapshot` untuk
guardrail runtime. Modul ini memakai pola yang sama, tetapi hanya untuk koleksi
STOK supaya POC tetap bebas membuat dokumen lain.

PENGAMAN: hanya berjalan bila `DB_NAME` mengandung `test`/`demo`/`dev`, atau
`KN_GATE_ALLOW_RESTORE=1`. Jadi tidak mungkin menyentuh basis data produksi.
Set `KN_GATE_NO_RESTORE=1` untuk MENGUKUR kebocoran (restore dimatikan).

Pemakaian di POC:

    from poc_stock_guard import snapshot_stock, restore_stock

    _STOCK = snapshot_stock()          # sebelum POC menulis apa pun
    ...
    restore_stock(_STOCK)             # di bagian CLEANUP, setelah dokumen POC dihapus
"""
import os
from typing import Any, Dict, List, Optional

G, Y, R, X = "\033[92m", "\033[93m", "\033[91m", "\033[0m"

# POC dijalankan sebagai skrip lepas (lewat HTTP), jadi env belum tentu memuat
# backend/.env. Muat di sini supaya nama DB yang dipakai SAMA dengan backend —
# kalau tidak, pengaman "hanya DB uji" salah menolak dan restore tak pernah jalan
# (pernah terjadi: DB_NAME='' → restore DIMATIKAN, residu tetap ada).
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except Exception:  # noqa: BLE001 — dotenv opsional
    pass


def _db_name() -> str:
    return (os.environ.get("DB_NAME") or "test_database").strip('"')


# Hanya koleksi STOK. Dokumen bisnis (SO/PO/jurnal/…) tetap tanggung jawab
# cleanup masing-masing POC supaya kesalahan cleanup tidak tersembunyi.
STOCK_COLLECTIONS = ["inventory_rolls", "inventory_balances", "inventory_movements",
                     "inventory_lots"]

# ── POC-RESIDU-02 (terukur 2026-08-20, sesi FASE U) ──────────────────────────
# Memulihkan STOK secara eksak sambil MENGHAPUS jurnal yang lahir dari peristiwa
# stok itu melahirkan residu jenis BARU: buku besar (GL 1-1300) turun sementara
# subledger roll kembali utuh → `verify_data_integrity` memunculkan
# `WARN INV-GL-DRIFT` (terukur Δ432.000.000 = 4 × satu penerimaan uji 108 juta,
# yaitu 3 kali POC FASE U + 1 kali uji lewat layar).
#
# Pelajarannya sama dengan POC-RESIDU-01, satu lapis lebih dalam: **dua sisi satu
# peristiwa harus dipulihkan ke SATU saat yang sama**. Karena itu POC yang
# menjalankan alur berjurnal (penerimaan · retur · pengiriman) memakai
# `snapshot_stock(STOCK_COLLECTIONS + LEDGER_COLLECTIONS)` — bukan hanya stok.
LEDGER_COLLECTIONS = ["journal_entries", "gl_postings"]

# ── POC-RESIDU-05 (terukur 2026-08-23, sesi FASE I) ─────────────────────────
# Sejak FASE I, **penerimaan barang melahirkan DOKUMEN**: begitu tugas penerimaan
# masuk antrean QC, `inspection_service.ensure_for_qc_task()` menerbitkan SPK
# `inspections` berisi satu baris per roll. Akibatnya setiap POC yang menjalankan
# alur terima-barang (U · P · P-0 · F-1 · F) tiba-tiba meninggalkan dokumen yang
# cleanup-nya TIDAK pernah tahu harus dihapus — dan gejalanya menyesatkan seperti
# biasa: bukan "POC FASE I merah", melainkan **INV-REF-01 merah di POC LAIN**
# ("dokumen turunan tanpa induk hidup", karena PO-nya sudah dihapus POC itu) lalu
# 8 POC berikutnya ikut merah pada baris "invarian global tetap HIJAU".
#
# Karena itu `inspections` dipulihkan BERSAMA stoknya, di sini, satu tempat:
# dokumen ini adalah **sisi lain dari peristiwa stok yang sama** (roll masuk →
# SPK-nya lahir), persis alasan yang sama dengan jurnal di POC-RESIDU-02.
# Memperbaikinya di masing-masing POC berarti lima salinan aturan yang akan
# menyimpang — dan yang tertinggal akan menuduh fase lain.
DOCUMENT_COLLECTIONS = ["inspections"]

STOCK_COLLECTIONS = STOCK_COLLECTIONS + DOCUMENT_COLLECTIONS

# ── POC-RESIDU-03 (terukur 2026-08-21, sesi lanjutan) ────────────────────────
# Diukur dengan membandingkan JUMLAH DOKUMEN SELURUH koleksi sebelum & sesudah
# satu kali POC FASE E-7 (bukan hanya koleksi yang kebetulan dipantau). Satu kali
# jalan meninggalkan, permanen, di data demo:
#
#     cash_transactions          34 -> 41   (+7)   uang keluar-masuk yang tak pernah terjadi
#     journal_entries           132 -> 141   (+9)  jurnal di DUA buku
#     interco_loans              10 -> 12   (+2)   dokumen pinjaman kembar
#     fin_fixed_assets            5 ->  7   (+2)   mesin uji + kembarannya di PT tujuan
#     intercompany_eliminations   6 ->  7   (+1)   eliminasi laba pindah aset
#     purchase_requisitions      12 -> 14   (+2)   PR uji pagar (dibatalkan, tak dihapus)
#
# Tak satu pun dari koleksi itu ada di `scripts/gate_residue.py::WATCH`, jadi
# INV-GATE-01 **HIJAU** sementara setiap `gate.sh --full` menyuntik 9 jurnal dan 7
# transaksi kas palsu ke buku demo. POC-nya sendiri menyebut ini "SENGAJA
# ditinggalkan karena uangnya sudah berpindah — append-only". Alasan itu benar
# untuk MENGHAPUS DOKUMENNYA SAJA (jurnal jadi yatim), tetapi salah sebagai
# kesimpulan: obat yang benar adalah memulihkan **kedua sisi pada satu saat yang
# sama** — pelajaran POC-RESIDU-02, satu lapis lebih luas.
MONEY_COLLECTIONS = ["cash_transactions", "journal_entries", "gl_postings",
                     "interco_loans", "fin_fixed_assets",
                     "intercompany_eliminations", "interco_accounts",
                     "purchase_requisitions"]

# Dipakai POC alur-penuh: stok + buku besar + KAS dipulihkan bersamaan.
# `cash_transactions` ditambahkan 2026-08-21 setelah pengukuran per-POC
# (`scripts/ukur_residu_poc.py`) menunjukkan 4 POC meninggalkan jurnal dan/atau
# kas: tahapan (+2 jurnal) · G-2 (+1) · G-3 (+1) · G-9 (+3 jurnal, +1 kas).
# Uang dan jurnalnya adalah DUA SISI satu peristiwa — memulihkan salah satu saja
# adalah cara membuat residu jenis baru (pelajaran POC-RESIDU-02).
CASH_COLLECTIONS = ["cash_transactions"]
FULL_COLLECTIONS = STOCK_COLLECTIONS + LEDGER_COLLECTIONS + CASH_COLLECTIONS

# ── POC-RESIDU-04 (terukur 2026-08-21 lewat `scripts/ukur_residu_poc.py`) ────
# Sisa residu terakhir sesudah uang & jurnal dibereskan, semuanya di koleksi yang
# TIDAK dipantau gate sehingga tak pernah kelihatan:
#
#   test_g0_config_poc            system_settings      3 -> 5   (+2)
#   test_fase_d_makloon_poc       system_settings      5 -> 6   (+1)
#   test_core_rantai_retur_poc    store_credit_ledger  1 -> 2   (+1)
#   test_fase_f_rnd_poc           approval_matrix_log 12 -> 14   (+2)
#   test_fase_f_us3_..._poc       credit_overrides     0 -> 1   (+1)
#
# Kenapa ini bukan "cuma baris tambahan": `system_settings` adalah SSOT
# konfigurasi (nilai yang tertinggal mengubah PERILAKU aplikasi demo),
# `store_credit_ledger` adalah SALDO UANG pelanggan, dan `credit_overrides`
# adalah pembebasan pagar kredit — ketiganya bisa membuat POC lain lulus/gagal
# karena keadaan yang ditinggalkan POC sebelumnya, bukan karena kodenya.
CONFIG_COLLECTIONS = ["system_settings", "config_values"]


def _restore_allowed() -> bool:
    if os.environ.get("KN_GATE_NO_RESTORE") == "1":
        print(f"{Y}  [poc-stock] KN_GATE_NO_RESTORE=1 — restore stok DIMATIKAN "
              f"(mode ukur kebocoran).{X}")
        return False
    if os.environ.get("KN_GATE_ALLOW_RESTORE") == "1":
        return True
    name = _db_name().lower()
    if any(tag in name for tag in ("test", "demo", "dev")):
        return True
    print(f"{Y}  [poc-stock] DB_NAME='{name}' bukan basis data uji — restore stok "
          f"DIMATIKAN (set KN_GATE_ALLOW_RESTORE=1 bila memang disengaja).{X}")
    return False


def _db():
    from pymongo import MongoClient
    url = os.environ.get("MONGO_URL", "mongodb://localhost:27017").strip('"')
    return MongoClient(url, serverSelectionTimeoutMS=5000)[_db_name()]


def snapshot_stock(collections: Optional[List[str]] = None) -> Dict[str, Any]:
    """Simpan isi koleksi stok apa adanya (termasuk `_id`) agar restore EKSAK."""
    cols = collections or STOCK_COLLECTIONS
    snap: Dict[str, Any] = {"__enabled__": _restore_allowed(), "data": {}}
    if not snap["__enabled__"]:
        return snap
    try:
        db = _db()
        for c in cols:
            snap["data"][c] = list(db[c].find({}))
        total = sum(len(v) for v in snap["data"].values())
        print(f"  [poc-stock] snapshot {total} dokumen stok dari {len(cols)} koleksi "
              f"— akan dipulihkan di CLEANUP.")
    except Exception as exc:  # noqa: BLE001
        print(f"{Y}  [poc-stock] snapshot GAGAL ({exc}) — restore dilewati.{X}")
        snap["__enabled__"] = False
    return snap


def restore_stock(snap: Optional[Dict[str, Any]]) -> bool:
    """Pulihkan koleksi stok ke keadaan snapshot. Return True bila benar-benar pulih."""
    if not snap or not snap.get("__enabled__") or not snap.get("data"):
        return False
    try:
        db = _db()
        for c, docs in snap["data"].items():
            db[c].delete_many({})
            if docs:
                db[c].insert_many(docs, ordered=False)
        total = sum(len(v) for v in snap["data"].values())
        print(f"  {G}[poc-stock] stok dipulihkan EKSAK ({total} dokumen, "
              f"{len(snap['data'])} koleksi) — nol residu roll & saldo.{X}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"{R}  [poc-stock] restore GAGAL: {exc}{X}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# sweep_ghost_refs — INV-REF-04 untuk POC  [BARU 2026-08-21]
# ─────────────────────────────────────────────────────────────────────────────
# MASALAH NYATA (terukur pada `gate.sh --full`, bukan dugaan):
#   `doc_refs_service.link()` menulis relasi DUA ARAH. Karena itu POC yang
#   menghapus dokumen ujinya langsung dari Mongo meninggalkan dokumen SEED yang
#   masih hidup memegang ref ke dokumen yang sudah tidak ada:
#
#     KSC/SCT-00004 --fulfilled_by--> makloon_order:mko_5dcd… (target tak ada)
#     KSC/SCT-00008 --fulfilled_by--> makloon_order:mko_a95e… (target tak ada)
#     KSC/SO-00010  --settled_by---->  finance_case:fcs_7775… (target tak ada)
#
#   Akibatnya nyata: panel "Referensi Dokumen" pada kontrak & pesanan demo
#   menawarkan tautan yang menuju 404, `audit_doc_refs --strict` MERAH, dan POC
#   P-0 (yang memanggil audit itu di dalamnya) memerah karena kesalahan POC LAIN.
#   Terukur 104 titik penghapusan di 28 berkas POC/uji — menambal satu per satu
#   bukan hanya mahal, ia juga akan terlupakan pada POC berikutnya.
#
# OBATNYA satu baris di CLEANUP tiap POC. Sengaja TIDAK dipakai di kode produksi:
# di produksi, ref yatim adalah GEJALA bug yang harus diperbaiki di akarnya
# (`doc_refs_service.unlink_all` dipanggil di titik hapus, dijaga INV-REF-04),
# bukan disapu diam-diam. Di POC, menyapu = memulihkan keadaan bersih.
def sweep_ghost_refs(verbose: bool = True) -> int:
    """Buang ref yang menunjuk dokumen yang sudah tidak ada. Return jumlah ref dibuang.

    Memakai registry `doc_refs_service.DOC_TYPES` sebagai sumber kebenaran (bukan
    daftar koleksi hardcode), jadi jenis dokumen baru otomatis ikut disapu.
    """
    if not _restore_allowed():
        return 0
    try:
        import os as _os
        import sys as _sys
        _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
        from services.doc_refs_service import DOC_TYPES  # noqa: PLC0415

        db = _db()
        # `load_doc()` mencari by `id` TANPA filter doc_type, jadi himpunan "hidup"
        # pun harus per KOLEKSI — kalau tidak, dokumen yang sah dianggap hantu.
        alive: Dict[str, set] = {}
        for meta in DOC_TYPES.values():
            coll = meta["collection"]
            if coll not in alive:
                alive[coll] = {d["id"] for d in db[coll].find({}, {"_id": 0, "id": 1})}
        swept = 0
        for coll in sorted({m["collection"] for m in DOC_TYPES.values()}):
            for row in db[coll].find({"refs.0": {"$exists": True}},
                                     {"_id": 1, "refs": 1}):
                refs: List[Any] = row.get("refs") or []
                keep = [r for r in refs
                        if not (r.get("doc_type") in DOC_TYPES
                                and r.get("doc_id") not in
                                alive.get(DOC_TYPES[r["doc_type"]]["collection"], set()))]
                if len(keep) != len(refs):
                    db[coll].update_one({"_id": row["_id"]}, {"$set": {"refs": keep}})
                    swept += len(refs) - len(keep)
        if verbose:
            print(f"  {G if not swept else Y}[poc-refs] {swept} tautan hantu disapu "
                  f"(INV-REF-04) — dokumen uji dihapus tanpa meninggalkan jejak "
                  f"menunjuk ketiadaan.{X}")
        return swept
    except Exception as exc:  # noqa: BLE001
        print(f"{R}  [poc-refs] sapuan tautan GAGAL: {exc}{X}")
        return 0
