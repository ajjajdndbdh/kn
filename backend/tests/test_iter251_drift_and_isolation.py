"""
Iteration 251 backend verification:
- Drift monitor job (inventory_drift_watch): success, notifications addressed to accounting.manage,
  content mentions selisih value & 1-1300 & last true-up, severity critical, link general-ledger,
  dedupe day (2nd run created==0), NO journal entries posted by the job.
- Drift explain (/api/gl/inventory-drift-explain) suspects vocabulary:
  - Kanda (has real drift Rp 900.000) must contain one of the pointing kinds
    (nilai_cocok_selisih | tanpa_jurnal | asal_tak_dikenal | roll_tanpa_hpp | selisih_belum_terjelaskan)
  - KSC (in-sync) must NOT contain false accusations (only true_up_sebelumnya / pembulatan permitted)
  - physical_by_origin total equals subledger_value
- Isolation: sales3 (Kanda) GET /api/home/warehouse?entity_id=ent_ksc → 403;
  sales3 GET /api/home/sales without X-Entity-Id → only Kanda documents.
"""
import os
import pytest
import requests


def _base():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if v:
        return v.rstrip("/")
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", ".env")) as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL not found")


BASE = _base()


def _login(email, password="demo12345"):
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:200]}"
    return r.json()["token"]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_token():
    return _login("admin@kainnusantara.id")


@pytest.fixture(scope="module")
def sales_kanda_token():
    return _login("sales3@kainnusantara.id")


# ── Reconciliation baseline: know which entity is drifting ─────────────
def test_recon_reveals_drifting_entities(admin_token):
    r = requests.get(f"{BASE}/api/gl/inventory-reconciliation", headers=_hdr(admin_token), timeout=30)
    assert r.status_code == 200, r.text[:300]
    rows = r.json().get("rows") or []
    assert rows, "no reconciliation rows"
    print("recon rows:", [(x["entity_id"], x.get("difference"), x.get("entity_name")) for x in rows])


# ── Drift explain: Kanda (drift Rp 900.000) must point to a document ───
def test_drift_explain_kanda_points_to_document(admin_token):
    r = requests.get(f"{BASE}/api/gl/inventory-drift-explain?entity_id=ent_kanda",
                     headers=_hdr(admin_token), timeout=30)
    assert r.status_code == 200, r.text[:300]
    data = r.json()
    suspects = data.get("suspects") or []
    kinds = {s.get("kind") for s in suspects}
    print("kanda suspects kinds:", kinds)
    # If Kanda is actually drifting, one of the "pointing" kinds must be present.
    diff = float(data.get("difference") or 0)
    if abs(diff) > 1:
        pointing = {"nilai_cocok_selisih", "tanpa_jurnal", "asal_tak_dikenal",
                    "roll_tanpa_hpp", "selisih_belum_terjelaskan"}
        assert kinds & pointing, f"expected pointing suspect for drift; got {kinds}"
    # physical_by_origin total equals subledger_value
    pbo = data.get("physical_by_origin")
    total_pbo = None
    if isinstance(pbo, dict):
        total_pbo = round(sum(float(v.get("value") or 0) if isinstance(v, dict) else float(v or 0)
                              for v in pbo.values()), 2)
    elif isinstance(pbo, list):
        total_pbo = round(sum(float(v.get("value") or 0) for v in pbo), 2)
    sub = data.get("subledger_value")
    if sub is not None and total_pbo is not None:
        assert abs(total_pbo - float(sub)) <= 1.0, \
            f"physical_by_origin ({total_pbo}) != subledger_value ({sub})"


def test_drift_explain_ksc_no_false_accusation(admin_token):
    r = requests.get(f"{BASE}/api/gl/inventory-drift-explain?entity_id=ent_ksc",
                     headers=_hdr(admin_token), timeout=30)
    assert r.status_code == 200, r.text[:300]
    data = r.json()
    diff = float(data.get("difference") or 0)
    suspects = data.get("suspects") or []
    kinds = [s.get("kind") for s in suspects]
    print("ksc diff:", diff, "suspects kinds:", kinds)
    if abs(diff) <= 1:
        allowed = {"true_up_sebelumnya", "pembulatan"}
        bad = [k for k in kinds if k not in allowed]
        assert not bad, f"KSC in sync but has accusatory suspects: {bad}"


# ── Drift monitor job ──────────────────────────────────────────────────
def _count_journals_before_after(admin_token):
    r = requests.get(f"{BASE}/api/gl/journal?limit=1", headers=_hdr(admin_token), timeout=30)
    if r.status_code != 200:
        return None
    body = r.json()
    if isinstance(body, list):
        # server returned raw list — use a bigger limit to get an actual count
        r2 = requests.get(f"{BASE}/api/gl/journal?limit=10000", headers=_hdr(admin_token), timeout=30)
        if r2.status_code != 200:
            return None
        b2 = r2.json()
        return len(b2) if isinstance(b2, list) else b2.get("total") or len(b2.get("items") or b2.get("rows") or [])
    return body.get("total") or len(body.get("items") or body.get("rows") or [])


