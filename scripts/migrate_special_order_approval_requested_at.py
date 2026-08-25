#!/usr/bin/env python3
"""B1 — MIGRASI `special_orders.approval_requested_at` (idempotent · `--dry-run`).

APA YANG DILAKUKAN & KENAPA
===========================
Papan PO Custom di beranda pemilik dan pengingat harian menyebut "sudah menunggu
N hari". Angka itu dulu dibaca dari field `submitted_at`/`approval_requested_at`
yang **TIDAK PERNAH DIISI SIAPA PUN** (grep jalur tulis = nol hasil), sehingga umur
tunggu selalu jatuh ke `created_at`. Untuk dokumen yang lama berstatus `draft` lalu
baru diajukan, papan **melebih-lebihkan** umurnya — dan tidak ada satu pun galat
yang memberi tahu; ia hanya diam. Itu kelas cacat paling mahal di repo ini.

Kebenarannya sudah ADA di dokumen: `status_history[]` menyimpan
`{"status": "pending_approval", "timestamp": …}`. Migrasi ini memindahkannya ke
field yang memang dibaca `AGING_META` supaya papan tidak perlu menebak.

Dokumen BARU tidak butuh migrasi ini: jalur pengajuan
(`routers/special_orders.py`) menuliskannya sendiri, dan penjaga
`scripts/guardrails/verify_aging_fields.py` (INV-AGING-01) memerah bila suatu hari
`AGING_META` kembali menyebut field yang tak ada jalur tulisnya.

SIFAT
-----
* **Idempotent** — hanya dokumen `pending_approval` yang belum punya field-nya.
* **Tidak menimpa** nilai yang sudah ada.
* Logikanya TIDAK ditulis ulang di sini: ia tinggal di
  `services/special_order_service.ensure_approval_requested_at()` — pintu yang sama
  dipakai bootstrap, jadi basis data lama & demo melewati jalur IDENTIK.

Usage:
    python scripts/migrate_special_order_approval_requested_at.py --dry-run
    python scripts/migrate_special_order_approval_requested_at.py
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

G, Y, B, X = "\033[92m", "\033[93m", "\033[1m", "\033[0m"


async def run(dbx: Any = None, *, dry_run: bool = False) -> Dict[str, int]:
    if dbx is None:
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        dbx = client[os.environ["DB_NAME"]]
    from services import special_order_service as sos      # noqa: PLC0415
    return await sos.ensure_approval_requested_at(dbx, dry_run=dry_run)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="hitung saja, jangan tulis")
    args = ap.parse_args()
    r = await run(dry_run=args.dry_run)
    print(f"{B}B1 — migrasi special_orders.approval_requested_at{X}")
    print(f"  PO custom menunggu keputusan : {r['total_pending']}")
    print(f"  belum punya field            : {r['missing_before']}")
    print(f"  {'akan diisi' if args.dry_run else 'diisi'}                   : "
          f"{r['missing_before'] if args.dry_run else r['written']}")
    if args.dry_run and r["missing_before"]:
        print(f"{Y}  dry-run: jalankan tanpa --dry-run untuk menulis.{X}")
    else:
        print(f"{G}  Selesai — umur tunggu tidak lagi ditebak dari created_at "
              f"(idempotent: jalan ulang melaporkan 0).{X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
