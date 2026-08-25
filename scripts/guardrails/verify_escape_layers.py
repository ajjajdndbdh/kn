#!/usr/bin/env python3
"""INV-UI-10 — **Esc menutup satu lapisan, bukan semuanya.** Pop-up dilarang
memasang pendengar `keydown`/`Escape` sendiri; wajib lewat `utils/escapeLayers`.

KELAS BUG YANG DICEGAH (terukur 2026-08-20 di peramban, saat menutup FASE U)
===========================================================================
`FormModal`, `DetailModal`, `ConfirmModal`, dan satu layar (`WhatsAppRules`)
masing-masing memasang `document.addEventListener("keydown", …)` sendiri lalu
memanggil `onClose()` begitu tombol **Esc** ditekan. Dropdown Radix
(`KNSelect` = Select/Popover/Combobox) juga menutup dirinya sendiri saat Esc.
Jadi **satu** tekan Esc dijawab **dua** lapisan:

    Buat Pesanan Pembelian → isi pemasok · gudang · 12 roll · 540 yard
    → buka pemilih satuan → tekan Esc (niat: tutup dropdown saja)
    → dropdown tertutup DAN seluruh pop-up ikut tertutup → semua isian HILANG.

Bukti empiris sebelum perbaikan (bukan dugaan): sesudah satu Esc,
`[role=option]` = 0 **dan** `[data-testid=create-po-form]` = 0.

Ini kembaran persis **INV-UI-01** (`overlayDismiss`, jalur KLIK backdrop) yang
sudah ditutup lebih dulu; jalur **papan tombol** terlewat karena tidak ada
penjaga untuk itu. Obatnya struktural: satu tumpukan lapisan
(`utils/escapeLayers.useEscapeClose`) — hanya lapisan **teratas** menanggapi Esc,
dan bila ada lapisan Radix terbuka, tumpukan ini **mengalah**.

ATURAN (STATIK, tidak butuh backend)
====================================
  A. Di seluruh `frontend/src`, dilarang memasang pendengar papan tombol sendiri
     untuk menutup sesuatu: `addEventListener("keydown", …)` di berkas yang juga
     menyebut `"Escape"`. Satu-satunya pengecualian: `utils/escapeLayers.js`
     (implementasi tunggalnya).
  B. Pop-up baku (`components/FormModal.jsx`, `ConfirmModal.jsx`,
     `DetailModal.jsx`) WAJIB memakai `useEscapeClose(...)`. Tanpa ini seseorang
     bisa "merapikan" dengan cara menghapus dukungan Esc sama sekali — pop-up
     yang tak bisa ditutup dengan Esc adalah regresi UX yang tak terlihat gate lain.
  C. `utils/escapeLayers.js` wajib mempertahankan tiga hal yang membuatnya benar:
     (C1) pendaftaran fase **capture** (`, true`) — kalau bubble, Radix bisa
     lebih dulu meng-unmount isinya sehingga penanda `[data-radix-…]` sudah hilang
     saat diperiksa dan bug-nya kembali; (C2) memeriksa lapisan Radix
     (`isRadixLayerOpen`); (C3) hanya lapisan **teratas** yang menanggapi.

Yang SENGAJA tidak dituduh:
  * kata "Escape" di komentar/dokumentasi;
  * pendengar `keydown` untuk hal LAIN (mis. `Ctrl+K` pembuka menu, navigasi panah)
    di berkas yang tidak menyebut `Escape`;
  * komponen Radix/shadcn bawaan (`components/ui/**`) — Esc-nya diurus Radix.

Jalankan:
    python scripts/guardrails/verify_escape_layers.py
    python scripts/guardrails/verify_escape_layers.py --self-test
"""
import os
import re
import sys
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(__file__))
from _common import FRONTEND, Guard, strip_comments_and_strings, B, G, R, X  # noqa: E402

SRC = FRONTEND / "src"

