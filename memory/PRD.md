# PRD — Kain Nusantara WMS/ERP (kn090909)

## Original Problem Statement
User meminta lanjutkan development dari repo `pandekomangyogaswastika-dot/kn090909`
(Kain Nusantara — WMS/ERP untuk produsen tekstil Indonesia). User memilih:
1. Verifikasi cukup pindahkan repo ke `/app` + jalankan backend & frontend + pastikan hidup.
2. Lanjutkan **FASE G-6 (Transaksi Antar Entitas — jual-beli antar-PT)** sesuai
   rencana `docs/KN_36_PLAN_FASE_G6_ANTAR_ENTITAS.md`.
3. Default keys.

## Sesi 2026-07-30 — FASE G-6 (Transaksi Antar Entitas) DIBANGUN

### Yang telah dibangun (2026-07-30)

**Backend (baru):**
- `schemas_interco.py` — Pydantic (IntercoCreate, IntercoActionIn, IntercoSettlementCreate).
- `config_catalog_interco.py` — 7 kunci config `antar_entitas.*` (pricing_mode,
  ppn_mode, ppn_rate_percent, approval_threshold_rupiah, approval_role,
  high_value_approval_role, settlement_reminder_days).
- `services/interco_service.py` — inti bisnis: resolusi harga (fixed_price dari
  kontrak internal / at_cost / cost_plus_pct), resolusi PPN per-PT, siklus
  `draft → confirmed → shipped → received → invoiced → settled`, dokumen kembar
  (pair_id + role='seller'|'buyer'), auto-post GL dengan margin (Buku PENJUAL:
  Dr IC-AR / Cr Pendapatan+PPN Keluaran + HPP; Buku PEMBELI: Dr Persediaan+PPN
  Masukan / Cr IC-AP), saldo `interco_accounts` (INV-IC-04), settlement/netting
  `interco_settlements` (US6).
- `routers/interco.py` — 15+ endpoint `/api/interco/*` (meta, summary,
  transactions CRUD + siklus, accounts, settlements, internal-contracts).

**Backend (dimodifikasi):**
- `config_registry.py` — group baru `antar-entitas` + import catalog.
- `entity_scope.py` — 3 koleksi `interco_*` ditambahkan ke `SCOPED_COLLECTIONS`.
- `permissions_config.py` — modul `interco` untuk admin/manager (full) +
  warehouse (view/ship/receive).
- `services/contract_service.py` — `CONTRACT_TYPES` menambah `"internal"` &
  `_partner_snapshot` mengenali `partner_kind="entity"` (kontrak internal antar-PT).
- `server.py` — router `interco` diregistrasi.

**Frontend (baru):**
- `features/finance/interco/intercoApi.js` — status/method labels + helpers.
- `features/finance/interco/IntercoView.jsx` — 3 tab: Daftar Transaksi · Saldo
  Antar-PT · Settlement. 4 KPI: total piutang, total utang, dokumen terbuka,
  pasangan PT aktif.
- `features/finance/interco/IntercoCreateModal.jsx` — wizard terbitkan transaksi
  (dokumen kembar) — pilih PT penjual/pembeli, mode harga (bawaan `fixed_price`
  dari kontrak internal), mode PPN, item, submit_now (langsung `confirmed`).
- `features/finance/interco/IntercoSettlementModal.jsx` — wizard netting (pola
  kontrabon G-7): centang transaksi terbuka → set applied_amount → terbitkan.

**Frontend (dimodifikasi):**
- `AppViewRouter.jsx` — lazy import `IntercoView` + route `interco-transactions`.
- `config/hubTabs.js` — tab baru "Antar Entitas (Jual-Beli)" di hub `accounts-payable`.
- `config/navMeta.js` — kicker/title untuk view `interco-transactions`.

### Invarian yang dijaga (FASE G-6)
- **INV-IC-01** — setiap transaksi antar-PT punya pasangan jurnal seimbang di DUA buku.
- **INV-IC-02** — IC-AR penjual = IC-AP pembeli untuk pasangan entitas.
- **INV-IC-04** — `interco_accounts` == Σ transaksi − Σ settlement (tidak drift).
- **INV-IC-05** — PPN Keluaran penjual == PPN Masukan pembeli (bila ber-PPN).

**Status test**: `testing_agent` menjalankan 13/13 test → **100% PASS**. Semua
invarian di atas diverifikasi. Test file: `/app/backend/tests/test_interco_g6.py`.

### Yang BELUM (dan dicatat untuk fase lanjutan)
- **INV-IC-03** (eliminasi *unrealized profit* konsolidasi) belum dibangun.
- Frontend penuh detail panel per-transaksi (jejak dokumen kembar visual).
- POC bukti-merah lengkap (`test_g6_poc.py` skenario 11 US) belum ditulis.
- Wiring `balance_reminders` job penjadwal (saat ini hanya `aging_days` inline).
- Barang fisik lewat `warehouse_transfers` belum dijembatan otomatis dari
  interco (masih dua alur terpisah — perlu integrasi US8).

## Backlog Prioritas (P0/P1/P2)

| Prioritas | Tugas |
|---|---|
| P0 | INV-IC-03 eliminasi *unrealized profit* di konsolidasi grup |
| P0 | POC `test_g6_poc.py` — 11 skenario US1..US11 sebagai bukti-merah |
| P1 | Detail panel transaksi antar-PT (jejak dokumen kembar + timeline aksi) |
| P1 | Integrasi US8 — transaksi antar-PT → auto-generate `warehouse_transfer` |
| P1 | Screen "Buat Kontrak Internal" untuk `partner_kind="entity"` (helper wizard) |
| P2 | `balance_reminders` — job penjadwal aktif untuk pengingat settlement |
| P2 | Cetak PDF Invoice Internal / Surat Jalan Internal per PT |

## Test Credentials
File: `/app/memory/test_credentials.md`
- `admin@kainnusantara.id` / `demo12345` (admin)
- Password sama untuk sales/manager/warehouse.

## Layanan yang berjalan
- Backend: `http://localhost:8001` (supervisor `backend`), root `GET /api/` → 200.
- Frontend: `http://localhost:3000` (supervisor `frontend`, static server dari
  `/app/frontend/build/`). Rebuild dengan `bash /app/scripts/rebuild_frontend.sh`.
- MongoDB: `mongodb://localhost:27017`, DB `test_database`.


---

## Sesi 2026-07-30 (repo `ghananamakaa/kn`) — **FASE G-6 DITUTUP**

Permintaan pemilik: *lanjutkan development repo ini, clone & verifikasi titik berhenti*
(testing agent sebelumnya berhenti tanpa menjalankan satu pun uji). Pemilik menyetujui
penutupan 5 lubang nyata yang ditemukan main agent.

### Yang dikerjakan
1. **Verifikasi titik henti** — POC G-6 memang 15/15; UI interco memang hidup. Tetapi
   blok jurnal Detail Panel selalu kosong (`/api/gl/entries` 404), eliminasi margin tanpa
   tombol, INV-IC belum dijaga gate, layar kosong setelah seed, dan transfer gudang antar-PT
   masih memposting jurnal at-cost → **risiko dobel posting**.
2. **Jembatan gudang (US8)** — tugas gudang tertaut transaksi antar-PT: jurnal at-cost M-3
   dilewati, roll pembeli dinilai ulang ke harga beli internal, lot ikut pindah pemilik.
