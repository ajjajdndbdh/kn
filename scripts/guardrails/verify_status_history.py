"""INV-HIST-01 — `status_history[]` hanya boleh punya SATU bentuk.

KELAS CACAT YANG DICEGAH. Field bernama sama dengan bentuk berbeda per koleksi:
`special_orders` menulis `{"status", "timestamp", "user"}` sementara `inventory_lots`
dulu menulis `{"status", "at", "actor"}`. Pembaca lintas koleksi (`waiting_since`,
timeline generik, laporan umur keputusan) membaca `entry["timestamp"]`, mendapat
`None` tanpa satu pun galat, lalu jatuh ke cadangan `created_at` — umur keputusan
karena itu tenang-tenang salah. Ini kelas cacat B1 ("field ditebak") yang persis
sama, hanya pintu masuknya lain.

APA YANG DIPERIKSA (statik, tanpa basis data — jadi ia menuduh KODE, bukan data):
setiap jalur tulis `status_history` di `backend/routers` & `backend/services` harus
menyertakan kunci waktu kanonik `"timestamp"`, atau memakai penyusun SSOT
`services/status_history.py` (`sh.entry(...)`/`status_history.entry(...)`).

Usage:
    python scripts/guardrails/verify_status_history.py
    python scripts/guardrails/verify_status_history.py --self-test
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Guard, G, R, B, X  # noqa: E402

TIME_KEY = "timestamp"
#: `"status_history": {…}` / `"status_history": [{…}]` — literal dict yang ditulis.
POLA = re.compile(r'"status_history"\s*:\s*\[?\s*(\{[^{}]*\})')
#: Pemanggilan penyusun SSOT (bentuknya dijamin oleh modulnya sendiri).
POLA_SSOT = re.compile(r'"status_history"\s*:\s*\[?\s*(?:sh|status_history)\.entry\(')


def periksa(g: Guard, berkas: dict) -> None:
    """`berkas` = {nama: isi sumber}. Fungsi murni → bisa diuji-merah."""
    for nama, src in sorted(berkas.items()):
        for m in POLA.finditer(src):
            g.bump()
            literal = m.group(1)
            if f'"{TIME_KEY}"' in literal:
                continue
            baris = src[:m.start()].count("\n") + 1
            g.add(f"{nama}:{baris} menulis entri `status_history` TANPA kunci waktu "
                  f"kanonik `\"{TIME_KEY}\"` ({literal[:70]}…) — field bernama sama "
                  f"dengan bentuk berbeda membuat pembaca lintas koleksi mendapat "
                  f"`None` tanpa galat lalu jatuh ke `created_at` (kelas cacat B1). "
                  f"Pakai `services/status_history.entry(...)`.")


def sumber_backend() -> dict:
    out = {}
    for sub in ("routers", "services"):
        d = ROOT / "backend" / sub
        for f in sorted(d.glob("*.py")):
            out[f"backend/{sub}/{f.name}"] = f.read_text(encoding="utf-8")
    # Penyemai juga menulis riwayat: data demo berbentuk lain sama merusaknya.
    boot = ROOT / "backend" / "bootstrap.py"
    if boot.exists():
        out["backend/bootstrap.py"] = boot.read_text(encoding="utf-8")
    return out


def self_test() -> int:
    kasus = [
        ("entri kanonik → hijau",
         {"a.py": '{"status_history": [{"status": s, "timestamp": now_iso(), "user": u}]}'}, 0),
        ("entri berkunci `at` (bentuk ke-dua) → merah",
         {"b.py": '{"status_history": [{"status": s, "actor": a, "at": now_iso()}]}'}, 1),
        ("dua jalur tulis, satu salah → satu tuduhan",
         {"c.py": '{"status_history": [{"status": s, "timestamp": t}]}\n'
                  '{"status_history": {"status": s, "changed_at": t}}'}, 1),
        ("memakai penyusun SSOT → hijau (bentuknya dijamin modulnya)",
         {"d.py": '{"status_history": [sh.entry(st, user=u)]}'}, 0),
        ("tanpa jalur tulis sama sekali → hijau",
         {"e.py": 'doc.get("status_history")'}, 0),
    ]
    gagal = 0
    print(f"{B}== SELF-TEST INV-HIST-01 (penjaga bentuk riwayat harus bisa MEMERAH) =={X}")
    for nama, berkas, harap in kasus:
        g = Guard("INV-HIST-01", "self-test")
        g.violations, g.checks = [], 0
        periksa(g, berkas)
        got = len(g.violations)
        ok_ = got == harap
        gagal += 0 if ok_ else 1
        print(f"  [{G + 'PASS' + X if ok_ else R + 'FAIL' + X}] {nama}  "
              f"(harap={harap}, dapat={got})")
    if gagal:
        print(f"{R}{B}  SELF-TEST MERAH — penjaga bentuk riwayat tak bisa dipercaya.{X}")
    else:
        print(f"{G}  HIJAU — penjaga terbukti menuduh bentuk riwayat ke-dua.{X}")
    return gagal


def main() -> int:
    g = Guard("INV-HIST-01", "`status_history` hanya boleh punya SATU bentuk")
    berkas = {k: v for k, v in sumber_backend().items()
              if not k.endswith("services/status_history.py")}
    periksa(g, berkas)
    return g.finish()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(1 if self_test() else 0)
    sys.exit(main())