# Berkas implementasi tunggal (boleh — memang di sinilah pendengarnya hidup).
IMPL = "utils/escapeLayers.js"
# Pop-up baku yang WAJIB mendukung Esc lewat tumpukan lapisan (aturan B).
MUST_USE_ESCAPE_CLOSE = [
    "components/FormModal.jsx",
    "components/ConfirmModal.jsx",
    "components/DetailModal.jsx",
]

LISTENER = re.compile(r"addEventListener\(\s*[\"']keydown[\"']")
ESCAPE_LIT = re.compile(r"[\"']Escape[\"']")


def analyze_text(src: str, rel: str = "some/File.jsx") -> List[str]:
    """Daftar alasan pelanggaran untuk SATU berkas (kosong = hijau). Fungsi murni."""
    out: List[str] = []
    # Penilaian pada kode TERSTRIP: kata "Escape" di komentar/dokumentasi tidak
    # boleh dihitung (pelajaran ux_audit & INV-UI-05: penjaga yang menuduh palsu
    # akan diabaikan, lalu berhenti menjaga apa pun). Literal string dipertahankan
    # oleh `strip_comments_and_strings`? TIDAK — ia membuang string juga, jadi
    # untuk mendeteksi literal "Escape" kita memakai teks tanpa KOMENTAR saja.
    kode = _buang_komentar(src)

    if rel.replace("\\", "/").endswith(IMPL):
        # Aturan C — implementasi tunggal wajib tetap benar.
        if not re.search(r"addEventListener\([^)]*keydown[^)]*,\s*true\s*\)", kode):
            out.append("pendengar Esc TIDAK dipasang di fase capture (`, true`) — "
                       "Radix bisa meng-unmount lapisannya lebih dulu sehingga "
                       "penandanya hilang saat diperiksa dan modal ikut tertutup lagi.")
        if not re.search(r"if\s*\(\s*isRadixLayerOpen\s*\(", kode):
            out.append("tidak memeriksa lapisan Radix (`if (isRadixLayerOpen())`) — Esc di dalam "
                       "dropdown akan ikut menutup pop-up induknya (kelas bug INV-UI-10).")
        if "layers[layers.length - 1]" not in kode.replace("  ", " "):
            out.append("tidak membatasi ke lapisan TERATAS — semua pop-up yang terbuka "
                       "akan tertutup sekaligus oleh satu Esc.")
        return out

    if rel.replace("\\", "/").startswith("components/ui/"):
        return out                              # komponen Radix/shadcn bawaan

    # Aturan A — pendengar papan tombol sendiri untuk menutup.
    if LISTENER.search(kode) and ESCAPE_LIT.search(kode):
        out.append("memasang pendengar `keydown` + `\"Escape\"` sendiri. Pakai "
                   "`useEscapeClose(open, onClose, busy)` dari `@/utils/escapeLayers` "
                   "supaya Esc hanya menutup lapisan TERATAS (dropdown/pemilih di dalam "
                   "pop-up tidak boleh ikut membuang isian pengguna).")

    # Aturan B — pop-up baku wajib memakai tumpukan lapisan.
    if rel.replace("\\", "/") in MUST_USE_ESCAPE_CLOSE and "useEscapeClose" not in kode:
        out.append("pop-up BAKU tanpa `useEscapeClose(...)` — dukungan Esc hilang "
                   "(pengguna keyboard terjebak di dalam pop-up).")
    return out


