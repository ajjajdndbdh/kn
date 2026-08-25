#!/usr/bin/env python3
"""Bersih-bersih dokumen UJI LAYAR FASE U (dijalankan sendiri di peramban).

Kenapa skrip, bukan hapus manual: uji lewat layar melahirkan RANTAI dokumen nyata
(PO → tugas gudang → 12 roll → lot → 12 mutasi → jurnal → relasi dokumen → jejak
audit). Menghapus PO-nya saja meninggalkan stok hantu yang akan memerahkan
`INV-GATE-01`/`verify_data_integrity` di ujung sesi — jauh dari penyebabnya
(pelajaran POC-RESIDU-01, FASE T).

Pemakaian:  python scripts/_cleanup_uji_layar_u.py [--tandai "UJI-LAYAR-U"]
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "backend", ".env"))

from db import db  # noqa: E402
from services.roll_service import rebuild_balance  # noqa: E402

TAG = "UJI-LAYAR-U"
for i, a in enumerate(sys.argv):
    if a == "--tandai" and i + 1 < len(sys.argv):
        TAG = sys.argv[i + 1]


async def main() -> int:
    pos = await db.purchase_orders.find({"notes": {"$regex": TAG}}, {"_id": 0}).to_list(50)
    if not pos:
        print(f"tidak ada dokumen uji ber-tanda {TAG!r} — nol residu.")
        return 0
    po_ids = [p["id"] for p in pos]
    print("PO uji:", [(p.get("po_number"), p["id"]) for p in pos])

    tasks = await db.wms_tasks.find({"po_id": {"$in": po_ids}}, {"_id": 0}).to_list(50)
    task_ids = [t["id"] for t in tasks]
    rolls = await db.inventory_rolls.find(
        {"$or": [{"po_id": {"$in": po_ids}}, {"grn_task_id": {"$in": task_ids}}]},
        {"_id": 0}).to_list(500)
    roll_ids = [r["id"] for r in rolls]
    lots = sorted({r.get("lot") for r in rolls if r.get("lot")})
    segments = {(r.get("product_id"), r.get("warehouse_id"), r.get("owner_entity_id"))
                for r in rolls}

    n = {}

    async def rm(coll: str, q: dict):
        res = await db[coll].delete_many(q)
        if res.deleted_count:
            n[coll] = n.get(coll, 0) + res.deleted_count

    await rm("inventory_movements", {"$or": [{"roll_id": {"$in": roll_ids}},
                                            {"reference_id": {"$in": po_ids + task_ids}},
                                            {"ref_id": {"$in": po_ids + task_ids}}]})
    await rm("inventory_rolls", {"id": {"$in": roll_ids}})
    if lots:
        await rm("inventory_lots", {"lot_number": {"$in": lots}})
        await rm("roll_labels", {"lot": {"$in": lots}})
    await rm("wms_tasks", {"id": {"$in": task_ids}})
    for pid in po_ids + task_ids:
        await rm("journal_entries", {"source_id": {"$regex": f"^{pid}"}})
        await rm("document_relations", {"$or": [{"from_id": pid}, {"to_id": pid}]})
        await rm("approval_requests", {"doc_id": pid})
        # NAMA FIELD DIUKUR, BUKAN DITEBAK (terukur 2026-08-20). Versi pertama skrip
        # ini memakai `notifications.ref_id` dan `audit_logs.entity_id` — DUA-DUANYA
        # TIDAK ADA: `notifications` memakai `ref`/`action_id`/`dedupe_key`
        # (`notification_service.create_notification`) dan `entity_id` di situ adalah
        # BADAN USAHA (`ent_ksc`), bukan id dokumen; `audit_logs` memakai `resource_id`
        # + `scope_entity_id`. Jadi kedua baris itu selalu menghapus 0 dokumen tanpa
        # bersuara — kelas cacat yang sama dengan pembersih notifikasi POC FASE U
        # (POC-RESIDU-03). Kalau salah lagi, `INV-GATE-01` yang memerah 300 detik
        # kemudian, jauh dari penyebabnya.
        await rm("notifications", {"$or": [{"ref": {"$regex": pid}},
                                          {"action_id": pid},
                                          {"dedupe_key": {"$regex": pid}}]})
        await rm("audit_logs", {"resource_id": pid})
    await rm("purchase_orders", {"id": {"$in": po_ids}})

    # Saldo dihitung ULANG dari roll yang tersisa (bukan dikurangi manual) — satu sumber.
    for (pid, wid, eid) in segments:
        if pid and wid:
            await rebuild_balance(pid, wid, eid or "")
    print("dihapus:", n, "· segmen saldo dihitung ulang:", len(segments))
    sisa = await db.purchase_orders.count_documents({"notes": {"$regex": TAG}})
    print("PO uji tersisa:", sisa)
    return 0 if sisa == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
