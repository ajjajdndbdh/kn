"""AUDIT 2026-08-24 → REGRESI 2026-08-25.

Berkas ini lahir sebagai **reproduksi** 11 temuan audit (semua TERBUKTI). Temuannya
sudah diperbaiki sesi 2026-08-25, jadi tiap uji di sini kini berbalik arah: ia
menuntut **perilaku yang sudah benar** supaya kelas cacatnya tidak bisa kembali.

Yang dijaga (kode temuan asli di HANDOFF_AUDIT_SESI_2026-08-24.md):
  B1  umur tunggu dibaca dari `approval_requested_at` (bukan ditebak dari `created_at`)
  B2  `count` > baris WAJIB disertai `shown`/`hidden`/`truncated`
  B3  dokumen TERTUA tidak boleh terpotong walau disisipkan terakhir
  B4  `total_amount` berupa teks TIDAK boleh 500-kan `GET /api/home/admin`
  D1  `check_payload` WAJIB menuduh bila payload admin tanpa `special_orders_waiting`
  A1  hanya SATU tempat menyusun pesan `special_order_approval`
  A2  satu PO custom → satu penagih (bukan dua mesin bicara di hari yang sama)

Semua dokumen uji ber-tag `_test_audit` dan DIHAPUS di akhir (nol residu).

> **Jalankan BERURUTAN** (`-n0`): berkas ini dan
> `test_verifikasi_sesi_2026_08_25.py` sama-sama menyuntik & menghapus dokumen di
> `special_orders`/`notifications`. `pytest.ini` menyalakan pytest-xdist, jadi dua
> berkas itu bisa berjalan di pekerja berbeda pada basis data yang SAMA dan saling
> menarik lantai (terukur: 7 gagal palsu; dengan `-n0` → 17 lulus).

Usage:  cd /app && python -m pytest backend/tests/test_audit_findings_reproduction.py -q -n0
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
import requests

sys.path.insert(0, "/app/backend")
try:                                     # .env tidak otomatis terbaca oleh pytest
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
except Exception:  # noqa: BLE001
    pass

BASE_URL = os.environ.get("POC_BASE", "http://localhost:8001").rstrip("/")
PWD = "demo12345"
TEST_TAG = "TEST_AUDIT_2026_08_24"


def login(email):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": PWD}, timeout=30)
    assert r.status_code == 200, f"login {email} gagal HTTP {r.status_code}: {r.text[:200]}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {login('admin@kainnusantara.id')}",
            "X-Entity-Id": "all"}


@pytest.fixture(scope="module")
def db():
    from pymongo import MongoClient
    return MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=5000)[
        os.environ["DB_NAME"]]


@pytest.fixture(scope="module", autouse=True)
def cleanup(db):
    """Nol residu (INV-GATE-01): snapshot diambil SEBELUM login.

    `POST /auth/login` menulis satu sesi + satu baris `audit_logs`; kalau snapshot
    diambil sesudahnya, baris itu di luar jendela restore dan setiap kali uji ini
    dijalankan basis data bertambah satu dokumen permanen.
    """
    sys.path.insert(0, "/app/scripts/guardrails")
    from _common import DbSnapshot
    tersentuh = ["special_orders", "notifications", "audit_logs", "sessions",
                 "login_attempts"]

    def _bersih():
        db.special_orders.delete_many({"_test_audit": TEST_TAG})
        db.notifications.delete_many({"ref": {"$regex": "^so_custom_appr:AUDIT_"}})
    _bersih()
    snap = DbSnapshot(db, collections=tersentuh, verbose=False).take()
    yield
    _bersih()
    snap.restore()


def _iso(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _mk_so(id_suffix, days_ago_created, extra=None):
    doc = {
        "id": f"AUDIT_SO_{id_suffix}",
        "number": f"AUDIT-SORD-{id_suffix}",
        "status": "pending_approval",
        "customer_name": f"Pelanggan Uji {id_suffix}",
        "customer_id": "cust_audit",
        "entity_id": "ent_ksc",
        "total_amount": 1_000_000,
        "created_at": _iso(days_ago_created),
        "required_approval_role": "manager",
        "custom_item": {"description": "Kain custom uji audit"},
        "_test_audit": TEST_TAG,
    }
    if extra:
        doc.update(extra)
    return doc


def _papan(admin_headers):
    res = requests.get(f"{BASE_URL}/api/home/admin", headers=admin_headers, timeout=60)
    assert res.status_code == 200, f"HTTP {res.status_code}: {res.text[:200]}"
    return res.json()["special_orders_waiting"]


# ═══════════════════════════════════════════════════════════════════════════
# B1 — umur tunggu TIDAK boleh ditebak dari `created_at`
# ═══════════════════════════════════════════════════════════════════════════
def test_B1_umur_tunggu_dari_field_nyata(db, admin_headers):
    so = _mk_so("B1", 20, {"status_history": [
        {"status": "draft", "timestamp": _iso(20)},
        {"status": "pending_approval", "timestamp": _iso(2)},
    ]})
    db.special_orders.insert_one(so)
    try:
        # dokumen warisan (tanpa field) di-backfill dari status_history
        from services import special_order_service as sos
        asyncio.run(sos.ensure_approval_requested_at(db_sync_wrapper(db)))
        segar = db.special_orders.find_one({"id": so["id"]}, {"_id": 0})
        assert segar.get("approval_requested_at"), "backfill tidak mengisi field"

        row = next((r for r in _papan(admin_headers)["rows"]
                    if r["id"] == so["id"]), None)
        assert row is not None, "dokumen uji tidak muncul di papan"
        print(f"\nB1 days_waiting={row['days_waiting']} (harus 2, bukan 20)")
        assert row["days_waiting"] == 2, (
            "papan kembali menebak umur dari `created_at` — regresi B1")
    finally:
        db.special_orders.delete_one({"id": so["id"]})


def db_sync_wrapper(db):
    """`ensure_approval_requested_at` menerima objek db async (motor).

    Uji ini memakai PyMongo (sinkron) untuk menyiapkan data, jadi backfill dipanggil
    dengan klien motor sendiri supaya jalurnya sama dengan produksi.
    """
    from motor.motor_asyncio import AsyncIOMotorClient
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


# ═══════════════════════════════════════════════════════════════════════════
# B2 + B3 — jujur saat dipotong & yang TERTUA wajib ikut
# ═══════════════════════════════════════════════════════════════════════════
def test_B2_B3_penanda_pemotongan_dan_tertua_ikut(db, admin_headers):
    muda = [_mk_so(f"B3_{i}", i, {"created_at": _iso(i),
                                  "approval_requested_at": _iso(i)})
            for i in range(1, 12)]
    db.special_orders.insert_many(muda)
    tertua = _mk_so("B3_OLDEST", 60, {"created_at": _iso(60),
                                      "approval_requested_at": _iso(60)})
    db.special_orders.insert_one(tertua)          # disisipkan TERAKHIR
    try:
        papan = _papan(admin_headers)
        rows, count = papan["rows"], papan["count"]
        print(f"\nB2 count={count} shown={papan.get('shown')} "
              f"hidden={papan.get('hidden')} truncated={papan.get('truncated')}")
        assert count > len(rows), "kasus uji harus terpotong"
        assert papan["shown"] == len(rows)
        assert papan["truncated"] is True
        assert papan["hidden"] == count - papan["shown"]

        ids = [r["id"] for r in rows]
        assert tertua["id"] in ids, "dokumen TERTUA terpotong — regresi B3"
        assert ids[0] == tertua["id"], "dokumen tertua bukan di baris pertama"
        umur = [r["days_waiting"] for r in rows]
        assert all(a >= b for a, b in zip(umur, umur[1:])), f"urutan pecah: {umur}"
    finally:
        db.special_orders.delete_many({"id": {"$regex": "^AUDIT_SO_B3_"}})


# ═══════════════════════════════════════════════════════════════════════════
# B4 — satu dokumen bertipe aneh tidak boleh menjatuhkan Control Tower
# ═══════════════════════════════════════════════════════════════════════════
def test_B4_amount_teks_tidak_menjatuhkan_beranda(db, admin_headers):
    so = _mk_so("B4", 5, {"total_amount": "43.500.000",
                          "approval_requested_at": _iso(5)})
    db.special_orders.insert_one(so)
    try:
        papan = _papan(admin_headers)          # assert 200 di dalam
        row = next((r for r in papan["rows"] if r["id"] == so["id"]), None)
        print(f"\nB4 HTTP 200 · amount={row and row.get('amount')!r}")
        assert row is not None
        assert row["amount"] == 0.0, "nilai tak terbaca harus 0, bukan melempar galat"
    finally:
        db.special_orders.delete_one({"id": so["id"]})


# ═══════════════════════════════════════════════════════════════════════════
# D1 — pagar tidak boleh bisa dimatikan dengan menghapus datanya
# ═══════════════════════════════════════════════════════════════════════════
def test_D1_pagar_menuduh_saat_papan_hilang():
    sys.path.insert(0, "/app/scripts/guardrails")
    import importlib.util
    from _common import Guard
    spec = importlib.util.spec_from_file_location(
        "vhk", "/app/scripts/guardrails/verify_home_kpi.py")
    vhk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vhk)

    payload = {"approvals_pending": 2,
               "approvals": {"total": 2, "all_items": [
                   {"key": "special_order", "count": 2, "view": "special-orders"}]}}
    g = Guard("D1", "test")
    g.violations, g.checks = [], 0
    vhk.check_payload(g, "admin", payload, {"special_order": 2},
                      {"special-orders", "approval-inbox"})
    print(f"\nD1 pelanggaran saat papan DIHAPUS dari payload admin: {len(g.violations)}")
    assert g.violations, "pagar HIJAU padahal papan hilang — regresi D1"

    # ...dan tetap TIDAK menuduh peran yang memang tak punya papan ini.
    g2 = Guard("D1", "test")
    g2.violations, g2.checks = [], 0
    vhk.check_payload(g2, "manager", payload, {"special_order": 2},
                      {"special-orders", "approval-inbox"})
    assert not g2.violations, "tuduhan palsu untuk beranda manajer"


# ═══════════════════════════════════════════════════════════════════════════
# A1 — SATU tempat menyusun pesan "PO custom menunggu"
# ═══════════════════════════════════════════════════════════════════════════
def test_A1_satu_penyusun_pesan():
    router = open("/app/backend/routers/special_orders.py", encoding="utf-8").read()
    service = open("/app/backend/services/notification_service.py",
                   encoding="utf-8").read()
    assert "notify_special_order_waiting" in router, "router harus memanggil penyusun tunggal"
    assert service.count('notif_type=SPECIAL_ORDER_WAITING_TYPE') == 1, (
        "pesan `special_order_approval` disusun lebih dari satu kali di service")
    # dan penjaga statiknya memerah bila aturan itu dilanggar
    sys.path.insert(0, "/app/scripts/guardrails")
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "vna", "/app/scripts/guardrails/verify_notification_audience.py")
    vna = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vna)
    # KODE router (bukan komentarnya) tidak boleh menyusun pesannya sendiri lagi
    assert not vna.scan_source(router, "routers/special_orders.py"), (
        "router menyusun pesan `special_order_approval` sendiri lagi — regresi A1")
    merah = vna.scan_source(
        'async def f():\n'
        '    await create_addressed(notif_type="special_order_approval",\n'
        '                           roles=("manager",), title="t", body="b")\n',
        "routers/special_orders.py")
    print(f"\nA1 penjaga K3 menuduh contoh pelanggaran: {len(merah)}")
    assert merah, "penjaga K3 tidak memerah — aturan satu-penyusun tak dijaga"


# ═══════════════════════════════════════════════════════════════════════════
# A2 — satu PO custom, satu penagih (bukan dua mesin di hari yang sama)
# ═══════════════════════════════════════════════════════════════════════════
def test_A2_satu_penagih_per_dokumen(db, admin_headers):
    mgr = db.users.find_one({"email": "manager@kainnusantara.id"}, {"_id": 0, "id": 1})
    assert mgr, "manager user tidak ada"
    so = _mk_so("A2", 9, {"approval_requested_at": _iso(9)})
    db.special_orders.insert_one(so)
    # Jangan menghapus notifikasi milik data demo (residu = gate merah palsu):
    # catat yang SUDAH ada, lalu hanya yang BARU yang dibersihkan.
    sebelum = {n["id"] for n in db.notifications.find({}, {"_id": 0, "id": 1})}
    try:
        async def _jalankan():
            """SATU event loop: klien motor terikat ke loop pertama, jadi memanggil
            `asyncio.run()` dua kali membuat panggilan kedua gagal diam-diam."""
            from services import approval_reminder as ar
            from services import notification_service as ns
            lahir1 = await ns._notify_pending_special_orders()      # noqa: SLF001
            lahir2 = await ns._notify_pending_special_orders()      # noqa: SLF001
            hasil = await ar.job_approval_backlog_reminder()
            # sesudah pesannya DIBACA, job keadaan tidak boleh menagih lagi
            db.notifications.update_many(
                {"ref": {"$regex": f"^so_custom_appr:{so['id']}"}},
                {"$set": {"read": True}})
            lahir3 = await ns._notify_pending_special_orders()      # noqa: SLF001
            return lahir1, lahir2, hasil, lahir3

        lahir1, lahir2, hasil, lahir3 = asyncio.run(_jalankan())
        print(f"\nA2 lahir1={lahir1} lahir2={lahir2} "
              f"reminder={hasil.get('notified')} lahir3(setelah dibaca)={lahir3}")
        assert lahir2 == 0, "job kedua menggandakan pesan — regresi A2"
        assert lahir3 == 0, "job keadaan menagih ulang sesudah dibaca — regresi A2"

        # pesan untuk dokumen ini, per orang → maksimal SATU
        per_orang = {}
        for n in db.notifications.find({"ref": {"$regex": f"^so_custom_appr:{so['id']}"}},
                                       {"_id": 0}):
            per_orang[n.get("recipient_user")] = per_orang.get(n.get("recipient_user"), 0) + 1
        assert all(v == 1 for v in per_orang.values()), f"pesan kembar: {per_orang}"

        # pengingat harian tetap LENGKAP & jujur (maks satu per orang per hari)
        per_hari = {}
        for n in db.notifications.find({"type": "approval_backlog"}, {"_id": 0}):
            kunci = (n.get("recipient_user"), n.get("dedupe_key"))
            per_hari[kunci] = per_hari.get(kunci, 0) + 1
        assert all(v == 1 for v in per_hari.values()), f"pengingat kembar: {per_hari}"
    finally:
        db.special_orders.delete_one({"id": so["id"]})
        db.notifications.delete_many({"id": {"$nin": list(sebelum)}})
