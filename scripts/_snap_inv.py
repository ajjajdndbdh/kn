"""Ambil cuplikan (snapshot) subledger persediaan + jurnal 1-1300 per entitas.

Dipakai untuk melacak INV-GL-DRIFT: jalankan `save` sebelum gate, `diff` sesudah.
"""
import asyncio, json, os, sys
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
PHYS = ["available", "reserved", "committed", "picked", "packed", "quarantine", "hold"]


async def snap():
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cli[os.environ["DB_NAME"]]
    rolls = {}
    async for r in db.inventory_rolls.find({}, {"_id": 0, "id": 1, "owner_entity_id": 1,
                                               "status": 1, "length_remaining": 1,
                                               "unit_cost": 1, "base_unit_cost": 1}):
        rolls[r.get("id")] = [r.get("owner_entity_id"), r.get("status"),
                              float(r.get("length_remaining") or 0),
                              float(r.get("unit_cost") or r.get("base_unit_cost") or 0)]
    jes = {}
    async for je in db.journal_entries.find({"status": {"$ne": "void"}},
                                            {"_id": 0, "id": 1, "number": 1, "entity_id": 1,
                                             "source_type": 1, "source_id": 1, "lines": 1}):
        amt = sum(float(l.get("debit") or 0) - float(l.get("credit") or 0)
                  for l in je.get("lines", []) if l.get("account_code") == "1-1300")
        if amt:
            jes[je.get("id")] = [je.get("entity_id"), je.get("number"),
                                 je.get("source_type"), je.get("source_id"), round(amt, 2)]
    cli.close()
    return {"rolls": rolls, "jes": jes}


def value(snap_data, eid):
    sub = round(sum(v[2] * v[3] for v in snap_data["rolls"].values()
                    if v[0] == eid and v[1] in PHYS), 2)
    gl = round(sum(v[4] for v in snap_data["jes"].values() if v[0] == eid), 2)
    return sub, gl


async def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "save"
    path = "/tmp/_snap_inv.json"
    cur = await snap()
    if mode == "save":
        with open(path, "w") as f:
            json.dump(cur, f)
        print(f"tersimpan {len(cur['rolls'])} roll · {len(cur['jes'])} jurnal 1-1300")
        for eid in sorted({v[0] for v in cur["rolls"].values() if v[0]}):
            print(f"  {eid}: sub={value(cur, eid)[0]:,.0f} gl={value(cur, eid)[1]:,.0f}")
        return
    old = json.load(open(path))
    for eid in sorted({v[0] for v in cur["rolls"].values() if v[0]}):
        s0, g0 = value(old, eid)
        s1, g1 = value(cur, eid)
        print(f"{eid}: sub {s0:,.0f} -> {s1:,.0f} (Δ{s1-s0:,.0f}) · gl {g0:,.0f} -> {g1:,.0f} "
              f"(Δ{g1-g0:,.0f}) · drift {s1-g1:,.0f} (sebelumnya {s0-g0:,.0f})")
    print("\n-- roll berubah --")
    for rid, v in cur["rolls"].items():
        o = old["rolls"].get(rid)
        if o is None:
            print(f"  BARU {rid}: {v}")
        elif o != v:
            print(f"  UBAH {rid}: {o} -> {v}")
    for rid, o in old["rolls"].items():
        if rid not in cur["rolls"]:
            print(f"  HILANG {rid}: {o}")
    print("\n-- jurnal 1-1300 berubah --")
    for jid, v in cur["jes"].items():
        if jid not in old["jes"]:
            print(f"  BARU {v}")
    for jid, o in old["jes"].items():
        if jid not in cur["jes"]:
            print(f"  HILANG {o}")


asyncio.run(main())
