# HANDOFF AUDIT — sesi 2026-08-24 (lanjutan ke-2 & ke-3)

> **STATUS 2026-08-25: SELURUH 14 TEMUAN SUDAH DIPERBAIKI.** Rincian perbaikan,
> bukti empirisnya, dan pagar barunya ditulis di
> **`HANDOFF_PERBAIKAN_SESI_2026-08-25.md`**. Berkas ini DIPERTAHANKAN apa adanya
> sebagai catatan temuan (jangan disunting isinya) — nilainya justru pada rumusan
> "kenapa itu penting" yang dipakai menulis pagar-pagar barunya.

> **Tujuan berkas ini:** audit MANDIRI atas segala yang dikembangkan sesi ini (bukan
> laporan keberhasilan). Setiap temuan ditulis dengan **berkas:baris**, **mengapa itu
> penting**, dan **usul perbaikan** supaya sesi berikutnya bisa langsung eksekusi.
> Semua temuan di bawah **BELUM diperbaiki** (permintaan pemilik: dibetulkan sesi depan).
>
> Keadaan gate saat audit ditulis: `bash scripts/gate.sh --full` **HIJAU 393 s** ·
> `verify_home_kpi` 86 cek/0 pelanggaran · `audit_md_erp_readiness` SELESAI 96 · BELUM 0 ·
> DRIFT 0. **Artinya: tak satu pun temuan di bawah tertangkap gate hari ini** — itulah
> sebabnya ia ditulis, dan sebagian besar usul perbaikannya mencakup "gate mana yang harus
> menangkapnya".

## Yang diubah sesi ini (lingkup audit)
| # | Berkas | Perubahan |
|---|---|---|
| 1 | `backend/test_core_notifikasi_alamat_poc.py` | pembersihan jejak (`audit_logs`/`sessions`) · pemulihan `permission_settings` · butir N3b |
| 2 | `scripts/gate_residue.py` | `permission_settings` masuk WATCH · catatan jebakan hot-reload |
| 3 | `backend/services/notification_service.py` | `_notify_pending_special_orders()` (butir 7 job) |
| 4 | `scripts/audit_md_erp_readiness.py` | fakta FASE N diarahkan ke `create_addressed(permission=…)` |
| 5 | `backend/services/config_resolver.py` | `clear_layer()` tidak meninggalkan cangkang `system_settings` |
| 6 | `backend/services/approval_backlog_service.py` | `queue_detail()` · `DETAIL_META` · `AGING_META["special_order"].since` |
| 7 | `backend/services/home_service.py` | payload `special_orders_waiting` |
| 8 | `frontend/src/features/home/AdminHome.jsx` | panel **Papan PO Custom** |
| 9 | `backend/bootstrap.py` | dokumen demo PO custom pending berumur 9 hari |
| 10 | `scripts/guardrails/verify_home_kpi.py` | invarian **H** + 5 kasus self-test |
| 11 | `scripts/_bisect_*.sh`, `scripts/_intip_settings.py` | alat bisect sementara |

---

## A. SSOT & DUPLIKASI

### A1 · P1 — DUA definisi pesan untuk SATU peristiwa "PO custom menunggu"
- **Di mana:** `backend/routers/special_orders.py:252-266` (saat dokumen LAHIR) dan
  `backend/services/notification_service.py:285-299` (job, saat KEADAAN masih menunggu).
- **Masalah:** judul, isi pesan, tautan, dan tingkat keparahan **ditulis dua kali**.
  Keduanya sudah TIDAK identik hari ini: versi endpoint menyebut *"Diajukan oleh
  \<nama\>"*, versi job tidak. Besok salah satu diperbaiki dan yang lain tidak — kelas
  cacat "dua layar bicara beda" yang persis sama dengan `approval_requests` dulu.
- **Usul:** pindahkan penyusunan pesan ke SATU fungsi (mis.
  `notification_service.notify_special_order_waiting(so)`), lalu endpoint dan job
  memanggilnya. Tambah pemeriksaan STATIK: nol pemakaian `notif_type="special_order_approval"`
  di luar fungsi itu (pola yang sama dipakai `verify_notification_audience`).

