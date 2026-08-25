#!/usr/bin/env python3
"""
gate_probe.py — PELACAK PENYEBAB: gate mana yang mengotori data
===============================================================

MASALAH NYATA (terukur 2026-08-21, sesi penutupan FASE P)
---------------------------------------------------------
`bash scripts/gate.sh --full` memerah di **POC P-0** dan **POC FASE P** dengan
satu pesan pendek:

    [FAIL] `INV-REF` HIJAU — PO mandiri TIDAK dituduh dokumen yatim
           → exit 1 · PASS 31 · FAIL 1

Padahal kedua POC itu **HIJAU saat dijalankan sendiri** dari data demo bersih
(36/36 dan 52/52), dan `python scripts/audit_doc_refs.py` juga hijau (32/0).
Artinya yang merah bukan kode POC-nya, melainkan **keadaan data saat gate
sampai ke sana** — sesuatu yang berjalan LEBIH DULU meninggalkan dokumen
ber-sumber tanpa tautan induk (dan, di jalan lain, +1 `audit_logs`/`inventory_lots`
yang menjatuhkan `INV-GATE-01`).

Menebak siapa pengotornya itu mahal: gate `--full` berisi ~90 langkah, dan
di ujungnya `seed_realistic.py` **menghapus jejak** dengan memulihkan data demo.

CARA PAKAI
----------
    KN_GATE_PROBE=1 bash scripts/gate.sh --full        # probe menempel di run_gate
    python scripts/gate_probe.py --report              # ringkasan: siapa mengubah apa

Setiap langkah gate menulis satu baris JSON ke `/app/.logs/gate_probe.jsonl`:
jumlah dokumen koleksi penting + hasil `audit_doc_refs --strict`. Baris pertama
(`--baseline`) adalah keadaan awal. `--report` menampilkan HANYA langkah yang
menggeser sesuatu — jadi pengotornya terbaca dalam satu tatapan.

Sengaja MURAH: hitung dokumen (cepat) + satu audit relasi dokumen (~2 s).
Tidak menulis apa pun ke basis data, jadi probe sendiri tidak bisa jadi
pengotor baru.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = Path(os.environ.get("KN_GATE_PROBE_LOG", "/app/.logs/gate_probe.jsonl"))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env")
except Exception:  # noqa: BLE001
    pass

#: Koleksi yang paling sering jadi jalan residu (dokumen bisnis + stok + jejak).
WATCH = ("purchase_orders", "purchase_requisitions", "rfqs", "sales_orders",
         "sales_returns", "purchase_returns", "vendor_bills", "tax_invoices",
         "ar_receipts", "shipments", "wms_tasks", "inventory_rolls",
         "inventory_lots", "inventory_movements", "inventory_balances",
         "journal_entries", "audit_logs", "notifications", "md_samples",
         "design_requests", "makloon_orders", "interco_transactions")


def _db():
    from pymongo import MongoClient
    url = (os.environ.get("MONGO_URL") or "mongodb://localhost:27017").strip('"')
    name = (os.environ.get("DB_NAME") or "test_database").strip('"')
    return MongoClient(url, serverSelectionTimeoutMS=5000)[name]


def _plain(s: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", s or "")


def _doc_refs() -> dict:
    """Jalankan audit relasi dokumen SUNGGUHAN → (rc, temuan pertama)."""
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "audit_doc_refs.py"),
                        "--strict"], capture_output=True, text=True, timeout=300)
    out = _plain((p.stdout or "") + (p.stderr or ""))
    fails = [ln.strip() for ln in out.splitlines() if "[FAIL]" in ln]
    return {"rc": p.returncode, "fails": fails[:3]}


def snap(label: str) -> dict:
    db = _db()
    row = {"label": label,
           "counts": {c: db[c].count_documents({}) for c in WATCH},
           "doc_refs": _doc_refs()}
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def report() -> int:
    if not LOG.exists():
        print(f"Belum ada {LOG} — jalankan: KN_GATE_PROBE=1 bash scripts/gate.sh --full")
        return 1
    rows = [json.loads(ln) for ln in LOG.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not rows:
        print("Berkas probe kosong.")
        return 1
    print(f"\n{'=' * 78}\n  PELACAK RESIDU GATE — {len(rows)} langkah terekam\n{'=' * 78}")
    prev = rows[0]
    print(f"  BASELINE: {prev['label']}  ·  doc_refs rc={prev['doc_refs']['rc']}")
    dirty = 0
    for cur in rows[1:]:
        delta = {c: (prev["counts"][c], cur["counts"][c])
                 for c in cur["counts"] if prev["counts"].get(c) != cur["counts"][c]}
        flip = prev["doc_refs"]["rc"] == 0 and cur["doc_refs"]["rc"] != 0
        if delta or flip:
            dirty += 1
            print(f"\n  ▶ {cur['label']}")
            for c, (a, b) in sorted(delta.items()):
                print(f"      {c:22s} {a:>5} → {b:<5} ({b - a:+d})")
            if flip:
                print("      \033[91mdoc_refs BERUBAH MERAH di langkah ini:\033[0m")
                for f in cur["doc_refs"]["fails"]:
                    print(f"        - {f}")
        prev = cur
    print(f"\n  {dirty} langkah menggeser data (yang lain bersih).\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--after", metavar="LABEL", help="rekam keadaan sesudah satu gate")
    ap.add_argument("--baseline", action="store_true", help="mulai berkas probe baru")
    ap.add_argument("--report", action="store_true", help="ringkasan langkah yang mengotori")
    a = ap.parse_args()
    if a.report:
        return report()
    if a.baseline:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        LOG.unlink(missing_ok=True)
        r = snap("BASELINE (sebelum gate pertama)")
        print(f"  [probe] baseline direkam · doc_refs rc={r['doc_refs']['rc']}")
        return 0
    if a.after:
        r = snap(a.after)
        print(f"  [probe] {a.after} · doc_refs rc={r['doc_refs']['rc']}")
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
