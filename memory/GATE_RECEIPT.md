# 🧾 GATE RECEIPT — Kain Nusantara

> Bukti verifikasi otomatis. Dihasilkan `scripts/gate.sh`. JANGAN edit manual.

- **Waktu:** 2026-08-25 15:44:21
- **Mode:** `full`  ·  **Durasi total:** 358s  ·  **Pekerja statik:** 2
- **Backend:** RUNNING + auth siap (gate runtime dijalankan)

| Gate | Hasil |
|------|-------|
| guard:auth_coverage (INV-AUTH-01) | PASS (0s) |
| guard:auth_coverage SELF-TEST (bukti-merah penjaga auth) | PASS (0s) |
| validate_compliance (file/naming/docs/api/env) | PASS (2s) |
| check_nav_map (navigasi vs SSOT) | PASS (0s) |
| guard:modal_dismiss (INV-UI-01, modal auto-close) | PASS (0s) |
| guard:create_modal SELF-TEST (bukti-merah penjaga create pop-up) | PASS (0s) |
| guard:create_modal (INV-UI-05, tombol Buat = pop-up konsisten) | PASS (0s) |
| guard:blocking_dialogs SELF-TEST (bukti-merah + anti tuduh palsu) | PASS (0s) |
| guard:blocking_dialogs (INV-UI-06, alert/confirm/prompt dilarang) | PASS (1s) |
| guard:list_export SELF-TEST (bukti-merah + CSV rusak harus memerah) | PASS (0s) |
| guard:list_export (INV-UI-07, daftar berhalaman wajib bisa diunduh) | PASS (1s) |
| guard:detail_modal SELF-TEST (bukti-merah + anti tuduh palsu) | PASS (0s) |
| guard:detail_modal (INV-UI-08, panel rincian wajib pop-up) | PASS (1s) |
| guard:picker_portal SELF-TEST (bukti-merah + anti tuduh palsu, 16 kasus) | PASS (5s) |
| guard:picker_portal (INV-UI-09, pemilih wajib ber-portal · pop-up bukan anak <label>) | PASS (6s) |
| guard:escape_layers SELF-TEST (bukti-merah + anti tuduh palsu, 13 kasus) | PASS (1s) |
| guard:escape_layers (INV-UI-10, Esc menutup lapisan teratas saja) | PASS (1s) |
| ux_audit SELF-TEST (bukti-merah baseline UX + anti tuduh palsu) | PASS (0s) |
| ux_audit --strict (INV-UX-01, loading/empty/chart baseline) | PASS (2s) |
| config_wiring (INV-CFG-01/04, satu sumber kebenaran) | PASS (1s) |
| config_wiring SELF-TEST (bukti-merah guardrail) | PASS (9s) |
| audit_doc_refs SELF-TEST (bukti-merah relasi dokumen) | PASS (0s) |
| guard:ref_unlink SELF-TEST (bukti-merah dua arah, 8 kasus) | PASS (1s) |
| guard:ref_unlink (INV-REF-04, hapus dokumen wajib sapu tautan balik) | PASS (3s) |
| guard:notif_audience SELF-TEST (bukti-merah dua arah, 14 kasus) | PASS (0s) |
| guard:notif_audience (INV-NOTIF-02, alamat notifikasi dari WEWENANG) | PASS (3s) |
| audit_i18n_id (label antarmuka Bahasa Indonesia) | PASS (2s) |
| audit_i18n_id SELF-TEST (bukti-merah guardrail bahasa) | PASS (0s) |
| fix_i18n_id SELF-TEST (codemod tak boleh sentuh kode) | PASS (0s) |
| guard:entity_label (INV-UI-02, id entitas tak boleh tampil) | PASS (1s) |
| guard:error_notice (INV-UI-03, error tak boleh senyap) | PASS (0s) |
| guard:role_label (INV-ROLE-01, peran dari registry & izin) | PASS (0s) |
| guard:derived_fields (INV-UI-04, field turunan tak boleh dari respons daftar) | PASS (0s) |
| audit_entity_isolation SELF-TEST (bukti-merah pagar isolasi) | PASS (1s) |
| guard:write_scope SELF-TEST (INV-ENTITY-02, mode gabungan hanya-lihat) | PASS (0s) |
| guard:warehouse_scope SELF-TEST (E4.1, gudang khusus badan usaha) | PASS (1s) |
| guard:numeric_bounds (INV-NUM-01, statik+runtime) | PASS (0s) |
| seed_realistic (data uji bersih) | PASS (14s) |
| verify_data_integrity (229 invarian domain/GL/alert/ledger/config/relasi/pembayaran/selisih/bank/kasus/kontrabon/antar-entitas) | PASS (3s) |
| verify_entity_scoping (F0-C, DB + STATIK anti-kebocoran PT) | PASS (1s) |
| audit_doc_refs (INV-REF cakupan data + kesehatan tautan) | PASS (0s) |
| guard:roll_identity SELF-TEST (bukti-merah + anti tuduh palsu) | PASS (5s) |
| guard:roll_identity (INV-ROLL-01, satu nomor untuk satu roll) | PASS (5s) |
| guard:cross_entity (INV-ENTITY-01, IDOR multi-PT) | PASS (2s) |
| guard:nonfinancial_sweep (INV-ENTITY-01+, IDOR non-finansial) | PASS (2s) |
| POC F0-C (isolasi lintas-entitas: kartu asal · roll retur · jejak UoM) | PASS (2s) |
| audit_entity_isolation (E0.9/E0.10 — 0 kebocoran lintas-entitas) | PASS (6s) |
| POC FASE E-0 (bukti-merah L1–L21: notifikasi·denda·audit·lot·AR·transfer·dokumen·pratinjau) | PASS (2s) |
| POC FASE E-3 (mode “Semua Entitas” hanya-lihat: 409 menuntun · master bersama tetap boleh) | PASS (2s) |
| POC FASE E-4 (gudang bersama/khusus · harga per badan usaha · CSV) | PASS (3s) |
| POC FASE E-4 master berlapis (global→badan usaha · override · kop surat per PT) | PASS (3s) |
| POC FASE E-5 (papan stok agregat · pegging · mutasi lintas-PT nama singkat · kartu riwayat) | PASS (2s) |
| POC FASE E-7 (pagar entitas grup · HPP taksiran berlabel · permintaan internal · kas grup dihapus · pinjaman & pindah aset antar-PT) | PASS (4s) |
| POC FASE E-8 G1 (peran sales_admin & finance · pemisahan tugas · penugasan entitas) | PASS (3s) |
| POC FASE E-8 G2/G3 (meja admin sales & finance · verifikasi · keputusan pemenuhan) | PASS (4s) |
| POC FASE E-9 (rantai jual→beli internal antar-PT→retur berantai · 41 pemeriksaan) | PASS (4s) |
| POC Cek Kenyataan Peran (utang migrasi ii E-8 · usulan peran dari jejak nyata) | PASS (2s) |
| audit_sales_roles_ux SELF-TEST (bukti-merah penilaian layar mati) | PASS (1s) |
| audit_sales_roles_ux (SEMUA peran: nol layar & panel mati) | PASS (40s) |
| POC F-2 Akses & UI/UX per peran (izin baca · pagar · KPI jujur · bukti-merah) | PASS (4s) |
| POC F-1b Migrasi kas tingkat grup (utang migrasi i · 4 lapis bukti · idempotent) | PASS (4s) |
| POC Pengingat Antrean Persetujuan (umur tunggu · eskalasi · idempotent · ambang pemilik) | PASS (2s) |
| POC FASE F-6 (pensiun mesin generik · 14 antrean nyata · anti dobel-hitung) | PASS (2s) |
| POC FASE F-6.7 (langkah Ajukan payroll & desain · selisih bayar · verifikasi SO) | PASS (5s) |
| guard:home_kpi SELF-TEST (bukti-merah penjaga KPI beranda) | PASS (0s) |
| guard:home_kpi (INV-HOME-01, KPI beranda = antrean nyata) | PASS (1s) |
| guard:aging_fields SELF-TEST (bukti-merah field umur ditebak) | PASS (0s) |
| guard:aging_fields (INV-AGING-01, field umur tunggu wajib nyata) | PASS (1s) |
| guard:status_history SELF-TEST (bukti-merah bentuk riwayat ke-dua) | PASS (0s) |
| guard:status_history (INV-HIST-01, satu bentuk riwayat status) | PASS (0s) |
| POC Papan PO Custom (umur tunggu bukan tebakan · yang tertua ikut · jujur saat dipotong · nol residu) | PASS (2s) |
| POC Sesi 2026-06 (true-up persediaan · papan manajer · umur tunggu antrean lain · satu bentuk riwayat) | PASS (2s) |
| guard:approval_queues SELF-TEST (bukti-merah penjaga antrean keputusan) | PASS (0s) |
| guard:approval_queues (INV-APPR-01, tiap pintu keputusan punya antrean) | PASS (1s) |
| guard:concurrency (INV-CONC-01, race/TOCTOU uang) | PASS (1s) |
| guard:state_machine (INV-STATE-01, transisi SO) | PASS (1s) |
| guard:line_scope SELF-TEST (bukti-merah pagar lini, 15 kasus dua arah) | PASS (0s) |
| guard:line_scope (INV-LINE-01/02, kode dikenal · turunan jujur · snapshot lengkap) | PASS (0s) |
| POC FASE L (lini produk: master bertambah · pagar keras · snapshot · isolasi PT) | PASS (3s) |
| guard:master_stages SELF-TEST (bukti-merah tahapan proses, 20 kasus dua arah) | PASS (0s) |
| guard:master_stages (INV-DOMAIN-06, master tahapan vs registry domain) | PASS (0s) |
| POC FASE T (tahapan proses: master bertambah · screen tak ubah kain · regresi identik) | PASS (5s) |
| guard:uom_vocab SELF-TEST (bukti-merah kosakata satuan, 23 kasus dua arah) | PASS (1s) |
| guard:uom_vocab (INV-UOM-02, satuan dokumen ⊆ master uoms · alias tak kembar · pemilih satuan dari master) | PASS (1s) |
| guard:qty_dual SELF-TEST (bukti-merah dua satuan, 32 kasus dua arah) | PASS (2s) |
| guard:qty_dual (INV-QTY-01, dua satuan satu arti di layar · PDF · CSV) | PASS (1s) |
| POC FASE U (dua satuan: PO→terima→PDF/CSV · retur turun serentak · satuan lini · dokumen lama "—") | PASS (10s) |
| guard:doc_origin SELF-TEST (bukti-merah asal dokumen PO, 26 kasus dua arah) | PASS (0s) |
| guard:doc_origin (INV-ORIG-01, satu definisi asal PO · sales dirunut bukan diketik · refs dua arah) | PASS (1s) |
| POC P-0 (asal dokumen PO: PO→PR→SO · Nama Sales dirunut · PO rutin kosong-jujur · nol residu) | PASS (4s) |
| guard:po_board SELF-TEST (bukti-merah papan PO, 22 kasus dua arah) | PASS (0s) |
| guard:po_board (INV-STAGE-01, tahap dari master · inspect turunan · tanda tahap ber-jejak) | PASS (1s) |
| POC FASE P (papan PO per lini: tahap dari master · sales dirunut · inspect turunan · terima dihitung · nol residu) | PASS (10s) |
| POC FASE D · PERMINTAAN DESAIN (DSR) (tugas→serah→revisi ber-alasan→ACC · rapor = hitung-ulang · peran ke-7 sempit tapi jujur) | PASS (5s) |
| guard:sample_types SELF-TEST (bukti-merah jenis sampling, 37 kasus dua arah) | PASS (0s) |
| guard:sample_types (INV-SAMPLE-01, jenis dari master · satu sumber · hasil ukur dinamis · jadi→kirim) | PASS (0s) |
| POC FASE S (sampling: dua jenis paralel · ukur dari master · jadi→kirim · nol residu) | PASS (8s) |
| POC FASE I (inspeksi & QC: SPK otomatis · grade dari mesin lama · tahanan warna dilepas manajer · nol residu) | PASS (10s) |
| POC FASE N (notifikasi beralamat: izin & divisi · dedupe per orang · nol siaran 'all') | PASS (1s) |
| audit_endpoint_sweep (semua GET → 5xx · paralel) | PASS (4s) |
| health_check (isi endpoint kritis) | PASS (2s) |
| INV-GATE-01 anti-residu (gate tak boleh merusak data) | PASS (1s) |
| POC FASE G-0 (fondasi konfigurasi) | PASS (11s) |
| POC FASE G-1 (amandemen ber-alasan) | PASS (3s) |
| POC FASE G-4 (relasi dokumen · referensi cetak · tanda tangan) | PASS (12s) |
| POC FASE G-2 (rencana pembayaran & denda) | PASS (13s) |
| POC FASE G-3 (selisih pembayaran lebih/kurang bayar) | PASS (12s) |
| POC FASE F-1 (penerimaan satuan supplier) | PASS (2s) |
| POC FASE F (R&D · labdip/proofing · lifecycle produk) | PASS (14s) |
| POC FASE F US3/US11/US12 (gating jual · mutasi sample · jejak dokumen) | PASS (1s) |
| POC FASE D (makloon rantai proses) | PASS (4s) |
| POC FASE G-8 (rekonsiliasi bank · titipan dana · isolasi PT) | PASS (15s) |
| POC FASE G-9 (pusat kasus keuangan · 11 playbook · SLA · dokumen turunan) | PASS (14s) |
| POC FASE G-7 (kontrabon · potongan · toleransi config · bayar sekali) | PASS (12s) |
| POC FASE G-6 (antar entitas · dokumen kembar · netting · eliminasi margin) | PASS (9s) |
| POC FASE G-6b (faktur pajak internal · retur antar-PT · pengingat · margin) | PASS (11s) |
| INV-GATE-01 anti-residu FASE POC (POC tak boleh menggeser stok/dokumen) | PASS (1s) |
| seed_realistic (pulihkan data demo setelah FASE POC) | PASS (15s) |
| verify_data_integrity (ulang, pasca pemulihan data) | PASS (2s) |

## ✅ VERDICT: HIJAU — boleh lanjut / klaim selesai (cakupan non-skip).

**Tingkatan:** `--quick` (statik ~7s) · default (~25s) · `--ci` (default + receipt JSON) · `--full` (+POC fase ~95s).

_Catatan: SKIP bukan PASS. Gate runtime harus dijalankan ulang saat backend hidup._
