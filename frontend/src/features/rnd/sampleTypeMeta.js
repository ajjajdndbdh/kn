/**
 * sampleTypeMeta (FASE S) — SATU pembaca kosakata **jenis sampling** untuk seluruh
 * layar R&D.
 *
 * KENAPA BERKAS INI ADA
 * Sebelum FASE S, label jenis sample adalah peta hardcode `SAMPLE_TYPE_LABEL` di
 * `rndMeta.js`. Begitu jenisnya bisa DITAMBAH pemilik lewat master `sample_types`,
 * peta hardcode berubah menjadi kebohongan yang tenang: jenis baru muncul di layar
 * sebagai kode teknis (`sanforize`) sementara masternya menyimpan namanya. Karena itu
 * label dibaca dari MASTER lebih dulu, dan peta lama hanya cadangan untuk jenis baku
 * bila `/api/rnd/meta` belum termuat (layar tetap terbaca, tidak pernah kosong).
 *
 * Yang TIDAK ada di sini dengan sengaja: aturan bisnis. `requires_design` &
 * `measurement_fields` ikut dibawa apa adanya dari master supaya form hanya
 * MENAMPILKAN keputusan server, bukan membuat keputusan kedua yang bisa menyimpang.
 */
import { SAMPLE_TYPE_LABEL } from "./rndMeta";

/** Tujuan pengiriman sample (label cadangan bila meta belum termuat). */
export const DELIVER_LABEL = {
  customer: "Pelanggan",
  sales: "Sales / Marketing",
  supplier: "Supplier (kirim balik)",
  internal: "Arsip internal / QC",
};

/** Label cadangan hasil ukur — dipakai hanya bila kamus dari server belum ada. */
export const MEASUREMENT_LABEL = {
  delta_e: "ΔE (selisih warna)",
  colorfastness_wash: "Tahan cuci",
  colorfastness_rub: "Tahan gosok",
  gsm_actual: "Gramasi aktual",
  lebar: "Lebar kain",
  shrinkage_pct: "Susut",
  handfeel_score: "Skor handfeel",
  repeat_cm: "Panjang repeat",
  register_mm: "Ketepatan register",
};

/** Jenis sampling pada satu dokumen — selalu DAFTAR, tidak pernah satu kata. */
export function sampleTypesOf(sample) {
  const out = [];
  for (const v of (sample?.sample_types || [])) {
    const code = String(v || "").trim().toLowerCase();
    if (code && !out.includes(code)) out.push(code);
  }
  // Dokumen yang lahir SEBELUM migrasi masih dibaca supaya layar tidak mendadak
  // kosong; `scripts/migrate_sample_types.py` yang menghapus field lamanya.
  if (out.length === 0 && sample?.sample_type) out.push(String(sample.sample_type));
  return out;
}

/** Jenis satu round (`type_code`); round lama diikat ke jenis pertama dokumennya. */
export function roundTypeOf(round, sample) {
  const code = String(round?.type_code || "").trim().toLowerCase();
  if (code) return code;
  const kinds = sampleTypesOf(sample);
  return kinds[0] || "";
}

/** Label manusia satu kode jenis — MASTER dulu, peta baku sebagai cadangan. */
export function typeLabel(code, types) {
  const key = String(code || "").trim().toLowerCase();
  if (!key) return "—";
  const hit = (types || []).find((t) => t.value === key);
  return hit?.label || SAMPLE_TYPE_LABEL[key] || key;
}

/** Baris master satu jenis (berisi `requires_design` & `measurement_fields`). */
export function typeMeta(code, types) {
  const key = String(code || "").trim().toLowerCase();
  return (types || []).find((t) => t.value === key) || {};
}

/** Jenis baku yang masih AKTIF — cadangan bila master belum termuat.
 *
 * `bulk_sample` sengaja TIDAK ada di sini: pemilik menonaktifkannya (keputusan #4),
 * jadi menawarkannya sebagai pilihan berarti layar mengundang pengguna memilih
 * sesuatu yang akan ditolak servernya sendiri. Ia tetap hidup di
 * `SAMPLE_TYPE_LABEL` supaya dokumen LAMA yang memakainya tetap terbaca.
 */
export const FALLBACK_TYPE_CODES = ["labdip", "handfeel", "proofing"];

/** Pilihan untuk pemilih jenis TUNGGAL (mis. "rencana sample" di spesifikasi). */
export function typeOptions(types) {
  const rows = (types || []).filter((t) => t?.value);
  if (rows.length) return rows.map((t) => ({ value: t.value, label: t.label || t.value }));
  return FALLBACK_TYPE_CODES.map((c) => ({ value: c, label: SAMPLE_TYPE_LABEL[c] || c }));
}

/** Hasil ukur yang WAJIB diisi untuk satu jenis — daftarnya dari master. */
export function measurementFieldsOf(code, types) {
  return typeMeta(code, types).measurement_fields || [];
}

/** Bentuk satu field hasil ukur (label · satuan · batas) dari kamus server. */
export function measurementMeta(field, dictionary) {
  const key = String(field || "").trim().toLowerCase();
  const hit = (dictionary || []).find((m) => m.value === key);
  return hit || { value: key, label: MEASUREMENT_LABEL[key] || key, unit: "" };
}

/** Ringkasan satu jenis untuk satu supplier (dari `participants[].types`). */
export function typeProgress(participant, code) {
  return (participant?.types || {})[String(code || "").toLowerCase()] || null;
}

/** Label tujuan pengiriman — pakai daftar server bila ada. */
export function deliverLabel(code, targets) {
  const key = String(code || "").trim().toLowerCase();
  if (!key) return "";
  const hit = (targets || []).find((t) => t.value === key);
  return hit?.label || DELIVER_LABEL[key] || key;
}
