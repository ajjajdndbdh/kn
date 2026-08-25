#!/usr/bin/env python3
"""FASE D (DRIFT **D4**) — isi `design_gallery.code` yang masih kosong.

Terukur 2026-08-20 pada data demo: **2 dari 4** entri galeri ber-`code` kosong.
Entri tanpa kode tidak bisa disebut dalam percakapan ("pakai motif yang mana?"),
tidak bisa dicari, dan tidak bisa dirujuk dokumen lain — padahal sejak FASE D
artwork adalah barang yang diserahkan sebuah **Permintaan Desain**.

Sifat skrip ini:
  * **idempotent** — dijalankan berulang tidak mengubah apa pun setelah bersih;
  * **tidak menyentuh kode yang sudah ada** (kode buatan pemilik tetap);
  * memakai penomor yang SAMA dengan jalur unggah baru
    (`design_gallery_service._next_design_code`) supaya tidak ada dua gaya kode;
  * `--dry-run` mencetak rencana tanpa menulis.

Pemakaian:
    python scripts/migrate_design_codes.py --dry-run
    python scripts/migrate_design_codes.py
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env")
except Exception:  # noqa: BLE001
    pass

G, Y, R, B, X = "\033[92m", "\033[93m", "\033[91m", "\033[1m", "\033[0m"


async def main(dry: bool) -> int:
    from db import db                                     # noqa: E402
    from services.design_gallery_service import _next_design_code  # noqa: E402

    kosong = await db.design_gallery.find(
        {"$or": [{"code": ""}, {"code": None}, {"code": {"$exists": False}}]},
        {"_id": 0, "id": 1, "title": 1, "entity_id": 1}).to_list(1000)
    total = await db.design_gallery.count_documents({})
    print(f"{B}MIGRASI D4 — kode desain{X}")
    print(f"  entri galeri: {total} · tanpa kode: {len(kosong)}")
    if not kosong:
        print(f"{G}  Tidak ada yang perlu dimigrasikan (semua entri sudah berkode).{X}")
        return 0
    diisi = 0
    for row in kosong:
        code = await _next_design_code(row.get("title", ""), row.get("entity_id", ""))
        print(f"  {row['id']} · \"{row.get('title', '')}\" → {code}"
              + (f" {Y}(dry-run){X}" if dry else ""))
        if not dry:
            await db.design_gallery.update_one({"id": row["id"]}, {"$set": {"code": code}})
            diisi += 1
    if dry:
        print(f"{Y}  DRY-RUN: {len(kosong)} entri AKAN diberi kode.{X}")
        return 0
    sisa = await db.design_gallery.count_documents(
        {"$or": [{"code": ""}, {"code": None}, {"code": {"$exists": False}}]})
    print(f"{G}  {diisi} entri diberi kode · sisa tanpa kode: {sisa}{X}")
    return 0 if sisa == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main("--dry-run" in sys.argv)))
