"""Verifikasi independen 11 temuan audit (sesi 2026-08-25).

Semua dokumen uji diberi penanda `_t1_probe=True` dan DIHAPUS di teardown.
Memakai HTTP nyata lewat REACT_APP_BACKEND_URL + MongoDB langsung.
"""
import os
import sys
import uuid
import asyncio
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


def now_iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


@pytest.fixture(scope="module")
def mongo():
    from pymongo import MongoClient
    cli = MongoClient(MONGO_URL)
    yield cli[DB_NAME]
    cli.close()


@pytest.fixture(scope="module")
def loop():
    class _Sync:
        @staticmethod
        def run_until_complete(x):
            return x
    return _Sync()


def _login(email, password="demo12345"):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email} gagal: {r.status_code} {r.text[:300]}"
    data = r.json()
    tok = data.get("token") or data.get("access_token")
    assert tok, f"tidak ada token: {list(data)}"
    s.headers.update({"Authorization": f"Bearer {tok}", "X-Entity-Id": ENT})
    return s


@pytest.fixture(scope="module", autouse=True)
def _nol_residu(mongo):
    """INV-GATE-01 — uji ini memanggil API sungguhan (login menulis `sessions` +
    `audit_logs`), jadi jejaknya WAJIB dipulihkan. Snapshot diambil SEBELUM login
    mana pun; tanpa ini setiap kali berkas ini dijalankan basis data bertambah
    beberapa baris audit permanen (terukur 2026-08-25: +7)."""
    import sys as _sys
    _sys.path.insert(0, "/app/scripts/guardrails")
    from _common import DbSnapshot
    snap = DbSnapshot(mongo, collections=[
        "special_orders", "notifications", "audit_logs", "sessions",
        "login_attempts"], verbose=False).take()
    yield
    snap.restore()


@pytest.fixture(scope="module")
def admin():
    return _login("admin@kainnusantara.id")


@pytest.fixture(scope="module")
def manager():
    return _login("manager@kainnusantara.id")


def _mk_doc(days_created, days_pending=None, number=None, amount=1000.0, role="manager"):
    now = datetime.now(timezone.utc)
    created = now - timedelta(days=days_created)
    doc = {
        "id": f"t1probe-{uuid.uuid4().hex[:10]}",
        "number": number or f"SORD-T1-{uuid.uuid4().hex[:4].upper()}",
        "entity_id": ENT,
        "status": "pending_approval",
        "customer_name": "T1 Probe Customer",
        "total_amount": amount,
        "required_approval_role": role,
        "created_at": now_iso(created),
        "custom_item": {"description": "T1 probe item"},
        PROBE: True,
    }
    if days_pending is not None:
        doc["status_history"] = [
            {"status": "draft", "timestamp": now_iso(created)},
            {"status": "pending_approval",
             "timestamp": now_iso(now - timedelta(days=days_pending))},
        ]
    return doc


def _cleanup(loop, mongo):
    loop.run_until_complete(mongo.special_orders.delete_many({PROBE: True}))


# ── B1 — umur tunggu tidak ditebak (field nyata + backfill) ────────────────────
def test_B1_backfill_dan_umur_dari_approval_requested_at(loop, mongo, admin):
    doc = _mk_doc(days_created=20, days_pending=2)
    doc.pop("approval_requested_at", None)
    try:
        loop.run_until_complete(mongo.special_orders.insert_one(dict(doc)))
        stored = loop.run_until_complete(mongo.special_orders.find_one({"id": doc["id"]}, {"_id": 0}))
        assert "approval_requested_at" not in stored

        import subprocess
        p = subprocess.run([sys.executable, "scripts/migrate_special_order_approval_requested_at.py"],
                           cwd="/app", capture_output=True, text=True, timeout=180)
        assert p.returncode == 0, p.stdout + p.stderr

        stored = loop.run_until_complete(mongo.special_orders.find_one({"id": doc["id"]}, {"_id": 0}))
        assert stored.get("approval_requested_at"), "backfill tidak menulis approval_requested_at"

        r = admin.get(f"{BASE_URL}/api/home/admin?entity_id={ENT}", timeout=60)
        assert r.status_code == 200, r.text[:300]
        rows = r.json()["special_orders_waiting"]["rows"]
        mine = [x for x in rows if x["id"] == doc["id"]]
        assert mine, f"dokumen uji tidak ada di rows (count={r.json()['special_orders_waiting']['count']})"
        assert mine[0]["days_waiting"] == 2, f"days_waiting={mine[0]['days_waiting']} (harap 2)"
    finally:
        _cleanup(loop, mongo)


