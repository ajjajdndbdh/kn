"""
Iteration 252 — verifikasi PERBAIKAN lonceng lintas badan usaha:
- Notifikasi drift KRITIS milik CV Kanda TAMPIL untuk admin walau konteks = ent_ksc
- Isolasi tetap: notifikasi NON-kritis (warning) milik ent_kanda TETAP tersaring pada konteks ent_ksc
- sales3 (Kanda) tidak boleh melihat notifikasi milik ent_ksc, baik ent_ksc maupun 'all'
- Anti-IDOR: sales3 tidak boleh menandai notif ent_ksc terbaca (404/403)
- Regresi cepat: drift job success, dedupe (created==0), explain ent_kanda ada 'nilai_cocok_selisih'
- Konsistensi lonceng: unread-count == jumlah unread yang benar-benar tampil (konteks sama)
"""
import os, uuid, pytest, requests

def _base():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if v: return v.rstrip("/")
    with open("/app/frontend/.env") as f:
        for l in f:
            if l.startswith("REACT_APP_BACKEND_URL="):
                return l.split("=",1)[1].strip().rstrip("/")
BASE = _base()

def _login(email, pw="demo12345"):
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:200]}"
    return r.json()["token"]

def _h(tok, entity=None):
    h = {"Authorization": f"Bearer {tok}"}
    if entity: h["X-Entity-Id"] = entity
    return h

@pytest.fixture(scope="module")
def admin_tok(): return _login("admin@kainnusantara.id")

@pytest.fixture(scope="module")
def sales3_tok(): return _login("sales3@kainnusantara.id")

@pytest.fixture(scope="module")
def sales_ksc_tok(): return _login("sales@kainnusantara.id")


def _items(body):
    return body if isinstance(body, list) else (body.get("items") or body.get("rows") or [])


def test_recon_shows_kanda_drift_900k(admin_tok):
    r = requests.get(f"{BASE}/api/gl/inventory-reconciliation", headers=_h(admin_tok), timeout=30)
    assert r.status_code == 200
    rows = r.json().get("rows") or []
    kanda = next((x for x in rows if x.get("entity_id") == "ent_kanda"), None)
    assert kanda is not None, rows
    diff = float(kanda.get("difference") or 0)
    assert abs(abs(diff) - 900000.0) < 1.0, f"expected Δ Rp 900.000 for Kanda, got {diff}"


def test_drift_job_success_and_dedupe(admin_tok):
    r = requests.post(f"{BASE}/api/scheduler/jobs/inventory_drift_watch/run", headers=_h(admin_tok), timeout=60)
    assert r.status_code == 200
    assert r.json().get("status") == "success"
    r2 = requests.post(f"{BASE}/api/scheduler/jobs/inventory_drift_watch/run", headers=_h(admin_tok), timeout=60)
    assert r2.status_code == 200
    assert int(r2.json().get("created") or 0) == 0, r2.json()


def test_drift_explain_kanda_has_pointing_suspect(admin_tok):
    r = requests.get(f"{BASE}/api/gl/inventory-drift-explain?entity_id=ent_kanda", headers=_h(admin_tok), timeout=30)
    assert r.status_code == 200
    kinds = {s.get("kind") for s in (r.json().get("suspects") or [])}
    assert "nilai_cocok_selisih" in kinds, f"expected nilai_cocok_selisih; got {kinds}"


# ── CORE FIX: kritis lintas entitas TAMPIL di konteks ent_ksc ──────────
def test_critical_kanda_drift_visible_under_ksc_context(admin_tok):
    r = requests.get(f"{BASE}/api/notifications", headers=_h(admin_tok, "ent_ksc"), timeout=30)
    assert r.status_code == 200
    items = _items(r.json())
    drifts = [n for n in items if n.get("type") == "inventory_drift" and n.get("entity_id") == "ent_kanda"]
    assert drifts, f"CRITICAL Kanda drift NOT visible under KSC context! got {len(items)} items"
    n = drifts[0]
    assert n.get("severity") == "critical"
    assert (n.get("link") or "").startswith("general-ledger")
    txt = (n.get("title") or "") + " " + (n.get("body") or "")
    assert "CV Kanda Suka" in txt or "Kanda" in txt
    assert "900" in txt  # 900.000


