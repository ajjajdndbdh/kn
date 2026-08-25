/**
 * rndApi (FASE F) — satu pintu akses API **R&D & Desain**.
 * Semua endpoint ber-prefix /api (REACT_APP_BACKEND_URL) via apiClient.
 */
import axios, { API } from "../../services/apiClient";

// ── Meta & kebijakan ─────────────────────────────────────────────────────────
export const rndMeta = (params) => axios.get(`${API}/rnd/meta`, { params }).then((r) => r.data);
export const lifecycleBoard = (params) =>
  axios.get(`${API}/rnd/lifecycle-board`, { params }).then((r) => r.data);
export const performerReport = (params) =>
  axios.get(`${API}/rnd/reports/performer`, { params }).then((r) => r.data);

// ── Spesifikasi (md_specs) ───────────────────────────────────────────────────
export const listSpecs = (params) => axios.get(`${API}/rnd/specs`, { params }).then((r) => r.data);
export const getSpec = (id) => axios.get(`${API}/rnd/specs/${id}`).then((r) => r.data);
export const createSpec = (body) => axios.post(`${API}/rnd/specs`, body).then((r) => r.data);
export const patchSpec = (id, body) =>
  axios.patch(`${API}/rnd/specs/${id}`, body).then((r) => r.data);
export const submitSpec = (id) =>
  axios.post(`${API}/rnd/specs/${id}/submit`).then((r) => r.data);
export const approveSpec = (id, body) =>
  axios.post(`${API}/rnd/specs/${id}/approve`, body).then((r) => r.data);
export const rejectSpec = (id, reason, note = "") =>
  axios.post(`${API}/rnd/specs/${id}/reject`, { reason, note }).then((r) => r.data);
export const releaseProduct = (id, reason, note = "") =>
  axios.post(`${API}/rnd/specs/${id}/release-product`, { reason, note }).then((r) => r.data);

// ── Permintaan sample (md_samples) ───────────────────────────────────────────
export const listSamples = (params) =>
  axios.get(`${API}/rnd/samples`, { params }).then((r) => r.data);
export const getSample = (id) => axios.get(`${API}/rnd/samples/${id}`).then((r) => r.data);
export const createSample = (body) => axios.post(`${API}/rnd/samples`, body).then((r) => r.data);
export const patchSample = (id, body) =>
  axios.patch(`${API}/rnd/samples/${id}`, body).then((r) => r.data);
export const sendSample = (id, body) =>
  axios.post(`${API}/rnd/samples/${id}/send`, body).then((r) => r.data);
export const openRound = (id, body) =>
  axios.post(`${API}/rnd/samples/${id}/rounds`, body).then((r) => r.data);
export const submitRound = (id, roundId, body) =>
  axios.post(`${API}/rnd/samples/${id}/rounds/${roundId}/submit`, body).then((r) => r.data);
export const assessRound = (id, roundId, body) =>
  axios.post(`${API}/rnd/samples/${id}/rounds/${roundId}/assess`, body).then((r) => r.data);
export const decideSample = (id, body) =>
  axios.post(`${API}/rnd/samples/${id}/decide`, body).then((r) => r.data);
export const issueMaterial = (id, body) =>
  axios.post(`${API}/rnd/samples/${id}/issue-material`, body).then((r) => r.data);
export const cancelSample = (id, reason) =>
  axios.post(`${API}/rnd/samples/${id}/cancel`, { reason }).then((r) => r.data);

// ── FASE S — jenis sampling (MASTER hidup) & pelaksanaan sample ──────────────
// `sampleTypes()` sengaja terpisah dari `rndMeta()`: pemilih jenis dipakai juga di
// layar Master (Pengaturan) dan tidak butuh statistik permintaan sample.
export const sampleTypes = (params) =>
  axios.get(`${API}/rnd/sample-types`, { params }).then((r) => r.data);
export const finishSample = (id, body) =>
  axios.post(`${API}/rnd/samples/${id}/finish`, body).then((r) => r.data);
export const deliverSample = (id, body) =>
  axios.post(`${API}/rnd/samples/${id}/deliver`, body).then((r) => r.data);

export const uploadRoundProof = (id, roundId, file) => {
  const fd = new FormData();
  fd.append("file", file);
  return axios.post(`${API}/rnd/samples/${id}/rounds/${roundId}/attachments`, fd)
    .then((r) => r.data);
};
export const roundProofUrl = (id, roundId, fileId) =>
  `${API}/rnd/samples/${id}/rounds/${roundId}/attachments/${fileId}`;

// ── Master desain (perluasan design_gallery — PS-14) ─────────────────────────
export const listDesigns = (params) =>
  axios.get(`${API}/design-gallery`, { params }).then((r) => r.data);
export const createDesign = (body) =>
  axios.post(`${API}/design-gallery`, body).then((r) => r.data);
export const patchDesign = (id, body) =>
  axios.put(`${API}/design-gallery/${id}`, body).then((r) => r.data);
export const deleteDesign = (id) =>
  axios.delete(`${API}/design-gallery/${id}`).then((r) => r.data);
export const bumpDesignVersion = (id, body) =>
  axios.post(`${API}/design-gallery/${id}/version`, body).then((r) => r.data);
export const approveDesign = (id, note = "") =>
  axios.post(`${API}/design-gallery/${id}/approve`, { note }).then((r) => r.data);
export const rateDesign = (id, stars, note = "") =>
  axios.post(`${API}/design-gallery/${id}/rating`, { stars, note }).then((r) => r.data);
export const unrateDesign = (id) =>
  axios.delete(`${API}/design-gallery/${id}/rating`).then((r) => r.data);
export const uploadDesignFile = (id, file) => {
  const fd = new FormData();
  fd.append("file", file);
  return axios.post(`${API}/design-gallery/${id}/files`, fd).then((r) => r.data);
};
export const designFileUrl = (id, fileId) => `${API}/design-gallery/${id}/files/${fileId}`;

// ── Master pendukung ─────────────────────────────────────────────────────────
export const listColors = () => axios.get(`${API}/color-library`).then((r) => r.data);
export const listRolls = (params) =>
  axios.get(`${API}/inventory/rolls`, { params }).then((r) => r.data);

// FASE D (2026-08-20) — DUA EKSPOR DICABUT DARI MODUL BERSAMA INI, dan sengaja
// dicatat supaya tidak "dirapikan" kembali ke sini:
//
//   listSuppliers  → dipindah ke satu-satunya pemakainya, `SampleSendModal.jsx`
//   listWarehouses → DIHAPUS (mati: diekspor, nol pemakai di seluruh frontend/src)
//
// Kenapa ini penting dan bukan kosmetik: `audit_sales_roles_ux` menilai layar dari
// **penutupan impor**-nya. `rndApi.js` diimpor oleh `RndDesignsView` (Desain & Pattern)
// dan `DesignGalleryView` (Galeri Desain) — dua layar yang dimiliki peran ke-7
// `designer`. Karena modul ini membawa `/suppliers` & `/warehouses` (yang memang 403
// untuk desainer, dan memang TIDAK pernah dipanggil kedua layar itu), audit melaporkan
// **3 PANEL MATI** milik desainer. Menutupnya dengan baris pembebasan di
// `TERGATED_DI_KODE` akan membuat gate hijau atas alasan yang tidak benar: pagarnya
// bukan "dipagari izin", melainkan "endpointnya menumpang di modul yang salah".
// Obat yang benar = endpoint hidup di dekat pemakainya.

