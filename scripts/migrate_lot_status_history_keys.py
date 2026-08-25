"""Satukan bentuk `inventory_lots.status_history[]` ke bentuk KANONIK (INV-HIST-01).

`at` → `timestamp`, `actor` → `user`. Idempotent: dokumen yang sudah kanonik
dilewati. Dipanggil juga dari `bootstrap` supaya data demo tidak pernah kembali ke
bentuk lama.

    python scripts/migrate_lot_status_history_keys.py [--dry-run]
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / "backend" / ".env")


async def migrate(dbx=None, *, dry_run: bool = False) -> dict:
    if dbx is None:
        from motor.motor_asyncio import AsyncIOMotorClient
        dbx = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    diperiksa = diubah = entri_diubah = 0
    async for lot in dbx.inventory_lots.find(
            {"status_history": {"$exists": True, "$ne": []}},
            {"_id": 0, "id": 1, "status_history": 1}):
        diperiksa += 1
        hist = lot.get("status_history") or []
        baru, ubah = [], False
        for h in hist:
            if not isinstance(h, dict):
                baru.append(h)
                continue
            row = dict(h)
            if not row.get("timestamp") and row.get("at"):
                row["timestamp"] = row.pop("at")
                ubah = True
            elif "at" in row:
                row.pop("at")
                ubah = True
            if not row.get("user") and row.get("actor"):
                row["user"] = row.pop("actor")
                ubah = True
            elif "actor" in row:
                row.pop("actor")
                ubah = True
            if ubah:
                entri_diubah += 1
            baru.append(row)
        if ubah:
            diubah += 1
            if not dry_run:
                await dbx.inventory_lots.update_one(
                    {"id": lot["id"]}, {"$set": {"status_history": baru}})
    return {"lot_diperiksa": diperiksa, "lot_diubah": diubah,
            "entri_diubah": entri_diubah}


if __name__ == "__main__":
    hasil = asyncio.run(migrate(dry_run="--dry-run" in sys.argv))
    print(f"inventory_lots.status_history → bentuk kanonik: {hasil}")
