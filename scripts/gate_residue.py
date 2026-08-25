#!/usr/bin/env python3
"""
gate_residue.py — GATE ANTI-RESIDU  (INV-GATE-01)
=================================================
Membuktikan bahwa MENJALANKAN GATE tidak mengubah data.

LATAR BELAKANG (kelas bug nyata, terukur 2026-07-26):
  Guardrail runtime memanggil API sungguhan sehingga mengubah data, dan sebelum
  perbaikan tak satu pun punya cleanup. Diukur dari seed bersih, SATU kali
  `gate.sh` meninggalkan:

    · sales_orders     : SO-0006 'reserved/Reserved' -> 'cancelled/Cancelled'  (permanen)
    · inventory_balances:
        prod_songket_palembang/wh_jakarta  available 135->145 · reserved 20->10
        prod_lurik_classic/wh_bandung      available 580->620 · reserved 40->0
    · inventory_movements : 38 -> 40   (+2 release_reservation)
    · audit_logs          : 6  -> 16   (+10)

  Tidak ada satu pun dari 183 invarian yang menangkapnya (semuanya memeriksa
  konsistensi INTERNAL, bukan "apakah gate itu sendiri merusak data").
  Skrip ini menutup celah itu secara permanen.

CARA PAKAI (dipakai otomatis oleh scripts/gate.sh):
    python scripts/gate_residue.py --save     # sebelum gate runtime
    python scripts/gate_residue.py --check    # sesudah gate runtime  (exit 1 bila ada residu)

Sidik jari disimpan di /tmp/kn_gate_residue.json (bukan di repo).
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env")
except Exception:
    pass

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

G, Y, R, B, X = "\033[92m", "\033[93m", "\033[91m", "\033[1m", "\033[0m"
SNAP = Path(os.environ.get("KN_RESIDUE_FILE", "/tmp/kn_gate_residue.json"))

# Koleksi yang HARUS identik sebelum & sesudah gate runtime.
# audit_logs & notifications SENGAJA disertakan: residu di situ pun berarti gate
# meninggalkan jejak yang tak dibersihkan.
WATCH = [
    "sales_orders", "purchase_orders", "products", "customers",
    "inventory_balances", "inventory_movements", "inventory_rolls",
    "wms_tasks", "audit_logs", "notifications", "shipments",
    "approval_requests", "invoices", "vendor_bills", "ar_receipts",
    # Antar-PT (ditambahkan setelah KN-G6-ICA-CLOBBER): POC E-7d mengubah
    # Permintaan Internal menjadi transaksi antar-PT dan TIDAK membersihkannya,
    # jadi setiap `gate --full` menambah satu dokumen KANDA/IC-##### permanen.
    # Residu itu tak pernah terlihat karena koleksi antar-PT belum dipantau —
    # dan justru residu itulah yang memicu tabrakan saldo dua arah.
    # Catatan sengaja: `interco_accounts` TIDAK dipantau di sini karena ia tabel
    # TURUNAN (lahir sendiri begitu sepasang PT mulai berhubungan, mis. lewat
    # pinjaman antar-PT yang memang append-only). Kebenarannya dijaga INV-IC-04
    # yang kini memeriksa KELENGKAPAN per arah dagang, bukan oleh gate residu.
    "interco_transactions", "interco_settlements", "interco_returns",
    # RETUR (ditambahkan FASE E-9): rantai retur menyentuh tiga koleksi dokumen +
    # lot & nota kredit. POC E-9 membersihkan miliknya sendiri, tetapi tanpa
    # dipantau di sini residu POC lain di jalur retur tetap tak terlihat — dan
    # justru koleksi inilah yang memegang nilai barang & uang balik.
    "sales_returns", "purchase_returns", "credit_notes",
    "inventory_lots", "supplier_contracts",
    # FASE D — permintaan desain adalah dokumen bernomor; POC yang membuat & memutus
    # permintaan wajib membersihkannya sendiri (kalau tidak, papan kanban demo
    # perlahan penuh dokumen uji yang tak pernah dihapus siapa pun).
    "design_requests",
    # FASE I — dokumen inspeksi bernomor (`<ENT>/INS-#####`). POC yang menerima barang
    # PO otomatis melahirkan SPK-nya, jadi POC yang tidak membersihkannya akan
    # menumpuk SPK uji yang tak pernah dikerjakan siapa pun.
    "inspections",
    # Ditambahkan 2026-08-21 — residu NYATA yang lolos berbulan-bulan: POC FASE E-7d
    # membuat `KSC/PIN-00003`, lalu "membatalkannya" lewat `POST /cancel` yang SELALU
    # gagal begitu statusnya `converted`. Dokumennya tertinggal permanen dan dua
    # ref `fulfilled_by`-nya menunjuk draf antar-PT yang dihapus pembersih POC →
    # `audit_doc_refs --strict` MERAH "Tautan menggantung: 2 temuan" pada gate
    # BERIKUTNYA (karena audit itu berjalan sebelum POC). Koleksi ini tak dipantau,
    # jadi INV-GATE-01 pun ikut buta.
    "internal_requests",
    # ── POC-RESIDU-03 (terukur 2026-08-21, dengan menghitung SELURUH koleksi) ──
    # Satu kali POC FASE E-7 menyuntik permanen ke buku demo: kas +7 · jurnal +9 ·
    # pinjaman antar-PT +2 · aset tetap +2 · eliminasi konsolidasi +1 · PR +2.
    # Tak satu pun dipantau di sini, jadi INV-GATE-01 melapor "nol residu" sementara
    # laporan kas & neraca demo terus diisi uang yang tidak pernah berpindah.
    # POC-nya kini memulihkan kedua sisi lewat `poc_stock_guard.MONEY_COLLECTIONS`;
    # baris di bawah memastikan POC/gate LAIN tidak bisa mengulangi diam-diam.
    "cash_transactions", "journal_entries", "interco_loans", "fin_fixed_assets",
    "intercompany_eliminations", "purchase_requisitions",
    # ── POC-RESIDU-04 (terukur 2026-08-21 dengan `scripts/ukur_residu_poc.py`) ──
    # Sisa residu terakhir, semuanya di koleksi yang dulu tak dipantau:
    #   system_settings      +2 (POC G-0) · +1 (POC FASE D makloon)
    #   store_credit_ledger  +1 (POC rantai retur)
    #   approval_matrix_log  +2 (POC FASE F R&D)
    #   credit_overrides     +1 (POC FASE F US3)
    # Ketiga yang pertama bukan "sekadar baris": `system_settings` adalah SSOT
    # PERILAKU aplikasi, `store_credit_ledger` adalah SALDO UANG pelanggan, dan
    # `credit_overrides` adalah pembebasan pagar kredit. Residu di sini membuat
    # POC berikutnya lulus/gagal karena keadaan WARISAN, bukan karena kodenya —
    # kelas "hijau palsu" yang paling sulit dipercaya orang saat akhirnya ketemu.
    "system_settings", "store_credit_ledger", "approval_matrix_log",
    "credit_overrides",
    # ── 2026-08-24 (POC FASE N) ───────────────────────────────────────────────
    # `permission_settings` adalah SSOT IZIN yang bisa disunting pemilik dari layar
    # Matriks Izin. POC FASE N menyuntingnya untuk membuktikan alamat notifikasi
    # mengikuti IZIN, lalu "memulihkan" dengan MENGHAPUS barisnya — jadi baris hasil
    # seed lenyap dan `verify_data_integrity` memerah ("kanonik KOSONG") pada setiap
    # POC berikutnya. Residunya tak terlihat di sini karena koleksinya belum dipantau.
    "permission_settings",
    # ── FASE S (2026-08-23) — SAMPLING ────────────────────────────────────────
    # `md_samples` adalah dokumen BERNOMOR (`<ENT>/SMP-#####`) yang POC fase ini
    # buat & hapus berulang; tanpa dipantau, sisa satu dokumen uji akan mengubah
    # angka rapor KPI desainer & papan SLA pada gate BERIKUTNYA — dan yang membaca
    # akan menyalahkan kodenya, bukan residunya.
    # `sample_types` dipantau karena POC menambah/menonaktifkan JENIS untuk
    # membuktikan master bisa bertambah tanpa kode: jenis uji yang tertinggal akan
    # muncul di form permintaan sample milik pemilik.
    "md_samples", "sample_types",
]
QTY_SUFFIX = "_qty"
# Jejak APPEND-ONLY: POC fase memang menjalankan alur nyata sehingga wajar
# meninggalkan catatan audit/notifikasi. Menghapusnya justru merusak jejak.
# Dengan `--ignore-trails`, pemeriksaan difokuskan ke KEBENARAN DATA
# (dokumen transaksi, stok, status SO) — bukan ke banyaknya jejak.
TRAILS = ["audit_logs", "notifications"]


async def fingerprint():
    db = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))[
        os.environ.get("DB_NAME", "test_database")]
    fp = {"counts": {}, "balances": {}, "so_status": {}}
    for c in WATCH:
        try:
            fp["counts"][c] = await db[c].count_documents({})
        except Exception:
            fp["counts"][c] = -1
    # nilai kuantitas stok (bukan hanya jumlah dokumen — perubahan nilai lebih berbahaya)
    async for b in db.inventory_balances.find({}, {"_id": 0}):
        key = f'{b.get("product_id")}|{b.get("warehouse_id")}'
        fp["balances"][key] = {k: v for k, v in b.items() if k.endswith(QTY_SUFFIX)}
    # status/stage SO (state-machine gate pernah membatalkan order seed)
    async for s in db.sales_orders.find({}, {"_id": 0, "id": 1, "number": 1,
                                             "status": 1, "stage": 1}):
        fp["so_status"][s.get("id")] = [s.get("number"), s.get("status"), s.get("stage")]
    return fp


def _diff(before, after, ignore_trails=False):
    problems = []
    for c, n in before["counts"].items():
        if ignore_trails and c in TRAILS:
            continue
        m = after["counts"].get(c, -1)
        if n != m:
            problems.append(f"koleksi '{c}': {n} -> {m} dok  (selisih {m - n:+d})")
    for k, v in before["balances"].items():
        w = after["balances"].get(k)
        if w is None:
            problems.append(f"balance '{k}' HILANG")
            continue
        for field in set(v) | set(w):
            if v.get(field) != w.get(field):
                problems.append(f"balance '{k}'.{field}: {v.get(field)} -> {w.get(field)}")
    for k, v in before["so_status"].items():
        w = after["so_status"].get(k)
        if w is None:
            problems.append(f"sales_order '{k}' HILANG")
        elif v[1:] != w[1:]:
            problems.append(f"sales_order {v[0]}: {tuple(v[1:])} -> {tuple(w[1:])}")
    return problems


async def _ghost_links():
    """Tautan menggantung SAAT INI (INV-REF-04) — dihitung lewat definisi bersama.

    KENAPA DI SINI, bukan cuma di `audit_doc_refs.py`: di `scripts/gate.sh` audit
    relasi dokumen berjalan **sebelum** semua POC, jadi tautan hantu yang
    ditinggalkan sebuah POC baru terlihat pada gate BERIKUTNYA — satu putaran
    terlambat, dan pada saat itu tidak ada lagi yang menghubungkannya dengan POC
    penyebabnya. `--check` berjalan SESUDAH POC, jadi di sinilah tempatnya.
    """
    sys.path.insert(0, str(ROOT / "backend"))
    try:
        from services import doc_refs_service as refs
    except Exception as exc:  # noqa: BLE001
        return [f"doc_refs_service tidak bisa diimpor: {exc}"]
    ghosts = await refs.dangling_refs(limit=10)
    return [f"tautan menggantung: {g['from_number'] or g['from']} "
            f"--{g['rel']}--> {g['to']} (target sudah tidak ada)" for g in ghosts]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--ignore-trails", action="store_true",
                    help="abaikan koleksi jejak append-only (audit_logs, notifications)")
    args = ap.parse_args()

    fp = await fingerprint()

    if args.save:
        SNAP.write_text(json.dumps(fp))
        tot = sum(v for v in fp["counts"].values() if v > 0)
        print(f"{G}[residue]{X} sidik jari disimpan "
              f"({tot} dok · {len(fp['balances'])} balance · {len(fp['so_status'])} SO)")
        return 0

    if not args.check:
        ap.print_help()
        return 0

    if not SNAP.exists():
        print(f"{Y}[residue] tak ada sidik jari awal — SKIP "
              f"(jalankan --save sebelum gate runtime).{X}")
        return 0

    before = json.loads(SNAP.read_text())
    problems = _diff(before, fp, ignore_trails=args.ignore_trails)
    # Hantu tautan TIDAK pernah diabaikan, bahkan dengan `--ignore-trails`:
    # ia bukan "jejak append-only", ia dokumen hidup yang menunjuk ke ketiadaan.
    ghosts = await _ghost_links()
    problems += ghosts
    scope = " (jejak append-only diabaikan)" if args.ignore_trails else ""
    print(f"\n{B}INV-GATE-01 — apakah menjalankan gate merusak data?{scope}{X}")
    if not problems:
        print(f"  {G}[PASS]{X} nol residu: {len(WATCH)} koleksi, "
              f"{len(fp['balances'])} balance, {len(fp['so_status'])} SO, "
              f"nol tautan menggantung — semuanya identik sebelum & sesudah gate.")
        return 0
    print(f"  {R}[FAIL]{X} gate MENINGGALKAN RESIDU ({len(problems)} perubahan):")
    for p in problems[:25]:
        print(f"    {R}✗{X} {p}")
    if len(problems) > 25:
        print(f"    ... dan {len(problems) - 25} perubahan lain")
    print(f"  {Y}→ Guardrail runtime wajib memulihkan data: pakai "
          f"`run_with_restore(main)` / `DbSnapshot` dari scripts/guardrails/_common.py.{X}")
    if any(p.startswith("koleksi 'system_settings'") for p in problems):
        # Jebakan yang memakan satu sesi (2026-08-24): `system_settings` bertambah +4
        # (`makloon` · `receiving` · `hr` · `alerts/lock`) TANPA satu POC pun bersalah —
        # baris itu lahir dari `bootstrap.run_bootstrap()` yang jalan setiap backend
        # START. Penyebabnya: berkas di `backend/` disunting SAAT gate berjalan →
        # uvicorn hot-reload → bootstrap jalan di tengah gate. Gate-nya benar,
        # pengukurannya yang tercemar.
        print(f"  {Y}→ CATATAN: selisih `system_settings` sering BUKAN residu POC. "
              f"Baris `makloon`/`receiving`/`hr`/`alerts` lahir dari bootstrap saat "
              f"backend START. Jangan menyunting berkas di `backend/` selagi gate "
              f"berjalan (hot-reload = bootstrap ulang).{X}")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