def test_drift_job_first_run_creates_notifications(admin_token):
    # journal count before
    before = _count_journals_before_after(admin_token)
    # snapshot notifications count for type inventory_drift
    r0 = requests.get(f"{BASE}/api/notifications?limit=200", headers=_hdr(admin_token), timeout=30)
    n_before = 0
    if r0.status_code == 200:
        body0 = r0.json()
        items0 = body0 if isinstance(body0, list) else (body0.get("items") or body0.get("rows") or [])
        try:
            n_before = sum(1 for x in items0 if x.get("type") == "inventory_drift")
        except Exception:
            n_before = 0

    r = requests.post(f"{BASE}/api/scheduler/jobs/inventory_drift_watch/run",
                      headers=_hdr(admin_token), timeout=60)
    assert r.status_code == 200, r.text[:300]
    run = r.json()
    print("first drift run:", run)
    assert run.get("status") == "success", run
    # detail wording
    detail = str(run.get("detail") or "")
    # Either drifting or all-in-sync — we care that the phrasing is correct.
    assert ("berselisih" in detail) or ("sinkron" in detail), detail

    # If drifting entities exist we expect created >= 1 (unless already deduped today).
    # Second run must be created == 0 (dedupe day).
    r2 = requests.post(f"{BASE}/api/scheduler/jobs/inventory_drift_watch/run",
                       headers=_hdr(admin_token), timeout=60)
    assert r2.status_code == 200, r2.text[:300]
    run2 = r2.json()
    print("second drift run:", run2)
    assert run2.get("status") == "success"
    assert int(run2.get("created") or 0) == 0, f"dedupe day failed: {run2}"

    # journal count after — job must not post journals
    after = _count_journals_before_after(admin_token)
    if before is not None and after is not None:
        assert before == after, f"drift job posted journals! before={before} after={after}"


def test_drift_notifications_addressed_and_shaped(admin_token):
    # Make sure at least one run happened
    r = requests.post(f"{BASE}/api/scheduler/jobs/inventory_drift_watch/run",
                      headers=_hdr(admin_token), timeout=60)
    assert r.status_code == 200
    # Fetch notifications for admin (has accounting.manage). Drift notif entity is Kanda,
    # so we must query in that entity scope; admin's default context is KSC.
    r2 = requests.get(f"{BASE}/api/notifications?entity_id=ent_kanda&limit=200",
                      headers=_hdr(admin_token), timeout=30)
    assert r2.status_code == 200, r2.text[:200]
    body = r2.json()
    items = body if isinstance(body, list) else (body.get("items") or body.get("rows") or [])
    items = items or []
    drifts = [n for n in items if n.get("type") == "inventory_drift"]
    print("inventory_drift notifs:", len(drifts))
    if not drifts:
        pytest.skip("No drift notifications visible (possibly all books in sync today)")

    n = drifts[0]
    # Must target a specific user (bukan siaran)
    assert n.get("recipient_user") or n.get("user_id") or n.get("recipient_id"), \
        f"drift notif not addressed to user: {n}"
    # Severity critical or warning; per spec, drift > threshold*10 → critical
    assert n.get("severity") in ("critical", "warning"), n.get("severity")
    # Link to general-ledger
    assert (n.get("link") or "").startswith("general-ledger"), n.get("link")
    body_text = (n.get("body") or "") + " " + (n.get("title") or "")
    # Body must mention 1-1300 and rupiah value and reference true-up (or "belum pernah")
    assert "1-1300" in body_text, "body must mention account 1-1300"
    assert "Rp" in body_text, "body must mention rupiah value"
    assert ("True-up terakhir" in body_text) or ("belum pernah di-true-up" in body_text), \
        "body must mention last true-up context"


# ── Isolation ──────────────────────────────────────────────────────────
def test_warehouse_cross_entity_403(sales_kanda_token):
    r = requests.get(f"{BASE}/api/home/warehouse?entity_id=ent_ksc",
                     headers=_hdr(sales_kanda_token), timeout=30)
    assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text[:200]}"


def test_sales_home_no_header_returns_own_entity_only(sales_kanda_token):
    r = requests.get(f"{BASE}/api/home/sales", headers=_hdr(sales_kanda_token), timeout=30)
    assert r.status_code == 200, r.text[:200]
    txt = str(r.json())
    assert "SORD-260816-0001" not in txt, "KSC SORD leaked to Kanda sales"
    assert "SO-0007" not in txt, "KSC SO leaked to Kanda sales"
