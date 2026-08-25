"""A2 — satu pemilik penagihan berulang (verifikasi independen T1).

Job keadaan dijalankan 3× dalam SATU event loop (ke-2 & ke-3 harus 0 notifikasi
baru, termasuk setelah pesannya DITANDAI DIBACA → dedupe_scope='ever'), lalu
pengingat harian diperiksa: maksimal 1 approval_backlog per orang per hari dan
judulnya menyebut umur dokumen TERTUA yang NYATA.

Notifikasi yang dibuat uji ini dihapus di akhir (nol residu).
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

G, R, X = "\033[92m", "\033[91m", "\033[0m"
hasil = []


def cek(nama, ok, info=""):
    hasil.append(ok)
    print(f"  [{G+'PASS'+X if ok else R+'FAIL'+X}] {nama} {info}")


async def main():
    from db import db
    from services import notification_service as ns
    from services import approval_reminder as ar

    now = datetime.now(timezone.utc)
    doc_id = f"t1a2-{uuid.uuid4().hex[:8]}"
    doc = {
        "id": doc_id, "number": f"SORD-T1A2-{uuid.uuid4().hex[:4].upper()}",
        "entity_id": "ent_ksc", "status": "pending_approval",
        "customer_name": "T1 A2 Probe", "total_amount": 5_000_000.0,
        "required_approval_role": "manager",
        "created_at": (now - timedelta(days=30)).isoformat(),
        "approval_requested_at": (now - timedelta(days=30)).isoformat(),
        "status_history": [{"status": "pending_approval",
                            "timestamp": (now - timedelta(days=30)).isoformat()}],
        "_t1_probe": True,
    }
    before_ids = {n["id"] for n in await db.notifications.find({}, {"_id": 0, "id": 1}).to_list(20000)}
    await db.special_orders.insert_one(dict(doc))
    try:
        async def new_notifs():
            rows = await db.notifications.find({}, {"_id": 0}).to_list(20000)
            return [n for n in rows if n["id"] not in before_ids]

        # ── job keadaan 1×
        await ns._notify_pending_special_orders()
        n1 = [n for n in await new_notifs() if n.get("type") == ns.SPECIAL_ORDER_WAITING_TYPE
              and doc_id in str(n.get("ref", "")) + str(n.get("link", "")) + str(n.get("ref_id", ""))]
        cek("job keadaan ke-1 melahirkan pesan untuk dokumen uji", len(n1) >= 1,
            f"({len(n1)} notif)")

        # ── job keadaan 2×
        c_before = len(await new_notifs())
        await ns._notify_pending_special_orders()
        c_after = len(await new_notifs())
        cek("job keadaan ke-2 → 0 notifikasi baru", c_after == c_before,
            f"({c_after - c_before} baru)")

        # ── tandai DIBACA lalu job ke-3
        ids = [n["id"] for n in n1]
        await db.notifications.update_many({"id": {"$in": ids}}, {"$set": {"read": True}})
        c_before = len(await new_notifs())
        await ns._notify_pending_special_orders()
        c_after = len(await new_notifs())
        cek("job keadaan ke-3 setelah DIBACA → 0 notifikasi baru (dedupe 'ever')",
            c_after == c_before, f"({c_after - c_before} baru)")

        # ── pengingat harian
        await ar.job_approval_backlog_reminder()
        rem = [n for n in await new_notifs() if n.get("type") == "approval_backlog"]
        per_orang = {}
        for n in rem:
            key = (n.get("recipient_user") or n.get("user_id") or n.get("recipient_role"),
                   n.get("entity_id"), n.get("ref"), str(n.get("created_at", ""))[:10])
            per_orang.setdefault(key, []).append(n)
        dobel = {k: len(v) for k, v in per_orang.items() if len(v) > 1}
        cek("pengingat: maksimal 1 approval_backlog per orang/entitas per hari", not dobel, f"{dobel}")

        # jalankan lagi → tetap 0 tambahan
        c_before = len(rem)
        await ar.job_approval_backlog_reminder()
        rem2 = [n for n in await new_notifs() if n.get("type") == "approval_backlog"]
        cek("pengingat dijalankan 2× dalam hari yang sama → 0 tambahan",
            len(rem2) == c_before, f"({len(rem2) - c_before} baru)")

        # judul menyebut umur dokumen TERTUA yang nyata
        from services import approval_backlog_service as abl
        bl = await abl.backlog("ent_ksc", with_oldest=True, oldest_limit=5)
        tertua = max([o.get("days_waiting", 0) for o in bl.get("oldest", [])] or [0])
        judul = " | ".join(str(n.get("title", "")) + " " + str(n.get("message", "")) for n in rem2)
        cek(f"judul pengingat menyebut umur tertua nyata ({tertua} hari)",
            (str(tertua) in judul) if rem2 else False, f"[{judul[:200]}]")
        cek("dokumen uji (30 hari) TIDAK disembunyikan dari ringkasan",
            tertua >= 30, f"(tertua={tertua})")
    finally:
        await db.special_orders.delete_many({"_t1_probe": True})
        rows = await db.notifications.find({}, {"_id": 0, "id": 1}).to_list(20000)
        sisa = [n["id"] for n in rows if n["id"] not in before_ids]
        if sisa:
            await db.notifications.delete_many({"id": {"$in": sisa}})
        print(f"  [bersih] {len(sisa)} notifikasi uji dihapus, dokumen uji dihapus")

    print(f"\nHASIL A2: {G}{sum(hasil)} PASS{X} · {R}{len(hasil)-sum(hasil)} FAIL{X}")
    return 0 if all(hasil) else 1


raise SystemExit(asyncio.run(main()))
