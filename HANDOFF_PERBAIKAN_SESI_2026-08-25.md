# HANDOFF PERBAIKAN — sesi 2026-08-25

> **Lingkup:** menutup SELURUH temuan `HANDOFF_AUDIT_SESI_2026-08-24.md` (11 temuan
> yang sudah dibuktikan empiris oleh agen uji + 3 sisanya), sesuai urutan kerja yang
> disarankan handoff itu. Tidak ada temuan yang ditunda.
>
> **Prinsip yang dipegang:** setiap perbaikan disertai (a) bukti perilaku yang bisa
> dijalankan ulang dan (b) PAGAR yang akan memerah bila kelasnya lahir kembali.
> Perbaikan tanpa pagar = temuan yang sama akan kembali dua sesi kemudian.

---

## 1 · B1 — umur tunggu tidak lagi DITEBAK (akar B3 juga)

| Aspek | Sebelum | Sesudah |
|---|---|---|
| `AGING_META["special_order"].since` | `["submitted_at", "approval_requested_at", "created_at"]` — dua field pertama **nol jalur tulis** | `["approval_requested_at", "created_at"]`, dan `approval_requested_at` **benar-benar ditulis** |
| Jalur tulis | tidak ada | `routers/special_orders.py` menulisnya saat dokumen MASUK `pending_approval` |
| Dokumen lama | selalu jatuh ke `created_at` | **backfill dari `status_history`** (`special_order_service.ensure_approval_requested_at`, dipanggil bootstrap + CLI `scripts/migrate_special_order_approval_requested_at.py`) |

Bukti: dokumen dibuat 20 hari lalu tetapi masuk antrean 2 hari lalu → papan
melaporkan **2 hari** (sebelumnya 20). Diuji di
`backend/test_core_papan_po_custom_poc.py` P1 dan
`backend/tests/test_audit_findings_reproduction.py::test_B1_umur_tunggu_dari_field_nyata`.

**Pagar baru — `INV-AGING-01` (`scripts/guardrails/verify_aging_fields.py`)**: setiap
kandidat field di `AGING_META` (selain `created_at`) wajib terbukti nyata di DATA
(≥1 dokumen) atau di KODE (kunci tulis di `backend/routers|services`). Ini menutup
SELURUH kelas "field ditebak", bukan satu kasusnya.

> **Temuan TAMBAHAN dari pagar itu (tidak ada di audit, langsung diperbaiki):**
> `sales_orders.submitted_for_approval_at` nol jalur tulis (umur SO jatuh ke cadangan);
> `warehouse_transfers.dest_warehouse_name`/`source_warehouse_name` ternyata field
> **TURUNAN saat dibaca** (`routers/transfers.py:133-134`) sehingga judul baris antrean
> transfer selalu "—". Ketiganya diganti field yang benar-benar tersimpan.

## 2 · B3 — pengurutan tidak lagi memotong yang TERTUA

`queue_detail()` dulu `.sort([(meta["since"][0], 1)]).limit(limit)` dengan field yang
`null` di semua dokumen → urutan alami koleksi, `limit(10)` memotong sembarang.
Sekarang polanya sama dengan `oldest()`: urut di basis data memakai `created_at` (field
yang PASTI ada), ambil `_OLDEST_SCAN` (200), lalu potong **setelah** diurutkan di
Python berdasarkan umur tunggu sebenarnya.

Bukti-merah: 12 dokumen menunggu, yang paling tua (60 hari) **disisipkan terakhir** →
wajib muncul DAN berada di baris pertama (POC P2 + regresi B2/B3).

## 3 · A1 — satu peristiwa, SATU penyusun pesan

`notification_service.notify_special_order_waiting(so, actor_name=…)` menjadi
satu-satunya tempat judul/isi/tautan/keparahan "PO custom menunggu" disusun.
Endpoint pembuatan dan job keadaan hanya memanggilnya.

**Pagar:** `INV-NOTIF-02` aturan **K3** — `notif_type="special_order_approval"` di luar
`services/notification_service.py::notify_special_order_waiting()` = MERAH
(dengan bukti-merah dua arah di `--self-test`).