def _buang_komentar(src: str) -> str:
    """Kosongkan KOMENTAR saja; literal string DIPERTAHANKAN.

    Dibutuhkan karena penanda yang dinilai justru hidup di dalam string
    (`addEventListener("keydown", …)`, `"Escape"`), jadi
    `strip_comments_and_strings` tidak bisa dipakai apa adanya. Pola yang sama
    dengan `INV-UI-09`/`INV-ROLL-01`.
    """
    out: List[str] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            while i < n and src[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if c == "/" and nxt == "*":
            while i < n and not (src[i] == "*" and i + 1 < n and src[i + 1] == "/"):
                out.append("\n" if src[i] == "\n" else " ")
                i += 1
            out.append("  ")
            i += 2
            continue
        if c in ("'", '"', "`"):
            quote = c
            out.append(c)
            i += 1
            while i < n:
                out.append(src[i])
                if src[i] == "\\":
                    i += 2
                    if i - 1 < n:
                        out.append(src[i - 1])
                    continue
                if src[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def scan() -> Tuple[Dict[str, List[str]], int]:
    hasil: Dict[str, List[str]] = {}
    diperiksa = 0
    for path in sorted(list(SRC.rglob("*.jsx")) + list(SRC.rglob("*.js"))):
        rel = str(path.relative_to(SRC))
        try:
            src = path.read_text(encoding="utf-8")
        except OSError:
            continue
        diperiksa += 1
        v = analyze_text(src, rel)
        if v:
            hasil[rel] = v
    # Aturan B juga harus memerah bila berkasnya HILANG dari repo.
    for rel in MUST_USE_ESCAPE_CLOSE + [IMPL]:
        if not (SRC / rel).exists():
            hasil.setdefault(rel, []).append("berkas standar Esc/pop-up tidak ditemukan.")
    return hasil, diperiksa


def main() -> int:
    g = Guard("INV-UI-10", "Esc menutup lapisan TERATAS saja (satu tumpukan, bukan pendengar sendiri)")
    hasil, diperiksa = scan()
    g.bump(diperiksa)
    pakai = [p for p in sorted(list(SRC.rglob("*.jsx")) + list(SRC.rglob("*.js")))
             if "useEscapeClose" in p.read_text(encoding="utf-8", errors="ignore")]
    print(f"  berkas diperiksa: {diperiksa} · memakai useEscapeClose: {len(pakai)}")
    for rel, alasan in sorted(hasil.items()):
        for a in alasan:
            g.add(f"{rel} — {a}")
    return g.finish()


# ─────────────────────────────────────────────────────────────────────────────
# SELF-TEST — penjaga wajib bisa MEMERAH pada pelanggaran buatan, dan wajib
# TIDAK menuduh bentuk yang sah.
# ─────────────────────────────────────────────────────────────────────────────
IMPL_BENAR = (
    "import { useEffect } from 'react';\n"
    "export function isRadixLayerOpen(doc = document) { return !!doc.querySelector('x'); }\n"
    "const layers = [];\n"
    "export function useEscapeClose(open, onClose, busy = false) {\n"
    "  useEffect(() => {\n"
    "    const entry = { onClose };\n"
    "    layers.push(entry);\n"
    "    const onKey = (e) => {\n"
    "      if (e.key !== 'Escape' || busy) return;\n"
    "      if (layers[layers.length - 1] !== entry) return;\n"
    "      if (isRadixLayerOpen()) return;\n"
    "      entry.onClose();\n"
    "    };\n"
    "    document.addEventListener('keydown', onKey, true);\n"
    "    return () => document.removeEventListener('keydown', onKey, true);\n"
    "  }, [open, onClose, busy]);\n}\n")


def self_test() -> int:
    kasus: List[Tuple[str, bool]] = []

    def cek(nama: str, benar: bool):
        kasus.append((nama, benar))

    # ── Lapis 1 — HARUS MEMERAH ───────────────────────────────────────────────
    cek("pop-up memasang pendengar Esc sendiri (document) → MERAH",
        len(analyze_text("useEffect(() => { const k = (e) => { if (e.key === \"Escape\") "
                         "onClose(); }; document.addEventListener(\"keydown\", k); }, []);",
                         "components/FooModal.jsx")) == 1)
    cek("bentuk `window.addEventListener` juga tertangkap",
        len(analyze_text("const k = (e) => { if (e.key === 'Escape') setShow(false); };\n"
                         "window.addEventListener('keydown', k);",
                         "features/x/Bar.jsx")) == 1)
    cek("FormModal tanpa `useEscapeClose` → MERAH (dukungan Esc hilang)",
        analyze_text("export default function FormModal(){ return null; }",
                     "components/FormModal.jsx") != [])
    cek("implementasi tunggal tanpa fase capture → MERAH",
        any("capture" in a for a in analyze_text(
            IMPL_BENAR.replace("onKey, true)", "onKey)"), "utils/escapeLayers.js")))
    cek("implementasi tunggal tanpa pemeriksaan lapisan Radix → MERAH",
        any("Radix" in a for a in analyze_text(
            IMPL_BENAR.replace("      if (isRadixLayerOpen()) return;\n", ""),
            "utils/escapeLayers.js")))
    cek("implementasi tunggal tanpa aturan lapisan TERATAS → MERAH",
        any("TERATAS" in a for a in analyze_text(
            IMPL_BENAR.replace("      if (layers[layers.length - 1] !== entry) return;\n", ""),
            "utils/escapeLayers.js")))

    # ── Lapis 2 — TIDAK boleh menuduh palsu ───────────────────────────────────
    cek("pop-up memakai `useEscapeClose` → hijau",
        analyze_text("import { useEscapeClose } from '@/utils/escapeLayers';\n"
                     "export default function FormModal({ open, onClose, busy }){\n"
                     "  useEscapeClose(open, onClose, busy);\n  return null;\n}",
                     "components/FormModal.jsx") == [])
    cek("kata \"Escape\" hanya di KOMENTAR → tidak dituduh",
        analyze_text("// Esc ditangani useEscapeClose (dulu listener \"Escape\" sendiri)\n"
                     "document.addEventListener('keydown', onArrowKeys);",
                     "features/x/Baz.jsx") == [])
    cek("pendengar keydown untuk hal LAIN (Ctrl+K) tanpa Escape → hijau",
        analyze_text("document.addEventListener('keydown', (e) => { if (e.key === 'k' "
                     "&& e.metaKey) open(); });", "components/CommandPalette.jsx") == [])
    cek("komponen Radix/shadcn bawaan dikecualikan",
        analyze_text("document.addEventListener('keydown', k); // 'Escape'\n"
                     "const t = \"Escape\";", "components/ui/select.jsx") == [])
    cek("implementasi tunggal yang BENAR → hijau",
        analyze_text(IMPL_BENAR, "utils/escapeLayers.js") == [])
    cek("berkas biasa tanpa pendengar apa pun → hijau",
        analyze_text("export default function Card(){ return null; }",
                     "components/Card.jsx") == [])

    # ── Lapis 3 — kode NYATA repo ini harus hijau ─────────────────────────────
    nyata, _ = scan()
    cek(f"kode nyata saat ini HIJAU ({len(nyata)} berkas melanggar)", not nyata)

    gagal = sum(0 if ok else 1 for _n, ok in kasus)
    print(f"{B}== SELF-TEST INV-UI-10 (Esc satu lapisan) =={X}")
    for nama, ok in kasus:
        print(f"  [{G + 'PASS' + X if ok else R + 'FAIL' + X}] {nama}")
    if gagal:
        print(f"{R}{B}  SELF-TEST MERAH ({gagal} kasus).{X}")
        for rel, alasan in sorted(nyata.items()):
            print(f"    ✗ {rel}: {alasan[0][:130]}")
    else:
        print(f"{G}  HIJAU — penjaga menangkap pendengar Esc sendiri & implementasi "
              f"tunggal yang dilemahkan, tanpa menuduh komentar, pendengar non-Esc, "
              f"maupun komponen Radix bawaan.{X}")
    return gagal


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(1 if self_test() else 0)
    raise SystemExit(main())