3. **Jurnal mengikuti barang** — akun baru `1-1310 Persediaan Dalam Perjalanan (Antar-PT)`;
   HPP memakai biaya nyata roll yang keluar. WARN drift persediaan HILANG.
4. **Eliminasi unrealized profit otomatis** + tombol sinkron & badge AUTO G-6 di layar
   Konsolidasi Grup; entri ikut diperbarui setelah settlement dan dihapus saat pembatalan.
5. **Pembatalan ber-alasan yang membalik jurnal** dua buku (modal alasan di layar).
6. **Gate & data demo** — INV-IC-01..06, POC G-6 di `gate.sh --full` (bukti-merah, nol residu),
   `seed_interco()` lewat jalur produksi, `entity_id` untuk `interco_accounts`.

### Bukti
* `pytest backend/tests/test_g6_poc.py` → **21 PASS / 0 FAIL**
* `python scripts/verify_data_integrity.py` → **229 PASS / 0 FAIL / 0 WARN**
* `bash scripts/gate.sh --full` → **SEMUA GATE HIJAU**
* `testing_agent_v3` iter_191 (BE 13/14 · FE 100%) + iter_192 (BE 14/15) + verifikasi layar
  oleh main agent untuk 3 alur yang tak terjangkau agen (tugas gudang · batal ber-alasan ·
  jurnal pembalik di panel detail)

### Belum dikerjakan (kandidat berikutnya)
* Faktur pajak NYATA (keluaran/masukan) untuk transaksi antar-PT ber-PPN
* Retur antar-PT (sekarang hanya pembatalan sebelum barang berpindah)
* Pengingat settlement terjadwal (config `antar_entitas.settlement_reminder_days` sudah ada)


---

## Sesi 2026-08-06 (repo `hanabavaja/kn`) — **FASE G-6b DITUTUP** (4 lanjutan Antar Entitas)

Permintaan pemilik: *"lanjutkan development dari repo ini, plan apa saja yang belum
diexekusi lanjutkan"* → pilihan pemilik: **4 lanjutan G-6** · lalu **G-5 Unlock
Periode** · lalu **utang teknis §G-12/F-2**.

### Verifikasi titik henti (lebih dulu, sebelum menulis apa pun)
G-6 memang SUDAH dibangun & hijau (POC 21/0 · integritas 229 · `gate.sh --full`
semua hijau · layar hidup dengan 8 dokumen kembar). Push pemilik berikutnya
melengkapi pencatatan penutupannya (KN_36 §8, ENTITY_REGISTRY, BUG_REGISTRY 9 entri,
tests/INDEX).

### Yang dibangun sesi ini (detail: `docs/KN_36…md` §9)
* **A. Faktur pajak internal ber-PPN** (`interco_tax_service.py`) — keluaran+masukan
  berpasangan, masuk rekap PPN kedua PT, pengganti & batal wajib ber-alasan.
* **B. Retur antar-PT** (`interco_return_service.py` + koleksi `interco_returns`) —
  dokumen kembar, dual-control, 4 blok jurnal, tugas gudang arah balik, roll dinilai
  ulang ke harga perolehan asli.
* **C. Pengingat settlement** (`interco_reminder.py` + job harian) — notifikasi nyata,
  umur saldo dari aktivitas nyata.
* **D. Rapor margin grup** (`interco_margin.py`) — realized vs unrealized dari sisa
  roll nyata; mesin eliminasi konsolidasi ikut diperbaiki.
* Invarian **INV-IC-07/08** baru + **INV-IC-03/04 diperkuat** (231 invarian).
* Frontend: 5 tab (2 baru), 2 modal baru, kolom Pajak & Diretur, tombol Ingatkan,
  blok bukti baru di panel detail. `IntercoView`/`IntercoDetailPanel` dipecah
  (`IntercoPanels`, `IntercoDetailParts`) → WARN panjang berkas hilang.
* Data demo lewat JALUR PRODUKSI: faktur pajak `KSC/FKT-00003 ↔ FPM-00001` + retur
  `KANDA/ICR-00001` (barang sudah kembali lewat `TRF-00005`, faktur ditandai perlu
  pengganti supaya tombolnya bisa dicoba).

### Bukti
`pytest tests/test_g6b_poc.py` **15/0** · `pytest tests/test_g6_poc.py` **21/0** ·
`verify_data_integrity` **231 PASS / 0 FAIL / 0 WARN** · `gate.sh --full` **SEMUA
GATE HIJAU (160s)** · `audit_i18n_id` 0 temuan · `audit_doc_refs --strict` hijau ·
`oxlint` 0 error · `testing_agent_v3` iter_193 backend **53/53**.

### Backlog berikutnya (urutan yang disetujui pemilik)
| Prioritas | Tugas |
|---|---|
| P0 | **G-5 Unlock Periode Berotoritas** — `period_unlock_requests` (`plu_`), permission `period:{unlock,backdate}`, dual-control, jendela berbatas waktu + auto-reclose, tag `backdated_in_unlock`, banner merah global di layar finance, INV-CLS-01/02 |
| P1 | **F-2 / §G-12** — contract picker di `POCreateForm`, `_create_po_core` memanggil `contract_service.resolve_active`, jejak sourcing di `PODetailPanel` |
| P2 | Cetak PDF nota retur & faktur pajak internal — ✅ SELESAI (termasuk Nota Retur/Kredit Antar-PT, sesi 2026-08-06) |
| P2 | FASE H — **PS-20 produk eksklusif per sales ✅ SELESAI (2026-08-06)** · **PS-18 KPI Desainer + eskalasi SLA ✅ SELESAI (2026-08-07)** · PS-17 butuh keputusan D-13 |

### PS-18 · KPI DESAINER + ESKALASI SLA OTOMATIS — ✅ SELESAI & HIJAU (2026-08-07)
*Permintaan pemilik: "eskalasi SLA otomatis (1a), KPI desainer diperkaya + **dipindahkan ke
menu Desainer yang TERPISAH dari R&D** (2a), filter periode (3a), data demo diperkaya (4a)".*

**Masalah yang ditutup.** Tenggat round sudah dihitung dan yang terlambat sudah ditandai
merah di "Papan SLA Round" — tetapi papan itu **PASIF**: bila tak ada yang membukanya,
keterlambatan bisa berumur berminggu-minggu tanpa ada yang tahu. Laporan kinerja pun hanya
menghitung round/ACC/revisi, belum menjawab "tepat waktu atau tidak" dan "siapa yang layak
dinaikkan".

**Backend baru:**
* `services/rnd_kpi_service.py` — KPI per desainer dari `md_samples.rounds[]` (nol input
  manual): `on_time_pct · acc_rate · rework_pct · late_submitted · overdue_now ·
  overdue_critical · max_days_late · avg_score · avg_days · cost_total` + **grade komposit**
  (`grade_base`, `grade_penalty`, `grade_score`, `grade_letter` A/B/C/D). Bobot **dinormalkan
  ulang** atas komponen yang PUNYA data → desainer baru tidak langsung jatuh ke D.
  Penanggung jawab round = `performed_by` → `opened_by` → `created_by` (round yang masih
  menggantung tetap punya pemilik). Filter periode `month|30d|90d|all` dari tanggal nyata
  round (`received_at` → `sent_at`).
