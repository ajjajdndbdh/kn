# Test Credentials — Kain Nusantara (WMS/ERP)

> Ditulis ulang tiap clone: berkas ini **di-.gitignore**, jadi kontainer baru selalu datang kosong.
> Semua akun berasal dari `python seed_realistic.py` (data demo). **Password sama untuk semua:**
> `demo12345`

| Peran | Email | Catatan |
|---|---|---|
| Admin | `admin@kainnusantara.id` | Budi Santoso — akses penuh (Pengaturan · Master · semua modul) |
| Manajer | `manager@kainnusantara.id` | Dewi Rahayu — persetujuan, laporan, **penyetuju permintaan desain** |
| Admin Sales | `salesadmin@kainnusantara.id` | Rina Kusumawati — Meja Admin Sales; **boleh membuat Permintaan Desain** |
| Finance | `finance@kainnusantara.id` | Hendra Wijaya — Meja Finance (uang masuk, pajak) |
| Sales | `sales@kainnusantara.id` | Ayu Permatasari (juga `sales2@`, `sales3@`) |
| Gudang | `warehouse@kainnusantara.id` | Eko Prasetyo (juga `warehouse2@`) |
| **Desainer (peran ke-7 · FASE D)** | **`designer@kainnusantara.id`** | **Sari Melati** — wilayah SENGAJA SEMPIT: papan Permintaan Desain (beranda perannya) + Desain & Pattern + Galeri Desain + Profil Saya. Tidak boleh membuat/menugaskan/ACC/minta-revisi. |
| Sales **berpagar lini printing** (FASE L) | `dewi.printing@kainnusantara.id` | `allowed_line_codes=["printing"]` — hanya melihat pekerjaan lini printing |
| **Manajer berpagar lini printing (FASE P)** | **`manager.printing@kainnusantara.id`** | **Fajar Nugroho** — `allowed_line_codes=["printing"]`, peran `manager`. Ada khusus supaya **pagar lini pada Papan PO** bisa diuji lewat layar: `dewi.printing@` berperan `sales` yang memang TIDAK punya izin `purchase_order.view`. Di papan ia hanya melihat tab **Printing** + lencana "akses lini terbatas", dan menandai tahap PO woven dijawab **403** |
| Manajer warisan (uji "cek kenyataan peran") | `adminsales.lama@kainnusantara.id` | peran `manager` tetapi jejaknya Admin Sales |

Akun ber-home **CV Kanda Suka** adalah **`sales3@`** (bukan `sales2@`/`warehouse2@`
seperti tertulis di catatan lama).

## Catatan penting untuk agen uji
* Layar masuk: `data-testid="login-email-input"`, `login-password-input`,
  `login-submit-button` (lihat `frontend/src/components/LoginScreen.jsx`).
* Setelah masuk, **pilih badan usaha** dulu (PT Kain Suka Cita "KSC" / CV Kanda Suka).
  Mode "Semua Entitas" sengaja **hanya-lihat** — aksi tulis dijawab **409** dengan kalimat
  menuntun. Jalan tercepat: klik pita `data-testid="scope-pick-ent_ksc"`.
* **Navigasi BUKAN hash-routing.** Aplikasi ini TIDAK PERNAH memakai `#/view`; satu-satunya
  jalur URL adalah `/verify-document/:id`. Klik `nav-{id}` di sidebar (atau
  `nav-group-{groupId}` → `nav-{id}`), lalu tab hub `hub-tab-{view}`.
* **`KNSelect` merender placeholder SEBAGAI OPSI** (`{testId}-option-empty`, mis.
  "Pilih desainer"). Memilihnya **mengosongkan** pilihan sehingga tombol simpan mati.
  Selalu pakai testid kanonik **`{testId}-option-{value}`** — jangan `[role="option"]`
  generik. Pola ini sudah memproduksi satu laporan bug palsu (2026-08-20).