## 4 · A2 — satu pemilik PENAGIHAN BERULANG

| Mesin | Tugas sekarang |
|---|---|
| `notification_service.notify_special_order_waiting` | **MELAHIRKAN** pesan SEKALI per dokumen (`dedupe_scope="ever"` — baru) |
| `services/approval_reminder.py` | satu-satunya yang **MENAGIH BERULANG** (harian, `dedupe_scope="day"`) |

`dedupe_scope="ever"` ditambahkan ke `create_notification`. Ini penting: dengan
`"unread"` (percobaan pertama) job keadaan akan menagih ULANG begitu pesannya dibaca —
dua mesin kembali bicara setiap hari.

Yang **sengaja TIDAK dilakukan**: menyaring dokumen dari ringkasan `approval_backlog`.
Percobaan itu sempat dibuat dan **ditolak sendiri oleh POC Pengingat Antrean**: begitu
dokumen tertua disembunyikan, judul pengingat berbunyi *"tertua 6 hari"* padahal
kenyataannya 9 — angka pengingat vs beranda berselisih, kelas cacat yang justru
diperangi INV-HOME-01. Pengingat tetap LENGKAP; yang dihentikan adalah pengulangannya.

Bukti: POC P5 (job dijalankan 2×, lalu pesannya DITANDAI DIBACA dan job dijalankan
lagi → tetap 0 pesan baru; pengingat harian maksimal 1 per orang per hari dan tetap
menyebut dokumen tertua yang nyata).

## 5 · D1 + D2 — pagar tidak bisa dimatikan + POC perilaku

* **D1:** `verify_home_kpi.check_payload` sekarang **MENUDUH** bila payload beranda
  `admin` tidak memuat `special_orders_waiting` (dulu: seluruh invarian H dilewati
  diam-diam). Beranda peran lain tetap bebas — 2 kasus self-test baru membuktikan
  keduanya (merah untuk admin, tetap hijau untuk manajer).
* **D2:** `backend/test_core_papan_po_custom_poc.py` — 32 pemeriksaan: membuat dokumen
  berumur (2 · 15 · 60 hari), mengukur papan, membersihkannya, plus bukti-merah
  pengukur residu sendiri. Terdaftar di `scripts/gate.sh --full`.

## 6 · B2 — jujur saat daftarnya dipotong

Backend mengirim `shown` · `hidden` · `truncated`; layar menampilkan
**"Menampilkan 10 dari 13 — 3 lainnya belum tampil · buka PO Custom →"**
(`data-testid="admin-home-special-orders-truncated"`). Invarian H kini MENUNTUT
penanda itu bila `count > len(rows)`, **dan** menuduh penanda yang berbohong ke arah
sebaliknya (mengaku terpotong padahal semuanya terkirim).

## 7 · B4 — satu dokumen aneh tidak lagi menjatuhkan Control Tower

`approval_backlog_service._as_float()` bertahan-galat (`"43.500.000"` → `0.0`,
bukan `ValueError` → HTTP 500 → seluruh beranda pemilik kosong). Supaya dokumen
bertipe salah tetap KETAHUAN (bukan diam-diam dilaporkan Rp 0):
`scripts/verify_data_integrity.py` menambah **INV-DB-SORD** —
`special_orders.total_amount` wajib numerik.

## 8 · B5 — kegagalan tidak lagi tampil sebagai kabar baik

Papan hanya boleh menyimpulkan "tidak ada" bila datanya terbaca. Bila `error` aktif
(termasuk saat `data` masih memegang isi LAMA), panel menampilkan
**"Papan PO Custom tidak bisa dibaca"** + tombol *Coba lagi*, dan judulnya "(—)".
Dibuktikan di peramban dengan mem-blokir `**/api/home/admin` (route interception).

## 9 · C1, C2, A3, B6, D3 — kebersihan