### A2 · P1 — DUA sistem menagih dokumen yang SAMA setiap hari
- **Di mana:** `backend/services/approval_reminder.py:75-88` (pengingat harian lintas
  antrean, membaca `backlog(with_oldest=True)` → **memuat antrean `special_order`**) vs
  `notification_service._notify_pending_special_orders()` (`dedupe_scope="day"`).
- **Masalah:** untuk satu PO custom yang menggantung, pemilik menerima **dua** pesan tiap
  hari dari dua mesin berbeda (`approval_backlog` dan `special_order_approval`). Kotak yang
  isinya berulang adalah kotak yang berhenti dibaca — justru cacat yang FASE N tutup.
- **Usul:** putuskan SATU pemilik pengingat. Pilihan paling bersih: job baru hanya
  **melahirkan** notifikasi untuk dokumen yang belum pernah punya penerima (sekali, bukan
  harian → `dedupe_scope="unread"`), dan penagihan berulang tetap milik
  `approval_reminder`. Pagarnya: uji "dua job dijalankan → maksimal SATU pesan per orang
  per dokumen per hari" di POC FASE N.

### A3 · P2 — nama layar tujuan punya nilai bawaan di frontend
- **Di mana:** `frontend/src/features/home/AdminHome.jsx:190,205` — `custom.view || "special-orders"`.
- **Masalah:** nama layar sudah dikirim backend (SSOT `QUEUES`); nilai bawaan yang diketik
  di layar adalah sumber kedua yang bisa menyimpang tanpa terdeteksi (invarian D
  `verify_home_kpi` hanya menilai nilai dari backend).
- **Usul:** buang fallback; kalau `view` kosong, tombolnya dinonaktifkan (jujur) — bukan
  menebak.

---

## B. LOGIKA & KEBENARAN DATA

### B1 · P1 — `AGING_META["special_order"].since` menyebut field yang TIDAK ADA
- **Di mana:** `backend/services/approval_backlog_service.py:212`
  (`["submitted_at", "approval_requested_at", "created_at"]`).
