#!/usr/bin/env python3
"""ukur_residu_poc.py — UKUR residu per-POC (alat diagnosis, bukan gate).

Kenapa ada: `gate_residue.py --check` benar tetapi hanya melapor "gate
meninggalkan residu" untuk SELURUH blok POC — ia tidak bisa menunjuk POC MANA.
Menebak dari nama koleksi memakan waktu dan sering salah, jadi alat ini
menjalankan tiap POC satu per satu dan menghitung SELISIH SELURUH koleksi.

Pemakaian:
    python scripts/ukur_residu_poc.py                  # semua POC di gate.sh
    python scripts/ukur_residu_poc.py --only g9 tahapan
    python scripts/ukur_residu_poc.py --seed-first     # seed bersih dulu
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

from pymongo import MongoClient

ROOT = Path(__file__).resolve().parent.parent
G, R, Y, C, B, X = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[1m", "\033[0m"

# Koleksi yang wajar bergeser (lihat VOLATILE di POC E-7): sesi masuk & penghitung
# nomor dokumen yang HARUS monoton.
VOLATILE = {"sessions", "login_attempts", "number_sequences"}


def poc_commands() -> list[str]:
    src = (ROOT / "scripts" / "gate.sh").read_text(encoding="utf-8")
    out, seen = [], set()
    for m in re.finditer(r'run_gate "POC[^"]*" "([^"]*)"', src):
        cmd = m.group(1)
        if cmd not in seen and "test_" in cmd:
            seen.add(cmd)
            out.append(cmd)
    return out


def counts(db) -> dict:
    return {c: db[c].count_documents({}) for c in db.list_collection_names()
            if c not in VOLATILE}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None,
                    help="hanya POC yang namanya memuat salah satu kata ini")
    ap.add_argument("--seed-first", action="store_true")
    args = ap.parse_args()

    db = MongoClient("mongodb://localhost:27017")["test_database"]
    if args.seed_first:
        print(f"{C}seed_realistic …{X}")
        subprocess.run([sys.executable, "seed_realistic.py"], cwd=ROOT,
                       capture_output=True, check=False)
        subprocess.run([sys.executable, "seed_e9_chain_demo.py"], cwd=ROOT,
                       capture_output=True, check=False)

    cmds = poc_commands()
    if args.only:
        cmds = [c for c in cmds if any(k in c for k in args.only)]
    print(f"{B}{len(cmds)} POC diukur — selisih SELURUH koleksi per POC{X}\n")

    dirty = []
    for cmd in cmds:
        name = cmd.split("/")[-1].replace(".py", "")
        before = counts(db)
        t0 = time.time()
        p = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True)
        after = counts(db)
        drift = sorted((c, before.get(c, 0), after.get(c, 0))
                       for c in set(before) | set(after)
                       if before.get(c, 0) != after.get(c, 0))
        dur = time.time() - t0
        rc = "" if p.returncode == 0 else f" {R}[rc={p.returncode}]{X}"
        if drift:
            dirty.append((name, drift))
            print(f"  {R}✗{X} {name:38s} {dur:5.1f}s{rc}")
            for c, b, a in drift:
                print(f"        {c:32s} {b:5d} -> {a:5d}  ({a - b:+d})")
        else:
            print(f"  {G}✓{X} {name:38s} {dur:5.1f}s{rc}  nol residu")

    print(f"\n{B}RINGKASAN:{X} {len(cmds) - len(dirty)} bersih · "
          f"{R if dirty else G}{len(dirty)} meninggalkan residu{X}")
    return 1 if dirty else 0


if __name__ == "__main__":
    sys.exit(main())