# ── B3 — dokumen TERTUA tidak boleh terpotong ────────────────────────────────
# ── B2 — penanda shown/hidden/truncated jujur ────────────────────────────────
def test_B3_B2_tertua_di_baris_pertama_dan_penanda_jujur(loop, mongo, admin):
    ages = [3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23]
    docs = [_mk_doc(days_created=a, days_pending=a) for a in ages]
    oldest = _mk_doc(days_created=60, days_pending=60)  # disisipkan TERAKHIR
    try:
        for d in docs:
            d["approval_requested_at"] = d["status_history"][-1]["timestamp"]
            loop.run_until_complete(mongo.special_orders.insert_one(dict(d)))
        oldest["approval_requested_at"] = oldest["status_history"][-1]["timestamp"]
        loop.run_until_complete(mongo.special_orders.insert_one(dict(oldest)))

        r = admin.get(f"{BASE_URL}/api/home/admin?entity_id={ENT}", timeout=60)
        assert r.status_code == 200, r.text[:300]
        pl = r.json()["special_orders_waiting"]
        rows = pl["rows"]
        assert rows[0]["id"] == oldest["id"], f"rows[0] bukan dokumen 60 hari: {rows[0]}"
        assert rows[0]["days_waiting"] >= 60
        dw = [x["days_waiting"] for x in rows]
        assert dw == sorted(dw, reverse=True), f"rows tidak terurut menurun: {dw}"
        # B2
        assert pl["shown"] == len(rows)
        assert pl["count"] >= 12
        assert pl["truncated"] is True
        assert pl["hidden"] == pl["count"] - pl["shown"]
    finally:
        _cleanup(loop, mongo)


# ── B4 — total_amount bertipe teks tidak menjatuhkan beranda + pagar INV-DB-SORD
def test_B4_total_amount_teks_tidak_500_dan_pagar_memerah(loop, mongo, admin):
    doc = _mk_doc(days_created=4, days_pending=4)
    doc["approval_requested_at"] = doc["status_history"][-1]["timestamp"]
    doc["total_amount"] = "43.500.000"
    try:
        loop.run_until_complete(mongo.special_orders.insert_one(dict(doc)))
        r = admin.get(f"{BASE_URL}/api/home/admin?entity_id={ENT}", timeout=60)
        assert r.status_code == 200, f"beranda jatuh: {r.status_code} {r.text[:300]}"
        rows = r.json()["special_orders_waiting"]["rows"]
        mine = [x for x in rows if x["id"] == doc["id"]]
        assert mine, "dokumen bertipe teks tidak muncul di papan"
        assert mine[0]["amount"] == 0, f"amount={mine[0]['amount']} (harap 0)"

        import subprocess
        p = subprocess.run([sys.executable, "scripts/verify_data_integrity.py", "--only", "db"],
                           cwd="/app", capture_output=True, text=True, timeout=300)
        out = p.stdout + p.stderr
        assert "FAIL" in out, f"pagar tidak memerah:\n{out[-2000:]}"
        assert "total_amount BUKAN angka" in out and doc["number"] in out, \
            f"pagar tidak menyebut dokumen bertipe teks:\n{out[-2000:]}"
        # CATATAN: keluaran CLI tidak mencetak id invarian `INV-DB-SORD`
        assert p.returncode != 0, "pagar memerah tetapi exit code 0 (tidak memblokir)"
    finally:
        _cleanup(loop, mongo)


# ── C1/C2 — label peran manusiawi + entitas disebut ──────────────────────────
def test_C1_C2_label_peran_dan_entitas(loop, mongo, admin):
    doc = _mk_doc(days_created=6, days_pending=6, role="manager")
    doc["approval_requested_at"] = doc["status_history"][-1]["timestamp"]
    try:
        loop.run_until_complete(mongo.special_orders.insert_one(dict(doc)))
        r = admin.get(f"{BASE_URL}/api/home/admin?entity_id={ENT}", timeout=60)
        assert r.status_code == 200
        rows = r.json()["special_orders_waiting"]["rows"]
        mine = [x for x in rows if x["id"] == doc["id"]]
        assert mine, "dokumen uji tidak ada"
        assert mine[0]["role"] == "manager"          # backend kirim kode
        assert mine[0]["entity_id"] == ENT           # entitas tersedia untuk lencana
        # label manusiawi wajib ada di frontend (roleLabel), bukan kode mentah
        src = open("/app/frontend/src/features/home/AdminHome.jsx", encoding="utf-8").read()
        assert "roleLabel(" in src, "AdminHome tidak memakai roleLabel()"
        assert "EntityBadge" in src, "AdminHome tidak memakai EntityBadge"
    finally:
        _cleanup(loop, mongo)