* `services/rnd_sla_service.py` — `overdue_rounds()`/`board()` (dipakai UI **dan** job,
  jadi angka di layar tak mungkin beda dari isi notifikasi) + `job_rnd_sla_escalation()`:
  round `open`/`submitted` yang lewat tenggat → notifikasi **manager**; bila keterlambatan
  ≥ `rnd.sla_escalate_admin_days` (bawaan 3) **ikut dinaikkan ke admin**. `dedupe_scope="day"`
  → idempotent 1×/hari/round. Permintaan `decided`/`cancelled` DILEWATI (anti-berisik).
* `scheduler_service.JOBS` + job `rnd_sla_escalation` (harian **07:35 WIB**) → muncul di
  layar "Penjadwal & Notifikasi", bisa on/off, diubah jamnya, dijalankan manual, ber-histori.
* `routers/rnd.py` — `GET /api/rnd/reports/designer-kpi?period=` · `GET /api/rnd/sla/board` ·
  `POST /api/rnd/sla/escalate`. **RBAC khusus** `APPRAISAL_ROLES = (admin, manager)`: `rnd.view`
  saja tidak cukup karena sales & gudang pun memilikinya — rapor orang bukan data sample.
  Endpoint lama `GET /api/rnd/reports/performer` TETAP hidup (backward compatible).
* `config_catalog_rnd.py` + `rnd_gate.POLICY_KEYS` — 6 kunci baru yang bisa diubah pemilik:
  `rnd.sla_escalate_admin_days` (3) · `rnd.kpi_weight_on_time` (40) · `rnd.kpi_weight_score`
  (40) · `rnd.kpi_weight_acc` (20) · `rnd.kpi_penalty_rework` (0,3) · `rnd.kpi_penalty_overdue`
  (0,3).

**IA — menu DESAINER dipisah dari R&D (permintaan eksplisit pemilik):**
* `NAV_STRUCTURE`: `rnd-hub` → **"R&D (Spesifikasi & Sample)"**; menu baru `designer-hub`
  **"Desainer"** (ikon Palette, admin+manager).
* `HUB_TABS`: `rnd-hub` = Spesifikasi Produk · Permintaan Sample · Laporan R&D.
  `designer-hub` = **KPI Desainer** · Desain & Pattern (pindah dari R&D) · Galeri Desain + AI
  (pindah dari HRD). Hub HRD kini "KPI Karyawan" (KPI manual `hr_kpi` tetap di HRD).
* FE baru `features/designer/`: `DesignerKpiView.jsx` · `DesignerKpiTable.jsx` (kolom bisa
  diurutkan + tooltip "nilai dasar − penalti") · `DesignerSlaPanel.jsx` (tingkat Manager vs
  Manager+Admin, tombol "Kirim peringatan sekarang") · `designerApi.js` · `designerMeta.js`.
  `RndReportsView` menyisakan ringkasan **3 teratas** + pintu ke KPI Desainer (satu sumber
  kebenaran kinerja).

**Data demo:** `scripts/seed_rnd_kpi_demo.py` (idempotent, ditandai `demo_batch="rnd_kpi_v1"`,
dipanggil juga dari `seed_realistic.seed_rnd()`): Rina Kartika (3 round tepat waktu, 2 ACC +
1 revisi→ACC, 1 round nunggak 1 hari) & Bagas Nugroho (2 round disetor terlambat: 1 tolak +
1 revisi, 1 round nunggak 4 hari) → grade nyata **B / C / D** dan dua tingkat eskalasi terlihat.

**Bukti:** POC `test_core_ps18.py` **23/23** · `check_nav_map` PASS · `validate_compliance`
22/0 · `verify_data_integrity` **233/0/0** · `audit_config_wiring` 0 DEAD/0 ORPHAN ·
`testing_agent_v3` iter_198 backend 91/93 + frontend 11/11 (satu temuan RBAC sudah DIPERBAIKI:
sales/gudang kini 403 di endpoint penilaian).

### FASE 4 (lanjutan PS-18, 2026-08-07) — ✅ SELESAI & HIJAU
Tiga permintaan lanjutan pemilik, semuanya terkirim:

**1. "KPI Saya" — desainer melihat nilai DIRINYA SENDIRI (tanpa nilai rekan).**
* `rnd_kpi_service.my_kpi()`/`my_rounds()` + `GET /api/rnd/reports/my-kpi?period=`.
  Sengaja tanpa `require_permission` (setiap orang berhak melihat nilainya sendiri),
  tetapi **penyaringan dilakukan di SERVER** sehingga nilai rekan tidak mungkin terkirim:
  yang keluar hanya `me`, `rank`/`total_designers`, `team` (AGREGAT rata-rata), `rounds[]`
  + `overdue[]` milik sendiri, dan `weights` (yang dinilai berhak tahu aturannya). Tidak
  ada key `items`/`leaderboard`.
* FE `features/hr/MyDesignerKpiCard.jsx` di Profil Saya (ESS): nilai + huruf grade,
  peringkat, pembanding tim, 5 metrik, blok "round Anda lewat tenggat", riwayat round
  sendiri, filter periode. Belum punya round → kartu ringkas penjelas, bukan tabel kosong.

**2. "Dasbor Manajer" — menutup satu-satunya sisa EPIC 1.**
* `home_service.manager_home()` + `_approval_queue`/`_late_today`/`_designer_snapshot`:
  antrean persetujuan **dirinci per jenis** (SO · PO · harga khusus · lain, tiap baris
  punya `view` tujuan klik), `target` dibandingkan dengan **kemajuan bulan**, `team[]`
  target & capaian per sales, `late_today` dari **4 sumber** (piutang · round R&D ·
  tugas gudang > 2 hari · WO dirilis > 3 hari), cuplikan kinerja desainer.
* FE `features/home/ManagerHome.jsx`, rute `manager-home`,
  `ROLE_HOME_REGISTRY.manager` diubah `reports` → `manager-home`.

**3. "Rapor Desainer" — unduh CSV / Excel / PDF.**
* `services/rnd_kpi_export.py`: **satu definisi kolom** untuk ketiga format (isi berkas
  tidak mungkin beda dari layar). CSV ber-BOM · Excel `openpyxl` (header navy, freeze
  pane, format rupiah) · PDF `reportlab` landscape (pola slip gaji, huruf grade berwarna).
* `GET /api/rnd/reports/designer-kpi/export?period=&format=` (RBAC penilai; format tak
  dikenal → 400 pesan jelas). FE: 3 tombol + notifikasi hasil unduhan.

**Perbaikan nyata yang ditemukan saat pengujian:** (a) landing peran kini deterministik —
`App.js` me-reset view saat `user.id` berubah (dulu layar peran sebelumnya bisa
tertinggal); (b) sesi basi (`kn_user` ada, `kn_token` hilang) dulu merender kerangka penuh
galat "Login diperlukan", sekarang kembali ke layar masuk dengan pesan jelas;
(c) `IntercoTaxModal.jsx` memakai path literal → `verify_api_contract` **0 ERROR/0 WARN**.

**Bukti FASE 4:** POC `test_core_phase4.py` **29/29** · `test_core_ps18.py` **23/23**
(tanpa regresi) · `testing_agent_v3` iter_199 backend **68/68 (100%)** + frontend 10/10
(satu temuan landing manajer sudah diperbaiki & diverifikasi ulang untuk 3 skenario ×
4 peran) · seluruh gate repo hijau.