* Pop-up **alasan wajib** memakai `ConfirmModal`. **BACA INI — sudah membuat satu agen uji
  gagal (2026-08-24):** testid-nya **BERAWALAN**, bukan selalu `confirm-modal-*`.
  Pola resminya `{testId}-reason` · `{testId}-confirm` · `{testId}-cancel` ·
  `{testId}-reason-hint`, dan `testId` **bawaan** `confirm-modal` hanya berlaku bila layar
  itu TIDAK mengirim prop `testId`. Contoh nyata: pop-up tolak retur beli memakai
  `return-reject-modal-reason` / `return-reject-modal-confirm` (BUKAN `confirm-modal-*`);
  FASE I memakai `confirm-modal-*` karena memang memakai bawaannya. Kalau
  `confirm-modal-confirm` tidak ditemukan: **baca prop `testId=` di berkas layarnya**,
  jangan simpulkan tombolnya tidak ada.
  Tombol confirm **DISABLED selama alasan kosong** — DISENGAJA. Ambang **minimal 15 huruf**
  hanya berlaku di tempat yang memang menuntutnya (mis. FASE I, `MIN_REASON = 15`);
  pop-up lain cukup "tidak kosong".
* `allowed_line_codes: []` berarti **SEMUA lini** (bukan "tidak boleh apa pun").
* Basis data uji: `test_database` (lihat `backend/.env`).
* **Pulihkan data demo**: `python seed_realistic.py` lalu `python seed_e9_chain_demo.py`.
* Pelanggan demo **"Toko Kain Sejahtera" TERBLOKIR KREDIT** — untuk uji pembuatan pesanan
  pakai "Butik Bali Indah" / "Fashion Bandung Kencana" / "Tekstil Medan Jaya".

## Keadaan awal FASE P (sesudah seed bersih) — PAPAN PO PER LINI
Buka: sidebar **Pembelian → Pesanan Pembelian (PO)** → tab hub **"Papan PO per Lini"**
(`hub-tab-po-board`; layar `data-testid="po-board-view"`).
* **3 rantai demo SO→PR→PO** membawa **Nama Sales hasil runutan** (tidak diketik):
  `KSC/PO-00013` ← `PR-00006` ← `SO-0007` **Ayu Permatasari** (printing · proofing &
  PFP selesai, screen berjalan) · `KSC/PO-00014` ← `PR-00007` ← `SO-0008`
  **Bima Saputra** (printing · proofing selesai) · `KSC/PO-00015` ← `PR-00008` ←
  `SO-0005` **Ayu Permatasari** (woven · benang selesai, tenun berjalan).
* **PO pembelian rutin menampilkan "—" di kolom Nama Sales** — itu BENAR (keputusan
  pemilik: PO yang bukan dari pesanan tidak punya sales; jangan dilaporkan sebagai bug).
* **Chip tahap `Inspect (inspeksi mutu)` SENGAJA MATI** (ber-ikon 🔒, `disabled`):
  statusnya diturunkan dari hasil QC penerimaan. Mengeklik/PATCH-nya dijawab **409**.
  Ini bukan tombol rusak.
* Tab lini datang dari **master** (`product_lines`) dengan urutan `sort`:
  Woven → Knit → Printing. Tab **Knit** wajar KOSONG di data demo (belum ada PO knit).
* Menandai tahap: klik chip tahap (bukan `inspect`) → pop-up `po-stage-modal` →
  `po-stage-status` (KNSelect; pakai testid kanonik `po-stage-status-option-done`) →
  `po-stage-note` (opsional) → `po-stage-submit`.

## Keadaan awal FASE D (sesudah seed bersih)
`design_requests` **4 dokumen**: `KSC/DSR-00001` submitted (belum ditugaskan) ·
`KSC/DSR-00002` in_progress · `KSC/DSR-00003` delivered (menunggu keputusan) ·
`KSC/DSR-00004` approved — tiga terakhir ditugaskan ke **Sari Melati**.
`design_gallery` 2 artwork: `DSG-PARANG-01` approved · `DSG-PARANG-02` pending_approval.
Manajer melihat **4**, desainer hanya **3** (DSR-00001 belum ditugaskan kepadanya) —
selisih itu adalah **pagar kepemilikan yang bekerja**, bukan bug.

