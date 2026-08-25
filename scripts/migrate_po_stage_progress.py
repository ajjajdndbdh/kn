#!/usr/bin/env python3
"""FASE P — MIGRASI `purchase_orders.stage_progress[]` (idempotent · `--dry-run`).

APA YANG DILAKUKAN & KENAPA
===========================
Papan PO menyimpan **satu** hal saja: `stage_progress[]` — keputusan manusia
("celup sudah selesai"), fakta yang tidak bisa dihitung dari mana pun. Semua
kolom papan lainnya adalah turunan (lihat `services/po_board_service.py`).

Migrasi ini memberi field itu kepada dokumen LAMA sebagai **daftar kosong**, bukan
membiarkannya tidak ada. Bedanya penting dan bukan kerapian:

    tidak ada field  → "papan tidak tahu apa-apa tentang dokumen ini"
    field = []       → "belum ada tahap yang ditandai orang"

Di layar keduanya tampak sama (semua chip abu-abu), tetapi saat seseorang bertanya
*"kenapa PO ini tidak pernah bergerak?"* jawabannya berbeda: yang pertama berarti
dokumennya lahir sebelum papan ada, yang kedua berarti memang belum dikerjakan.
Tanpa pembedaan ini, tiap layar/laporan berikutnya akan menebak sendiri — dan
tebakan yang berbeda-beda adalah cara paling murah membuat angka saling berselisih.

PO baru **tidak** butuh migrasi ini: keempat pintu lahirnya PO men-spread
`po_board_service.PO_BOARD_EMPTY` (dijaga gate `INV-STAGE-01`). Migrasi ini untuk
basis data yang sudah berisi.

SIFAT
-----
* **Idempotent** — hanya menyentuh dokumen yang belum punya field-nya; dijalankan
  dua kali, laporan kedua "0 diubah".
* **Tidak pernah menimpa** progres yang sudah ada (`$exists: true` dilewati) —
  migrasi yang bisa menghapus keputusan manusia adalah migrasi yang berbahaya.
* Blanket/kontrak payung ikut diberi field kosong: ia dokumen `purchase_orders`
  juga, dan bentuk dokumen yang berbeda-beda di satu koleksi adalah sumber bug
  yang mahal. (Papan sendiri menyaringnya keluar — kontrak payung bukan pesanan
  yang menempuh tahap.)

Usage:
    python scripts/migrate_po_stage_progress.py --dry-run
    python scripts/migrate_po_stage_progress.py
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env")
except Exception:  # noqa: BLE001
    pass

G, Y, R, B, X = "\033[92m", "\033[93m", "\033[91m", "\033[1m", "\033[0m"

FIELD = "stage_progress"


async def run(dbx: Any = None, *, dry_run: bool = False) -> Dict[str, int]:
    """Bungkus tipis di atas `po_board_service.ensure_stage_field()`.

    Logikanya SENGAJA tidak ditulis ulang di sini: seeder data demo memanggil
    fungsi service yang sama, jadi basis data lama & basis data demo melewati
    pintu yang IDENTIK. Skrip ini hanya menyediakan CLI + laporan.
    """
    if dbx is None:
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(os.environ.get("MONGO_URL",
                                                   "mongodb://localhost:27017"))
        dbx = client[os.environ.get("DB_NAME", "test_database")]
    from services import po_board_service as board      # noqa: PLC0415
    return await board.ensure_stage_field(dbx, dry_run=dry_run)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="hitung saja, jangan tulis")
    args = ap.parse_args()
    r = await run(dry_run=args.dry_run)
    print(f"{B}FASE P — migrasi purchase_orders.{FIELD}{X}")
    print(f"  PO total                     : {r['total']}")
    print(f"  belum punya field            : {r['missing_before']}")
    print(f"  {'akan diisi' if args.dry_run else 'diisi'}                   : "
          f"{r['missing_before'] if args.dry_run else r['written']}")
    print(f"  sudah punya progres berisi   : {r['with_progress']} "
          "(TIDAK disentuh — keputusan manusia tak boleh ditimpa migrasi)")
    sisa = r["missing_before"] if args.dry_run else 0
    if args.dry_run and r["missing_before"]:
        print(f"{Y}  dry-run: jalankan tanpa --dry-run untuk menulis.{X}")
    elif sisa == 0:
        print(f"{G}  Selesai — seluruh PO punya field papan (idempotent: jalan ulang "
              f"akan melaporkan 0).{X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
