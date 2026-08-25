"""
Backend test for iteration 250:
- /api/home/warehouse (new boards: transfer, cycle_count, inspection_hold)
- /api/home/sales (boards: special_order, sales_order, price)
- /api/home/warehouse cross-entity isolation (403)
- /api/gl/inventory-drift-explain?entity_id=ent_ksc
"""
import os
import pytest
import requests

def _read_backend_url():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if v:
        return v.rstrip("/")
    # fallback: parse frontend/.env
    fpath = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", ".env")
    with open(fpath) as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL not found")

BASE = _read_backend_url()


def _login(email: str, password: str = "demo12345") -> str:
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text[:200]}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_token():
    return _login("admin@kainnusantara.id")


@pytest.fixture(scope="module")
def sales_ksc_token():
    return _login("sales@kainnusantara.id")


@pytest.fixture(scope="module")
def sales_kanda_token():
    return _login("sales3@kainnusantara.id")


@pytest.fixture(scope="module")
def warehouse_token():
    return _login("warehouse@kainnusantara.id")


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


# --- warehouse home boards ---
def test_home_warehouse_boards_present(warehouse_token):
    r = requests.get(f"{BASE}/api/home/warehouse", headers=_hdr(warehouse_token), timeout=30)
    assert r.status_code == 200, r.text[:300]
    data = r.json()
    boards = data.get("boards") or data.get("waiting_boards") or {}
    # allow either flat 'boards' or nested structure
    keys = set(boards.keys()) if isinstance(boards, dict) else set()
    print("warehouse boards keys:", keys, "top-level keys:", list(data.keys())[:20])
    assert any(k in str(data) for k in ["transfer", "cycle_count", "inspection_hold"]), \
        f"expected warehouse board keys in response, got {list(data.keys())}"


def test_home_warehouse_cross_entity_403(sales_kanda_token):
    # sales3 belongs to CV Kanda Suka; asking for ent_ksc must 403
    r = requests.get(f"{BASE}/api/home/warehouse?entity_id=ent_ksc",
                     headers=_hdr(sales_kanda_token), timeout=30)
    assert r.status_code == 403, f"expected 403 got {r.status_code} {r.text[:200]}"


# --- sales home boards ---
def test_home_sales_boards_present(sales_ksc_token):
    r = requests.get(f"{BASE}/api/home/sales", headers=_hdr(sales_ksc_token), timeout=30)
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    txt = str(body)
    for key in ("special_order", "sales_order", "price"):
        assert key in txt, f"missing board key {key} in sales home"
    # SORD demo
    assert "SORD-260816-0001" in txt or "SORD" in txt, "expected special order document"


def test_home_sales_isolation_no_ksc_docs_for_kanda(sales_kanda_token):
    r = requests.get(f"{BASE}/api/home/sales", headers=_hdr(sales_kanda_token), timeout=30)
    assert r.status_code == 200, r.text[:300]
    txt = str(r.json())
    assert "SORD-260816-0001" not in txt, "KSC special order leaked to Kanda sales"
    assert "SO-0007" not in txt, "KSC sales order leaked to Kanda sales"


# --- inventory drift explain ---
def test_inventory_drift_explain(admin_token):
    r = requests.get(f"{BASE}/api/gl/inventory-drift-explain?entity_id=ent_ksc",
                     headers=_hdr(admin_token), timeout=30)
    assert r.status_code == 200, r.text[:300]
    data = r.json()
    # Expect physical breakdown by 'via' and GL breakdown by source
    keys = list(data.keys())
    print("drift-explain keys:", keys)
    # Check for expected shape
    has_physical = "physical_by_origin" in data
    has_gl = "gl_by_source" in data
    assert has_physical, f"missing physical breakdown, got keys={keys}"
    assert has_gl, f"missing GL breakdown, got keys={keys}"
    assert "suspects" in data, f"missing 'suspects' (dugaan penyebab), got keys={keys}"
