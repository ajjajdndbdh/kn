/**
 * escapeLayers — satu aturan untuk tombol **Esc** di seluruh aplikasi:
 * *Esc menutup **lapisan paling atas**, bukan semua lapisan sekaligus.*
 *
 * MASALAH YANG DIPERBAIKI (bug kelas "isian hilang", terukur 2026-08-20 di peramban)
 * =================================================================================
 * `FormModal`/`DetailModal`/`ConfirmModal` masing-masing memasang pendengar
 * `keydown` sendiri di `document` dan langsung memanggil `onClose()` begitu Esc
 * ditekan. Sementara itu dropdown Radix (`KNSelect` = Select/Popover/Combobox)
 * juga menutup dirinya sendiri saat Esc. Akibatnya **satu** tekan Esc dijawab
 * DUA lapisan:
 *
 *     buka "Buat Pesanan Pembelian" → isi pemasok, gudang, 12 roll · 540 yard
 *     → buka pemilih satuan → tekan Esc (niatnya: tutup dropdown-nya saja)
 *     → dropdown tertutup **dan seluruh pop-up ikut tertutup** → semua isian HILANG.
 *
 * Direproduksi sendiri di peramban (bukan dugaan): sesudah satu Esc,
 * `[role=option]` = 0 **dan** `[data-testid=create-po-form]` = 0.
 * Ini kembaran persis dari kelas bug INV-UI-01 (`overlayDismiss`) yang sudah
 * ditutup untuk KLIK backdrop — jalur papan tombolnya terlewat.
 *
 * ATURANNYA
 * =========
 *  1. Tiap pop-up mendaftar ke satu **tumpukan**. Hanya entri **teratas** yang
 *     menanggapi Esc (jadi pemilih produk di dalam modal menutup pemilihnya saja).
 *  2. Bila ada **lapisan Radix** yang sedang terbuka (Select/Popover/Menu/cmdk),
 *     Esc **diabaikan** oleh tumpukan ini — Radix yang menutup lapisannya sendiri.
 *  3. Pendengar dipasang di fase **CAPTURE** supaya berjalan SEBELUM pendengar
 *     Radix (yang memakai fase bubble). Kalau dipasang di bubble, Radix bisa
 *     lebih dulu meng-unmount isinya sehingga penanda `[data-radix-…]` sudah
 *     hilang saat kita memeriksa → modal tetap tertutup dan bug-nya kembali.
 *  4. `busy` (sedang menyimpan) tetap dihormati: Esc tidak menutup apa pun.
 *
 * Pemakaian:
 *   import { useEscapeClose } from "@/utils/escapeLayers";
 *   useEscapeClose(open, onClose, busy);          // di dalam komponen pop-up
 *
 * Dijaga gate **INV-UI-10** (`scripts/guardrails/verify_escape_layers.py`):
 * mendaftarkan `keydown` + `Escape` sendiri di komponen pop-up = MERAH.
 */
import { useEffect } from "react";

/** Penanda DOM lapisan Radix yang HIDUP (ada hanya selama lapisannya terbuka). */
export const RADIX_LAYER_SELECTOR = [
  "[data-radix-popper-content-wrapper]", // Select/Popover/Dropdown ber-posisi popper
  "[data-radix-select-viewport]",         // Select mode item-aligned
  "[data-radix-menu-content]",            // DropdownMenu / ContextMenu
  "[cmdk-root]",                          // Combobox pencarian (cmdk) di KNSelect
  "[role='listbox']",                     // daftar opsi apa pun yang masih terbuka
].join(",");

/** true bila ada lapisan Radix terbuka → Esc bukan milik tumpukan kita. */
export function isRadixLayerOpen(doc = typeof document === "undefined" ? null : document) {
  if (!doc) return false;
  return !!doc.querySelector(RADIX_LAYER_SELECTOR);
}

// Tumpukan lapisan (modul-level: satu untuk seluruh aplikasi).
const layers = [];

/** Untuk uji/diagnostik: berapa lapisan yang sedang mendaftar. */
export function escapeLayerCount() {
  return layers.length;
}

/**
 * Daftarkan pop-up ke tumpukan Esc.
 * @param {boolean} open   pop-up sedang terbuka
 * @param {Function} onClose  penutup pop-up ini
 * @param {boolean} busy   sedang menyimpan → Esc diabaikan
 */
export function useEscapeClose(open, onClose, busy = false) {
  useEffect(() => {
    if (!open || typeof onClose !== "function") return undefined;
    const entry = { onClose };
    layers.push(entry);

    const onKey = (e) => {
      if (e.key !== "Escape" || busy) return;
      if (layers[layers.length - 1] !== entry) return; // bukan lapisan teratas
      if (isRadixLayerOpen()) return;                  // Radix menutup miliknya sendiri
      e.stopPropagation();
      entry.onClose();
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      const i = layers.indexOf(entry);
      if (i >= 0) layers.splice(i, 1);
    };
  }, [open, onClose, busy]);
}

export default useEscapeClose;
