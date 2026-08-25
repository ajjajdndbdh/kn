/**
 * designRequestsApi — FASE D · satu pintu pemanggilan API **Permintaan Desain**.
 *
 * Label & kelas warna status ditaruh di sini (bukan di tiap komponen) supaya papan
 * kanban, tabel, panel rincian, dan rapor tidak pernah menyebut satu status dengan
 * dua nama berbeda.
 */
import axios, { API } from "../../services/apiClient";
import { apiErrorText } from "../../utils/apiError";

export const apiText = apiErrorText;

/** Urutan kolom papan — cermin `design_request_service.BOARD_ORDER`. */
export const DSR_BOARD_ORDER = [
  "draft", "submitted", "assigned", "in_progress", "delivered", "revision", "approved",
];

export const DSR_STATUS_LABEL = {
  draft: "Draf",
  submitted: "Menunggu penugasan",
  assigned: "Ditugaskan",
  in_progress: "Dikerjakan",
  delivered: "Menunggu keputusan",
  approved: "Disetujui (ACC)",
  revision: "Minta revisi",
  cancelled: "Dibatalkan",
};

/** Kelas pil status — memakai kosakata `status-pill` yang sudah ada (tanpa warna baru). */
export const DSR_STATUS_CLASS = {
  draft: "pill-muted",
  submitted: "pill-warning",
  assigned: "pill-info",
  in_progress: "pill-info",
  delivered: "pill-warning",
  approved: "pill-success",
  revision: "pill-danger",
  cancelled: "pill-muted",
};

export const DSR_TARGET_LABEL = {
  motif: "Motif",
  pattern: "Pattern / Pola",
  artwork: "Artwork Printing",
};

export async function dsrMeta() {
  const r = await axios.get(`${API}/design-requests/meta`);
  return r.data || {};
}

export async function getDesignRequest(id) {
  const r = await axios.get(`${API}/design-requests/${id}`);
  return r.data || null;
}

export async function createDesignRequest(payload) {
  const r = await axios.post(`${API}/design-requests`, payload);
  return r.data || null;
}

export async function submitDesignRequest(id) {
  const r = await axios.post(`${API}/design-requests/${id}/submit`, {});
  return r.data || null;
}

export async function assignDesignRequest(id, assigned_to, due_date = "") {
  const r = await axios.post(`${API}/design-requests/${id}/assign`, { assigned_to, due_date });
  return r.data || null;
}

export async function startDesignRequest(id) {
  const r = await axios.post(`${API}/design-requests/${id}/start`, {});
  return r.data || null;
}

export async function deliverDesignRequest(id, gallery_id, note = "") {
  const r = await axios.post(`${API}/design-requests/${id}/deliver`, { gallery_id, note });
  return r.data || null;
}

export async function approveDesignRequest(id, note = "") {
  const r = await axios.post(`${API}/design-requests/${id}/approve`, { note });
  return r.data || null;
}

export async function rejectDesignRequest(id, reason) {
  const r = await axios.post(`${API}/design-requests/${id}/reject`, { reason });
  return r.data || null;
}

export async function cancelDesignRequest(id, reason) {
  const r = await axios.post(`${API}/design-requests/${id}/cancel`, { reason });
  return r.data || null;
}

export async function designerReport(params = {}) {
  const r = await axios.get(`${API}/design/reports/by-designer`, { params });
  return r.data || { items: [], totals: {} };
}

/**
 * Rapor **SAYA** (peran `designer`). Endpoint terpisah dengan sengaja: rapor lintas
 * desainer menuntut izin `design_request.report` (wewenang menilai orang), sedangkan
 * melihat angka diri sendiri hanya butuh `view`. Server mengirim baris milik pemanggil
 * + rata-rata tim yang agregat — tanpa satu nama rekan pun (pola PS-18).
 */
export async function myDesignerReport(params = {}) {
  const r = await axios.get(`${API}/design/reports/mine`, { params });
  return r.data || { me: null, totals: {}, team: {} };
}

/** Entri Galeri Desain badan usaha aktif — dipakai saat desainer menyerahkan hasil. */
export async function galleryOptions() {
  const r = await axios.get(`${API}/design-gallery`);
  const rows = Array.isArray(r.data) ? r.data : (r.data?.items || []);
  return rows.map((g) => ({
    value: g.id,
    label: `${g.code || "(tanpa kode)"} · ${g.title || ""}`.trim(),
  }));
}
