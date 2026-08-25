"""Suntik/bersihkan dokumen uji papan PO Custom (T1). Usage: inject | clean"""
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient
from dotenv import dotenv_values

e = dotenv_values("/app/backend/.env")
db = MongoClient(e["MONGO_URL"])[e["DB_NAME"]]
now = datetime.now(timezone.utc)


def mk(days, role="manager"):
    ts = (now - timedelta(days=days)).isoformat()
    return {
        "id": f"t1ui-{uuid.uuid4().hex[:8]}",
        "number": f"SORD-T1UI-{uuid.uuid4().hex[:4].upper()}",
        "entity_id": "ent_ksc", "status": "pending_approval",
        "customer_name": "T1 UI Probe", "total_amount": 2_500_000.0,
        "required_approval_role": role, "created_at": ts,
        "approval_requested_at": ts,
        "status_history": [{"status": "pending_approval", "timestamp": ts}],
        "custom_item": {"description": "Kain custom uji T1"},
        "_t1_probe": True,
    }


if sys.argv[1] == "inject":
    docs = [mk(d) for d in (2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 45)]
    db.special_orders.insert_many(docs)
    print("disuntik", len(docs), "count pending ent_ksc =",
          db.special_orders.count_documents({"status": "pending_approval", "entity_id": "ent_ksc"}))
else:
    r = db.special_orders.delete_many({"_t1_probe": True})
    print("dihapus", r.deleted_count, "sisa probe =",
          db.special_orders.count_documents({"_t1_probe": True}))
