#!/usr/bin/env python3
"""Pemantau sekali-pakai: SIAPA yang meninggalkan dokumen `inspections` saat gate jalan.

Dipakai 2026-08-23 untuk menemukan sumber residu +1 pada `gate.sh --full`. Gejalanya
muncul JAUH dari sebabnya (POC P-0 & FASE P memerah lewat INV-REF "Tautan
menggantung"), jadi menebak-nebak POC mana yang salah akan mahal. Pemantau ini
mencatat: kapan dokumen baru muncul, isinya, dan **baris gate yang sedang berjalan**
saat itu — sehingga penyebabnya bisa ditunjuk dengan bukti, bukan dugaan.

Jalankan bersamaan dengan gate:
    python .logs/_pantau_residu_inspeksi.py /tmp/gate_run2.log 460 &
"""
import re
import sys
import time

from pymongo import MongoClient

LOG = sys.argv[1] if len(sys.argv) > 1 else "/tmp/gate_run2.log"
DETIK = int(sys.argv[2]) if len(sys.argv) > 2 else 460
OUT = "/app/.logs/leaker.log"

db = MongoClient("mongodb://localhost:27017")["test_database"]
awal = {d["id"] for d in db.inspections.find({}, {"_id": 0, "id": 1})}
terlihat = set(awal)
baris = []


def gate_sekarang() -> str:
    """Nama gate terakhir yang MULAI berjalan (penanda '▶' di keluaran gate.sh)."""
    try:
        with open(LOG, encoding="utf-8", errors="replace") as f:
            teks = f.read()
    except OSError:
        return "(log belum ada)"
    tanda = re.findall(r"▶ (.{0,90})", re.sub(r"\x1b\[[0-9;]*m", "", teks))
    return tanda[-1].strip() if tanda else "(belum ada gate)"


mulai = time.time()
while time.time() - mulai < DETIK:
    for d in db.inspections.find({}, {"_id": 0, "id": 1, "number": 1, "kind": 1,
                                      "ref_doc_number": 1, "task_id": 1,
                                      "created_by": 1, "remark": 1, "entity_id": 1}):
        if d["id"] in terlihat:
            continue
        terlihat.add(d["id"])
        baris.append(f"[+{int(time.time() - mulai):>3}s] LAHIR {d.get('number')} "
                     f"kind={d.get('kind')} ref={d.get('ref_doc_number')!r} "
                     f"task={d.get('task_id')!r} oleh={d.get('created_by')!r} "
                     f"| GATE SAAT ITU: {gate_sekarang()}")
    time.sleep(2)

akhir = {d["id"] for d in db.inspections.find({}, {"_id": 0, "id": 1})}
sisa = akhir - awal
with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(baris) or "(tidak ada dokumen inspeksi baru sepanjang pemantauan)")
    f.write(f"\n\nSISA di akhir: {len(sisa)} dokumen — {sorted(sisa)}\n")
print("\n".join(baris) or "(nol dokumen baru)")
print("SISA:", len(sisa))