### PS-20 · PRODUK EKSKLUSIF PER SALES ("PO SENDIRI") — ✅ SELESAI & HIJAU (2026-08-06)
*"Penanda kepemilikan/visibilitas pada produk: `exclusivity = umum | sales_tertentu` +
`owner_sales_ids[]`; katalog/POS/pencarian & SO WAJIB menghormatinya; filter DI BACKEND."*
* `services/product_exclusivity.py` (SSOT) — `visibility_query`/`can_view`/`assert_can_order`/
  `normalize`. Aturan: hanya role `sales` yang dibatasi (umum + miliknya); admin/manajer/gudang
  lihat semua; produk legacy tanpa field = `umum`.
* `routers/products.py` — `GET /products` pakai `visibility_query` (paksa di query Mongo);
  `POST`/`PATCH` menormalisasi (owner wajib sales aktif bila eksklusif, min 1); endpoint
  `GET /products/sales-owners` (gated `product:update`).
* `routers/sales_orders.py` — `assert_can_order` di loop create (kriteria c: SO item eksklusif
  hanya oleh pemilik → else 403). `sales_order_helpers.compute_frequent_products` tak lagi
  membocorkan item eksklusif ke non-pemilik.
* FE: `ProductMasterForm` (toggle Umum/Eksklusif + multiselect sales), badge "Eksklusif · N sales"
  di daftar Master Produk, badge "Eksklusif — PO sendiri" di kartu POS.
* Demo: **Endek Bali Rangrang (ENK-BALI-001) → Ayu (user_sales_01)**.
* **Bukti**: POC `test_ps20_exclusive_poc.py` **14/14** · integritas **233/0/0** ·
  `testing_agent_v3` iter_197 backend **16/16** + frontend semua lulus (Ayu lihat, Bima tidak).


---

## LINGKUP FASE BERIKUTNYA — DISETUJUI PEMILIK 2026-08-06 (urut dikerjakan)

### P0 · G-5 UNLOCK PERIODE BEROTORITAS — ✅ SELESAI & HIJAU (2026-08-06)
Permintaan pemilik: *"Bangun izin buka periode tertutup yang wajib dua orang dan
menutup sendiri saat waktunya habis."* Spesifikasi asal `plan.md` §G-5.
**Status: TERKIRIM.** POC `tests/test_g5_poc.py` 12/12 · gate 233 PASS/0 FAIL
(INV-CLS-01/02) · testing agent backend 16/16. Ringkas implementasi (SSOT: `SESSION_HANDOFF.md` sesi 2026-08-06):
* Koleksi `period_unlock_requests` (`plu_`): `entity_id · period(YYYY-MM) · reason
  (WAJIB) · requested_by/at · approved_by/at · window_until · status(pending|
  approved|expired|reclosed|rejected) · je_ids[]`.
* **Dual-control**: pengusul ≠ penyetuju (pola retur G-6b `approve()`).
* **Jendela berbatas waktu**: config `periode.unlock_window_hours` (bawaan 24) →
  lewat batas = **auto-reclose** (job penjadwal `period_auto_reclose`, pola
  `interco_settlement_reminder`). Batas mundur: `periode.max_days_after_close`.
* Setiap JE yang lahir di dalam jendela ditandai `backdated_in_unlock: <plu_id>`.
* Permission baru `period: [unlock, backdate]` (dipisah dari `accounting:manage`).
* FE: layar usul/approve/riwayat + **banner merah global** di semua layar finance
  ("Periode 2026-06 sedang DIBUKA sampai 15:00 oleh Dewi — alasan: …").
* Invarian **INV-CLS-01** (tak ada JE di periode `closed` tanpa
  `backdated_in_unlock`) & **INV-CLS-02** (tiap unlock ber-alasan + 2 orang berbeda),
  bukti-merah + gate + POC `backend/tests/test_g5_poc.py`.

### P1 · F-2 HARGA KONTRAK DI PO MANUAL (utang teknis §G-12 #1–#3)
*"Pakai harga kontrak supplier otomatis saat PO dibuat manual, plus jejak asal
harganya."* — `POCreateForm.jsx` masih 0 referensi kontrak & memakai
`/supplier-price-list/resolve` (price-list lama). Rencana: contract picker di form ·
`_create_po_core` memanggil `contract_service.resolve_active` · tampilkan
`contract_number`/`supplier_sku`/`price_source`/`sourcing_explain[]` di
`PODetailPanel` (datanya SUDAH tersimpan, hanya tak pernah terlihat).

### P2 · CETAK NOTA RETUR & FAKTUR PAJAK INTERNAL — ✅ SELESAI & HIJAU (2026-08-06)
*"Terbitkan PDF nota retur dan faktur pajak internal yang bisa ditandatangani kedua
PT."* **Status: TUNTAS.** Sebelumnya faktur pajak internal + retur jual/beli biasa
sudah bisa dicetak/e-sign, TETAPI **Nota Retur Antar-PT belum** (tak ada `doc_type`
`interco_return` di `DOC_REGISTRY`, baris retur di panel detail interco tanpa tombol
Pratinjau/Unduh/E-Sign). Ditutup sesi ini:
* `pdf_resolvers.py` — resolver `resolve_interco_return` (peka `role`): **returner →
  "Nota Retur Antar-PT"**, **receiver → "Nota Kredit Antar-PT"** (dokumen kembar).
  Watermark **"ANTAR-PT"**, disclaimer INTERNAL (bukan dokumen pajak DJP), blok
  Referensi Dokumen (G-4) + QR, DPP/PPN/total + terbilang, tanda tangan bernama.
* `DOC_REGISTRY` — entri `interco_return` (collection `interco_returns`, module
  `interco`, `esignable: True`) → render PDF/HTML, e-sign, WhatsApp, Pusat Dokumen
  semuanya AKTIF otomatis lewat platform dokumen yang ada.
* `IntercoDetailPanel.jsx` — kolom **"Dokumen"** + `DocumentActionsBar` (Pratinjau ·
  Unduh · E-Sign · Kirim WA) di tiap baris retur (returner & receiver).
* **Poles**: emoji ⚠️ di `POCreateForm.jsx` (hint harga di bawah MOQ) diganti ikon
  lucide `AlertTriangle` (guideline "tanpa emoji sebagai ikon UI").
* **Bukti**: POC `test_p2_interco_return_poc.py` **21/21** · integritas **233 PASS /
  0 FAIL / 0 WARN** · doc_refs strict HIJAU · `testing_agent_v3` iter_196 backend
  **31/31** + frontend semua UI kritis lulus (Pratinjau Nota Retur/Kredit ter-render).

### P2 (ARSIP SPEC AWAL) · CETAK NOTA RETUR & FAKTUR PAJAK INTERNAL
*"Terbitkan PDF nota retur dan faktur pajak internal yang bisa ditandatangani kedua
PT."* — pakai platform dokumen yang sudah ada (`document_templates` +
`generated_documents` + `esign_service`): template **Nota Retur Antar-PT**
(`interco_returns`) & **Nota Kredit** pasangannya, plus render faktur pajak internal
(`tax_invoice_service.render_faktur_html` sudah ada — tinggal disambungkan untuk
dokumen `source_type="interco"`), blok tanda tangan bernama + QR verifikasi + blok
"Referensi Dokumen" (G-4).

### P3 · RAPOR MARGIN PER BARANG
*"Tunjukkan barang mana yang paling besar margin antar-PT-nya di satu layar ringkas."*
— perluas `services/interco_margin.py`: agregasi per `product_id` (nilai jual
internal · HPP · margin · %margin · belum terealisasi), tab/tabel baru di **Rapor
Margin** dengan urut margin terbesar + penyaring pasangan PT.