- **Fakta terukur:** `grep -n "submitted_at\|approval_requested_at"
  backend/routers/special_orders.py backend/services/special_order_service.py` → **nol
  hasil**. Tidak ada satu pun jalur tulis yang mengisi kedua field itu; `approval_requested_at`
  murni **hasil menebak** (dosa besar repo ini: "kalau salah baca, fungsinya tidak error —
  ia hanya diam").
- **Akibat nyata:** umur tunggu SELALU jatuh ke `created_at`. Untuk dokumen yang lama
  berstatus `draft` lalu baru diajukan, papan **melebih-lebihkan** umurnya; sesudah
  penomoran/pengarsipan ulang bisa juga melaporkan lebih muda.
- **Kebenaran yang sesungguhnya ADA di dokumen:** `status_history[]` berisi
  `{"status": "pending_approval", "timestamp": …}` (`routers/special_orders.py:212,348`).
- **Usul:** (a) buang `approval_requested_at`; (b) hitung umur dari entri `status_history`
  terakhir yang berstatus menunggu — atau tulis `submitted_at` di jalur pengajuan lalu
  backfill; (c) pagar: invarian yang menuntut setiap kunci `AGING_META.since` benar-benar
  muncul sebagai field di ≥1 dokumen koleksinya ATAU ada di jalur tulis (statik) —
  penjaga ini akan menangkap SELURUH kelas "field ditebak", bukan hanya kasus ini.

### B2 · P1 — jumlah di judul papan bisa lebih besar dari jumlah baris, tanpa diberitahu
- **Di mana:** `home_service.py:272` (`limit=10`) + `approval_backlog_service.queue_detail`
  (`count` = `count_documents`, `rows` = 10 teratas) + panel di `AdminHome.jsx`.
- **Masalah:** dengan 12 PO custom menunggu, judul berbunyi "(12)" sementara hanya 10 baris
  tampil dan **tak ada satu pun tanda** bahwa 2 disembunyikan. Angka yang tidak cocok
  dengan daftar di layar yang sama = kelas cacat yang justru diperangi INV-HOME-01.
- **Usul:** kirim `shown`/`truncated` dari backend dan tampilkan baris "…2 lainnya —
  buka PO Custom"; tambah kasus ke invarian H (`count > len(rows)` wajib disertai penanda).

### B3 · P2 — pengurutan papan bisa memotong dokumen TERTUA
- **Di mana:** `approval_backlog_service.py:384` —
  `.sort([(meta["since"][0], 1)]).limit(max(1, limit))`.
- **Masalah:** field pengurut adalah `meta["since"][0]` = `submitted_at`, yang (lihat B1)
  **tidak ada di dokumen mana pun** → seluruh dokumen bernilai `null` → urutannya urutan
  alami koleksi, dan `limit(10)` memotong sembarang. Ini persis kelas bug yang sudah
  didokumentasikan & ditutup untuk `oldest()` (`_OLDEST_SCAN`, bukti-merah 201 dokumen di
  `test_core_f67_workflow_poc.py`) — dan sekarang lahir kembali di fungsi tetangganya.
- **Usul:** urutkan dengan field yang PASTI ada (`created_at`) atau ambil `_OLDEST_SCAN`
  dokumen lalu potong SETELAH mengurutkan di Python (seperti `oldest()`), dan tiru
  bukti-merahnya (≥ limit+1 dokumen, yang tertua wajib ikut muncul).

### B4 · P2 — `float()` di jalur beranda bisa menjatuhkan SELURUH Control Tower
- **Di mana:** `approval_backlog_service.py:391` —
  `float(_pick_path(d, extra.get("amount", []), 0) or 0)`.
- **Masalah:** satu dokumen dengan `total_amount` berupa teks (mis. `"43.500.000"` hasil
  impor/entri lama) melempar `ValueError` yang **tidak ditangkap** → `GET /api/home/admin`
  500 → beranda pemilik kosong seluruhnya, bukan hanya papannya.
- **Usul:** konversi bertahan-galat (`try/except → 0.0`) + pemeriksaan tipe di
  `verify_data_integrity` (`special_orders.total_amount` wajib numerik).

### B5 · P2 — panel mengklaim "tidak ada yang menunggu" ketika pemuatan GAGAL
- **Di mana:** `AdminHome.jsx:195-199` — saat `load()` gagal, `data` tetap `null`, jadi
  `customRows` kosong dan papan menampilkan *"Tidak ada PO custom yang menunggu keputusan 🎉"*.
- **Masalah:** kegagalan jaringan tampil sebagai **kabar baik**. `ErrorNotice` memang
  muncul di atas, tetapi pesan hijau di papan tetap menyesatkan — kelas "hijau tapi hampa".
- **Usul:** papan hanya boleh menyimpulkan "tidak ada" bila `data` benar-benar terbaca;
  bila `error` aktif, tampilkan keadaan "tidak bisa dibaca" + tombol coba lagi.

### B6 · P2 — nomor dokumen demo bertanggal HARI INI tetapi diklaim berumur 9 hari
- **Di mana:** `backend/bootstrap.py` (`seed_sales_extras_foundation`) — `dibuat` = 9 hari
  lalu, sedangkan `generate_special_order_number()` menomori dengan tanggal **hari ini**
  (`SORD-260824-0002`).
- **Masalah:** data demo jadi tidak konsisten dengan dirinya sendiri; siapa pun yang
  memeriksa penomoran vs tanggal akan mengira ada bug penomoran.
- **Usul:** nomor dokumen demo dibentuk dari tanggal `dibuat`, atau `umur_hari` diterapkan
  ke seluruh trio contoh secara konsisten (dan disebut di dokumentasi seed).

---

## C. TAMPILAN & KONTRAK UI

### C1 · P2 — kode peran mentah tampil di layar
- **Di mana:** `AdminHome.jsx:212` — `` `· perlu ${r.role}` `` mencetak `manager`/`admin`
  apa adanya, padahal repo punya `roleLabel()` (`frontend/src/config/roles.js`) dan
  kontraknya sudah dipakai `NotificationCenter`.
- **Usul:** pakai `roleLabel(r.role)`; pertimbangkan menambah pemeriksaan ke penjaga
  `verify_role_label.py` agar kelas ini tak terulang.

### C2 · P2 — dalam mode "Semua Entitas" baris papan tidak menyebut badan usaha
- **Di mana:** panel Papan PO Custom (baris tidak menampilkan entitas; `rows[].entity_id`
  sudah dikirim backend).
- **Masalah:** pemilik yang bekerja di mode gabungan tidak bisa membedakan PO custom KSC
  dari Kanda. Repo sudah punya jawabannya: `utils/entityLabel.js` / `<EntityBadge/>` —
  dan **INV-UI-02** melarang menampilkan id teknis `ent_*`, jadi menampilkannya mentah
  juga bukan pilihan.
- **Usul:** tampilkan `<EntityBadge/>` hanya saat mode gabungan.

---

## D. PAGAR (GATE) YANG MASIH BOLONG

### D1 · P1 — invarian H **lewat diam-diam** bila papannya hilang
- **Di mana:** `scripts/guardrails/verify_home_kpi.py:251` — `if isinstance(papan, dict)`.
- **Masalah:** hapus `special_orders_waiting` dari payload → seluruh invarian H **dilewati**
  dan penjaga tetap HIJAU. Pagar yang bisa dimatikan dengan menghapus datanya bukan pagar.
- **Usul:** untuk beranda `admin`, keberadaan `special_orders_waiting` menjadi **wajib**
  (tuduh bila tidak ada); untuk beranda lain tetap opsional. Tambah kasus self-test
  "payload admin tanpa papan → merah".

### D2 · P2 — tidak ada POC PERILAKU untuk papan ini
- **Masalah:** buktinya hari ini = penjaga statik/HTTP + agen uji. Belum ada POC yang
  MEMBUAT dokumen berumur (mis. 8 hari), mengukur papan, lalu membersihkannya — padahal
  itulah pola yang dipakai seluruh fase lain di repo ini ("bukti-merah, nol residu").
- **Usul:** `backend/test_core_papan_po_custom_poc.py`: suntik 2 dokumen (2 hari & 8 hari)
  → papan menyebut keduanya dengan umur BENAR & terurut → hapus → papan kembali seperti
  semula (nol residu), plus bukti-merah untuk B2/B3.

### D3 · P3 — alat bisect sementara masih di `scripts/`
- `scripts/_bisect_residu_audit.sh`, `scripts/_bisect_residu_settings.sh`,
  `scripts/_bisect_gl_drift.sh`, `scripts/_intip_settings.py` — dua di antaranya masih
  memakai `shlex.split` yang **gagal** pada baris `run_gate` berkelanjutan (`\`) sehingga
  melewatkan dua POC tanpa berkata apa-apa (terlihat di `.logs/bisect_settings.log`).
- **Usul:** pindahkan ke `scripts/_legacy/` + perbaiki parsernya, atau hapus; jangan
  biarkan alat ukur yang bisa "melewatkan dengan tenang" tinggal di jalur utama.

---

## E. Yang SUDAH diperiksa dan TERBUKTI benar (supaya tidak diaudit ulang)
- `queue_detail` **tidak** melahirkan definisi antrean baru: ia membaca `QUEUES` &
  `AGING_META` yang sama; invarian B `verify_home_kpi` menghitung ULANG `special_order`
  dari MongoDB, jadi papan terverifikasi **transitif** terhadap basis data.
- `/api/home/admin` menerima `entity_id` dari query tanpa `assert_entity_access` — **bukan
  cacat**: endpoint dipagari `require_role(["manager"])` dan `admin`/`manager` memang
  `cross_entity: True` di `role_registry.ROLES`. Papan tidak membocorkan apa pun yang belum
  dibocorkan `approvals.oldest`.
- Pemulihan `permission_settings` di POC FASE N tidak bisa dijatuhkan bootstrap: bootstrap
  hanya menulis bila koleksinya KOSONG dan memakai `id="default"` yang sama → jumlah
  dokumen tetap, `INV-GATE-01` tidak memberi positif-palsu.
- Alamat notifikasi: nol dokumen `recipient_role="all"` di seluruh data demo (diukur
  setelah gate: 98 notifikasi · 0 siaran).

---

## Urutan kerja yang disarankan untuk sesi berikutnya
1. **B1** (field ditebak) — akar dari **B3** juga; sekalian tambah penjaga anti-tebak-field.
2. **A1 + A2** (satu pesan, satu penagih) — sentuh pengalaman pengguna paling langsung.
3. **D1 + D2** (pagar tidak bisa dimatikan + POC perilaku) — supaya perbaikan di atas tak bisa mundur.
4. **B2, B4, B5** (jujur saat terpotong / gagal / bertipe aneh).
5. **C1, C2, A3, B6, D3** (kebersihan tampilan & alat).