## Jangan diuji oleh agen otomatis
Drag-and-drop · unggah berkas fisik / kamera / scan RFID · suara.
Dan jangan melaporkan "NaN" dari pencarian **case-insensitive**: kata Indonesia ber-"nan"
(mis. "Pena**nan**ganan") sering tertangkap — cari `NaN` **case-sensitive**.

## Keadaan awal FASE I (sesudah seed bersih) — SPK INSPEKSI & QC
**Jalan ke layar** (navigasi BUKAN hash-routing — jangan pakai URL `/#/...`):
sidebar `nav-group-gudang` → `nav-wms-operations` → tab hub **`hub-tab-inspections`**
(layar `data-testid="inspections-view"`). Untuk akun **gudang**, layar hub itu sudah
menjadi beranda perannya sehingga `hub-tab-inspections` bisa langsung diklik.

**3 dokumen demo** (dari `seed_realistic.seed_inspections()`):
* `KSC/INS-00001` — **Penerimaan PO**, status *Sedang Diperiksa*, punya **1 baris DITAHAN**
  (warna beda dari sample → keputusan pemilik #5: warna beda = **DITAHAN**).
* `KSC/INS-00002` — **Retur Pelanggan**, status *Selesai*.
* `KANDA/INS-00001` — status **Draf** (badan usaha CV Kanda Suka → hanya terlihat dari
  konteks entitas itu; dari KSC ia memang TIDAK boleh muncul, jangan laporkan sebagai bug).

Pendukung: 3 retur jual (ber-garis waktu milestone), 5 order makloon, **7 alasan keluhan**
(master `complaint_reasons`), 28 sample.

**Testid penting:** `ins-kpi-total/draft/progress/hold/rejected` · `ins-policy-note` ·
`ins-search` · `ins-refresh` · `ins-chip-kind-{kind}` · `ins-chip-status-{status}` ·
`ins-chip-hold` · `ins-row-{id}` · `ins-detail-{id}` · `ins-detail-panel` ·
`ins-detail-number/status/baseline/reject-reason/history` · `ins-line-{lineId}` ·
`ins-line-inspect-{lineId}` · `ins-line-release-{lineId}` · `ins-line-hold-{lineId}` ·
`ins-assign-select` · `ins-assign-bagian` · `ins-assign-button` · `ins-start-button` ·
`ins-decision-select` · `ins-finish-button` · `ins-reopen-button` · `ins-create-button` ·
`ins-create-modal` · `ins-kind-select` · `ins-ref-select` · `ins-ref-spk-open` ·
`ins-ref-spk-done` · `ins-assignee-select` · `ins-remark-input` · `ins-create-submit` ·
`ins-color-select` · `ins-handfeel-select` · `ins-handfeel-score` · `ins-delta-e` ·
`ins-gsm-actual` · `ins-width-actual` · `ins-defect-{kodeCacat}` · `ins-points-preview` ·
`ins-will-hold-warning` · `ins-line-remark`.

**YANG SENGAJA TIDAK ADA — jangan laporkan sebagai bug:**
* peran `warehouse`: **tidak ada** `ins-create-button` (gudang boleh MEMERIKSA, tidak
  menerbitkan SPK) dan **tidak ada** `ins-line-release-*` — **pelepas tahanan hanya
  manajer/admin** (keputusan pemilik #5).
* `ins-finish-button` / `ins-reopen-button` hanya untuk admin & manajer.
* Pop-up **alasan wajib** (`confirm-modal`): tombol `confirm-modal-confirm` **DISABLED**
  selama alasan kosong **atau kurang dari 15 huruf** — DISENGAJA (`MIN_REASON = 15`,
  ditegakkan server DAN pop-up).
* SPK **kedua ditolak** selama SPK lama untuk dokumen yang sama masih berjalan; pemilih
  menandainya **"sudah ada SPK"** lebih dulu.
* Chip tahap `Inspect` pada **Papan PO** memang MATI (🔒) — statusnya diturunkan dari
  hasil QC penerimaan; PATCH-nya dijawab **409**.