## Changelog 2026-08-07 (lanjutan)
- Fix seed Kontrabon (contra_bon biweekly overflow).
- Fitur: Rating desain 1-5 bintang (per-penilai, rata-rata) di design_gallery.
- Fitur: Tren nilai desainer/bulan (Recharts) + endpoint trend.
- Fitur: Rapor per-desainer 1 halaman PDF + tombol per baris.
- Regresi diperbaiki: GET /rnd/sla/board (dekorator route).
- PS-17 ditunda: menunggu keputusan D-13.

---

## Sesi 2026-08-18 (sore) — LANJUTAN "MD ERP": RENCANA v2 DIVERIFIKASI + ALAT UKUR

**Permintaan pemilik (verbatim, diringkas):** lanjutkan development repo
`github.com/wasakalakaha/kn`; sebelum eksekusi ulang, *"coba satu iterasi lagi: cek
kondisi sekarang, tambahkan apa yang harus diedit, pastikan UI/UX tidak berubah,
pastikan rules entitas terimplementasi dengan benar terutama soal dokumen, recheck &
double check, pastikan agen selanjutnya paham konteksnya."*

**Yang dikerjakan (dokumentasi + alat ukur, TANPA mengubah fitur):**
- Repo dipulihkan ke pod (HEAD `cecb511`), `bash .restore_env.sh` hijau; backend 200,
  frontend 200; `.env` tidak disentuh.
- `RENCANA_EKSEKUSI_MD_ERP.md` → **v2** (1.276 baris): §0 konteks agen berikutnya ·
  §2 tujuh koreksi klaim v1 + enam DRIFT terukur · §3 kontrak pagar entitas 12 titik
  (+3 khusus dokumen) & aturan anti-duplikat grade/cacat · §4 kontrak "UI/UX tidak
  berubah" (11 invarian + tabel komponen wajib pakai-ulang + prosedur bukti) ·
  §7 sembilan fase dengan **peta berkas yang diedit** + POC + gate + user story ·
  §12 lima keputusan pemilik dengan bukti ukuran. v1 diarsipkan di `docs/arsip/`.
- **BARU** `scripts/audit_md_erp_readiness.py` — mengukur 96 fakta kesiapan
  (SELESAI/BELUM/DRIFT, `--fase`, `--strict`). Baseline: 16 SELESAI / 73 BELUM / 7 DRIFT.
- `plan.md` → bagian `§STATUS MD-ERP` (serah-terima). `docs/KN_00_AGENT_QUICK_START.md`
  → pointer ke rencana aktif + alat ukur.

**Belum dikerjakan (fitur):** FASE L·T·U·S·I·P·D·N·M seluruhnya masih **BELUM** —
itu memang isi rencana. Urutan berikutnya: L → T → U → (D + P-0) → S → I → P → N → M.

---

## Sesi 2026-08-24 (lanjutan ke-2) — TUTUP 1 FAIL WARISAN + LUNASI UTANG FASE N

### Problem statement sesi ini (verbatim ringkas)
Lanjutkan development repo `hagacafasaya/kn`. Development terhenti dengan **satu** gate
merah: `INV-GATE-01 — koleksi 'audit_logs': 103 -> 105 (+2)` dan POC FASE G-8
`121 PASS · 1 FAIL`. Pilihan user: perbaiki FAIL yang tersisa **dan** lanjut ke POC FASE
G-9; pendekatan perbaikan residu diserahkan ke agen; repo publik; kredensial default.

### Yang dikerjakan & bukti
| Pekerjaan | Berkas | Bukti |
|---|---|---|
| Residu `audit_logs +2` ditutup (jejak `audit_logs`+`sessions` dibuang lewat selisih himpunan ID, direkam sebelum permintaan pertama) | `backend/test_core_notifikasi_alamat_poc.py` | POC N **35 PASS · 0 FAIL** · `gate_residue --check` nol residu |
| `permission_settings/default` tidak lagi DIHAPUS oleh POC N (dipulihkan apa adanya) + koleksi ini masuk `gate_residue.WATCH` | POC N · `scripts/gate_residue.py` | POC G-8 **122 PASS · 0 FAIL** · `verify_data_integrity` PASS 241 · FAIL 0 · WARN 0 |
| POC FASE G-9 diverifikasi (tidak perlu perubahan) | `backend/test_g9_case_poc.py` | **119 PASS · 0 FAIL** |
| Notifikasi PO custom menilai KEADAAN, bukan kejadian (`_notify_pending_special_orders`) | `backend/services/notification_service.py` | readiness **SELESAI 96 · BELUM 0 · DRIFT 0** · POC N butir N3b |
| Fakta readiness diarahkan ke API yang NYATA (`create_addressed(permission=…)`) | `scripts/audit_md_erp_readiness.py` | idem |
| Cangkang `system_settings` kosong sesudah "Kembalikan ke global" dihapus | `backend/services/config_resolver.py` | `backend/tests/test_config_clear_layer.py` |
| Pesan gagal `INV-GATE-01` menyebut jebakan hot-reload/bootstrap | `scripts/gate_residue.py` | terbukti saat backend restart |

**Gate penuh:** `bash scripts/gate.sh --full` → **HIJAU 419 s** (`memory/GATE_RECEIPT.md`).
**Uji tambahan (agen uji):** `backend/tests/test_notifications_addressing.py` 5/5 PASS.

### Backlog terprioritas (sesi berikutnya)
- **P1** `INV-GL-DRIFT` (`ent_kanda` Δ900.000 persediaan subledger vs GL `1-1300`) pernah
  muncul SETELAH gate & tidak reproduksi dari POC uang mana pun. Bila muncul lagi tanpa
  penyuntingan `backend/` saat gate berjalan → periksa `bootstrap.post_inventory_opening_balance`
  dan job penjadwal, bukan POC-nya.
- **P1** Layar/UI FASE N: kotak notifikasi per peran belum pernah diuji di peramban
  (backend & alamatnya sudah dijaga POC).
- **P2** Login mengembalikan `token` (bukan `access_token`) — usul agen uji, murni DX.
- **P2** Bersihkan alat bisect sementara (`scripts/_bisect_*.sh`, `scripts/_intip_settings.py`)
  atau pindahkan ke `scripts/_legacy/` bila tidak dipakai lagi.

---

## Sesi 2026-08-24 (lanjutan ke-3) — PAPAN PO CUSTOM + UJI LAYAR NOTIFIKASI

Permintaan user (verbatim): (1) "Papan PO Custom: Tampilkan PO custom yang menunggu
keputusan di beranda pemilik lengkap dengan umur tunggunya" · (2) "Layar Notifikasi: Uji
kotak notifikasi tiap peran di peramban supaya alamat yang sudah benar terlihat benar juga
di layar".