# ── ISOLATION: warning entitas lain TIDAK bocor ────────────────────────
def test_non_critical_other_entity_stays_filtered(admin_tok):
    """Sisipkan notif warning ent_kanda ditujukan user_admin_01; pastikan
    TIDAK tampil pada konteks ent_ksc; lalu hapus."""
    from pymongo import MongoClient
    mc = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    dbn = os.environ.get("DB_NAME", "test_database")
    coll = mc[dbn]["notifications"]
    probe_id = f"ntf_probe_{uuid.uuid4().hex[:8]}"
    coll.insert_one({
        "id": probe_id, "type": "test_probe", "entity_id": "ent_kanda",
        "recipient_user": "user_admin_01", "severity": "warning",
        "title": "PROBE non-kritis Kanda", "body": "seharusnya tidak muncul di konteks KSC",
        "link": "general-ledger", "read": False, "created_at": "2026-01-01T00:00:00Z"
    })
    try:
        r = requests.get(f"{BASE}/api/notifications", headers=_h(admin_tok, "ent_ksc"), timeout=30)
        assert r.status_code == 200
        ids = [n.get("id") for n in _items(r.json())]
        assert probe_id not in ids, "warning of other entity leaked into KSC context!"
        # Positive control: it should be visible in ent_kanda context
        r2 = requests.get(f"{BASE}/api/notifications", headers=_h(admin_tok, "ent_kanda"), timeout=30)
        ids2 = [n.get("id") for n in _items(r2.json())]
        assert probe_id in ids2, "probe not visible even in its own entity — fixture broken"
    finally:
        coll.delete_one({"id": probe_id})


# ── ISOLATION: sales3 (Kanda) tidak melihat KSC ────────────────────────
def test_sales3_notifications_own_entity_only(sales3_tok):
    for q in ["", "?entity_id=all", "?entity_id=ent_kanda"]:
        r = requests.get(f"{BASE}/api/notifications{q}", headers=_h(sales3_tok), timeout=30)
        assert r.status_code == 200, r.text[:200]
        for n in _items(r.json()):
            assert n.get("entity_id") != "ent_ksc", f"KSC leaked to sales3 (query={q}): {n}"


def test_sales3_cannot_query_ksc_scope(sales3_tok):
    r = requests.get(f"{BASE}/api/notifications?entity_id=ent_ksc", headers=_h(sales3_tok), timeout=30)
    # Should be 403 (not assigned) or empty list — either is acceptable isolation
    if r.status_code == 200:
        for n in _items(r.json()):
            assert n.get("entity_id") != "ent_ksc"
    else:
        assert r.status_code in (403, 404)


# ── ANTI-IDOR: sales3 tidak boleh menandai notif ent_ksc terbaca ───────
def test_sales3_cannot_mark_ksc_notification_read(sales3_tok, admin_tok):
    # find a real ent_ksc notification id via admin
    r = requests.get(f"{BASE}/api/notifications?entity_id=ent_ksc&limit=200", headers=_h(admin_tok), timeout=30)
    assert r.status_code == 200
    ksc = [n for n in _items(r.json()) if n.get("entity_id") == "ent_ksc"]
    if not ksc:
        pytest.skip("no ent_ksc notifications to probe IDOR")
    target = ksc[0]["id"]
    r2 = requests.post(f"{BASE}/api/notifications/{target}/read", headers=_h(sales3_tok), timeout=30)
    assert r2.status_code in (403, 404), f"IDOR! sales3 marked KSC notif read: {r2.status_code} {r2.text[:200]}"


# ── Konsistensi lonceng: unread-count == jumlah unread tampil ──────────
def test_unread_count_matches_visible_unread_under_ksc(admin_tok):
    r1 = requests.get(f"{BASE}/api/notifications?entity_id=ent_ksc", headers=_h(admin_tok, "ent_ksc"), timeout=30)
    r2 = requests.get(f"{BASE}/api/notifications/unread-count?entity_id=ent_ksc", headers=_h(admin_tok, "ent_ksc"), timeout=30)
    assert r1.status_code == 200 and r2.status_code == 200
    visible_unread = sum(1 for n in _items(r1.json()) if not n.get("read"))
    reported = int(r2.json().get("count") or 0)
    # List capped at 100; unread-count is a full count — check either equal or reported>=visible when list is full
    items = _items(r1.json())
    if len(items) < 100:
        assert reported == visible_unread, f"badge={reported} vs list_unread={visible_unread}"
    else:
        assert reported >= visible_unread
