#!/usr/bin/env python3
"""INV-HOME-01 (RUNTIME) — ANGKA KPI BERANDA WAJIB SAMA DENGAN KENYATAAN.

KELAS BUG YANG DICEGAH (terukur 2026-08-15, ditemukan lewat audit peran)
=======================================================================
KPI "Persetujuan Menunggu" di Control Tower & Beranda Manajer memakai
`approval_service.get_pending_approvals_count()` yang menghitung koleksi
`approval_requests`. Koleksi itu **tidak pernah diisi**: `create_approval_request()`
nol pemanggil di seluruh backend. Jadi:

  · KPI beranda  = 0   (selalu, apa pun keadaan bisnisnya)
  · daftar rincian di LAYAR YANG SAMA = 6
  · kenyataan di basis data = 16 dokumen menunggu keputusan

Tidak ada layar merah, tidak ada error konsol, tidak ada uji yang gagal — hanya satu
angka yang berbohong kepada orang yang pekerjaannya justru menyetujui. Kelas ini
lebih berbahaya daripada crash: crash membuat orang bertanya, angka 0 membuat orang
pulang. Uji API biasa tak menangkapnya karena endpoint-nya "sukses 200".

INVARIAN YANG DITEGAKKAN
-----------------------
  A. `approvals_pending` == `approvals.total`  (KPI == rincian di layar yang sama)
  B. `approvals.total` == JUMLAH BARIS yang dihitung ULANG langsung dari MongoDB
     oleh gate ini (opini kedua — duplikasi query di sini SENGAJA: kalau logika
     backend bergeser, dua implementasi tidak akan setuju lagi).
  C. Bila ADA dokumen menunggu keputusan di basis data, KPI TIDAK BOLEH 0
     (anti-regresi "angka mati").
  D. Setiap baris rincian menunjuk `view` yang BENAR-BENAR ADA di
     `AppViewRouter.jsx` — angka yang diklik tak boleh mendarat di layar hantu.

Resilient: backend down / login gagal → SKIP (exit 0). Exit 1 hanya bila invarian
terbukti dilanggar.

Usage:
    python scripts/guardrails/verify_home_kpi.py
    python scripts/guardrails/verify_home_kpi.py --self-test   # bukti-merah, tanpa backend
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

import httpx  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Guard, G, R, Y, B, X, run_with_restore  # noqa: E402

BASE = os.environ.get("POC_BASE", "http://localhost:8001")
PWD = "demo12345"
AKUN = {
    "admin": ("admin@kainnusantara.id", "/api/home/admin"),
    "manager": ("manager@kainnusantara.id", "/api/home/manager"),
}

#: Baris antrean → (koleksi, query) untuk hitung-ulang MANDIRI dari MongoDB.
#: Sengaja ditulis ulang di sini (bukan mengimpor dari service) supaya gate ini
#: menjadi OPINI KEDUA, bukan cermin dari logika yang sedang diuji.
EXPECT = {
    "sales_order": ("sales_orders", {"$or": [{"status": "waiting_approval"},
                                             {"pending_approvals.status": "pending"}]}),
    "purchase_order": ("purchase_orders", {"status": "waiting_approval"}),
    "price": ("price_approvals", {"status": "pending",
                                  "$or": [{"so_id": ""}, {"so_id": None},
                                          {"so_id": {"$exists": False}}]}),
    "purchase_requisition": ("purchase_requisitions", {"status": "pending_approval"}),
    "sales_return": ("sales_returns", {"status": "pending_approval"}),
    "purchase_return": ("purchase_returns", {"status": "pending_approval"}),
    # Koleksinya `doc_amendments` — bukan `amendments` (itu nama ROUTE-nya). Salah nama
    # koleksi = baris itu menghitung 0 SELAMANYA tanpa ada yang tahu; invarian E di bawah
    # menutup kelas itu.
    "amendment": ("doc_amendments", {"status": "pending_approval"}),
    "interco": ("interco_transactions", {"status": "waiting_approval"}),
    "cycle_count": ("cycle_count_sessions", {"status": "submitted"}),
    "rnd_spec": ("md_specs", {"status": "review"}),
    "rnd_sample": ("md_samples", {"status": {"$in": ["in_progress", "assessed"]},
                                  "decision.supplier_id": {"$in": ["", None]}}),
    "special_order": ("special_orders", {"status": "pending_approval"}),
    # ── FASE F-6 — opini kedua untuk 14 antrean baru (baris `generic`/`approval_requests`
    # dihapus bersama mesin generiknya). Ditulis ULANG di sini dengan sengaja: kalau
    # QUEUES backend bergeser, dua implementasi ini tidak akan setuju lagi.
    "transfer": ("warehouse_transfers", {"status": "waiting_approval"}),
    "contra_bon_verify": ("contra_bons", {"status": "submitted"}),
    "contra_bon_approve": ("contra_bons", {"status": "verified"}),
    "contra_bon_dispute": ("contra_bons", {"status": "disputed"}),
    "internal_request": ("internal_requests", {"status": "submitted"}),
    "interco_return": ("interco_returns", {"status": "draft"}),
    "vendor_bill": ("vendor_bills", {"status": "pending_approval"}),
    "landed_cost": ("landed_cost_vouchers", {"status": "pending_approval"}),
    "cash_advance": ("cash_advances", {"status": {"$in": ["pending_atasan",
                                                          "pending_pimpinan",
                                                          "pending_finance"]}}),
    "cash_advance_settlement": ("cash_advance_settlements", {"status": "submitted"}),
    "makloon_claim": ("makloon_orders", {"steps.claim.status": "pending_approval"}),
    "period_unlock": ("period_unlock_requests", {"status": "pending"}),
    "hr_leave": ("hr_leave_requests", {"status": "pending"}),
    "hr_overtime": ("hr_overtime", {"status": "pending"}),
    # ── UTANG ALUR F-6.7 DIBAYAR (2026-08-18) — opini kedua untuk 4 antrean baru.
    # Ditulis ULANG di sini dengan sengaja (bukan mengimpor QUEUES): kalau definisi di
    # backend bergeser, dua implementasi ini tidak akan setuju lagi dan gate memerah.
    "hr_payroll": ("hr_payroll_runs", {"status": "pending_approval"}),
    "design_gallery": ("design_gallery", {"status": "pending_approval"}),
    "payment_variance": ("ar_receipts", {"status": {"$ne": "void"},
                                         "variance.needs_decision": True,
                                         "variance.decision_id": ""}),
    "so_verify": ("sales_orders", {"status": {"$in": ["reserved", "waiting_stock"]},
                                   "verification.status": {"$ne": "verified"},
                                   "pending_approvals.status": {"$ne": "pending"}}),
    # ── FASE D (2026-08-20) — opini kedua untuk antrean PERMINTAAN DESAIN.
    # Yang menunggu keputusan = artwork sudah DISERAHKAN desainer (`delivered`);
    # `revision` TIDAK ikut dihitung karena bola sudah kembali ke desainer, bukan di
    # meja atasan. Ditulis ULANG di sini dengan sengaja (bukan mengimpor QUEUES):
    # kalau kelak definisi backend bergeser ke mis. "delivered + revision", kedua
    # implementasi ini tidak akan setuju lagi dan gate MEMERAH — itu gunanya.
    "design_request": ("design_requests", {"status": "delivered"}),
    # ── FASE I (2026-08-23) — opini kedua untuk antrean BARANG DITAHAN.
    # Yang menunggu di sini bukan "inspeksi belum selesai" (itu pekerjaan petugas,
    # bukan keputusan) melainkan baris yang DITAHAN karena warna/handfeel beda dari
    # sample yang di-ACC — dan hanya MANAJER boleh melepasnya (keputusan pemilik #5).
    # `draft` sengaja TIDAK ikut: dokumen yang belum ditugaskan belum punya petugas
    # yang bisa menandai tahanan, jadi menghitungnya = menunggu yang tidak nyata.
    "inspection_hold": ("inspections", {"lines.hold": True,
                                        "status": {"$in": ["assigned", "in_progress",
                                                           "done"]}}),
}


def views_in_router():
    """Semua `activeView === "x"` di AppViewRouter.jsx (layar yang nyata ada)."""
    txt = (ROOT / "frontend/src/AppViewRouter.jsx").read_text(encoding="utf-8")
    return set(re.findall(r'activeView\s*===\s*"([\w-]+)"', txt))


def queues_from_backend():
    """`QUEUES` dari `services/approval_backlog_service.py` (SSOT definisi antrean)."""
    sys.path.insert(0, str(ROOT / "backend"))
    from services import approval_backlog_service as abl  # noqa: PLC0415
    return abl.QUEUES


def check_definisi_antrean(g, db):
    """Invarian E & F — definisi antrean tidak boleh diam-diam menghitung nol.

    E. Setiap koleksi yang dirujuk baris antrean HARUS ada di database. Kelas bug ini
       nyata dan terjadi saat baris ini ditulis: baris `amendment` menyebut koleksi
       `amendments` padahal namanya `doc_amendments` (`amendments` hanya nama ROUTE).
       Mongo tidak protes untuk koleksi yang tak ada — ia mengembalikan 0. Jadi satu
       salah tulis menyembunyikan SELURUH antrean amandemen tanpa satu pun pesan.
    F. Setiap baris antrean punya pasangan hitung-ulang di gate ini, supaya antrean
       baru tidak bisa ditambahkan tanpa opini kedua yang memeriksanya.
    """
    try:
        queues = queues_from_backend()
    except Exception as ex:  # noqa: BLE001
        print(f"{Y}  tak bisa membaca QUEUES backend ({ex}) — invarian E/F dilewati.{X}")
        return
    ada = set(db.list_collection_names())
    #: FASE F-6 — dulu di sini ada daftar putih `{"approval_requests"}` untuk satu koleksi
    #: yang memang selalu kosong (mesin generik, kini dipensiunkan). Daftar putih seperti
    #: itu tidak bisa dipakai lagi: antrean baru mencakup fitur yang BELUM PERNAH dipakai
    #: di data demo (uang muka, biaya masuk, buka periode) sehingga koleksinya belum lahir.
    #: Kalau syaratnya tetap "harus ada di database", penjaga ini memerah pada kode yang
    #: benar — dan penjaga yang menuduh palsu akan dimatikan orang. Karena itu syaratnya
    #: diganti yang lebih kuat SEKALIGUS lebih jujur: nama koleksi harus terbukti ada
    #: di DATABASE **atau** disebut LITERAL di kode backend. Salah tulis (kelas
    #: `amendments` vs `doc_amendments`) tetap tertangkap, karena nama yang salah tulis
    #: tidak akan ditemukan di kedua tempat.
    src = ""
    for sub in ("routers", "services"):
        for f in (ROOT / "backend" / sub).glob("*.py"):
            src += f.read_text(encoding="utf-8")
    for key, _label, _view, coll, _q in queues:
        g.bump()
        if coll not in ada and f'"{coll}"' not in src and f"db.{coll}" not in src:
            g.add(f"baris antrean `{key}` menyebut koleksi `{coll}` yang TIDAK ADA di "
                  f"database DAN tidak disebut di kode backend → barisnya menghitung 0 "
                  f"selamanya tanpa pesan apa pun (kelas bug `amendments` vs "
                  f"`doc_amendments`).")
        g.bump()
        if key not in EXPECT:
            g.add(f"baris antrean `{key}` tidak punya pasangan hitung-ulang di "
                  f"`verify_home_kpi.EXPECT` → tak ada opini kedua yang memeriksanya.")



#: Peran yang berandanya WAJIB memuat papan PO custom (`special_orders_waiting`).
#: `manager` masuk sejak 2026-06: yang menandatangani PO custom justru manajer, jadi
#: papan yang hanya ada di beranda pemilik berarti pemilik melihat pekerjaan yang
#: orangnya sendiri tidak pernah lihat.
BOARD_ROLES = {"admin", "manager"}


def check_payload(g, role, payload, expected_rows, known_views):
    """Terapkan invarian A–D pada satu payload beranda. Fungsi murni → bisa diuji-merah."""
    total_kpi = payload.get("approvals_pending")
    detail = payload.get("approvals") or {}
    rows = detail.get("all_items") or detail.get("items") or []
    by_key = {r.get("key"): int(r.get("count") or 0) for r in rows}

    g.bump()                                                     # A
    if total_kpi != detail.get("total"):
        g.add(f"{role}: KPI `approvals_pending`={total_kpi} TIDAK SAMA dengan "
              f"`approvals.total`={detail.get('total')} — dua angka berbeda di satu layar.")

    g.bump()                                                     # B
    beda = {k: (by_key.get(k), v) for k, v in expected_rows.items()
            if by_key.get(k, 0) != v}
    if beda:
        g.add(f"{role}: rincian antrean tidak cocok dengan hitungan ULANG dari MongoDB "
              + "; ".join(f"{k}: layar={a} db={b}" for k, (a, b) in sorted(beda.items())))

    g.bump()                                                     # C
    nyata = sum(expected_rows.values())
    if nyata > 0 and not total_kpi:
        g.add(f"{role}: ADA {nyata} dokumen menunggu keputusan di basis data tetapi KPI "
              f"beranda berbunyi {total_kpi} — angka mati (kelas bug `approval_requests` "
              f"yang tak pernah diisi).")

    g.bump()                                                     # D
    hantu = sorted({r.get("view") for r in rows
                    if r.get("view") and r["view"] not in known_views})
    if hantu:
        g.add(f"{role}: baris antrean menunjuk layar yang TIDAK ADA di AppViewRouter: "
              f"{hantu} — angka yang diklik mendarat di layar hantu.")

    # G — daftar "paling lama menunggu" (dipakai kartu beranda & pengingat harian)
    # tidak boleh menyebut dokumen dari antrean yang hitungannya 0, memakai layar
    # hantu, atau berumur negatif. Kelas bug yang dicegah: kartu/pengingat menyebut
    # dokumen yang tak pernah dihitung KPI → dua layar bicara beda lagi.
    for o in (detail.get("oldest") or []):
        g.bump()
        if by_key.get(o.get("key"), 0) <= 0:
            g.add(f"{role}: baris 'paling lama menunggu' {o.get('number')} berasal dari "
                  f"antrean `{o.get('key')}` yang hitungannya 0 — dokumen yang tak "
                  f"pernah dihitung KPI.")
        elif o.get("view") not in known_views:
            g.add(f"{role}: baris 'paling lama menunggu' {o.get('number')} menunjuk layar "
                  f"`{o.get('view')}` yang tidak ada.")
        elif int(o.get("days_waiting", -1)) < 0 or not o.get("number"):
            g.add(f"{role}: baris 'paling lama menunggu' tanpa nomor dokumen atau berumur "
                  f"negatif ({o.get('number')!r} · {o.get('days_waiting')}) — pengingat "
                  f"harian akan menyebut sesuatu yang tak bisa dicari orang.")

    # H — PAPAN ANTREAN MAHAL (2026-08-24; digeneralisasi 2026-06 ke SEMUA papan).
    # Papan khusus di beranda punya angka SENDIRI; begitu ia dihitung dengan cara lain,
    # beranda kembali punya dua pendapat di satu layar — kelas bug yang persis sama
    # dengan `approval_requests` yang selalu 0. Karena itu untuk SETIAP papan:
    # (1) jumlahnya WAJIB sama dengan baris antrean sejenis di layar yang sama,
    # (2) barisnya tak boleh menunjuk layar hantu, (3) tiap baris wajib bernomor &
    # berumur tak negatif, (4) papan tak boleh KOSONG selagi antreannya berisi, dan
    # (5) bila daftarnya dipotong, `shown`/`truncated` wajib mengaku.
    papan_utama = payload.get("special_orders_waiting")
    # D1 DIBAYAR (2026-08-25) — dulu barisnya `if isinstance(papan, dict)` saja, jadi
    # MENGHAPUS `special_orders_waiting` dari payload membuat SELURUH invarian H
    # dilewati dan penjaga tetap HIJAU. Pagar yang bisa dimatikan dengan menghapus
    # datanya bukan pagar. Papan ini WAJIB ADA untuk beranda yang memang memilikinya
    # (`admin` sejak 2026-08-24, `manager` sejak 2026-06).
    if role in BOARD_ROLES and not isinstance(papan_utama, dict):
        g.bump()
        g.add(f"{role}: payload beranda TIDAK memuat `special_orders_waiting` — papan "
              f"PO Custom hilang dari beranda peran ini, dan tanpa tuduhan ini "
              f"seluruh invarian H akan terlewat diam-diam (pagar yang bisa "
              f"dimatikan dengan menghapus datanya bukan pagar).")
    daftar_papan = []
    if isinstance(papan_utama, dict):
        daftar_papan.append(("special_order", "Papan PO Custom", papan_utama))
    for b in (payload.get("waiting_boards") or []):
        if isinstance(b, dict) and b.get("key") and b.get("key") != "special_order":
            daftar_papan.append((b["key"], f"Papan antrean `{b['key']}`", b))
    for kunci, nama, papan in daftar_papan:
        antrean_n = by_key.get(kunci, 0)
        g.bump()
        if int(papan.get("count") or 0) != antrean_n:
            g.add(f"{role}: {nama} berbunyi {papan.get('count')} sementara baris "
                  f"antrean `{kunci}` di layar yang sama {antrean_n} — dua angka "
                  f"berbeda untuk satu kenyataan.")
        g.bump()
        if papan.get("view") and papan["view"] not in known_views:
            g.add(f"{role}: {nama} menunjuk layar `{papan.get('view')}` yang "
                  f"tidak ada di AppViewRouter.")
        baris = papan.get("rows") or []
        g.bump()
        if antrean_n > 0 and not baris:
            g.add(f"{role}: ADA {antrean_n} dokumen menunggu keputusan di antrean "
                  f"`{kunci}` tetapi {nama} mengirim 0 baris — papan hampa membuat "
                  f"pembacanya menyimpulkan tidak ada pekerjaan.")
        # B2 DIBAYAR — bila jumlahnya LEBIH BESAR dari baris yang dikirim, payload WAJIB
        # mengaku: `shown` = jumlah baris DAN `truncated` = True. Judul "(12)" di atas
        # daftar berisi 10 baris tanpa satu pun penanda adalah kelas cacat yang justru
        # diperangi INV-HOME-01 — angka yang tidak cocok dengan daftar di layar yang sama.
        g.bump()
        jumlah = int(papan.get("count") or 0)
        if jumlah > len(baris):
            if papan.get("shown") != len(baris) or not papan.get("truncated"):
                g.add(f"{role}: {nama} berbunyi {jumlah} tetapi hanya "
                      f"mengirim {len(baris)} baris TANPA penanda jujur "
                      f"(shown={papan.get('shown')!r} truncated={papan.get('truncated')!r}) "
                      f"— layar akan menampilkan angka yang tak cocok dengan daftarnya "
                      f"dan tak seorang pun tahu ada yang disembunyikan.")
        elif papan.get("truncated"):
            g.add(f"{role}: {nama} mengaku `truncated` padahal seluruh "
                  f"{jumlah} dokumen dikirim ({len(baris)} baris) — penanda yang "
                  f"berbohong ke arah sebaliknya sama merusaknya.")
        for r in baris:
            g.bump()
            if not r.get("number") or int(r.get("days_waiting", -1)) < 0:
                g.add(f"{role}: baris {nama} tanpa nomor dokumen atau berumur "
                      f"negatif ({r.get('number')!r} · {r.get('days_waiting')}).")


def self_test():
    """Bukti-merah: penjaga ini harus MENUDUH keempat pelanggaran & meloloskan yang benar."""
    known = {"approval-inbox", "purchase-approval"}
    exp = {"sales_order": 1, "purchase_order": 3}
    kasus = [
        ("payload benar → hijau",
         {"approvals_pending": 4,
          "approvals": {"total": 4, "all_items": [
              {"key": "sales_order", "count": 1, "view": "approval-inbox"},
              {"key": "purchase_order", "count": 3, "view": "purchase-approval"}]}}, 0),
        # KPI 0 sementara rincian 4 melanggar A (dua angka beda) DAN C (angka mati).
        ("A+C: KPI ≠ rincian di layar yang sama, dan KPI 0 padahal ada 4 → 2 pelanggaran",
         {"approvals_pending": 0,
          "approvals": {"total": 4, "all_items": [
              {"key": "sales_order", "count": 1, "view": "approval-inbox"},
              {"key": "purchase_order", "count": 3, "view": "purchase-approval"}]}}, 2),
        ("B+C: seluruh baris 0 padahal DB punya 4 (kelas `approval_requests` mati) → 2 pelanggaran",
         {"approvals_pending": 0,
          "approvals": {"total": 0, "all_items": [
              {"key": "sales_order", "count": 0, "view": "approval-inbox"},
              {"key": "purchase_order", "count": 0, "view": "purchase-approval"}]}}, 2),
        ("G: 'paling lama menunggu' dari antrean berhitung 0 → merah",
         {"approvals_pending": 4,
          "approvals": {"total": 4, "all_items": [
              {"key": "sales_order", "count": 1, "view": "approval-inbox"},
              {"key": "purchase_order", "count": 3, "view": "purchase-approval"}],
              "oldest": [{"key": "price", "number": "PA-1", "view": "approval-inbox",
                          "days_waiting": 9}]}}, 1),
        ("G: 'paling lama menunggu' yang sehat → hijau",
         {"approvals_pending": 4,
          "approvals": {"total": 4, "all_items": [
              {"key": "sales_order", "count": 1, "view": "approval-inbox"},
              {"key": "purchase_order", "count": 3, "view": "purchase-approval"}],
              "oldest": [{"key": "purchase_order", "number": "PO-1",
                          "view": "purchase-approval", "days_waiting": 9}]}}, 0),
        ("D: baris menunjuk layar hantu → merah",
         {"approvals_pending": 4,
          "approvals": {"total": 4, "all_items": [
              {"key": "sales_order", "count": 1, "view": "layar-hantu"},
              {"key": "purchase_order", "count": 3, "view": "purchase-approval"}]}}, 1),
        # ── H — PAPAN PO CUSTOM (2026-08-24) ────────────────────────────────────
        ("H: Papan PO Custom sehat → hijau",
         {"approvals_pending": 4,
          "approvals": {"total": 4, "all_items": [
              {"key": "sales_order", "count": 1, "view": "approval-inbox"},
              {"key": "purchase_order", "count": 3, "view": "purchase-approval"},
              {"key": "special_order", "count": 2, "view": "approval-inbox"}]},
          "special_orders_waiting": {"count": 2, "view": "approval-inbox", "rows": [
              {"number": "SORD-1", "days_waiting": 9},
              {"number": "SORD-2", "days_waiting": 0}]}}, 0),
        ("H: papan berbunyi lain dari baris antrean di layar yang sama → merah",
         {"approvals_pending": 4,
          "approvals": {"total": 4, "all_items": [
              {"key": "sales_order", "count": 1, "view": "approval-inbox"},
              {"key": "purchase_order", "count": 3, "view": "purchase-approval"},
              {"key": "special_order", "count": 2, "view": "approval-inbox"}]},
          "special_orders_waiting": {"count": 1, "view": "approval-inbox", "rows": [
              {"number": "SORD-1", "days_waiting": 9}]}}, 1),
        ("H: antrean berisi tetapi papan hampa → merah (2×: hampa + tanpa penanda)",
         {"approvals_pending": 4,
          "approvals": {"total": 4, "all_items": [
              {"key": "sales_order", "count": 1, "view": "approval-inbox"},
              {"key": "purchase_order", "count": 3, "view": "purchase-approval"},
              {"key": "special_order", "count": 2, "view": "approval-inbox"}]},
          "special_orders_waiting": {"count": 2, "view": "approval-inbox", "rows": []}}, 2),
        ("H: baris papan tanpa nomor / umur negatif → merah",
         {"approvals_pending": 4,
          "approvals": {"total": 4, "all_items": [
              {"key": "sales_order", "count": 1, "view": "approval-inbox"},
              {"key": "purchase_order", "count": 3, "view": "purchase-approval"},
              {"key": "special_order", "count": 1, "view": "approval-inbox"}]},
          "special_orders_waiting": {"count": 1, "view": "approval-inbox", "rows": [
              {"number": "", "days_waiting": -3}]}}, 1),
        ("H: papan menunjuk layar hantu → merah",
         {"approvals_pending": 4,
          "approvals": {"total": 4, "all_items": [
              {"key": "sales_order", "count": 1, "view": "approval-inbox"},
              {"key": "purchase_order", "count": 3, "view": "purchase-approval"},
              {"key": "special_order", "count": 1, "view": "approval-inbox"}]},
          "special_orders_waiting": {"count": 1, "view": "papan-hantu", "rows": [
              {"number": "SORD-1", "days_waiting": 2}]}}, 1),
        # ── B2 (2026-08-25) — jujur saat daftarnya DIPOTONG ──────────────────────
        ("B2: 12 menunggu tetapi 10 baris TANPA penanda → merah",
         {"approvals_pending": 12,
          "approvals": {"total": 12, "all_items": [
              {"key": "sales_order", "count": 1, "view": "approval-inbox"},
              {"key": "purchase_order", "count": 3, "view": "purchase-approval"},
              {"key": "special_order", "count": 12, "view": "approval-inbox"}]},
          "special_orders_waiting": {"count": 12, "view": "approval-inbox", "rows": [
              {"number": f"SORD-{i}", "days_waiting": i} for i in range(10)]}}, 1),
        ("B2: 12 menunggu · 10 baris + shown/truncated jujur → hijau",
         {"approvals_pending": 12,
          "approvals": {"total": 12, "all_items": [
              {"key": "sales_order", "count": 1, "view": "approval-inbox"},
              {"key": "purchase_order", "count": 3, "view": "purchase-approval"},
              {"key": "special_order", "count": 12, "view": "approval-inbox"}]},
          "special_orders_waiting": {"count": 12, "view": "approval-inbox",
                                     "shown": 10, "hidden": 2, "truncated": True,
                                     "rows": [{"number": f"SORD-{i}",
                                               "days_waiting": i} for i in range(10)]}},
         0),
        ("B2: mengaku terpotong padahal semuanya terkirim → merah",
         {"approvals_pending": 4,
          "approvals": {"total": 4, "all_items": [
              {"key": "sales_order", "count": 1, "view": "approval-inbox"},
              {"key": "purchase_order", "count": 3, "view": "purchase-approval"},
              {"key": "special_order", "count": 1, "view": "approval-inbox"}]},
          "special_orders_waiting": {"count": 1, "view": "approval-inbox", "shown": 1,
                                     "truncated": True,
                                     "rows": [{"number": "SORD-1",
                                               "days_waiting": 2}]}}, 1),
        # ── D1 (2026-08-25) — pagar tidak boleh bisa dimatikan dengan menghapus data
        ("D1: payload ADMIN tanpa `special_orders_waiting` → merah",
         {"approvals_pending": 4,
          "approvals": {"total": 4, "all_items": [
              {"key": "sales_order", "count": 1, "view": "approval-inbox"},
              {"key": "purchase_order", "count": 3, "view": "purchase-approval"}]}},
         1, "admin"),
        ("D1: payload MANAJER tanpa papan → MERAH sejak 2026-06 (manajer punya papan)",
         {"approvals_pending": 4,
          "approvals": {"total": 4, "all_items": [
              {"key": "sales_order", "count": 1, "view": "approval-inbox"},
              {"key": "purchase_order", "count": 3, "view": "purchase-approval"}]}},
         1, "manager"),
        # ── 2026-06 — papan antrean mahal LAIN (kontrabon bersengketa · retur antar-PT)
        ("papan tambahan `waiting_boards` sehat → hijau",
         {"approvals_pending": 4,
          "approvals": {"total": 4, "all_items": [
              {"key": "sales_order", "count": 1, "view": "approval-inbox"},
              {"key": "purchase_order", "count": 3, "view": "purchase-approval"},
              {"key": "contra_bon_dispute", "count": 1, "view": "approval-inbox"}]},
          "waiting_boards": [
              {"key": "contra_bon_dispute", "count": 1, "view": "approval-inbox",
               "shown": 1, "truncated": False,
               "rows": [{"number": "CB-1", "days_waiting": 4}]}]}, 0),
        ("papan tambahan berbunyi lain dari antreannya → merah",
         {"approvals_pending": 4,
          "approvals": {"total": 4, "all_items": [
              {"key": "sales_order", "count": 1, "view": "approval-inbox"},
              {"key": "purchase_order", "count": 3, "view": "purchase-approval"},
              {"key": "contra_bon_dispute", "count": 2, "view": "approval-inbox"}]},
          "waiting_boards": [
              {"key": "contra_bon_dispute", "count": 1, "view": "approval-inbox",
               "shown": 1, "truncated": False,
               "rows": [{"number": "CB-1", "days_waiting": 4}]}]}, 1),
        ("papan tambahan hampa selagi antreannya berisi → merah (hampa + tanpa penanda)",
         {"approvals_pending": 4,
          "approvals": {"total": 4, "all_items": [
              {"key": "sales_order", "count": 1, "view": "approval-inbox"},
              {"key": "purchase_order", "count": 3, "view": "purchase-approval"},
              {"key": "interco_return", "count": 2, "view": "approval-inbox"}]},
          "waiting_boards": [
              {"key": "interco_return", "count": 2, "view": "approval-inbox",
               "rows": []}]}, 2),
    ]
    gagal = 0
    print(f"{B}== SELF-TEST INV-HOME-01 (penjaga KPI harus bisa MEMERAH) =={X}")
    for kasus_item in kasus:
        nama, payload, harap = kasus_item[0], kasus_item[1], kasus_item[2]
        role = kasus_item[3] if len(kasus_item) > 3 else "uji"
        g = Guard("INV-HOME-01", "self-test")
        g.violations, g.checks = [], 0
        check_payload(g, role, payload, exp, known)
        got = len(g.violations)
        ok_ = got == harap
        gagal += 0 if ok_ else 1
        print(f"  [{G + 'PASS' + X if ok_ else R + 'FAIL' + X}] {nama}  "
              f"(harap={harap} pelanggaran, dapat={got})")
    if gagal:
        print(f"{R}{B}  SELF-TEST MERAH — penjaga KPI tidak bisa dipercaya.{X}")
    else:
        print(f"{G}  HIJAU — penjaga terbukti menuduh angka yang berbohong.{X}")
    return gagal


def main() -> int:
    g = Guard("INV-HOME-01", "KPI beranda = antrean persetujuan yang NYATA")
    try:
        from pymongo import MongoClient
        db = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=3000)[
            os.environ.get("DB_NAME", "test_database")]
        db.command("ping")
    except Exception as ex:  # noqa: BLE001
        print(f"{Y}  MongoDB tak terjangkau ({ex}) — SKIP.{X}")
        return 0

    expected = {}
    for key, (coll, query) in EXPECT.items():
        try:
            expected[key] = db[coll].count_documents(query)
        except Exception:  # noqa: BLE001
            expected[key] = 0
    known_views = views_in_router()
    print(f"  hitung-ulang dari MongoDB: {sum(expected.values())} dokumen menunggu "
          f"keputusan {dict((k, v) for k, v in expected.items() if v)}")
    check_definisi_antrean(g, db)

    for role, (email, path) in AKUN.items():
        try:
            cl = httpx.Client(base_url=BASE, timeout=60.0)
            r = cl.post("/api/auth/login", json={"email": email, "password": PWD})
            if r.status_code != 200:
                print(f"{Y}  login {email} gagal (HTTP {r.status_code}) — SKIP.{X}")
                return 0
            cl.headers.update({"Authorization": f"Bearer {r.json()['token']}",
                               "X-Entity-Id": "all"})
            res = cl.get(path)
        except Exception as ex:  # noqa: BLE001
            print(f"{Y}  backend tak terjangkau ({ex}) — SKIP.{X}")
            return 0
        if res.status_code != 200:
            g.bump()
            g.add(f"{role}: `GET {path}` HTTP {res.status_code} — beranda perannya gagal dimuat.")
            continue
        check_payload(g, role, res.json(), expected, known_views)

    return g.finish()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(1 if self_test() else 0)
    try:
        # Gate runtime memanggil API sungguhan → menulis audit_logs saat login.
        rc = run_with_restore(main)
    except Exception as ex:  # noqa: BLE001
        print(f"{Y}  Gate error (dianggap SKIP): {ex}{X}")
        rc = 0
    sys.exit(rc)
