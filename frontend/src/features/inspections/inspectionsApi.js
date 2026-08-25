/**
 * inspectionsApi — FASE I · satu pintu pemanggilan API **Inspeksi & QC** (`<ENT>/INS-#####`).
 *
 * Label & kelas warna ditaruh di sini (bukan di tiap komponen) supaya daftar, pop-up
 * rincian, dan pop-up isi hasil tidak pernah menyebut satu status/hasil dengan dua
 * nama berbeda — kelas cacat yang sudah tiga kali muncul di repo ini.
 *
 * CATATAN PENTING: kosakata **yang berlaku** (jenis · status · keputusan · hasil warna
 * & handfeel) tetap datang dari server lewat `inspectionsMeta()`. Peta di bawah hanya
 * cadangan untuk baris yang belum termuat metanya, karena kebijakan warna/handfeel
 * bisa berbeda per badan usaha dan layar tidak boleh menebaknya.
 */
import axios, { API } from "../../services/apiClient";
import { apiErrorText } from "../../utils/apiError";

export const apiText = apiErrorText;

/** Urutan papan — cermin `inspection_service.BOARD_ORDER`. */
export const INS_BOARD_ORDER = ["draft", "assigned", "in_progress", "done", "closed"];

export const INS_STATUS_LABEL = {
  draft: "Draf (belum ditugaskan)",
  assigned: "Ditugaskan",
  in_progress: "Sedang diperiksa",
  done: "Selesai (sudah diputuskan)",
  closed: "Ditutup",
};

/** Kelas pil status — memakai kosakata `status-pill` yang sudah ada (tanpa warna baru). */
export const INS_STATUS_CLASS = {
  draft: "pill-muted",
  assigned: "pill-info",
  in_progress: "pill-warning",
  done: "pill-success",
  closed: "pill-muted",
};

export const INS_KIND_LABEL = {
  po_receipt: "Inspeksi Penerimaan PO",
  makloon_output: "Inspeksi Hasil Makloon",
  return_customer: "Inspeksi Retur Pelanggan",
  return_supplier: "Inspeksi Retur ke Supplier",
  replacement: "Inspeksi Barang Pengganti",
};

/** Nama pendek untuk chip penyaring — judul panjang membuat bilah filter melipat. */
export const INS_KIND_SHORT = {
  po_receipt: "Penerimaan PO",
  makloon_output: "Hasil Makloon",
  return_customer: "Retur Pelanggan",
  return_supplier: "Retur ke Supplier",
  replacement: "Barang Pengganti",
};

export const INS_COLOR_LABEL = {
  sesuai: "Sesuai sample",
  beda_shade: "Beda shade",
  tolak: "Warna ditolak",
};

export const INS_HANDFEEL_LABEL = {
  sesuai: "Sesuai sample",
  beda: "Beda rasa/konstruksi",
  tolak: "Handfeel ditolak",
};

export const INS_DECISION_LABEL = {
  terima: "Diterima seluruhnya",
  terima_sebagian: "Diterima sebagian",
  turun_grade: "Diterima dengan turun grade",
  tolak: "Ditolak",
};

/** Kelas pil untuk hasil banding sample: "sesuai" hijau, sisanya menuntut perhatian. */
export function resultPill(value) {
  if (!value) return "pill-muted";
  if (value === "sesuai") return "pill-success";
  if (value === "tolak") return "pill-danger";
  return "pill-warning";
}

export async function inspectionsMeta(entityId = "") {
  const r = await axios.get(`${API}/inspections/meta`, {
    params: entityId && entityId !== "all" ? { entity_id: entityId } : {},
  });
  return r.data || {};
}

export async function getInspection(id) {
  const r = await axios.get(`${API}/inspections/${id}`);
  return r.data || null;
}

export async function createInspection(payload) {
  const r = await axios.post(`${API}/inspections`, payload);
  return r.data || null;
}

export async function assignInspection(id, assigned_to, bagian = "", spk_date = "") {
  const r = await axios.post(`${API}/inspections/${id}/assign`,
    { assigned_to, bagian, spk_date });
  return r.data || null;
}

export async function startInspection(id) {
  const r = await axios.post(`${API}/inspections/${id}/start`, {});
  return r.data || null;
}

export async function inspectLine(id, lineId, payload) {
  const r = await axios.post(`${API}/inspections/${id}/lines/${lineId}/inspect`, payload);
  return r.data || null;
}

export async function releaseHold(id, lineId, reason) {
  const r = await axios.post(`${API}/inspections/${id}/lines/${lineId}/release-hold`,
    { reason });
  return r.data || null;
}

export async function finishInspection(id, decision, remark = "") {
  const r = await axios.post(`${API}/inspections/${id}/finish`, { decision, remark });
  return r.data || null;
}

export async function reopenInspection(id, reason) {
  const r = await axios.post(`${API}/inspections/${id}/reopen`, { reason });
  return r.data || null;
}

/**
 * Tugas QC yang BELUM punya SPK — jaring pengaman, bukan pintu kedua.
 *
 * Dokumen `po_receipt` lahir OTOMATIS saat barang masuk antrean QC. Daftar ini ada
 * supaya kalau otomatisasi itu pernah gagal (mis. penerimaan sebelum FASE I), kepala
 * gudang MELIHATNYA — bukan menemukannya setahun kemudian saat barang sudah terjual.
 */
export async function qcTasksWithoutDoc() {
  const r = await axios.get(`${API}/inspections/queue/qc-tasks`);
  return Array.isArray(r.data) ? r.data : [];
}

/**
 * Pilihan DOKUMEN SUMBER untuk pop-up "Buat SPK" — dilayani modul inspeksi SENDIRI.
 *
 * Versi pertama layar ini memanggil `/api/sales-returns`, `/api/purchase-returns`, dan
 * `/api/makloon-orders` langsung. Terukur 2026-08-23: petugas **gudang** — yang punya
 * `inspection.view` tetapi TIDAK punya `sales_return.view` — dijawab **403**, jadi
 * pemilih dokumennya mati tanpa satu kalimat penjelasan (`audit_sales_roles_ux`:
 * `warehouse → inspections → /sales-returns`). Menyembunyikan pemilihnya untuk gudang
 * bukan obat: penilaian layar memakai penutupan IMPOR, dan yang salah memang
 * arsitekturnya — pelajaran FASE D, "endpoint baru jangan menumpang modul API bersama".
 *
 * Jawabannya ringkas & seragam: `{ items: [{value, label, spk_number, spk_status}] }`
 * (nomor + nama pihak saja — nilai transaksi tidak dikirim ke peran yang tak berhak
 * melihatnya), sehingga label pemilih SAMA dengan isi dokumen yang nanti lahir.
 */
export async function refDocOptions(kind) {
  if (!kind || kind === "po_receipt") return [];
  const r = await axios.get(`${API}/inspections/meta/ref-docs`, { params: { kind } });
  return Array.isArray(r.data?.items) ? r.data.items : [];
}
