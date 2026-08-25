#!/usr/bin/env python3
"""Pembaca baris `run_gate "label" "perintah"` dari scripts/gate.sh.

KENAPA ADA (D3 · 2026-08-25): dua alat bisect sementara memakai
`shlex.split(baris)[2]` untuk mengambil perintahnya. Pada baris `run_gate` yang
BERLANJUT ke baris berikutnya (akhiran `\\`) hasil `shlex.split` tidak berisi
perintah utuh — alatnya lalu **melewati POC itu tanpa berkata apa-apa** (terlihat
di `.logs/bisect_settings.log`: dua POC hilang tanpa jejak). Alat ukur yang bisa
"melewatkan dengan tenang" lebih berbahaya daripada tidak ada alat ukur.

Pemakaian:
    python scripts/_legacy/_parse_run_gate.py scripts/gate.sh 807 848
Keluaran: satu baris per gate → `label<TAB>perintah`. Baris yang TIDAK bisa
dibaca dicetak ke stderr sebagai `LEWAT: …` (berisik, bukan diam).
"""
from __future__ import annotations

import re
import sys

QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')


def gabung_lanjutan(baris: list[str]) -> list[str]:
    """Satukan baris yang berakhir `\\` dengan baris sesudahnya."""
    out: list[str] = []
    buf = ""
    for b in baris:
        b = b.rstrip("\n")
        if buf:
            buf += " " + b.strip()
        else:
            buf = b
        if buf.rstrip().endswith("\\"):
            buf = buf.rstrip()[:-1]
            continue
        out.append(buf)
        buf = ""
    if buf:
        out.append(buf)
    return out


def main() -> int:
    path, awal, akhir = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    with open(path, encoding="utf-8") as fh:
        semua = fh.readlines()[awal - 1:akhir]
    for baris in gabung_lanjutan(semua):
        if not baris.strip().startswith("run_gate "):
            continue
        petik = QUOTED.findall(baris)
        if len(petik) < 2:
            print(f"LEWAT: tidak bisa dibaca → {baris.strip()[:120]}", file=sys.stderr)
            continue
        print(f"{petik[0]}\t{petik[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