| Pekerjaan | Berkas | Bukti |
|---|---|---|
| Papan PO Custom di Beranda pemilik: semua PO custom menunggu + umur tunggu berlencana warna, bisa diklik ke layar PO Custom, ter-scope badan usaha | `frontend/src/features/home/AdminHome.jsx` · `backend/services/home_service.py` · `backend/services/approval_backlog_service.py` (`queue_detail`, `DETAIL_META`) | agen uji iteration_243: panel tampil "(1)" · SORD-260824-0002 · Rp 43.500.000 · lencana **9 hari** · CV Kanda → papan kosong |
| Data demo PO custom pending diberi umur 9 hari (jumlah dokumen tidak berubah) | `backend/bootstrap.py` | lencana umur akhirnya bisa dilihat & diuji |
| Pagar baru INV-HOME-01 **invarian H** (papan == baris antrean · tak boleh hampa · layar bukan hantu · baris bernomor & umur tak negatif) | `scripts/guardrails/verify_home_kpi.py` | self-test **11/11 PASS** · runtime **86 cek · 0 pelanggaran** |
| Kotak notifikasi 6 peran diuji di peramban | `frontend/src/components/NotificationCenter.jsx` (sudah ada) | finance 0 pesan stok · sales 0 PO custom · admin/manajer memuat PO custom · **nol pita "Umum"** untuk 4 jenis berpagar |

**Gate:** `bash scripts/gate.sh --full` → **HIJAU 393 s**.

### AUDIT MANDIRI atas pekerjaan sesi ini → `HANDOFF_AUDIT_SESI_2026-08-24.md`
Permintaan pemilik: audit sendiri hasil sesi ini (cacat logika · SSOT salah · duplikasi)
dan tulis handoff, perbaikannya sesi depan. **14 temuan, nol yang tertangkap gate hari ini**:
4× P1 (`A1` dua definisi pesan · `A2` dua sistem menagih dokumen sama tiap hari ·
`B1` `AGING_META.since` menyebut field yang tak pernah ditulis siapa pun · `D1` invarian H
bisa dimatikan dengan menghapus datanya), 8× P2, 1× P3. Urutan kerja & usul perbaikan per
temuan ada di berkasnya.

### Backlog terprioritas berikutnya
- **P1** Kerjakan temuan audit `HANDOFF_AUDIT_SESI_2026-08-24.md` (urutan §"Urutan kerja").
- **P1** `INV-GL-DRIFT` (`ent_kanda` Δ900.000) — lihat sesi lanjutan ke-2 §4.
- **P2** Papan PO Custom baru ada di Beranda **admin**; Beranda Manajer belum memilikinya.
- **P2** Lencana umur tunggu bisa dipakai ulang untuk antrean lain yang mahal bila menunggu
  (kontrabon bersengketa, retur antar-PT).
- **P2** Bersihkan alat bisect sementara (`scripts/_bisect_*.sh`, `scripts/_intip_settings.py`).

---

## Sesi 2026-08-25 — MELUNASI SELURUH TEMUAN AUDIT 2026-08-24

Permintaan user (verbatim ringkas): lanjutkan development repo `Gafasavawarase/KN`;
audit agen uji sudah MEMBUKTIKAN temuannya secara empiris (9 dari 11 TERBUKTI, 1
sebagian) — *"Perbaiki SEMUA 11 temuan audit (B1, A1+A2, D1+D2, B2, B4, B5, C1, C2, A3,
B6, D3) sesuai urutan prioritas handoff; pastikan masalah real"*. Pilihan user: B1
ditutup dengan **menulis `approval_requested_at` + backfill dari `status_history`**;
B2 ditutup dengan **penanda `shown/truncated` DAN pengurutan tertua dulu**; verifikasi
**penuh** (gate + `gate_residue`).

