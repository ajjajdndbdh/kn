#!/usr/bin/env python3
"""POC **P-0** — ASAL DOKUMEN PO: rantai `PO → PR → SO` & kolom **Nama Sales**.

Rencana: `RENCANA_EKSEKUSI_MD_ERP.md` §FASE P langkah **P.0** (prasyarat papan PO).
Keputusan pemilik yang mengikat (2026-08-20 & 2026-08-21):
  · tautan hanya untuk **dokumen BARU** — 14 PO lama **DIBIARKAN kosong**
    (tanpa `scripts/migrate_po_pr_link.py`);
  · PO pembelian rutin (tidak lahir dari pesanan) menampilkan **sel kosong "—"**,
    BUKAN label karangan dan BUKAN nama pembuat PO.

KENAPA POC INI ADA
==================
Sebelum P-0 keadaannya terukur: **0 dari 14** PO menyimpan `pr_id`, dan
`purchase_requisitions.po_ids` terisi 1 dari 5. Artinya kolom **Nama Sales** di
papan PO (FASE P) akan **selamanya kosong** — tanpa satu galat pun. Kelas cacat
seperti ini tidak bisa dibuktikan hilang dengan membaca kode: PO lahir dari
**EMPAT pintu** dan tiap pintu bisa diam-diam berbeda.

APA YANG DIBUKTIKAN (dan kenapa masing-masing perlu)
----------------------------------------------------
  P0-1 **Tiga pintu lahirnya PO menulis asal dokumen yang SAMA** — realisasi PR,
       award RFQ, dan PO manual. (Pintu ke-4, kontrak payung/blanket, dijaga gate
       statik `INV-ORIG-01`; ia tidak pernah lahir dari PR sehingga tidak punya
       jalur runtime yang berbeda.)
  P0-2 **Nama Sales DIRUNUT, bukan diketik.** Yang menekan tombol di POC ini adalah
       **admin** (Budi Santoso), sedangkan yang muncul di PO adalah **sales pemilik
       pesanan** (Ayu Permatasari). Kalau kelak seseorang "memperbaiki" kolom ini
       dengan `created_by`, POC ini memerah. Angkanya juga dihitung ulang MANDIRI
       dari MongoDB (opini kedua), bukan dibandingkan dengan dirinya sendiri.
  P0-3 **Payload permintaan TIDAK PERNAH memuat nama sales.** Dibuktikan dengan
       memeriksa badan permintaan yang POC ini kirim: nol kunci `sales_*`.
  P0-4 **PO pembelian rutin: field ADA tetapi KOSONG.** Papan PO harus bisa
       membedakan "memang tidak ada sales-nya" dari "field-nya tidak ada" — dua hal
       yang tampak identik di layar tetapi beda artinya.
  P0-5 **`refs` dua arah** (PO→PR *dan* PR→PO), plus RFQ→PR, supaya penelusuran
       bisa dimulai dari dokumen mana pun.
  P0-6 **Backfill relasi bersih**: `doc_refs_service.backfill(dry_run=True)` →
       `would_add=0` **dan** `skipped=0`. (`skipped` pernah 1 karena aturan
       backfill mengiterasi koleksi yang salah — hijau di permukaan, tetapi arah
       tautannya tidak pernah terbentuk.)
  P0-7 **Gate sungguhan HIJAU** (dijalankan, bukan ditiru): `INV-ORIG-01`
       (+ `--self-test`-nya) dan `scripts/audit_doc_refs.py --strict` — yang
       terakhir membuktikan PO mandiri **tidak** dituduh dokumen yatim.
  P0-8 **Data demo punya rantainya** (3 rantai SO→PR→PO dari `seed_realistic.py`),
       karena fitur yang tak punya data demo tidak pernah benar-benar dilihat
       pemilik maupun agen uji ("hijau tapi hampa", §11 risiko #11).
  P0-9 **Keputusan "tanpa backfill" DIHORMATI**: PO lama tetap tanpa `pr_id`, dan
       itu bukan pelanggaran.
  P0-10 **NOL RESIDU** — seluruh dokumen yang POC ini buat dihapus, dan jumlah
       dokumen tiap koleksi tersentuh diukur "sebelum == sesudah". POC aman
       dijalankan berulang.

Jalankan:  cd /app && python backend/test_core_p0_poc.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import requests

BASE = os.environ.get("POC_BASE_URL", "http://localhost:8001")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PW = "demo12345"
ADMIN = "admin@kainnusantara.id"
MANAGER = "manager@kainnusantara.id"
ENT_A = "ent_ksc"

#: Koleksi yang alur ini menyentuh — dipakai pengukuran nol residu (P0-10).
WATCH = ("purchase_orders", "purchase_requisitions", "rfqs", "wms_tasks",
         "notifications", "inventory_movements", "inventory_rolls")

TOKENS: list[str] = []
#: Semua badan permintaan yang POC ini kirim — dipakai P0-3 (nol kunci `sales_*`).
SENT_PAYLOADS: list[tuple[str, dict]] = []

PASS = 0
FAIL = 0
FAILED_LABELS: list[str] = []


def ok(cond: bool, label: str, extra: str = "") -> bool:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {label}" + (f"  \033[2m{extra}\033[0m" if extra else ""))
    else:
        FAIL += 1
        FAILED_LABELS.append(label)
        print(f"  \033[91m[FAIL]\033[0m {label}" + (f"\n         → {extra}" if extra else ""))
    return bool(cond)


def head(t: str) -> None:
    print(f"\n\033[93m{t}\033[0m")


def login(email: str) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"email": email, "password": PW}, timeout=30)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:300]}"
    tok = r.json()["token"]
    TOKENS.append(tok)
    s.headers.update({"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    return s


def h(entity: str = ENT_A) -> dict:
    return {"X-Entity-Id": entity}


def post(sess: requests.Session, path: str, payload: dict) -> requests.Response:
    """POST + catat payload-nya (bukti P0-3: nama sales tidak pernah dikirim)."""
    SENT_PAYLOADS.append((path, payload))
    return sess.post(f"{BASE}{path}", json=payload, headers=h(), timeout=60)


def _db():
    from pymongo import MongoClient
    cli = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    return cli[os.environ.get("DB_NAME", "test_database")]


def run_gate(rel_path: str, *args: str) -> tuple[int, str]:
    """Jalankan gate SUNGGUHAN (bukan menirunya) → (exit code, ekor keluaran).

    Kalau gate MEMERAH, yang dikembalikan adalah baris `[FAIL]`-nya — bukan ekor
    keluaran. Alasannya terukur (2026-08-21): `gate.sh --full` memerah di POC ini
    dengan pesan "PASS 31 · FAIL 1" **tanpa menyebut temuannya**, sehingga sesi
    berikutnya harus menebak. Ekor keluaran hanya berguna saat gate hijau.
    """
    p = subprocess.run([sys.executable, os.path.join(ROOT, rel_path), *args],
                       capture_output=True, text=True, cwd=ROOT, timeout=420)
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0:
        fails = [re.sub(r"\033\[[0-9;]*m", "", ln).strip()
                 for ln in out.splitlines() if "[FAIL]" in ln]
        if fails:
            return p.returncode, " ‖ ".join(fails)[-1200:]
    return p.returncode, out[-400:]


def refs_backfill_dry_run() -> dict:
    """Panggil `doc_refs_service.backfill(dry_run=True)` di proses TERPISAH.

    Dijalankan sebagai subproses supaya POC (yang sinkron, berbasis HTTP) tidak
    perlu membuka koneksi Motor sendiri — dan supaya yang diukur benar-benar kode
    layanan yang dipakai aplikasi, bukan tiruannya.
    """
    code = (
        "import asyncio, json, sys\n"
        "sys.path.insert(0, 'backend')\n"
        "from dotenv import load_dotenv; load_dotenv('backend/.env')\n"
        "from services import doc_refs_service as refs\n"
        "print('JSON:' + json.dumps(asyncio.run(refs.backfill(dry_run=True))))\n"
    )
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       cwd=ROOT, timeout=300)
    for line in (p.stdout or "").splitlines():
        if line.startswith("JSON:"):
            return json.loads(line[5:])
    return {"error": (p.stdout or "") + (p.stderr or "")}


def in_days(n: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=n)).strftime("%Y-%m-%d")


def approve_pr_if_needed(mgr: requests.Session, pr: dict) -> dict:
    if pr.get("status") == "approved":
        return pr
    r = post(mgr, f"/api/purchase-requisitions/{pr['id']}/approve", {"notes": "POC P-0"})
    assert r.status_code == 200, f"approve PR: {r.status_code} {r.text[:300]}"
    return r.json()


# ═══════════════════════════════════════════════════════════════════════════
def main() -> int:  # noqa: C901 — POC linear supaya terbaca sebagai bukti
    db = _db()
    before = {c: db[c].count_documents({}) for c in WATCH}
    audit_before = {d["id"] for d in db.audit_logs.find({}, {"_id": 0, "id": 1})}
    notif_before = {d["id"] for d in db.notifications.find({}, {"_id": 0, "id": 1})}

    created_po: list[str] = []
    created_pr: list[str] = []
    created_rfq: list[str] = []
    touched_so: list[str] = []

    print("\033[1m" + "=" * 78)
    print("  POC P-0 — asal dokumen PO (PO→PR→SO) & kolom Nama Sales")
    print("=" * 78 + "\033[0m")

    adm = login(ADMIN)
    mgr = login(MANAGER)

    # Data demo acuan — dibaca dari MongoDB, bukan diasumsikan.
    so1 = db.sales_orders.find_one({"id": "so_001"}, {"_id": 0})
    so2 = db.sales_orders.find_one({"id": "so_003"}, {"_id": 0})
    sup_ntt = db.suppliers.find_one({"name": "NTT Weaving Co"}, {"_id": 0, "id": 1})
    sup_plb = db.suppliers.find_one({"name": "Palembang Silk House"}, {"_id": 0, "id": 1})
    sup_crb = db.suppliers.find_one({"name": "Cirebon Craft"}, {"_id": 0, "id": 1})
    assert so1 and so2 and sup_ntt and sup_plb and sup_crb, (
        "data demo belum lengkap — jalankan `python seed_realistic.py` lebih dulu.")
    admin_name = adm.get(f"{BASE}/api/auth/me", headers=h(), timeout=30).json().get("name", "")

    # ══════════════════════════════════════════════════════════════════════
    head("P0-1a · PINTU 1 — realisasi PR → PO (jalur paling sering dipakai)")
    r = post(adm, f"/api/sales-orders/{so1['id']}/repeat-restock", {
        "items": [{"product_id": "prod_tenun_ikat", "quantity": 25, "unit": "yard"}],
        "reason": "POC P-0 — ulangi pesanan", "warehouse_id": "wh_surabaya",
        "needed_by_date": in_days(10), "submit_now": True})
    ok(r.status_code == 200, "PR lahir dari pesanan lewat tombol 'Ulangi pesanan'",
       f"HTTP {r.status_code} {r.text[:180]}")
    if r.status_code != 200:
        return 1
    pr1 = r.json()["pr"]
    created_pr.append(pr1["id"])
    touched_so.append(so1["id"])
    ok(pr1.get("source") == "so_repeat" and pr1.get("source_ref_id") == so1["id"],
       "PR menyimpan jejak pesanan asalnya (`source=so_repeat` + `source_ref_id`)",
       f"{pr1.get('number')} · source={pr1.get('source')} ref={pr1.get('source_ref_id')}")

    pr1 = approve_pr_if_needed(mgr, pr1)
    r = post(adm, f"/api/purchase-requisitions/{pr1['id']}/realize-po", {
        "supplier_id": sup_ntt["id"], "warehouse_id": "wh_surabaya",
        "expected_delivery_date": in_days(14), "notes": "POC P-0 realisasi"})
    ok(r.status_code == 200, "PR direalisasikan menjadi PO",
       f"HTTP {r.status_code} {r.text[:200]}")
    if r.status_code != 200:
        return 1
    po1 = r.json()["po"]
    created_po.append(po1["id"])
    ok(po1.get("pr_id") == pr1["id"] and po1.get("pr_number") == pr1["number"],
       "PO menyimpan `pr_id` + `pr_number` (field KANONIK, bukan `source_pr_*` yatim)",
       f"{po1.get('po_number')} ← {po1.get('pr_number')}")
    ok(po1.get("source") == "pr" and po1.get("source_so_ids") == [so1["id"]],
       "PO menyimpan jalur lahirnya (`source=pr`) & pesanan asal (`source_so_ids`)",
       f"source={po1.get('source')} so_ids={po1.get('source_so_ids')}")

    # ══════════════════════════════════════════════════════════════════════
    head("P0-2 · Nama Sales DIRUNUT dari pesanan — bukan diketik, bukan pembuat PO")
    # Opini kedua: hitung ulang MANDIRI dari MongoDB (bukan membandingkan respons
    # dengan dirinya sendiri).
    so1_db = db.sales_orders.find_one({"id": so1["id"]},
                                      {"_id": 0, "sales_name": 1, "created_by": 1})
    expect_name = (so1_db or {}).get("sales_name", "")
    expect_uid = (so1_db or {}).get("created_by", "")
    ok(po1.get("sales_name") == expect_name and expect_name != "",
       "`sales_name` PO == hitung-ulang mandiri dari SO asal",
       f"PO={po1.get('sales_name')!r} · Mongo(SO)={expect_name!r}")
    ok(po1.get("sales_user_id") == expect_uid and expect_uid != "",
       "`sales_user_id` PO == `sales_orders.created_by` (id pengguna, bukan nama)",
       f"PO={po1.get('sales_user_id')!r} · Mongo={expect_uid!r}")
    ok(po1.get("sales_name") != admin_name,
       "nama yang muncul BUKAN nama penekan tombol (admin) — kolom tidak berbohong",
       f"sales={po1.get('sales_name')!r} vs penekan tombol={admin_name!r}")
    po1_db = db.purchase_orders.find_one({"id": po1["id"]}, {"_id": 0})
    ok((po1_db or {}).get("sales_name") == expect_name,
       "yang TERSIMPAN di MongoDB sama dengan yang dikembalikan API (bukan hiasan respons)",
       f"db={(po1_db or {}).get('sales_name')!r}")

    # ══════════════════════════════════════════════════════════════════════
    head("P0-3 · Payload permintaan tidak pernah memuat nama sales")
    kotor = [(path, k) for path, body in SENT_PAYLOADS
             for k in json.loads(json.dumps(body)).keys() if str(k).startswith("sales")]
    dalam_teks = [path for path, body in SENT_PAYLOADS
                  if expect_name and expect_name in json.dumps(body, ensure_ascii=False)]
    ok(not kotor and not dalam_teks,
       "nol kunci `sales_*` dan nol nama sales di seluruh badan permintaan POC ini",
       f"kunci={kotor} · badan memuat nama={dalam_teks}")

    # ══════════════════════════════════════════════════════════════════════
    head("P0-1b · PINTU 2 — award RFQ → PO (rantai PO → RFQ → PR → SO)")
    r = post(adm, f"/api/sales-orders/{so2['id']}/repeat-restock", {
        "items": [{"product_id": "prod_songket_palembang", "quantity": 12, "unit": "yard"}],
        "reason": "POC P-0 — ulangi pesanan (jalur RFQ)", "warehouse_id": "wh_jakarta",
        "needed_by_date": in_days(12), "submit_now": True})
    ok(r.status_code == 200, "PR kedua lahir dari pesanan lain",
       f"HTTP {r.status_code} {r.text[:180]}")
    if r.status_code != 200:
        return 1
    pr2 = r.json()["pr"]
    created_pr.append(pr2["id"])
    touched_so.append(so2["id"])
    pr2 = approve_pr_if_needed(mgr, pr2)

    r = post(adm, "/api/rfqs", {
        "source": "pr", "pr_id": pr2["id"], "warehouse_id": "wh_jakarta",
        "supplier_ids": [sup_plb["id"]], "title": "POC P-0 RFQ",
        "due_date": in_days(5), "needed_by_date": in_days(12)})
    ok(r.status_code == 200, "RFQ dibuat dari PR", f"HTTP {r.status_code} {r.text[:200]}")
    if r.status_code != 200:
        return 1
    rfq = r.json()
    created_rfq.append(rfq["id"])
    post(adm, f"/api/rfqs/{rfq['id']}/send", {})
    line_id = (rfq.get("items") or [{}])[0].get("line_id", "L1")
    r = post(adm, f"/api/rfqs/{rfq['id']}/quote", {
        "supplier_id": sup_plb["id"],
        "lines": [{"line_id": line_id, "price": 320000, "available": True}],
        "lead_time_days": 7})
    ok(r.status_code == 200, "penawaran supplier masuk", f"HTTP {r.status_code}")
    r = post(adm, f"/api/rfqs/{rfq['id']}/award", {
        "mode": "full", "full_supplier_id": sup_plb["id"]})
    ok(r.status_code == 200, "RFQ di-award → PO lahir", f"HTTP {r.status_code} {r.text[:200]}")
    if r.status_code != 200:
        return 1
    award_pos = [p for p in (r.json().get("pos") or [])] or []
    po2 = award_pos[0] if award_pos else {}
    if not po2:            # bentuk respons berbeda antar-versi → cari lewat MongoDB
        po2 = db.purchase_orders.find_one({"pr_id": pr2["id"]}, {"_id": 0}) or {}
    if po2.get("id"):
        created_po.append(po2["id"])
    so2_db = db.sales_orders.find_one({"id": so2["id"]}, {"_id": 0, "sales_name": 1})
    ok(po2.get("pr_id") == pr2["id"] and po2.get("source") in ("pr", "rfq"),
       "PO hasil award RFQ memakai definisi asal dokumen yang SAMA",
       f"{po2.get('po_number')} pr={po2.get('pr_number')} source={po2.get('source')}")
    ok(po2.get("sales_name") == (so2_db or {}).get("sales_name") != "",
       "Nama Sales ikut terunut lewat jalur RFQ (tiga pintu, satu arti)",
       f"PO={po2.get('sales_name')!r} · Mongo(SO)={(so2_db or {}).get('sales_name')!r}")

    # ══════════════════════════════════════════════════════════════════════
    head("P0-4 · PINTU 3 — PO manual (pembelian rutin): field ADA tetapi KOSONG")
    r = post(adm, "/api/purchase-orders", {
        "supplier_id": sup_crb["id"], "warehouse_id": "wh_jakarta",
        "items": [{"product_id": "prod_batik_mega", "quantity": 8, "unit": "yard",
                   "price": 150000, "expected_grade": "A"}],
        "expected_delivery_date": in_days(9), "notes": "POC P-0 — PO rutin tanpa sales"})
    ok(r.status_code == 200, "PO manual dibuat", f"HTTP {r.status_code} {r.text[:220]}")
    if r.status_code != 200:
        return 1
    po3 = r.json()
    created_po.append(po3["id"])
    po3_db = db.purchase_orders.find_one({"id": po3["id"]}, {"_id": 0}) or {}
    KANON = ("pr_id", "pr_number", "source", "source_so_ids", "sales_user_id", "sales_name")
    hilang = [f for f in KANON if f not in po3_db]
    ok(not hilang,
       "SELURUH field asal dokumen ADA di PO manual (papan bisa bedakan kosong vs tak ada)",
       f"hilang={hilang}" if hilang else f"{len(KANON)} field lengkap")
    kosong = {f: po3_db.get(f) for f in ("pr_id", "pr_number", "sales_user_id", "sales_name")}
    ok(all(v in ("", [], None) for v in kosong.values()),
       "isinya KOSONG (bukan nama pembuat PO) — sel '—' yang jujur di papan",
       f"{kosong}")
    ok(po3_db.get("sales_name") != admin_name,
       "PO rutin TIDAK mencatut nama admin yang mengetiknya (kelas bug C · INV-ORIG-01 R3)",
       f"sales_name={po3_db.get('sales_name')!r} · admin={admin_name!r}")

    # ══════════════════════════════════════════════════════════════════════
    head("P0-5 · Jejak `refs` DUA ARAH (PO↔PR · RFQ→PR)")
    po1_db = db.purchase_orders.find_one({"id": po1["id"]}, {"_id": 0, "refs": 1}) or {}
    pr1_db = db.purchase_requisitions.find_one({"id": pr1["id"]},
                                              {"_id": 0, "refs": 1, "po_ids": 1}) or {}
    ok(any(x.get("rel") == "parent" and x.get("doc_type") == "purchase_requisition"
           and x.get("doc_id") == pr1["id"] for x in (po1_db.get("refs") or [])),
       "PO → PR: `refs[rel=parent]` tertulis di PO",
       f"{[ (x.get('rel'), x.get('doc_number')) for x in (po1_db.get('refs') or []) ]}")
    ok(any(x.get("rel") == "child" and x.get("doc_type") == "purchase_order"
           and x.get("doc_id") == po1["id"] for x in (pr1_db.get("refs") or [])),
       "PR → PO: arah BALIK tertulis di PR (penelusuran bisa mulai dari mana pun)",
       f"{[ (x.get('rel'), x.get('doc_number')) for x in (pr1_db.get('refs') or []) ]}")
    ok(po1["id"] in (pr1_db.get("po_ids") or []),
       "`PR.po_ids` ikut terisi (dipakai layar PR & realisasi parsial)",
       f"po_ids={pr1_db.get('po_ids')}")
    rfq_db = db.rfqs.find_one({"id": rfq["id"]}, {"_id": 0, "refs": 1}) or {}
    ok(any(x.get("rel") == "parent" and x.get("doc_type") == "purchase_requisition"
           for x in (rfq_db.get("refs") or [])),
       "RFQ → PR: rantai PO → RFQ → PR → SO tidak putus di tengah",
       f"{[ (x.get('rel'), x.get('doc_number')) for x in (rfq_db.get('refs') or []) ]}")

    # ══════════════════════════════════════════════════════════════════════
    head("P0-6 · Backfill relasi dokumen BERSIH (`would_add=0` DAN `skipped=0`)")
    bf = refs_backfill_dry_run()
    ok(bf.get("would_add") == 0 and bf.get("skipped") == 0,
       "backfill dry-run tidak menemukan tautan yang tertinggal maupun yang dilewatkan",
       f"{bf}")

    # ══════════════════════════════════════════════════════════════════════
    head("P0-7 · Gate SUNGGUHAN dijalankan (bukan ditiru)")
    rc, tail = run_gate("scripts/guardrails/verify_doc_origin.py")
    ok(rc == 0, "gate `INV-ORIG-01` HIJAU (satu definisi · sales dirunut · refs dua arah)",
       f"exit {rc} · {tail}")
    rc, tail = run_gate("scripts/guardrails/verify_doc_origin.py", "--self-test")
    ok(rc == 0, "`INV-ORIG-01 --self-test` membuktikan gate BISA memerah (bukti-merah)",
       f"exit {rc} · {tail}")
    rc, tail = run_gate("scripts/audit_doc_refs.py", "--strict")
    ok(rc == 0, "`INV-REF` HIJAU — PO mandiri TIDAK dituduh dokumen yatim",
       f"exit {rc} · {tail}")

    # ══════════════════════════════════════════════════════════════════════
    head("P0-8 · Data demo memang punya rantainya (bukan 'hijau tapi hampa')")
    demo_chain = list(db.purchase_orders.find(
        {"pr_id": {"$nin": ["", None]}, "id": {"$nin": created_po}},
        {"_id": 0, "po_number": 1, "pr_id": 1, "sales_name": 1, "line_codes": 1}))
    ok(len(demo_chain) >= 3,
       "≥3 rantai SO→PR→PO tersedia di data demo (papan PO punya isi untuk diklik)",
       f"{[(d['po_number'], d.get('sales_name')) for d in demo_chain]}")
    ok(all((d.get("sales_name") or "") for d in demo_chain),
       "setiap rantai demo membawa Nama Sales yang dirunut (bukan kosong)",
       f"{[d.get('sales_name') for d in demo_chain]}")
    nama_demo = {d.get("sales_name") for d in demo_chain}
    ok(len(nama_demo) >= 2,
       "data demo memuat ≥2 nama sales BERBEDA — membuktikan kolom mengikuti SO-nya",
       f"{sorted(nama_demo)}")

    # ══════════════════════════════════════════════════════════════════════
    head("P0-9 · Keputusan pemilik: PO lama DIBIARKAN kosong (tanpa backfill)")
    tanpa_asal = db.purchase_orders.count_documents(
        {"$or": [{"pr_id": {"$exists": False}}, {"pr_id": ""}]})
    ok(tanpa_asal > 0,
       "PO lama tetap tanpa `pr_id` — dan gate di atas tetap HIJAU (bukan pelanggaran)",
       f"{tanpa_asal} PO berdiri sendiri")
    bocor = db.purchase_orders.count_documents(
        {"sales_name": {"$nin": ["", None]},
         "$or": [{"pr_id": {"$exists": False}}, {"pr_id": ""}]})
    ok(bocor == 0,
       "nol PO yang memuat Nama Sales tanpa jejak dokumen (nama tidak dikarang)",
       f"{bocor} pelanggaran")

    # ══════════════════════════════════════════════════════════════════════
    head("P0-10 · CLEANUP + NOL RESIDU (diukur, bukan diklaim)")
    # Tugas gudang yang lahir dari PO POC ini WAJIB ikut dihapus: tanpa ini setiap
    # jalan-ulang menambah tugas inbound hantu ke papan operasi gudang.
    db.wms_tasks.delete_many({"po_id": {"$in": created_po}})
    db.purchase_orders.delete_many({"id": {"$in": created_po}})
    db.purchase_requisitions.delete_many({"id": {"$in": created_pr}})
    db.rfqs.delete_many({"id": {"$in": created_rfq}})
    # Jejak `restock_requests` yang ditanam DI PESANAN DEMO harus dicabut, kalau
    # tidak layar pesanan lama akan menampilkan riwayat permintaan yang PR-nya
    # sudah tidak ada (pelajaran POC FASE D: relasi hantu di dokumen milik demo).
    db.sales_orders.update_many(
        {"id": {"$in": touched_so}},
        {"$pull": {"restock_requests": {"pr_id": {"$in": created_pr}}}})
    db.sales_orders.update_many({"id": {"$in": touched_so}},
                                {"$unset": {"last_restock_note": ""}})
    for coll in ("purchase_orders", "purchase_requisitions", "rfqs", "sales_orders"):
        db[coll].update_many(
            {"refs.doc_id": {"$in": created_po + created_pr + created_rfq}},
            {"$pull": {"refs": {"doc_id": {"$in": created_po + created_pr + created_rfq}}}})
    # Audit, notifikasi & sesi yang lahir SELAMA POC dibuang dengan selisih id —
    # bukan menebak nama aksinya (`POST /auth/login` sendiri menulis 1 baris audit
    # + 1 sesi per akun).
    db.sessions.delete_many({"token": {"$in": TOKENS}})
    for coll, seen in (("audit_logs", audit_before), ("notifications", notif_before)):
        baru = {d["id"] for d in db[coll].find({}, {"_id": 0, "id": 1})} - seen
        if baru:
            db[coll].delete_many({"id": {"$in": list(baru)}})

    after = {c: db[c].count_documents({}) for c in WATCH}
    drift = {c: (before[c], after[c]) for c in WATCH if before[c] != after[c]}
    ok(not drift, "nol residu: jumlah dokumen tiap koleksi SAMA sebelum & sesudah POC",
       f"drift={drift}" if drift else f"{len(WATCH)} koleksi identik")
    sisa = db.sales_orders.count_documents(
        {"restock_requests.pr_id": {"$in": created_pr}})
    ok(sisa == 0, "nol jejak hantu: pesanan demo tidak menyimpan permintaan ke PR yang dihapus",
       f"{sisa} pesanan masih menyimpannya")
    bf2 = refs_backfill_dry_run()
    ok(bf2.get("would_add") == 0 and bf2.get("skipped") == 0,
       "sesudah pembersihan, backfill relasi tetap bersih (nol tautan menggantung)",
       f"{bf2}")

    print("\n\033[1m" + "=" * 78)
    warna = "\033[92m" if FAIL == 0 else "\033[91m"
    print(f"  HASIL: \033[92m{PASS} PASS\033[0m · {warna}{FAIL} FAIL\033[0m "
          f"dari {PASS + FAIL} pemeriksaan")
    if FAILED_LABELS:
        print("\033[91m  GAGAL:\033[0m")
        for lbl in FAILED_LABELS:
            print(f"   - {lbl}")
    print("=" * 78 + "\033[0m")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
