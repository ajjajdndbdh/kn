/**
 * poBoardApi.js — FASE P · akses data **PAPAN PO PER LINI** + kosakata tampilannya.
 *
 * KENAPA MODUL SENDIRI (bukan menumpang modul API pembelian yang sudah ada)
 * ------------------------------------------------------------------------
 * `audit_sales_roles_ux` menilai sebuah layar dari **penutupan impor**-nya: kalau
 * endpoint papan ini ditaruh di modul API bersama, layar LAIN yang mengimpor modul
 * itu akan dituduh punya "panel mati" (403) hanya karena kebetulan satu berkas.
 * Pelajaran FASE D (2026-08-20) — `listWarehouses`/`listSuppliers` yang menumpang
 * di `features/rnd/rndApi.js` membuat tiga layar desainer dituduh panel mati.
 *
 * Label status tahap ditulis SEKALI di sini supaya papan, modal penanda, dan CSV
 * memakai kata yang sama. Nama TAHAP-nya sendiri **tidak** ada di berkas ini: ia
 * datang dari master (`process_stages`) lewat respons server — kalau ditulis di
 * frontend, tahap baru yang ditambah pemilik akan tampil sebagai kode mentah.
 */
import axios, { API } from "../../services/apiClient";

/** Status tahap — arti & warnanya sama di seluruh layar (server: STAGE_STATUSES). */
export const STAGE_STATUS_LABEL = {
  pending: "Belum mulai",
  in_progress: "Sedang dikerjakan",
  done: "Selesai",
};

/** Kelas chip per status. Memakai palet yang SUDAH ada (kontrak UI/UX §4). */
export const STAGE_STATUS_CLASS = {
  pending: "border-[#E5E5EA] bg-white text-[#8E8E93]",
  in_progress: "border-[#F0B429] bg-[#FFF8E6] text-[#8A5B00]",
  done: "border-[#1F9D55] bg-[#E9F7EF] text-[#166534]",
};

/** Penyaring status PO di papan (nilai `?status=`). */
export const PO_STATUS_TABS = [
  { key: "open", label: "Berjalan" },
  { key: "", label: "Semua" },
  { key: "pending", label: "Menunggu kirim" },
  { key: "receiving", label: "Sedang diterima" },
  { key: "partial", label: "Diterima sebagian" },
  { key: "completed", label: "Selesai" },
];

/** Ambil satu halaman papan (dipakai `usePagedList` untuk baris + ringkasan). */
export async function fetchBoard(params = {}) {
  const r = await axios.get(`${API}/purchase-orders/board`, { params });
  return r.data || {};
}

/**
 * Tandai satu tahap PO. Mengembalikan **baris papan yang sudah diperbarui**
 * sehingga layar menyegarkan satu baris — bukan memuat ulang seluruh papan
 * (papan MD bisa panjang; memuat ulang semuanya membuat klik terasa berat).
 */
export async function setStage(poId, { stage_code, status, note = "" }) {
  const r = await axios.patch(`${API}/purchase-orders/${poId}/stage`,
    { stage_code, status, note });
  return r.data;
}

/** Pesan galat yang bisa dibaca manusia (detail dari server diutamakan). */
export function apiText(e, fallback) {
  return e?.response?.data?.detail || e?.message || fallback;
}

/** Tanggal ISO → `21 Agu 2026` (kosong → "—"). */
export function shortDate(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleDateString("id-ID", { day: "2-digit", month: "short", year: "numeric" });
}

/** Tanggal + jam untuk tooltip jejak tahap ("siapa & kapan"). */
export function longDateTime(value) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString("id-ID", {
    day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}
