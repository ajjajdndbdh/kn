"""Verifikasi sesi 2026-06 (T1) — papan antrean mahal di beranda admin & manajer,
bentuk kanonik `status_history` pada lot, dan regresi beranda peran lain.

Semua dokumen uji ditandai `_t1_probe=True` dan DIHAPUS di teardown (INV-GATE-01).
"""
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests
from dotenv import dotenv_values

sys.path.insert(0, "/app/backend")

fe = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or fe.get("REACT_APP_BACKEND_URL")).rstrip("/")
be = dotenv_values("/app/backend/.env")
MONGO_URL = be.get("MONGO_URL")
DB_NAME = be.get("DB_NAME")

PROBE = "_t1_probe"
ENT = "ent_ksc"
BOARD_KEYS = ["special_order", "contra_bon_dispute", "interco_return"]
ROW_FIELDS = ["number", "title", "amount", "note", "role", "entity_id", "since", "days_waiting"]


def now_iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def _login(email, password="demo12345"):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=60)
    assert r.status_code == 200, f"login {email} gagal: {r.status_code} {r.text[:300]}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, f"tidak ada token: {list(r.json())}"
    s.headers.update({"Authorization": f"Bearer {tok}", "X-Entity-Id": ENT})
    return s


@pytest.fixture(scope="module")
def mongo():
    from pymongo import MongoClient
    cli = MongoClient(MONGO_URL)
    yield cli[DB_NAME]
    cli.close()


@pytest.fixture(scope="module")
def admin():
    return _login("admin@kainnusantara.id")


@pytest.fixture(scope="module")
def manager():
    return _login("manager@kainnusantara.id")


def _home(sess, role):
    r = sess.get(f"{BASE_URL}/api/home/{role}", params={"entity_id": ENT}, timeout=120)
    assert r.status_code == 200, f"/api/home/{role} → {r.status_code} {r.text[:400]}"
    return r.json()


# ── Papan antrean mahal: bentuk payload API ────────────────────────────────
class TestWaitingBoardsPayload:
    @pytest.mark.parametrize("role", ["admin", "manager"])
    def test_boards_shape(self, admin, manager, role):
        data = _home(admin if role == "admin" else manager, role)
        assert "special_orders_waiting" in data, f"{role}: special_orders_waiting hilang"
        boards = data.get("waiting_boards")
        assert isinstance(boards, list) and len(boards) == 3, f"{role}: waiting_boards={boards}"
        assert [b["key"] for b in boards] == BOARD_KEYS, f"{role}: urutan papan salah"
        for b in boards:
            for f in ("count", "shown", "hidden", "truncated", "rows", "view", "label"):
                assert f in b, f"{role}/{b['key']}: field {f} hilang"
            assert isinstance(b["rows"], list)
            for row in b["rows"]:
                for f in ROW_FIELDS:
                    assert f in row, f"{role}/{b['key']}: baris tanpa field {f}"
                assert isinstance(row["days_waiting"], int)
        assert data["special_orders_waiting"]["key"] == "special_order"

    @pytest.mark.parametrize("role", ["admin", "manager"])
    def test_count_matches_approval_queue(self, admin, manager, role):
        data = _home(admin if role == "admin" else manager, role)
        items = data["approvals"]["all_items"]
        q = next((i for i in items if i.get("key") == "special_order"), None)
        assert q is not None, f"{role}: antrean special_order tidak ada di approvals.all_items"
        assert data["special_orders_waiting"]["count"] == q["count"], (
            f"{role}: papan {data['special_orders_waiting']['count']} vs antrean {q['count']}")

    def test_admin_and_manager_identical_boards(self, admin, manager):
        a = _home(admin, "admin")["waiting_boards"]
        m = _home(manager, "manager")["waiting_boards"]
        for ba, bm in zip(a, m):
            assert ba["key"] == bm["key"]
            assert ba["count"] == bm["count"], f"{ba['key']}: count beda {ba['count']} vs {bm['count']}"
            ra = {r["number"]: (r["amount"], r["days_waiting"]) for r in ba["rows"]}
            rm = {r["number"]: (r["amount"], r["days_waiting"]) for r in bm["rows"]}
            assert ra == rm, f"{ba['key']}: baris admin != manajer ({ra} vs {rm})"

    def test_demo_special_order_row(self, admin):
        b = _home(admin, "admin")["special_orders_waiting"]
        assert b["count"] >= 1
        row = b["rows"][0]
        assert row["number"] == "SORD-260816-0001", f"nomor tak terduga: {row['number']}"
        assert row["amount"] == 43500000, f"nilai tak terduga: {row['amount']}"
        assert row["days_waiting"] >= 1
        assert row["entity_id"] == ENT
        assert row["role"], "role kosong → teks 'perlu Manajer' tidak akan tampil"


