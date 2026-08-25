"""services/approval_backlog_service.py — SATU sumber "apa yang menunggu keputusan".

MASALAH YANG DISELESAIKAN (terukur 2026-08-15)
=============================================
Angka "berapa yang menunggu persetujuan" dulu dihitung di TIGA tempat berbeda dan
ketiganya tidak pernah sama:

  1. KPI beranda (`home_service`) → `approval_service.get_pending_approvals_count()`
     yang menghitung koleksi `approval_requests`. Koleksi itu **tak pernah diisi
     siapa pun** (`create_approval_request()` nol pemanggil) → KPI SELALU **0**.
  2. Daftar rincian di beranda manajer → 4 baris buatan sendiri → **6**.
  3. Layar "Pusat Persetujuan" → 7 sumber yang diambil & dihitung di BROWSER,
     jadi angkanya hanya sebesar yang boleh dibaca peran itu.

Kenyataan di basis data: **16** dokumen memang menunggu keputusan. Orang yang
pekerjaannya menyetujui melihat "0" di berandanya lalu pulang; kalau ia membuka
Pusat Persetujuan ia melihat angka ketiga lagi. Tidak ada error, tidak ada uji
yang gagal — hanya angka yang berbohong.

Modul ini menjadi SATU-SATUNYA tempat definisi itu ditulis. KPI beranda, rincian
beranda, dan ringkasan Pusat Persetujuan semuanya membaca dari sini, sehingga
mustahil berbeda pendapat. Penjaga `scripts/guardrails/verify_home_kpi.py`
(INV-HOME-01) menegakkannya lewat HTTP nyata + hitung-ulang mandiri dari MongoDB.

ATURAN MENAMBAH ANTREAN BARU
---------------------------
Satu baris = satu keadaan dokumen yang MENUNGGU KEPUTUSAN ORANG, dan `view`-nya
WAJIB layar yang benar-benar ada di `AppViewRouter.jsx` (dijaga invarian D). Jangan
menambah baris yang tak punya tempat kerja — angka tanpa jalan hanya membuat panik.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from db import db

#: (kunci, label, layar tujuan, koleksi, query) — urut sesuai kelaziman kerja.
QUEUES: List[tuple] = [
    ("sales_order", "Pesanan penjualan menunggu ACC", "approval-inbox", "sales_orders",
     # SSOT persetujuan SO = `pending_approvals`; `status` lama tetap dihitung supaya
     # dokumen tahap sebelumnya tidak hilang dari antrean.
     {"$or": [{"status": "waiting_approval"}, {"pending_approvals.status": "pending"}]}),
    ("purchase_order", "Pesanan pembelian menunggu ACC", "purchase-approval",
     "purchase_orders", {"status": "waiting_approval"}),
    ("price", "Permintaan harga khusus", "price-approvals", "price_approvals",
     # yang tertaut SO sudah terhitung di baris `sales_order` (hindari dobel).
     {"status": "pending", "$or": [{"so_id": ""}, {"so_id": None},
                                   {"so_id": {"$exists": False}}]}),
    ("purchase_requisition", "Permintaan pembelian (PR) menunggu ACC",
     "purchase-requisitions", "purchase_requisitions", {"status": "pending_approval"}),
    ("sales_return", "Retur jual menunggu ACC", "returns", "sales_returns",
     {"status": "pending_approval"}),
    ("purchase_return", "Retur beli menunggu ACC", "purchase-returns", "purchase_returns",
     {"status": "pending_approval"}),
    ("amendment", "Koreksi & amandemen menunggu ACC", "amendments", "doc_amendments",
     # Koleksinya `doc_amendments` (bukan `amendments` — itu nama ROUTE-nya). Versi
     # pertama baris ini salah menebak nama koleksi sehingga menghitung 0 sementara
     # layar Pusat Persetujuan menampilkan 1 amandemen menunggu: ketidaksesuaian itu
     # langsung terlihat begitu KEDUA angka dipasang di satu layar — alasan kenapa
     # ringkasan antrean ditaruh persis di atas daftarnya.
     {"status": "pending_approval"}),
    ("interco", "Transaksi antar-PT menunggu ACC", "interco-transactions",
     # US22 — di atas `antar_entitas.approval_threshold_rupiah` transaksi antar-PT
     # otomatis menunggu persetujuan. Tanpa baris ini ambang itu menahan uang
     # tanpa satu pun angka yang memberi tahu siapa pun.
     "interco_transactions", {"status": "waiting_approval"}),
    ("cycle_count", "Stock opname menunggu ACC", "operations", "cycle_count_sessions",
     {"status": "submitted"}),
    ("rnd_spec", "Spesifikasi desain menunggu ACC", "rnd-specs", "md_specs",
     {"status": "review"}),
    ("rnd_sample", "Sample menunggu keputusan", "rnd-samples", "md_samples",
     {"status": {"$in": ["in_progress", "assessed"]},
      "decision.supplier_id": {"$in": ["", None]}}),
    # ── FASE S (2026-08-23) — SENGAJA BUKAN ANTREAN: `POST /rnd/samples/{id}/finish`
    # dan `POST /rnd/samples/{id}/deliver`.
    # Keputusan pemilik sesi FASE S: menandai sample JADI dan mencatat PENGIRIMANNYA
    # adalah **pencatatan pelaksanaan**, bukan keputusan yang menunggu persetujuan
    # siapa pun. Karena itu keduanya memakai izin `rnd.submit` (pelaksana), bukan
    # `rnd.decide`, dan TIDAK didaftarkan sebagai antrean di sini.
    # Alasan itu ditulis DI SINI — bukan di `verify_approval_queues.DOOR_EXEMPT` —
    # karena `DOOR_RE` hanya mengenali path ber-kata `approve|reject|verify|decide`,
    # sehingga entri di sana akan langsung dianggap "klasifikasi basi" dan
    # memerahkan INV-APPR-01 atas alasan yang salah.
    # Yang MENJAGA keputusan ini tetap benar adalah `INV-SAMPLE-01` aturan G: gate itu
    # memeriksa kedua endpoint masih memakai izin pelaksana dan urutannya (jadi → kirim)
    # ditegakkan server. Begitu suatu hari pengiriman sample memang harus disetujui,
    # ganti izinnya ke pintu keputusan dan daftarkan barisnya di sini — gate akan
    # menuntutnya.
    ("special_order", "Pesanan khusus menunggu ACC", "special-orders", "special_orders",
     {"status": "pending_approval"}),
    # ── FASE F-6 (2026-08-17) — 14 ANTREAN YANG SELAMA INI TAK TERHITUNG ─────────
    # Baris `generic` (mesin persetujuan `approval_requests`) DIHAPUS: koleksinya tak
    # pernah diisi siapa pun, endpoint & izin `approval.approve` dipensiunkan — rincian
    # di `services/approval_service.py`. Menghitung koleksi mati membuat orang percaya
    # ada pintu yang sebenarnya tidak ada.
    #
    # Sebagai gantinya, sapuan bukti (endpoint `approve|reject|verify|decide` di KODE +
    # sapuan status di DATA) menemukan pintu keputusan NYATA yang sudah lama hidup tanpa
    # satu pun baris antrean yang menghitungnya. Selama itu KPI "Persetujuan Menunggu"
    # tetap berbohong — hanya dengan selisih yang lebih kecil. Penjaga INV-APPR-01
    # (`scripts/guardrails/verify_approval_queues.py`) kini membuat pintu baru mustahil
    # ditambahkan tanpa antreannya.
    ("transfer", "Transfer gudang menunggu ACC", "operations", "warehouse_transfers",
     {"status": "waiting_approval"}),
    ("contra_bon_verify", "Kontrabon menunggu verifikasi", "contra-bons", "contra_bons",
     {"status": "submitted"}),
    ("contra_bon_approve", "Kontrabon menunggu persetujuan", "contra-bons", "contra_bons",
     {"status": "verified"}),
    ("contra_bon_dispute", "Kontrabon bersengketa menunggu keputusan", "contra-bons",
     "contra_bons", {"status": "disputed"}),
    ("internal_request", "Permintaan internal antar-PT menunggu keputusan",
     "internal-requests", "internal_requests", {"status": "submitted"}),
    # FASE D — permintaan desain yang HASILNYA sudah diserahkan menunggu keputusan
    # atasan (ACC / minta revisi ber-alasan). Tanpa baris ini `INV-APPR-01` memerah
    # karena menemukan pintu `/approve` & `/reject` di router tanpa antrean.
    ("design_request", "Permintaan desain menunggu keputusan", "design-requests",
     "design_requests", {"status": "delivered"}),
    # FASE I — barang yang DITAHAN karena warna/handfeel beda dari sample yang di-ACC.
    # Yang menunggu di sini BUKAN "inspeksi belum selesai" (itu pekerjaan, bukan
    # keputusan) melainkan tahanan yang hanya MANAJER boleh melepas (keputusan
    # pemilik #5). Tanpa antrean ini, barang bisa tertahan di gudang berminggu-minggu
    # tanpa ada satu pun layar yang menyebutnya.
    ("inspection_hold", "Barang ditahan (warna/handfeel) menunggu keputusan manajer",
     "inspections", "inspections",
     {"lines.hold": True, "status": {"$in": ["assigned", "in_progress", "done"]}}),
    ("interco_return", "Retur antar-PT menunggu persetujuan", "interco-transactions",
     # Dual control: pembuat ≠ penyetuju, dan dokumen retur langsung menunggu begitu
     # dibuat (`draft` → `approved`), jadi `draft` di SINI benar-benar keadaan menunggu.
     "interco_returns", {"status": "draft"}),
    ("vendor_bill", "Tagihan supplier menunggu ACC", "vendor-bills", "vendor_bills",
     {"status": "pending_approval"}),
    ("landed_cost", "Voucher biaya masuk menunggu ACC", "landed-cost",
     "landed_cost_vouchers", {"status": "pending_approval"}),
    ("cash_advance", "Uang muka (panjar) menunggu ACC", "cash-advances", "cash_advances",
     # Persetujuan berjenjang: atasan → pimpinan → finance. Ketiganya = menunggu orang.
     {"status": {"$in": ["pending_atasan", "pending_pimpinan", "pending_finance"]}}),
    ("cash_advance_settlement", "Pertanggungjawaban uang muka menunggu ACC",
     "cash-advances", "cash_advance_settlements", {"status": "submitted"}),
    ("makloon_claim", "Klaim makloon menunggu ACC", "makloon-claims", "makloon_orders",
     # Klaim menempel pada LANGKAH proses (`steps[].claim`), bukan dokumen tersendiri.
     {"steps.claim.status": "pending_approval"}),
    ("period_unlock", "Permintaan buka periode menunggu ACC", "period-unlock",
     "period_unlock_requests", {"status": "pending"}),
    ("hr_leave", "Pengajuan cuti menunggu ACC", "hr-leave", "hr_leave_requests",
     {"status": "pending"}),
    ("hr_overtime", "Pengajuan lembur menunggu ACC", "hr-overtime", "hr_overtime",
     {"status": "pending"}),
    # ── UTANG ALUR F-6.7 DIBAYAR (2026-08-18) — 4 antrean yang dulu SENGAJA dibebaskan
    # dari penjaga karena alurnya belum memungkinkan menghitungnya dengan jujur.
    # Alasan pembebasannya bertanda "UTANG ALUR" di `verify_approval_queues.DOOR_EXEMPT`;
    # sekarang alurnya diperbaiki, jadi pembebasannya DIHAPUS dan digantikan baris ini.
    ("hr_payroll", "Payroll menunggu pengesahan", "hr-payroll-runs", "hr_payroll_runs",
     # Dulu pengesahan bekerja dari `draft` → draf yang masih dikerjakan HR tak bisa
     # dibedakan dari yang siap disahkan, sehingga menghitungnya = menyebut pekerjaan
     # orang sebagai antrean. Kini ada langkah "Ajukan" (`pending_approval`).
     {"status": "pending_approval"}),
    ("design_gallery", "Desain menunggu pengesahan", "cs-design-gallery", "design_gallery",
     # Sama seperti payroll: `draft` adalah keadaan bekerja milik desainer.
     {"status": "pending_approval"}),
    ("payment_variance", "Selisih pembayaran menunggu keputusan", "payment-plans",
     # Keadaan menunggunya TIDAK butuh status dokumen baru: ia sudah presisi sebagai
     # (selisih perlu diputus) DAN (belum ada dokumen keputusannya) pada kwitansi.
     # Query ini SAMA dengan `payment_variance_service.pending()` yang sudah lama
     # dipakai layar antrean finance — jadi angka beranda & layar mustahil berbeda.
     "ar_receipts", {"status": {"$ne": "void"}, "variance.needs_decision": True,
                     "variance.decision_id": ""}),
    ("so_verify", "Pesanan menunggu verifikasi administratif", "sales-admin-desk",
     # Verifikasi menempel sebagai `sales_orders.verification` (bukan status dokumen),
     # jadi barisnya harus dibatasi ke tahap yang memang menunggu Admin Sales DAN
     # dikecualikan dari yang sudah dihitung baris `sales_order` (anti dobel-hitung:
     # pesanan yang menunggu keputusan manajer bukan pekerjaan verifikasi).
     "sales_orders", {"status": {"$in": ["reserved", "waiting_stock"]},
                      "verification.status": {"$ne": "verified"},
                      "pending_approvals.status": {"$ne": "pending"}}),
]


def _scope(entity_id: Optional[Any]) -> Dict[str, Any]:
    """Saringan badan usaha. Menerima `str`, `{"$in": [...]}`, atau kosong (gabungan)."""
    if not entity_id or entity_id == "all":
        return {}
    return {"entity_id": entity_id}


#: Dari mana UMUR TUNGGU satu dokumen dihitung, dan bagaimana ia disebut di layar.
#: `since` = kandidat field tanggal (yang pertama ADA & terisi dipakai) — yang paling
#: benar lebih dulu: kapan ia MULAI menunggu keputusan (diajukan), bukan kapan dibuat.
#: Tanpa daftar ini "sudah menunggu berapa lama" hanya bisa ditebak dari `created_at`,
#: padahal dokumen bisa lama berstatus draf sebelum diajukan → umurnya jadi
#: kelihatan lebih tua daripada kenyataan dan pengingat berbohong.
AGING_META: Dict[str, Dict[str, List[str]]] = {
    # INV-AGING-01 (2026-08-25) — temuan TAMBAHAN penjaga anti-tebak-field, kelas
    # yang sama dengan B1: `submitted_for_approval_at` NOL jalur tulis di seluruh
    # backend (`grep` = nol hasil di luar berkas ini) → seluruh dokumen null dan umur
    # tunggu diam-diam jatuh ke cadangan. Kebenaran yang memang ADA: entri
    # `pending_approvals[].requested_at` dibuat pada saat SO LAHIR
    # (`routers/sales_orders.py` → `so_approvals.make_approval`), jadi `created_at`
    # adalah tanggal yang SAMA — dan ia benar-benar ada di tiap dokumen.
    "sales_order": {"since": ["created_at"],
                    "number": ["number"], "title": ["customer_name"]},
    "purchase_order": {"since": ["submitted_at", "created_at"],
                       "number": ["po_number", "number"], "title": ["supplier_name"]},
    "price": {"since": ["created_at"], "number": ["number", "sku"],
              "title": ["product_name", "customer_name"]},
    "purchase_requisition": {"since": ["submitted_at", "created_at"],
                             "number": ["number"], "title": ["reason", "warehouse_name"]},
    "sales_return": {"since": ["submitted_at", "created_at"], "number": ["number"],
                     "title": ["customer_name", "order_number"]},
    "purchase_return": {"since": ["submitted_at", "created_at"], "number": ["number"],
                        "title": ["supplier_name", "po_number"]},
    "amendment": {"since": ["proposed_at", "created_at"], "number": ["number"],
                  "title": ["doc_number", "reason_label"]},
    "interco": {"since": ["submitted_at", "created_at"], "number": ["number"],
                "title": ["counterparty_name", "notes"]},
    "cycle_count": {"since": ["submitted_at", "created_at"], "number": ["number"],
                    "title": ["name", "warehouse_name"]},
    "rnd_spec": {"since": ["submitted_at", "created_at"], "number": ["number"],
                 "title": ["title", "design_title"]},
    "rnd_sample": {"since": ["sent_at", "created_at"], "number": ["number"],
                   "title": ["title", "spec_number"]},
    # B1 DIBAYAR (2026-08-25) — versi lama menyebut `submitted_at` DAN
    # `approval_requested_at` padahal TIDAK ADA satu pun jalur tulis yang mengisinya
    # (grep di `routers/special_orders.py` + `services/special_order_service.py` = nol
    # hasil). Umur tunggu karena itu SELALU jatuh ke `created_at`: dokumen yang lama
    # berstatus `draft` lalu baru diajukan dilaporkan JAUH lebih tua dari kenyataan —
    # dan tidak ada galat apa pun yang memberi tahu. Sekarang `approval_requested_at`
    # BENAR-BENAR ditulis saat dokumen MASUK keadaan menunggu (create + ajukan +
    # naik tingkat) dan dokumen lama di-backfill dari `status_history`
    # (`scripts/migrate_special_order_approval_requested_at.py`). Penjaga
    # `scripts/guardrails/verify_aging_fields.py` (INV-AGING-01) melarang kelas
    # "field ditebak" ini lahir kembali di antrean mana pun.
    "special_order": {"since": ["approval_requested_at", "created_at"],
                      "number": ["number"], "title": ["customer_name"]},
    # ── FASE F-6 — antrean baru (field nomor/judul/tanggal DIVERIFIKASI dari dokumen
    # nyata di basis data & dari fungsi pembuatnya, bukan ditebak). Nomor yang salah
    # nama field berarti pengingat harian menyebut sesuatu yang tak bisa dicari orang.
    # INV-AGING-01 (2026-08-25) — `dest_warehouse_name`/`source_warehouse_name` BUKAN
    # field dokumen: keduanya ditempelkan saat DIBACA (`routers/transfers.py:133-134`,
    # dari koleksi `warehouses`). Membacanya dari dokumen mentah selalu kosong →
    # judul baris antrean jatuh ke "—" tanpa satu pun galat. Diganti field yang
    # BENAR-BENAR tersimpan saat transfer dibuat (`routers/transfers.py:238-239`).
    "transfer": {"since": ["created_at"], "number": ["code", "id"],
                 "title": ["notes", "requested_by"]},
    "contra_bon_verify": {"since": ["submitted_at", "created_at"], "number": ["number"],
                          "title": ["supplier_name"]},
    "contra_bon_approve": {"since": ["verified_at", "submitted_at", "created_at"],
                           "number": ["number"], "title": ["supplier_name"]},
    "contra_bon_dispute": {"since": ["disputed_at", "submitted_at", "created_at"],
                           "number": ["number"],
                           "title": ["supplier_name", "dispute_reason_code"]},
    "internal_request": {"since": ["created_at"], "number": ["number"],
                         "title": ["source_entity_name", "reason", "notes"]},
    "interco_return": {"since": ["created_at"], "number": ["number"],
                       "title": ["counterparty_name", "reason", "notes"]},
    "vendor_bill": {"since": ["bill_date", "created_at"],
                    "number": ["bill_number", "number"],
                    "title": ["supplier_name", "supplier_invoice_no"]},
    "landed_cost": {"since": ["submitted_at", "created_at"],
                    "number": ["voucher_number", "number"],
                    "title": ["supplier_name", "po_number"]},
    "cash_advance": {"since": ["tanggal_pengajuan", "created_at"], "number": ["number"],
                     "title": ["kegiatan", "divisi", "created_by"]},
    "cash_advance_settlement": {"since": ["created_at"], "number": ["number"],
                                "title": ["cash_advance_number", "kegiatan"]},
    "makloon_claim": {"since": ["created_at"], "number": ["mko_number", "po_number"],
                      "title": ["material_name", "final_output_name"]},
    "period_unlock": {"since": ["requested_at", "created_at"],
                      "number": ["number", "period_label", "id"],
                      "title": ["reason", "period_label"]},
    "hr_leave": {"since": ["created_at"], "number": ["number"],
                 "title": ["employee_name", "leave_label"]},
    "hr_overtime": {"since": ["created_at"], "number": ["number"],
                    "title": ["employee_name", "reason"]},
    # ── UTANG ALUR F-6.7 DIBAYAR — umur tunggu dihitung dari kapan ia MULAI menunggu
    # (diajukan), bukan kapan dibuat; kalau tidak, payroll yang lama berstatus draf
    # akan tampak menunggu berbulan-bulan dan pengingat harian berbohong.
    "hr_payroll": {"since": ["submitted_at", "created_at"],
                   "number": ["number", "period"], "title": ["period", "entity_id"]},
    "design_gallery": {"since": ["submitted_at", "created_at"],
                       "number": ["code"], "title": ["title", "design_type"]},
    "payment_variance": {"since": ["created_at"], "number": ["number"],
                         "title": ["customer_name", "method"]},
    "so_verify": {"since": ["created_at"], "number": ["number"],
                  "title": ["customer_name", "sales_name"]},
}


def _pick(doc: Dict[str, Any], fields: List[str], default: str = "") -> str:
    for f in fields:
        v = doc.get(f)
        if v not in (None, "", [], {}):
            return str(v)
    return default


def days_waiting(since: str) -> int:
    """Umur tunggu dalam hari penuh (0 = hari ini). Tanggal kosong/rusak → 0."""
    if not since:
        return 0
    try:
        d = datetime.fromisoformat(str(since).replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return 0
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - d).days)


#: Berapa dokumen per antrean yang dibaca saat menyusun daftar "paling lama menunggu".
#: Dibaca TERURUT dari yang tertua (lihat `oldest()`), jadi batas ini memotong yang
#: paling MUDA — bukan yang paling lama, yang justru sedang dicari.
_OLDEST_SCAN = 200


async def oldest(entity_id: Optional[Any] = None, limit: int = 8) -> List[Dict[str, Any]]:
    """Dokumen yang PALING LAMA menunggu keputusan, lintas semua antrean.

    KENAPA PENTING: angka "17 menunggu" memberi tahu ADA pekerjaan, tetapi tidak
    memberi tahu MANA yang paling menyakitkan. Yang membuat orang bertindak adalah
    "PO-00010 · Palembang Silk House · menunggu 12 hari". Dipakai kartu "Paling Lama
    Menunggu" di beranda dan pengingat harian (`services/approval_reminder.py`).
    """
    scope = _scope(entity_id)
    rows: List[Dict[str, Any]] = []
    for key, label, view, coll, query in QUEUES:
        meta = AGING_META.get(key) or {"since": ["created_at"], "number": ["number"],
                                       "title": ["title"]}
        try:
            # DI-URUT DI BASIS DATA, bukan hanya di Python. Sebelumnya barisnya
            # `.to_list(200)` tanpa `sort`: 200 dokumen diambil dalam URUTAN ALAMI
            # koleksi, jadi begitu SATU antrean berisi lebih dari 200 dokumen menunggu,
            # dokumen yang PALING LAMA bisa tidak ikut terbaca sama sekali — kartu
            # "Paling Lama Menunggu" dan pengingat harian lalu menyebut dokumen yang
            # SALAH tanpa satu pun galat. Ini kelas kerusakan "angka yang tenang-tenang
            # salah", persis yang paling mahal di sini. Bukti-merahnya permanen di
            # `test_core_f67_workflow_poc.py` (W2b, 201 dokumen muda + 1 tertua).
            # `limit()` bukan hiasan: dengan limit, MongoDB memakai sort ber-batas-K
            # (memori terbatas) alih-alih memuat seluruh hasil ke memori. Dokumen yang
            # field umurnya kosong bernilai null → terbaca paling awal, dan umurnya
            # tetap dihitung dari field cadangan di Python (`_pick`).
            docs = await (db[coll].find({**scope, **query}, {"_id": 0})
                          .sort([(meta["since"][0], 1)])
                          .limit(_OLDEST_SCAN).to_list(_OLDEST_SCAN))
        except Exception:  # noqa: BLE001
            continue
        for d in docs:
            since = _pick(d, meta["since"])
            rows.append({
                "key": key, "queue_label": label, "view": view,
                "id": d.get("id", ""),
                "number": _pick(d, meta["number"], d.get("id", "")),
                "title": _pick(d, meta["title"], "—"),
                "entity_id": d.get("entity_id", ""),
                "since": since, "days_waiting": days_waiting(since),
            })
    rows.sort(key=lambda r: (-r["days_waiting"], r["since"] or ""))
    return rows[:limit]


#: Kolom TAMBAHAN yang hanya berarti untuk papan khusus satu antrean (nilai rupiah,
#: keterangan barang, peran yang wewenangnya diminta). Dipisah dari `AGING_META` supaya
#: kartu "Paling Lama Menunggu" — yang harus seragam lintas 33 antrean — tidak berubah.
#: Titik berarti bersarang (`custom_item.description`).
DETAIL_META: Dict[str, Dict[str, List[str]]] = {
    "special_order": {
        "amount": ["total_amount"],
        "note": ["custom_item.description", "notes"],
        "role": ["required_approval_role", "approval_role"],
    },
    # 2026-06 — dua antrean lain yang salah-tundanya MAHAL, karena itu keduanya
    # mendapat papan ber-umur-tunggu yang sama dengan PO custom:
    # · kontrabon bersengketa: uang pemasok tertahan & hubungan dagang memburuk
    #   selama sengketanya menggantung;
    # · retur antar-PT: barang fisik sudah/akan bergerak antar badan usaha, tetapi
    #   dua buku belum berjurnal sampai dokumennya diputuskan.
    # `role` sengaja TIDAK diisi untuk keduanya: dokumennya tidak menyimpan peran
    # penyetuju yang diminta, dan menebaknya persis kelas cacat B1.
    "contra_bon_dispute": {
        "amount": ["totals.net_payable", "totals.bills_total"],
        "note": ["dispute_reason_code", "notes"],
    },
    "interco_return": {
        "amount": ["grand_total", "subtotal"],
        "note": ["reason", "notes"],
    },
}


def _pick_path(doc: Dict[str, Any], fields: List[str], default: Any = "") -> Any:
    """Seperti `_pick`, tetapi mengerti jalur bersarang `a.b.c` dan menjaga tipe angka."""
    for f in fields:
        cur: Any = doc
        for part in f.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
            if cur is None:
                break
        if cur not in (None, "", [], {}):
            return cur
    return default


def _as_float(value: Any) -> float:
    """Angka rupiah yang BERTAHAN-GALAT.

    B4 DIBAYAR (2026-08-25): versi lama memanggil `float(...)` mentah. Satu dokumen
    dengan `total_amount` berupa teks (mis. `"43.500.000"` hasil impor/entri lama)
    melempar `ValueError` yang tidak ditangkap → `GET /api/home/admin` **HTTP 500**,
    sehingga SELURUH Control Tower pemilik kosong — bukan hanya papannya. Satu
    dokumen aneh tidak boleh menjatuhkan beranda; nilainya cukup dilaporkan 0 dan
    `verify_data_integrity` (INV-DB-SORD) yang menuntut tipenya dibetulkan.
    """
    if isinstance(value, bool) or value in (None, "", [], {}):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


async def queue_detail(key: str, entity_id: Optional[Any] = None,
                       limit: int = 12) -> Dict[str, Any]:
    """Isi SATU antrean beserta umur tunggu tiap dokumen — untuk papan khusus.

    KENAPA ADA: kartu "Paling Lama Menunggu" mencampur 33 antrean dan hanya memuat 5
    baris, jadi sebuah PO custom yang menunggu bisa TIDAK PERNAH terlihat di beranda
    hanya karena antrean lain lebih tua. Untuk dokumen yang salah-tundanya paling
    mahal (kain dipesan khusus — tak bisa dijual ke pelanggan lain) pemilik butuh
    papannya sendiri: semua yang menunggu, terurut dari yang paling lama.

    Definisi "menunggu" & umur tunggunya TETAP dibaca dari `QUEUES`/`AGING_META` di
    modul ini — papan baru tidak boleh melahirkan definisi ke-empat (INV-HOME-01).
    """
    row = next((q for q in QUEUES if q[0] == key), None)
    if row is None:
        return {"key": key, "count": 0, "shown": 0, "hidden": 0,
                "truncated": False, "rows": []}
    _, label, view, coll, query = row
    meta = AGING_META.get(key) or {"since": ["created_at"], "number": ["number"],
                                   "title": ["title"]}
    extra = DETAIL_META.get(key, {})
    scope = _scope(entity_id)
    count = await db[coll].count_documents({**scope, **query})
    # B3 DIBAYAR (2026-08-25) — dulu barisnya `.sort([(meta["since"][0], 1)]).limit(limit)`.
    # Field pengurutnya bisa TIDAK ADA di dokumen mana pun (lihat B1): seluruh dokumen
    # bernilai `null`, jadi urutannya = urutan alami koleksi dan `limit(10)` memotong
    # sembarang — termasuk dokumen yang PALING TUA, yang justru sedang dicari. Bukti-merah
    # permanennya di `backend/test_core_papan_po_custom_poc.py` (dokumen 60 hari
    # disisipkan TERAKHIR wajib tetap muncul). Polanya sama dengan `oldest()`: urut di
    # basis data dengan `created_at` (field yang PASTI ada), ambil `_OLDEST_SCAN`, lalu
    # potong SETELAH diurutkan di Python berdasarkan umur tunggu yang sesungguhnya.
    docs = await (db[coll].find({**scope, **query}, {"_id": 0})
                  .sort([("created_at", 1)])
                  .limit(_OLDEST_SCAN).to_list(_OLDEST_SCAN))
    rows = []
    for d in docs:
        since = _pick(d, meta["since"])
        rows.append({
            "id": d.get("id", ""), "number": _pick(d, meta["number"], d.get("id", "")),
            "title": _pick(d, meta["title"], "—"),
            "amount": _as_float(_pick_path(d, extra.get("amount", []), 0)),
            "note": str(_pick_path(d, extra.get("note", []), "") or ""),
            "role": str(_pick_path(d, extra.get("role", []), "") or ""),
            "entity_id": d.get("entity_id", ""),
            "since": since, "days_waiting": days_waiting(since),
        })
    rows.sort(key=lambda r: (-r["days_waiting"], r["since"] or ""))
    rows = rows[:max(1, limit)]
    # B2 DIBAYAR (2026-08-25) — angka di judul papan bisa lebih besar dari jumlah baris
    # yang dikirim. Tanpa `shown`/`truncated` layar berbunyi "(12)" sementara hanya 10
    # baris tampil dan TAK ADA satu pun tanda bahwa 2 disembunyikan: angka yang tidak
    # cocok dengan daftar di layar yang sama adalah kelas cacat yang justru diperangi
    # INV-HOME-01. Invarian H `verify_home_kpi` sekarang MENUNTUT penanda ini.
    shown = len(rows)
    return {"key": key, "label": label, "view": view, "count": int(count),
            "shown": shown, "hidden": max(0, int(count) - shown),
            "truncated": int(count) > shown, "rows": rows}


async def boards(keys: List[str], entity_id: Optional[Any] = None,
                 limit: int = 10) -> List[Dict[str, Any]]:
    """Beberapa papan antrean sekaligus, dalam urutan yang diminta.

    Dipakai beranda pemilik & manajer. Satu pintu supaya papan baru cukup
    ditambahkan di daftar kunci beranda — bukan dengan menulis ulang logika
    "menunggu" untuk kali ke-empat (INV-HOME-01).
    """
    out: List[Dict[str, Any]] = []
    for key in keys:
        out.append(await queue_detail(key, entity_id, limit=limit))
    return out


async def backlog(entity_id: Optional[str] = None,
                  with_oldest: bool = False, oldest_limit: int = 5) -> Dict[str, Any]:
    """`{total, items (hanya yang > 0), all_items[, oldest]}` — antrean keputusan NYATA.

    `with_oldest=True` menambahkan daftar dokumen yang paling lama menunggu (dipakai
    beranda & Pusat Persetujuan). Dimatikan secara bawaan supaya pemanggil yang hanya
    butuh ANGKA tidak membayar biaya membaca dokumen.
    """
    scope = _scope(entity_id)
    rows: List[Dict[str, Any]] = []
    for key, label, view, coll, query in QUEUES:
        try:
            count = await db[coll].count_documents({**scope, **query})
        except Exception:  # noqa: BLE001 — koleksi belum ada di instalasi baru
            count = 0
        rows.append({"key": key, "label": label, "view": view, "count": int(count)})
    out = {"total": sum(r["count"] for r in rows),
           "items": [r for r in rows if r["count"] > 0], "all_items": rows}
    if with_oldest:
        out["oldest"] = await oldest(entity_id, limit=oldest_limit)
    return out