### Yang dikerjakan & bukti
| Temuan | Perbaikan | Bukti |
|---|---|---|
| **B1** field ditebak | `approval_requested_at` ditulis di jalur pengajuan + backfill dari `status_history` (bootstrap & CLI migrasi) | POC baru P1: dibuat 20 hari lalu, masuk antrean 2 hari lalu → papan lapor **2 hari** |
| **B3** tertua terpotong | `queue_detail` urut `created_at` di DB → ambil 200 → potong SETELAH urut umur (pola `oldest()`) | POC P2: dokumen 60 hari disisipkan TERAKHIR wajib muncul & di baris pertama |
| **A1** dua definisi pesan | satu penyusun `notification_service.notify_special_order_waiting()` | INV-NOTIF-02 **K3** (self-test dua arah) |
| **A2** penagih ganda | `dedupe_scope="ever"` (baru) → job keadaan MELAHIRKAN sekali; penagihan berulang milik `approval_reminder` saja | POC P5: pesan ditandai DIBACA → job tetap 0 pesan baru; pengingat harian tetap menyebut dokumen TERTUA yang nyata |
| **B2** angka vs daftar | backend kirim `shown/hidden/truncated`; layar: "Menampilkan 10 dari 13 — 3 lainnya belum tampil" | peramban (screenshot) + invarian H menuntut penanda (dua arah) |
| **B4** float mentah → 500 | `_as_float()` bertahan-galat + **INV-DB-SORD** (`total_amount` wajib numerik) | POC P4: `"43.500.000"` → HTTP **200**, nilai 0 |
| **B5** gagal tampak kabar baik | papan menampilkan "tidak bisa dibaca" + Coba lagi bila `error` aktif (termasuk data basi) | peramban dengan `route.abort('**/api/home/admin')` |
| **D1** pagar bisa dimatikan | `special_orders_waiting` WAJIB untuk beranda `admin` | 2 kasus self-test baru (admin merah · manajer tetap hijau) |
| **D2** tak ada POC perilaku | `backend/test_core_papan_po_custom_poc.py` — **32 PASS · nol residu** | terdaftar di `gate.sh --full` |
| **C1 · C2 · A3** | `roleLabel()` · `<EntityBadge/>` mode gabungan · nol fallback nama layar (tombol dinonaktifkan bila `view` kosong) | peramban: "perlu **Manajer**" + lencana KSC |
| **B6** nomor demo | `generate_special_order_number(on_date)` → PO custom 9 hari bernomor `SORD-260816-0001` | seed ulang + baca dokumen |
| **D3** alat bisect | dipindah ke `scripts/_legacy/` **dan** parsernya diperbaiki (`_parse_run_gate.py`: mengerti baris `\` berlanjut, berisik bila tak terbaca) | `bash -n` + uji baca 5 baris gate |

**Pagar BARU:** `INV-AGING-01` (`scripts/guardrails/verify_aging_fields.py`) — field umur
tunggu wajib nyata (DATA atau KODE). Saat pertama dijalankan ia langsung menemukan **3
field tebakan lain** di luar audit: `sales_orders.submitted_for_approval_at` (nol jalur
tulis) dan `warehouse_transfers.dest/source_warehouse_name` (field TURUNAN saat dibaca) —
ketiganya diperbaiki.

`backend/tests/test_audit_findings_reproduction.py` diubah dari **reproduksi** menjadi
**regresi** (6 uji, semuanya menuntut perilaku yang sudah benar, nol residu).

Rincian lengkap + perintah verifikasi: **`HANDOFF_PERBAIKAN_SESI_2026-08-25.md`**.

### Catatan lingkungan (kontainer baru)
`reportlab` · `qrcode` · `apscheduler` · `openpyxl` sudah ADA di
`backend/requirements.txt` tetapi TIDAK terpasang di kontainer bersih → backend gagal
start dan belasan POC merah karena PDF/QR/XLSX. Bukan bug kode: `pip install` keempatnya
lalu `sudo supervisorctl restart backend`. Bundel frontend tidak hot-reload:
`bash scripts/rebuild_frontend.sh`.

### Backlog terprioritas berikutnya
- **P1** `INV-GL-DRIFT` (`ent_kanda` Δ900.000 persediaan subledger vs GL `1-1300`) — masih terbuka.
- **P2** Papan PO Custom baru ada di Beranda **admin**; Beranda Manajer belum memilikinya.
- **P2** `INV-AGING-01` baru menilai `AGING_META`; `DETAIL_META` & metadata papan lain belum diikat.
- **P2** `INV-DB-SORD` baru memeriksa `special_orders.total_amount`; kolom uang koleksi lain masih bisa bertipe teks.
- **P2** Lencana umur tunggu bisa dipakai ulang untuk antrean lain yang mahal bila menunggu (kontrabon bersengketa, retur antar-PT).
- **P3** `queue_detail` memindai 200 dokumen lalu memotong di Python — antrean > 200 dokumen menunggu perlu paginasi sungguhan.

---

## Sesi 2026-06 (lanjutan) — REGRESI B5 DITUTUP DI DASBOR MANAJER + LANJUTAN INV-GL-DRIFT

Permintaan user (verbatim ringkas): *"lanjutkan development dari repo ini
https://github.com/wasaskamanabasda/kn — sebelumnya development terhenti di sini"*.
Pilihan user: **(1) perbaiki dulu semua temuan laporan uji terakhir**, lalu **(2)
lanjutkan true-up persediaan (INV-GL-DRIFT)**; tanpa integrasi baru; verifikasi PENUH
(agen uji frontend + backend) diizinkan.

### Pemulihan lingkungan (kontainer baru, repo baru di-clone)
`pip install -r backend/requirements.txt` GAGAL karena baris `litellm @ <url>` bentrok
dengan `emergentintegrations==0.2.0`; dipasang tanpa dua baris itu (keduanya tidak
dipakai kode ini) → backend hidup. Data demo dipulihkan (`seed_realistic.py` +
`seed_e9_chain_demo.py`) dan bundle frontend di-build ulang
(`scripts/rebuild_frontend.sh` — TIDAK ada hot-reload).

### Yang dikerjakan & bukti
| Pekerjaan | Berkas | Bukti |
|---|---|---|
| **B5 masih bocor di Dasbor Manajer** (temuan HIGH agen uji `iteration_248`): cabang "tidak bisa dibaca" ditulis DI DALAM cabang "daftar kosong", jadi saat pemuatan ulang gagal daftar BASI tetap tampil percaya diri | `frontend/src/features/home/ManagerHome.jsx` | peramban: keempat testid `*-unreadable`/`-retry` tampil, `*-empty` & daftar basi TIDAK; `iteration_249` 100% |
| Angka BASI di KPI ikut ditutup: manajer "Menunggu tanda tangan" → `—`, header "Terlambat Hari Ini" → "tidak bisa dibaca"; admin KPI "Persetujuan Menunggu" → `—` + blok `admin-home-approval-backlog` disembunyikan | `ManagerHome.jsx` · `AdminHome.jsx` | peramban (screenshot) |
| **Pagar baru B5.2** — menuduh URUTAN cabangnya secara statis di KEDUA beranda (kelasnya, bukan satu kasusnya) + menuntut kedua testid manajer ada | `backend/test_core_papan_po_custom_poc.py` | **36 PASS · 0 FAIL** · bukti-merah regex diuji terhadap bentuk lama |
| **INV-GL-DRIFT lanjutan #1 — drift tidak lagi menunggu ditemukan orang:** job harian `inventory_drift_watch` membandingkan subledger roll vs GL 1-1300 tiap buku dan memberi tahu pemegang izin `accounting.manage` (alamat FASE N, `dedupe_scope="day"`). Job ini TIDAK memposting jurnal apa pun | `backend/services/inventory_drift_watch.py` (BARU) · `services/scheduler_service.py` | POC G1b · agen uji: job dijalankan manual → Sukses, jumlah jurnal `inventory_opening` tidak berubah |
| Ambang jadi milik pemilik, bukan kode: `inventory.drift_alert_rupiah` (bawaan Rp 1.000, grup "Dasar Keuangan & Periode") | `backend/config_catalog_core.py` | `audit_config_wiring.py` HIJAU · agen uji mengubah 5000 → kembali 1000 dari layar |
| **INV-GL-DRIFT lanjutan #2 — ALASAN true-up sampai ke jurnalnya** (deskripsi + field `reason`). Layar sudah lama mewajibkan alasan, tetapi alasannya berhenti di `audit_logs`: yang dibaca akuntan saat tutup buku adalah JURNAL | `services/gl_service.py` · `routers/gl.py` | POC G1b: `reason` terbaca di JE & deskripsinya |
| **INV-GL-DRIFT lanjutan #3 — riwayat true-up terlihat di layar** (nomor · tanggal · nilai · pelaku · dasar; "tanpa dasar tercatat" ditandai merah) | `frontend/src/features/finance/InventoryReconTab.jsx` | agen uji: `recon-history` menampilkan `KSC/JE-00021` |

**Verifikasi:** `bash scripts/gate.sh --full` → **HIJAU 358 s** ·
`backend/test_core_sesi_2026_06_poc.py` **43 PASS · 0 FAIL** (7 cek baru G1b, nol residu) ·
`scripts/verify_data_integrity.py` **PASS 242 · FAIL 0 · WARN 0** ·
`verify_home_kpi` 108 cek · `verify_aging_fields` 131 cek · `verify_notification_audience`
HIJAU · agen uji `iteration_249` **backend 100% · frontend 100% · nol temuan**.

### Backlog terprioritas berikutnya
- **P2** Riwayat true-up di layar tidak difilter per badan usaha saat mode "Semua Entitas"
  (aman hari ini: hanya 1 jurnal). Ikutkan `entity_id` bila kelak Kanda ikut di-true-up.
- **P2** Jurnal true-up warisan seed (`KSC/JE-00021`) tanpa `reason` — jujur ditandai
  "tanpa dasar tercatat"; bisa diberi dasar di `seed_realistic` bila demo perlu lebih rapi.
- **P2** `INV-AGING-01` baru menilai `AGING_META`; `DETAIL_META` & metadata papan lain belum diikat.
- **P2** `INV-DB-SORD` baru memeriksa `special_orders.total_amount`; kolom uang koleksi lain masih bisa bertipe teks.
- **P3** `queue_detail` memindai 200 dokumen lalu memotong di Python — antrean > 200 dokumen menunggu perlu paginasi sungguhan.
- **P3** `backend/requirements.txt` memuat `litellm @ <url>` + `emergentintegrations` yang saling bentrok dan tidak dipakai kode ini — hapus supaya `pip install -r` bersih di kontainer baru.

---

## Sesi 2026-06 (lanjutan ke-2) — NEXT ACTION ITEMS DIKERJAKAN

Permintaan user: *"ya lanjutkan next action items pastikan fungsional dan ambil dari
collection data yang benar"*.

| Item | Apa yang dibangun | Koleksi sumber (BENAR, diverifikasi) | Bukti |
|---|---|---|---|
| **Riwayat true-up per PT** | Riwayat di tab Rekonsiliasi difilter `entity_id`; mode "Semua Entitas" memberi lencana nama badan usaha per baris | `journal_entries` (`source_type=inventory_opening`) | agen uji `iteration_250`: KSC → hanya `KSC/JE-00021`; mode gabungan → 2 baris berlencana |
| **Penjelas selisih** `GET /api/gl/inventory-drift-explain` + panel layar | Memecah KEDUA sisi: nilai fisik per **asal barang** vs mutasi GL per **sumber jurnal**, lalu menuduh kategori yang tak punya pasangan. Tidak menerbitkan jurnal | fisik: `inventory_rolls.acquired.via` (status & rumus SAMA dengan `inventory_reconciliation`) · GL: `journal_entries.lines` akun `1-1300` | POC G3c: rincian per asal menjumlah PAS ke nilai fisik; bukti-merah dua arah (roll asal tak dikenal → tertuduh, dibuang → tuduhan hilang) |
| **Papan antrean di meja SALES** (`special_order`·`sales_order`·`price`) | Beranda Performa Saya kini menjawab "dokumen saya tertahan di tanda tangan siapa" | `special_orders`·`sales_orders`·`price_approvals` lewat `approval_backlog_service` (nol query baru) | POC G3b + peramban: SORD-260816-0001 Rp 43.500.000/9 hari, SO-0007 Rp 17.427.000 |
| **Papan antrean di layar GUDANG** (`transfer`·`cycle_count`·`inspection_hold`) | `WaitingBoardsStrip` ditempel di atas tab Operasi; klik papan memindahkan tab yang benar | `warehouse_transfers`·`cycle_count_sessions`·`inspections` | POC G3b menghitung ulang tiap koleksi (layar=db) |
| Judul & nilai baris papan baru berhenti berbunyi "—"/Rp 0 | `AGING_META['inspection_hold']` + `DETAIL_META` untuk 5 antrean, field diperiksa dari dokumen nyata | idem | `verify_aging_fields` 152 cek HIJAU |
| **KEBOCORAN ISOLASI ditutup** | `/api/home/sales` & `/api/home/warehouse` dulu meneruskan `entity_id=None` = TANPA saringan → sales PT-B ikut melihat dokumen PT-A. Kosong = badan usaha AKTIF; di luar penugasan → **403** | `routers/home.py::_own_entity` | `audit_entity_isolation` dari **MERAH (2 kebocoran) → HIJAU**; POC G3b memagari kelasnya |
| `requirements.txt` bersih | Baris `litellm @ <url>` + `emergentintegrations` yang saling bentrok & tak dipakai dibuang | — | `pip install -r` jalan di kontainer baru |

**Verifikasi:** `gate.sh --full` **HIJAU 364 s** · POC sesi 2026-06 **61 PASS · 0 FAIL**
(nol residu diukur) · `audit_i18n_id` HIJAU (label baru wajib Bahasa Indonesia + `rupiah()`)
· agen uji `iteration_250` **backend 100% · frontend 100% · nol temuan**.

### Backlog terprioritas berikutnya
- **P2** `INV-AGING-01` baru menilai `AGING_META`; `DETAIL_META` (yang kini dipakai 8 antrean) belum diikat pagar yang sama.
- **P2** Papan gudang belum punya jalan langsung ke SATU dokumen (klik baris membuka tab, bukan dokumennya).
- **P2** Penjelas selisih belum menautkan tuduhan ke daftar roll/jurnal yang bisa diklik.
- **P3** `queue_detail` memindai 200 dokumen lalu memotong di Python — antrean > 200 perlu paginasi sungguhan.

---

## Sesi 2026-06 (lanjutan ke-3) — VERIFIKASI FUNGSIONAL + 1 CACAT NYATA DITUTUP

User meminta pembuktian bahwa fitur sesi sebelumnya "benar-benar berfungsi". Hasil
penelusuran ulang (peramban + API + POC), bukan klaim:

| Yang dibuktikan | Bukti |
|---|---|
| Navigasi papan SALES benar-benar berpindah layar (3/3) | peramban: `special-orders`, Pusat Persetujuan, Persetujuan Harga Khusus |
| Navigasi papan GUDANG (3/3) | tab `wms-tab-transfer` & `wms-tab-cycle` menjadi aktif; `inspection_hold` → layar SPK Inspeksi & QC |
| Pemantau drift bekerja END-TO-END pada drift NYATA | job manual → `success`, `created=3`, detail "1 buku berselisih di luar ambang"; notifikasi "Persediaan berselisih Rp 900.000 — CV Kanda Suka" (severity critical, link `general-ledger`) ke 3 pemegang `accounting.manage`; run kedua `created=0` (dedupe); nol jurnal terbit |
| Penjelas selisih MENUNJUK dokumen, bukan cuma kategori | suspect baru **`nilai_cocok_selisih`** menunjuk `Roll RTN-00001 · Rp 900.000 — PERSIS sebesar selisihnya` + dokumen `trn_8e7c61d55670`; suspect **`selisih_belum_terjelaskan`** menyebut 3 roll terbaru bila tak ada kategori yang cocok |
| **CACAT NYATA DITEMUKAN & DITUTUP** — peringatan kritis yang tak pernah terbaca | Notifikasi drift milik CV Kanda Suka TIDAK terlihat di lonceng selama konteks pemilih = KSC: pemantau menulis pesan yang tak dibaca siapa pun. Sekarang `routers/notifications.py::_scope_query` (1) meneruskan `entity_id=all` apa adanya (dulu diubah jadi `None` → jatuh ke satu badan usaha), dan (2) mengangkat notifikasi **severity `critical`** untuk badan usaha yang memang jadi PENUGASAN pengguna. Isolasi tetap: notifikasi non-kritis badan usaha lain TETAP tersaring; sales PT lain tetap nol; anti-IDOR `mark_read` tetap 404 |

**Verifikasi:** `gate.sh --full` **HIJAU 362 s** · POC sesi 2026-06 **66 PASS · 0 FAIL**
(deterministik, pagar baru: kritis-lintas-PT tampil · biasa tersaring · sales PT lain nol)
· POC isolasi E-0 **83 PASS · 0 FAIL** · agen uji `iteration_251` & `iteration_252`
**backend 100% · frontend 100% · nol temuan**.

### Catatan penting untuk sesi berikutnya
- **`INV-GL-DRIFT` masih P1 TERBUKA (akar masalah, bukan pemantauannya).** Drift
  `ent_kanda` Δ Rp 900.000 nyata dan reproducible: roll `RTN-00001` (retur pelanggan
  yang dikembalikan lewat retur antar-PT `KSC/ICR-00002`, transfer `KSC/TRF-00005`)
  mendarat di buku Kanda dengan HPP Rp 90.000/unit, tetapi pasangan jurnal
  `interco_return:…:goods_in` (Dr 1-1300 / Cr 5-1000) TIDAK pernah terbit — dokumen
  retur menyimpan `returned_cost = 0` & `goods_in_value = 0`, sementara
  `cost_basis.previous_unit_cost = 0` padahal roll dinilai ulang ke Rp 90.000.
  Titik periksa: `services/interco_return_service.on_return_task_executed` (urutan
  baca roll vs pemindahan kepemilikan) & `_post_goods_gl` (lewat karena `cost_back`
  terbaca 0). Pemantau + penjelas sekarang menunjuk tepat ke roll & dokumen itu.
- **P2** Badge lonceng tak berbatas sementara daftarnya dibatasi 100 baris — bila
  notifikasi menumpuk, angka badge bisa tak bisa ditelusuri sampai baris terakhir.
- **P2** Aturan "kritis boleh lintas badan usaha" bergantung `severity`; bila kelak ada
  peringatan penting ber-severity `warning`, pakai flag khusus (`cross_entity_visible`).