# ── Papan tambahan dengan dokumen uji (dihapus di teardown) ────────────────
class TestExtraBoardsWithProbes:
    @pytest.fixture(scope="class")
    def probes(self, mongo):
        cb_id = f"t1cb-{uuid.uuid4().hex[:8]}"
        ir_id = f"t1ir-{uuid.uuid4().hex[:8]}"
        d5 = now_iso(datetime.now(timezone.utc) - timedelta(days=5, hours=1))
        d12 = now_iso(datetime.now(timezone.utc) - timedelta(days=12, hours=1))
        mongo.contra_bons.insert_one({
            "id": cb_id, PROBE: True, "entity_id": ENT, "status": "disputed",
            "number": "T1/CB-PROBE-01", "supplier_name": "T1 Probe Supplier",
            "disputed_at": d5, "created_at": d5,
            "dispute_reason_code": "T1 selisih kuantitas",
            "totals": {"net_payable": 12345678, "bills_total": 12345678},
        })
        mongo.interco_returns.insert_one({
            "id": ir_id, PROBE: True, "entity_id": ENT, "status": "draft",
            "number": "T1/ICR-PROBE-01", "counterparty_name": "T1 Probe PT",
            "created_at": d12, "reason": "T1 retur uji", "grand_total": 7654321,
        })
        yield {"cb": cb_id, "ir": ir_id}
        mongo.contra_bons.delete_many({PROBE: True})
        mongo.interco_returns.delete_many({PROBE: True})

    @pytest.mark.parametrize("role", ["admin", "manager"])
    def test_probe_rows_visible(self, admin, manager, probes, role):
        boards = {b["key"]: b for b in _home(admin if role == "admin" else manager, role)["waiting_boards"]}
        cb = boards["contra_bon_dispute"]
        assert cb["count"] >= 1, f"{role}: papan kontrabon bersengketa tetap 0"
        rcb = next((r for r in cb["rows"] if r["id"] == probes["cb"]), None)
        assert rcb, f"{role}: baris kontrabon uji tidak ada"
        assert rcb["days_waiting"] == 5, f"{role}: umur kontrabon {rcb['days_waiting']} != 5"
        assert rcb["amount"] == 12345678, f"{role}: nilai kontrabon {rcb['amount']}"

        ir = boards["interco_return"]
        assert ir["count"] >= 1, f"{role}: papan retur antar-PT tetap 0"
        rir = next((r for r in ir["rows"] if r["id"] == probes["ir"]), None)
        assert rir, f"{role}: baris retur antar-PT uji tidak ada"
        assert rir["days_waiting"] == 12, f"{role}: umur retur {rir['days_waiting']} != 12"
        assert rir["amount"] == 7654321, f"{role}: nilai retur {rir['amount']}"

    def test_cleanup_returns_boards_to_zero(self, mongo, admin, probes):
        mongo.contra_bons.delete_many({PROBE: True})
        mongo.interco_returns.delete_many({PROBE: True})
        boards = {b["key"]: b for b in _home(admin, "admin")["waiting_boards"]}
        assert boards["contra_bon_dispute"]["count"] == 0
        assert boards["interco_return"]["count"] == 0
        assert mongo.contra_bons.count_documents({PROBE: True}) == 0
        assert mongo.interco_returns.count_documents({PROBE: True}) == 0


# ── INV-HIST-01: bentuk kanonik status_history pada lot ────────────────────
class TestLotStatusHistoryShape:
    def test_lot_history_canonical(self, admin):
        r = admin.get(f"{BASE_URL}/api/lots", params={"entity_id": ENT, "limit": 50}, timeout=60)
        assert r.status_code == 200, f"/api/lots → {r.status_code} {r.text[:300]}"
        body = r.json()
        lots = body.get("items", body) if isinstance(body, dict) else body
        assert lots, "tidak ada lot di data demo"
        checked = 0
        for lot in lots[:15]:
            d = admin.get(f"{BASE_URL}/api/lots/{lot['id']}", timeout=60)
            assert d.status_code == 200, f"lot {lot['id']} → {d.status_code}"
            hist = d.json().get("status_history") or []
            for h in hist:
                assert h.get("timestamp"), f"lot {lot.get('lot_number')}: entri tanpa `timestamp` → {h}"
                assert h.get("user"), f"lot {lot.get('lot_number')}: entri tanpa `user` → {h}"
                assert "at" not in h and "actor" not in h, f"bentuk lama masih ada: {h}"
                datetime.fromisoformat(str(h["timestamp"]).replace("Z", "+00:00"))
                checked += 1
        assert checked > 0, "tidak satu pun lot demo punya status_history — blok riwayat tak bisa diuji"


# ── Regresi beranda peran lain ────────────────────────────────────────────
class TestOtherRoleHomes:
    @pytest.mark.parametrize("email,role", [
        ("finance@kainnusantara.id", "admin"),
        ("sales@kainnusantara.id", "sales"),
        ("warehouse@kainnusantara.id", "admin"),
    ])
    def test_role_home_loads(self, email, role):
        s = _login(email)
        r = s.get(f"{BASE_URL}/api/home/{role}", params={"entity_id": ENT}, timeout=120)
        assert r.status_code in (200, 403), f"{email} /api/home/{role} → {r.status_code} {r.text[:300]}"
        if r.status_code == 200:
            assert isinstance(r.json(), dict) and r.json()
