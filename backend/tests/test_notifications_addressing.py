"""HTTP-level regression tests for special_order_approval notification addressing.

Covers the review request items:
  - generate creates 'special_order_approval' notifs for pending special_orders (incl. legacy demo docs)
  - notif is addressed (recipient_user set, recipient_role != 'all')
  - sales user does NOT see 'special_order_approval'
  - job is idempotent (running twice does not duplicate)
  - cross-entity isolation on GET /api/notifications (X-Entity-Id header)
"""
import os
import pytest
import requests

BASE = "http://localhost:8001"
PWD = "demo12345"


def _login(email):
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": PWD})
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_tok():
    return _login("admin@kainnusantara.id")


@pytest.fixture(scope="module")
def sales_tok():
    return _login("sales@kainnusantara.id")


def _h(tok, entity=None):
    h = {"Authorization": f"Bearer {tok}"}
    if entity:
        h["X-Entity-Id"] = entity
    return h


def _get_notifs(tok, entity=None, limit=500):
    r = requests.get(f"{BASE}/api/notifications", headers=_h(tok, entity),
                     params={"limit": limit, "unread_only": False})
    assert r.status_code == 200, r.text
    return r.json()


def test_generate_creates_special_order_approval(admin_tok):
    # First run — may or may not create depending on already-generated for today
    r = requests.post(f"{BASE}/api/notifications/generate", headers=_h(admin_tok))
    assert r.status_code == 200, r.text

    # Fetch as admin
    all_notifs = _get_notifs(admin_tok)
    so_notifs = [n for n in all_notifs if n.get("type") == "special_order_approval"]
    assert len(so_notifs) > 0, "expected at least one special_order_approval after generate"

    # All must be addressed (per person)
    for n in so_notifs:
        assert n.get("recipient_user"), f"notif missing recipient_user: {n}"
        role = n.get("recipient_role") or ""
        assert role != "all", f"broadcast notif detected: {n}"


def test_generate_is_idempotent(admin_tok):
    """Calling generate twice must not duplicate special_order_approval notifs."""
    # baseline (already generated in previous test today)
    before = [n for n in _get_notifs(admin_tok) if n.get("type") == "special_order_approval"]
    r = requests.post(f"{BASE}/api/notifications/generate", headers=_h(admin_tok))
    assert r.status_code == 200
    after = [n for n in _get_notifs(admin_tok) if n.get("type") == "special_order_approval"]
    # per-person-per-day dedupe: count must not grow
    assert len(after) == len(before), (
        f"special_order_approval duplicated on 2nd generate: {len(before)} -> {len(after)}"
    )


def test_sales_does_not_see_special_order_approval(sales_tok):
    notifs = _get_notifs(sales_tok)
    leaked = [n for n in notifs if n.get("type") == "special_order_approval"]
    assert not leaked, f"sales sees {len(leaked)} approval notifs; must be zero: {leaked[:2]}"


def test_recipients_are_approvers_only(admin_tok):
    """Recipients of special_order_approval must hold order.approve (admin/manager),
    not plain sales."""
    notifs = [n for n in _get_notifs(admin_tok) if n.get("type") == "special_order_approval"]
    assert notifs, "no special_order_approval available"

    # Fetch users list to inspect roles of recipients
    r = requests.get(f"{BASE}/api/users", headers=_h(admin_tok))
    assert r.status_code == 200, r.text
    users = {u["id"]: u for u in r.json()}

    for n in notifs:
        uid = n["recipient_user"]
        u = users.get(uid)
        assert u is not None, f"recipient {uid} not a known user"
        # Only admin/manager roles are expected approvers in seed data
        assert u.get("role") in {"admin", "manager"}, (
            f"non-approver role received notif: {u.get('email')} role={u.get('role')}"
        )


def test_entity_isolation_on_notifications(admin_tok):
    """GET /api/notifications with X-Entity-Id header must not leak other entities' notifs."""
    ksc = _get_notifs(admin_tok, entity="ent_ksc")
    kanda = _get_notifs(admin_tok, entity="ent_kanda")

    def entity_set(items):
        return {n.get("entity_id") for n in items if n.get("entity_id")}

    ksc_entities = entity_set(ksc)
    kanda_entities = entity_set(kanda)

    # any entity-scoped notifs seen in ent_kanda must not include ent_ksc
    assert "ent_ksc" not in kanda_entities, (
        f"ent_ksc notifs leaked into ent_kanda context: {kanda_entities}"
    )
    assert "ent_kanda" not in ksc_entities, (
        f"ent_kanda notifs leaked into ent_ksc context: {ksc_entities}"
    )