| Kode | Perbaikan |
|---|---|
| **C1** | `roleLabel(r.role)` → layar menulis "perlu **Manajer**", bukan `manager` |
| **C2** | `<EntityBadge/>` hanya di mode "Semua Entitas" (INV-UI-02: id `ent_*` dilarang) |
| **A3** | nol fallback `custom.view \|\| "special-orders"`; tombol **dinonaktifkan** bila server tidak mengirim `view` (jujur, bukan menebak) |
| **B6** | nomor dokumen demo dibentuk dari TANGGAL DOKUMEN (`generate_special_order_number(on_date)`) → PO custom berumur 9 hari sekarang bernomor `SORD-260816-0001`, bukan tanggal hari ini |
| **D3** | alat bisect dipindah ke `scripts/_legacy/` **dan** parsernya diperbaiki: `scripts/_legacy/_parse_run_gate.py` mengerti baris `run_gate` berlanjut (`\`) dan BERISIK (`LEWAT: …`) bila tak bisa dibaca — versi lama memakai `shlex.split(...)[2]` dan melewatkan dua POC tanpa berkata apa-apa |

---

## Berkas yang berubah

**Backend**
`services/approval_backlog_service.py` · `services/notification_service.py` ·
`services/approval_reminder.py` · `services/special_order_service.py` ·
`routers/special_orders.py` · `bootstrap.py`

**Frontend** `src/features/home/AdminHome.jsx`

**Pagar & alat** `scripts/guardrails/verify_aging_fields.py` (BARU) ·
`scripts/guardrails/verify_home_kpi.py` · `scripts/guardrails/verify_notification_audience.py` ·
`scripts/verify_data_integrity.py` · `scripts/gate.sh` ·
`scripts/migrate_special_order_approval_requested_at.py` (BARU) ·
`scripts/_legacy/_parse_run_gate.py` (BARU) · `scripts/_legacy/_bisect_*.sh` (dipindah+diperbaiki)

**Uji** `backend/test_core_papan_po_custom_poc.py` (BARU, 32 cek) ·
`backend/tests/test_audit_findings_reproduction.py` (dari REPRODUKSI menjadi REGRESI)

**Dokumen** `memory/INVARIANTS.md` (INV-AGING-01 + perluasan INV-HOME-01) ·
`memory/PRD.md` · berkas ini

---

## Cara memverifikasi ulang (perintah nyata)

```bash
python scripts/guardrails/verify_aging_fields.py --self-test    # 5 kasus dua arah
python scripts/guardrails/verify_aging_fields.py                # 118 cek · 0 pelanggaran
python scripts/guardrails/verify_home_kpi.py --self-test        # 16 kasus (5 baru)
python scripts/guardrails/verify_notification_audience.py --self-test   # 16 kasus (2 baru K3)
python backend/test_core_papan_po_custom_poc.py                 # 32 PASS · nol residu
python -m pytest backend/tests/test_audit_findings_reproduction.py -q   # 6 regresi
python backend/test_core_approval_reminder_poc.py               # 26 PASS (tak ada regresi A2)
bash scripts/gate.sh --full
```

## Catatan lingkungan (kontainer baru)

`pip install reportlab qrcode apscheduler` — tiga modul ini TIDAK terpasang di
kontainer bersih dan membuat backend gagal start (`reportlab`) serta 12 POC/gate merah
karena PDF/QR (`qrcode`) dan penjadwal (`apscheduler`) — bukan bug kode.
Sesudah dipasang: `sudo supervisorctl restart backend`.
Bundel frontend TIDAK hot-reload: `bash scripts/rebuild_frontend.sh` setelah menyunting
`frontend/src`.

## Sisa pekerjaan (tidak menghalangi)

* `verify_aging_fields` baru menilai `AGING_META`. Metadata serupa di modul lain
  (mis. `DETAIL_META`, kolom papan lain) belum diikat pagar yang sama.
* `INV-DB-SORD` hanya memeriksa `special_orders.total_amount`; kolom uang di koleksi
  lain masih bisa bertipe teks tanpa ada yang menuduh.
* `queue_detail` sekarang memindai 200 dokumen per antrean lalu memotong di Python.
  Untuk antrean yang suatu hari berisi > 200 dokumen menunggu, pola `_OLDEST_SCAN`
  yang sama akan perlu paginasi sungguhan.
