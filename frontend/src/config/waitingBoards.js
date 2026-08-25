/**
 * Tampilan papan "menunggu keputusan" per antrean (ikon · warna · teks kosong).
 *
 * Yang BUKAN di sini: judul, tujuan klik, jumlah, umur tunggu — semuanya datang dari
 * backend (`approval_backlog_service`) supaya layar tak pernah punya pendapat sendiri.
 * Daftar antrean mana yang diberi papan juga milik backend (`HOME_BOARD_KEYS`);
 * berkas ini hanya menjawab "papan ini digambar seperti apa".
 */
import { Scissors, ReceiptText, PackageOpen, Clock } from "lucide-react";

export const BOARD_LOOK = {
  special_order: {
    icon: Scissors, accent: "#6C3FD1",
    title: "Papan PO Custom — menunggu keputusan",
    goto: "Buka PO Custom →",
    empty: "Tidak ada PO custom yang menunggu keputusan",
  },
  contra_bon_dispute: {
    icon: ReceiptText, accent: "#C0392B",
    title: "Kontrabon bersengketa — menunggu keputusan",
    goto: "Buka Kontrabon →",
    empty: "Tidak ada kontrabon bersengketa",
  },
  interco_return: {
    icon: PackageOpen, accent: "#0058CC",
    title: "Retur antar-PT — menunggu persetujuan",
    goto: "Buka Antar Entitas →",
    empty: "Tidak ada retur antar-PT yang menunggu persetujuan",
  },
};

export const boardLook = (key) => BOARD_LOOK[key] || {
  icon: Clock, accent: "#6B6B73", goto: "Buka layarnya →",
  empty: "Tidak ada dokumen yang menunggu keputusan",
};

/**
 * Papan mana yang digambar — SATU pemilih untuk semua beranda.
 *
 * REGRESI B5 YANG DITUTUP (temuan agen uji, 2026-06): dulu tiap beranda menyaring
 * sendiri `waiting_boards`, dan penyaringnya menghasilkan daftar KOSONG ketika
 * pemuatan gagal (`data === null`). Akibatnya papan hilang total — jadi keadaan
 * "tidak bisa dibaca" yang justru dibuat untuk kegagalan TIDAK PERNAH tampil, dan
 * layar kembali terasa seperti kabar baik. Karena itu:
 *   · gagal dibaca  → tetap kembalikan KERANGKA papan PO custom (papannya harus ADA
 *     supaya bisa berkata "tidak bisa dibaca" + tombol Coba lagi);
 *   · terbaca       → papan PO custom selalu tampil, papan lain hanya bila berisi
 *     (tiga papan nol berturut-turut membuat yang penting ikut terabaikan).
 */
export function selectWaitingBoards(data, unreadable = false) {
  const all = data?.waiting_boards
    || (data?.special_orders_waiting
      ? [{ key: "special_order", ...data.special_orders_waiting }] : []);
  if (unreadable) {
    const utama = all.filter((b) => b.key === "special_order");
    return utama.length ? utama : [{ key: "special_order" }];
  }
  return all.filter((b) => b.key === "special_order" || (b.count ?? 0) > 0);
}