# ── A3 — nol tebakan nama layar ──────────────────────────────────────────────
def test_A3_tanpa_fallback_nama_layar():
    src = open("/app/frontend/src/features/home/AdminHome.jsx", encoding="utf-8").read()
    assert '"special-orders"' not in src.replace("custom.view", "custom.view"), \
        "masih ada literal nama layar di AdminHome (fallback tebakan)"
    assert "custom.view ||" not in src


# ── A1 — satu penyusun pesan ─────────────────────────────────────────────────
def test_A1_satu_penyusun_pesan():
    import subprocess
    hits = subprocess.run(
        ["grep", "-rn", "special_order_approval", "/app/backend"],
        capture_output=True, text=True).stdout.splitlines()
    hits = [h for h in hits if "/tests/" not in h and "test_" not in h and ".pyc" not in h]
    hits = [h for h in hits if "services/notification_service.py" not in h]
    # buang baris komentar (#) — yang dilarang adalah PENYUSUNAN pesan, bukan penjelasan
    bad = []
    for h in hits:
        body = h.split(":", 2)[-1].strip()
        if body.startswith("#") or body.startswith("(`") or body.startswith('"'):
            continue
        if '"special_order_approval"' not in body and "'special_order_approval'" not in body:
            continue  # sekadar nama fungsi/variabel yang mirip
        bad.append(h)
    assert not bad, f"notif_type disusun di luar notification_service: {bad}"


# ── D1 — pagar tidak bisa dimatikan ──────────────────────────────────────────
def test_D1_pagar_home_kpi_tidak_bisa_dimatikan(loop):
    sys.path.insert(0, "/app/scripts/guardrails")
    sys.path.insert(0, "/app/scripts")
    import importlib.util
    spec = importlib.util.spec_from_file_location("vhk", "/app/scripts/guardrails/verify_home_kpi.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    payload = {
        "approvals_pending": 2,
        "approvals": {"total": 2, "all_items": [
            {"key": "special_order", "label": "Pesanan khusus menunggu ACC",
             "view": "special-orders", "count": 2}]},
    }
    sys.path.insert(0, "/app/scripts")
    from guardrails._common import Guard

    def _run(role):
        g = Guard("INV-HOME-01", "t1")
        m.check_payload(g, role, dict(payload), {}, {"special-orders", "approval-inbox"})
        return g.violations

    res_admin = _run("admin")
    res_mgr = _run("manager")
    n_admin, n_mgr = len(res_admin), len(res_mgr)
    assert n_admin > 0, "payload admin tanpa special_orders_waiting TIDAK dituduh"
    assert n_mgr == 0, f"payload manager dituduh palsu: {res_mgr}"


# ── B6 — nomor dokumen demo konsisten ────────────────────────────────────────
def test_B6_nomor_demo_bertanggal_dokumen(loop, mongo):
    docs = loop.run_until_complete(
        list(mongo.special_orders.find({"status": "pending_approval", PROBE: {"$exists": False}},
                                       {"_id": 0}).limit(50)))
    assert docs, "tidak ada PO custom pending demo"
    bad = []
    for d in docs:
        num = d.get("number", "")
        created = str(d.get("created_at", ""))[:10].replace("-", "")
        if len(num.split("-")) >= 3 and num.startswith("SORD-"):
            tgl = num.split("-")[1]
            if len(tgl) == 6 and created:
                if tgl != created[2:]:
                    bad.append((num, d.get("created_at")))
    assert not bad, f"nomor demo tidak konsisten dengan tanggal dokumen: {bad}"


# ── REGRESI umum ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("role", ["admin", "manager"])
def test_regresi_home_konsisten(admin, manager, role):
    for sess, who in ((admin, "admin"), (manager, "manager")):
        r = sess.get(f"{BASE_URL}/api/home/{role}?entity_id={ENT}", timeout=60)
        if who == "manager" and role == "admin":
            assert r.status_code in (200, 403), r.status_code
            if r.status_code == 403:
                continue
        assert r.status_code == 200, f"{who}→/home/{role}: {r.status_code} {r.text[:200]}"
        d = r.json()
        if "approvals_pending" in d and "approvals" in d:
            assert d["approvals_pending"] == d["approvals"]["total"], \
                f"{who}→{role}: {d['approvals_pending']} != {d['approvals']['total']}"


def test_regresi_special_orders_list_dan_notifikasi(admin, manager):
    r = admin.get(f"{BASE_URL}/api/special-orders?entity_id={ENT}", timeout=60)
    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
    for sess, who in ((admin, "admin"), (manager, "manager")):
        n = sess.get(f"{BASE_URL}/api/notifications", timeout=60)
        assert n.status_code == 200, f"{who} notifikasi: {n.status_code}"
