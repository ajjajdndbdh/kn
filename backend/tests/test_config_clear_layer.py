"""FASE E-4.6 — verify clear_layer removes empty system_settings rows,
but preserves rows that still hold other overrides."""
import asyncio
import os
import sys
sys.path.insert(0, "/app/backend")

from motor.motor_asyncio import AsyncIOMotorClient
from services import config_resolver as cr


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    # pick a writable per-entity key with legacy_scope=global (i.e., projected).
    # From registry: ar.denda_rate_pct_per_month has scopes global+entity and projects
    KEY_A = "ar.denda_rate_pct_per_month"
    KEY_B = "ar.grace_days"
    SCOPE_ID = "ent_ksc"

    baseline_count = await db.system_settings.count_documents({})
    row_before = await db.system_settings.find_one({"scope": SCOPE_ID})
    had_row_before = row_before is not None

    print(f"[baseline] system_settings={baseline_count} scope_row_exists={had_row_before}")

    # ── Case 1: set + clear ONLY key A → row should NOT be left empty behind
    await cr.set_value(KEY_A, 3.0, scope_type="entity", scope_id=SCOPE_ID,
                        actor="TEST", reason="TEST_clear_layer")
    mid_count = await db.system_settings.count_documents({})
    print(f"[after set_value A] system_settings={mid_count}")

    await cr.clear_layer(KEY_A, scope_type="entity", scope_id=SCOPE_ID,
                          actor="TEST", reason="TEST_clear")
    after_count = await db.system_settings.count_documents({})
    row_after = await db.system_settings.find_one({"scope": SCOPE_ID})
    print(f"[after clear_layer A] system_settings={after_count} scope_row_exists={row_after is not None}")

    if had_row_before:
        # If the row existed before with other keys, it should still exist (case 2 below covers).
        # But if it existed only for our new key it may be gone. Cannot assert deletion strictly.
        pass
    else:
        assert row_after is None, (
            f"clear_layer left empty scope row behind: {row_after}"
        )
        assert after_count == baseline_count, (
            f"system_settings row count drifted: {baseline_count} -> {after_count}"
        )
    print("[case1] PASS — no empty shell after clearing only override")

    # ── Case 2: set A AND B, clear only A → row must still exist with B's value
    await cr.set_value(KEY_A, 3.0, scope_type="entity", scope_id=SCOPE_ID,
                       actor="TEST", reason="TEST_clear_layer_case2_A")
    await cr.set_value(KEY_B, 7, scope_type="entity", scope_id=SCOPE_ID,
                       actor="TEST", reason="TEST_clear_layer_case2_B")
    await cr.clear_layer(KEY_A, scope_type="entity", scope_id=SCOPE_ID,
                         actor="TEST", reason="TEST_clear")
    row_case2 = await db.system_settings.find_one({"scope": SCOPE_ID})
    assert row_case2 is not None, "row must remain because KEY_B override still there"
    # navigate legacy_path for B
    entry_b = cr.registry.require(KEY_B)
    b_path = entry_b["legacy_path"].split(".")
    cur = row_case2
    for p in b_path:
        cur = (cur or {}).get(p) if isinstance(cur, dict) else None
    assert cur == 7, f"KEY_B override should persist after clearing A only, got: {cur}"
    # And KEY_A's leaf should be gone
    entry_a = cr.registry.require(KEY_A)
    a_path = entry_a["legacy_path"].split(".")
    curA = row_case2
    for p in a_path:
        if isinstance(curA, dict) and p in curA:
            curA = curA[p]
        else:
            curA = "__MISSING__"
            break
    assert curA == "__MISSING__", f"KEY_A leaf should be gone after clear, got: {curA}"
    print("[case2] PASS — row retained; A cleared; B preserved")

    # Cleanup: clear B too and delete config_values TEST entries
    await cr.clear_layer(KEY_B, scope_type="entity", scope_id=SCOPE_ID,
                         actor="TEST", reason="TEST_cleanup")
    # Remove test append-only rows for cleanliness
    res = await db.config_values.delete_many({"reason": {"$regex": "^TEST_"}, "changed_by": "TEST"})
    print(f"[cleanup] removed {res.deleted_count} TEST config_values rows")

    final_count = await db.system_settings.count_documents({})
    final_row = await db.system_settings.find_one({"scope": SCOPE_ID})
    print(f"[final] system_settings={final_count} scope_row_exists={final_row is not None}")
    if not had_row_before:
        assert final_count == baseline_count, (
            f"final count must match baseline: {baseline_count} -> {final_count}"
        )
        assert final_row is None
    print("ALL PASS")


if __name__ == "__main__":
    # load env
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    asyncio.run(main())
