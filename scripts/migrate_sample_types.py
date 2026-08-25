#!/usr/bin/env python3
"""FASE S — MIGRASI JENIS SAMPLING: `sample_type` (tunggal) → `sample_types[]` + master.

KENAPA ADA SKRIP INI (dan bukan hanya seed data demo)
=====================================================
`seed_realistic.py` melayani basis data DEMO yang dihapus-ulang. Basis data yang
sudah dipakai tidak boleh dihapus, tetapi tetap harus:
  1. punya baris master `sample_types` (labdip · handfeel · proofing · bulk_sample)
     supaya pemilik bisa menambah jenis dari layar — bukan menunggu programmer;
  2. punya `md_samples.sample_types[]` sebagai **satu-satunya** sumber jenis, dan
     `rounds[].type_code` supaya iterasi tiap jenis punya rangkaiannya sendiri;
  3. punya penanda pelaksanaan (`finished_at`, `delivered_at`, `delivered_to`) yang
     ADA sebagai field — kalau tidak, layar tidak bisa membedakan "belum" dari
     "field-nya tidak pernah ada".

DUA JAMINAN YANG DIPEGANG SKRIP INI
-----------------------------------
* **Idempotent** — dijalankan dua kali hasilnya sama (upsert per `code` pada lapisan
  global; dokumen yang sudah bermigrasi dilewati). `--dry-run` melaporkan HASIL
  SUNGGUHAN yang akan terjadi, bukan perkiraan.
* **FIELD LAMA DIHAPUS, bukan dibiarkan.** Rencana §S.B menuntutnya, dan alasannya
  bukan kerapian: selama `sample_type` masih ada, tiap pembaca baru punya dua tempat
  untuk bertanya dan keduanya akan menyimpang dalam beberapa sesi. Gate
  `INV-SAMPLE-01` aturan B memerah bila ada sisa.

Pemakaian:
    python scripts/migrate_sample_types.py --dry-run
    python scripts/migrate_sample_types.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env")
except Exception:  # noqa: BLE001
    pass

G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; C = "\033[96m"; B = "\033[1m"; X = "\033[0m"

import domain_registry as dr  # noqa: E402

# SATU daftar, dua pintu masuk (seed data demo & migrasi basis data lama): nilainya
# diambil LANGSUNG dari benih registry supaya tidak mungkin bercabang. Kalau daftar
# ini disalin, cabangnya hidup diam-diam — kelas bug yang FASE S ini justru tutup.
SEED_TYPES: List[Dict[str, Any]] = [dict(v) for v in dr.enum_items("sample_type")]

MASTER_FIELDS = ("code", "name", "applies_to_lines", "seq", "active", "notes",
                 "requires_design", "measurement_fields")


def row_of(seed: Dict[str, Any]) -> Dict[str, Any]:
    code = str(seed.get("code") or seed.get("value") or "").strip().lower()
    out = {k: seed.get(k) for k in MASTER_FIELDS if k in seed}
    out["code"] = code
    out["name"] = seed.get("name") or seed.get("label") or code
    out.setdefault("applies_to_lines", [])
    out.setdefault("measurement_fields", [])
    out.setdefault("requires_design", False)
    out.setdefault("active", True)
    out.setdefault("notes", seed.get("description", "") or "")
    return out


async def main() -> int:
    dry = "--dry-run" in sys.argv
    from motor.motor_asyncio import AsyncIOMotorClient
    from core_utils import new_id, now_iso

    mongo_url = os.environ.get("MONGO_URL")
    if not mongo_url:
        print(f"{R}MONGO_URL tidak ada — migrasi dibatalkan.{X}")
        return 2
    db = AsyncIOMotorClient(mongo_url)[os.environ.get("DB_NAME", "test_database")]

    print(f"{C}{B}FASE S — MIGRASI JENIS SAMPLING{X}"
          + (f"  {Y}[DRY-RUN — tidak ada yang ditulis]{X}" if dry else ""))

    # ── 1. Master `sample_types` (lapisan GLOBAL `entity_id="all"`) ───────────
    created, updated, unchanged = [], [], []
    for seed in SEED_TYPES:
        row = row_of(seed)
        code = row["code"]
        existing = await db.sample_types.find_one({"code": code, "entity_id": "all"},
                                                  {"_id": 0})
        if not existing:
            created.append(code)
            if not dry:
                await db.sample_types.insert_one({
                    **row, "id": new_id("stype"), "entity_id": "all",
                    "created_by": "migrate_sample_types", "created_at": now_iso(),
                    "updated_at": now_iso()})
            continue
        # Field yang HILANG diisi; field yang sudah ada TIDAK ditimpa — baris yang
        # sudah disesuaikan pemilik tetap miliknya.
        # PENTING: `[]` pada `applies_to_lines`/`measurement_fields` adalah NILAI
        # BERMAKNA ("berlaku semua lini" / "tidak ada hasil ukur wajib"), bukan
        # "belum diisi"; `False` pada `requires_design` juga bermakna. Kalau ketiganya
        # dianggap hilang, jalankan-kedua akan selalu melaporkan "dilengkapi" dan
        # laporan idempotensi berhenti bisa dipercaya (pelajaran FASE T).
        missing = (None, "")
        patch = {k: v for k, v in row.items()
                 if k != "code" and existing.get(k) in missing and v not in missing}
        if patch:
            updated.append(f"{code}({','.join(sorted(patch))})")
            if not dry:
                await db.sample_types.update_one(
                    {"code": code, "entity_id": "all"},
                    {"$set": {**patch, "updated_at": now_iso()}})
        else:
            unchanged.append(code)
    print(f"  master: {G}{len(created)} dibuat{X} · {Y}{len(updated)} dilengkapi{X} · "
          f"{len(unchanged)} sudah sesuai")
    if created:
        print(f"    + {', '.join(created)}")
    if updated:
        print(f"    ~ {', '.join(updated)}")

    # ── 2. `md_samples`: sample_type → sample_types[] (+ hapus field lama) ────
    live = {r["code"] for r in await db.sample_types.find(
        {"entity_id": "all"}, {"_id": 0, "code": 1}).to_list(500)} or \
        {r["code"] for r in (row_of(s) for s in SEED_TYPES)}
    moved, already, rounds_tagged, marks_added, unknown = 0, 0, 0, 0, []
    async for s in db.md_samples.find({}, {"_id": 0, "id": 1, "number": 1,
                                           "sample_type": 1, "sample_types": 1,
                                           "rounds": 1, "finished_at": 1,
                                           "delivered_at": 1, "delivered_to": 1}):
        legacy = str(s.get("sample_type") or "").strip().lower()
        kinds = [str(v).strip().lower() for v in (s.get("sample_types") or [])
                 if str(v or "").strip()]
        set_doc: Dict[str, Any] = {}
        unset_doc: Dict[str, Any] = {}
        if not kinds and legacy:
            kinds = [legacy]
            set_doc["sample_types"] = kinds
            moved += 1
        elif kinds and legacy:
            # Sudah punya daftar TAPI field lama masih menempel → dua sumber hidup.
            moved += 1
        elif kinds:
            already += 1
        else:
            # Tidak punya jenis sama sekali: jangan menebak. Dokumen begini akan
            # dilaporkan gate INV-SAMPLE-01 supaya diputuskan orang, bukan skrip.
            unknown.append(s.get("number") or s.get("id"))
        if legacy:
            unset_doc["sample_type"] = ""
        if kinds and legacy not in live and legacy:
            print(f"  {Y}· {s.get('number')}: jenis lama '{legacy}' tidak ada di master "
                  f"— tetap dipindahkan, tambahkan barisnya supaya labelnya benar.{X}")
        # `rounds[].type_code`: round lama milik dokumen ber-satu-jenis diikat ke
        # jenis itu. Dokumen lama TIDAK PERNAH punya lebih dari satu jenis, jadi
        # pengikatan ini pasti benar — bukan tebakan.
        rounds = s.get("rounds") or []
        changed_rounds = False
        for r in rounds:
            if str(r.get("type_code") or "").strip():
                continue
            if len(kinds) != 1:
                continue
            r["type_code"] = kinds[0]
            r.setdefault("qc", {})
            changed_rounds = True
            rounds_tagged += 1
        if changed_rounds:
            set_doc["rounds"] = rounds
        # Penanda pelaksanaan WAJIB ada sebagai field (bedakan "belum" dari
        # "tidak ada field"-nya). Nilainya kosong — migrasi tidak boleh mengarang
        # tanggal jadi/kirim untuk dokumen lama.
        for f in ("finished_at", "delivered_at", "delivered_to"):
            if f not in s:
                set_doc.setdefault(f, "")
                marks_added += 1
        if not (set_doc or unset_doc) or dry:
            continue
        upd: Dict[str, Any] = {}
        if set_doc:
            upd["$set"] = {**set_doc, "updated_at": now_iso()}
        if unset_doc:
            upd["$unset"] = unset_doc
        await db.md_samples.update_one({"id": s["id"]}, upd)

    total = await db.md_samples.count_documents({})
    print(f"  dokumen: {G}{moved} dipindahkan ke sample_types[]{X} · {already} sudah "
          f"bermigrasi · {rounds_tagged} round diberi `type_code` · "
          f"{marks_added} penanda pelaksanaan ditambahkan (dari {total} dokumen)")
    if unknown:
        print(f"  {Y}{len(unknown)} dokumen TIDAK punya jenis sama sekali "
              f"({', '.join(map(str, unknown[:6]))}) — isi jenisnya dari layar; skrip "
              f"sengaja tidak menebak.{X}")

    sisa = await db.md_samples.count_documents({"sample_type": {"$exists": True}})
    if dry:
        print(f"{Y}  (dry-run) sisa field lama saat ini: {sisa}{X}")
    elif sisa:
        print(f"{R}  MASIH ADA {sisa} dokumen ber-`sample_type` — dua sumber untuk satu "
              f"fakta. Jalankan ulang skrip ini.{X}")
        return 1
    else:
        print(f"  {G}nol sisa `sample_type`: satu sumber jenis tercapai.{X}")

    print(f"{G}{B}SELESAI{X}" + (f" {Y}(dry-run — tidak ada yang ditulis){X}" if dry else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
