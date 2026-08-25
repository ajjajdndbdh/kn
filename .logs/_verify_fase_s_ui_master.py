#!/usr/bin/env python3
"""Bukti kecil FASE S (frontend): jenis sampling yang DITAMBAH pemilik langsung
terbaca oleh pemilih & label layar — tanpa satu baris kode frontend berubah.

Kenapa perlu: sebelum FASE S label jenis adalah peta hardcode di `rndMeta.js`, jadi
jenis baru muncul di layar sebagai kode teknis (`wash_test`). Pemeriksaan ini
mengukur ENDPOINT yang dibaca layar (`/api/rnd/sample-types` & `/api/rnd/meta`),
lalu MEMBERSIHKAN jejaknya sendiri (nol residu — master kembali seperti semula).
"""
import os
import sys

import requests

BASE = os.environ.get("POC_BASE_URL", "http://localhost:8001")
ADMIN = "admin@kainnusantara.id"
PW = "demo12345"
ENT = "ent_ksc"
CODE = "wash_test_probe"
PASS = FAIL = 0


def ok(cond, label, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         → {extra}" if extra else ""))
    return bool(cond)


s = requests.Session()
r = s.post(f"{BASE}/api/auth/login", json={"email": ADMIN, "password": PW}, timeout=30)
r.raise_for_status()
s.headers.update({"Authorization": f"Bearer {r.json()['token']}",
                  "Content-Type": "application/json", "X-Entity-Id": ENT})

before = s.get(f"{BASE}/api/rnd/sample-types", timeout=30).json()
created_id = ""
try:
    r = s.post(f"{BASE}/api/entity-masters/sample-types", timeout=30, json={
        "code": CODE, "name": "Uji Cuci (probe)", "seq": 90, "active": True,
        "requires_design": False, "measurement_fields": ["shrinkage_pct"],
        "notes": "Dibuat pemeriksaan FASE S — dihapus lagi di akhir.",
        "entity_id": ENT})
    ok(r.status_code in (200, 201), f"master jenis baru dibuat lewat API ({r.status_code})",
       r.text[:200])
    created_id = (r.json() or {}).get("id", "") if r.status_code in (200, 201) else ""

    after = s.get(f"{BASE}/api/rnd/sample-types", timeout=30).json()
    hit = next((t for t in after if t.get("value") == CODE), None)
    ok(bool(hit), "pemilih jenis (`/api/rnd/sample-types`) MEMUAT jenis baru")
    ok(bool(hit) and hit.get("label") == "Uji Cuci (probe)",
       "labelnya NAMA dari master (bukan kode teknis `wash_test_probe`)",
       str(hit))
    ok(bool(hit) and hit.get("measurement_fields") == ["shrinkage_pct"],
       "hasil ukur wajib ikut terbawa ke layar (form setor hasil)", str(hit))

    meta = s.get(f"{BASE}/api/rnd/meta", timeout=30).json()
    ok(any(t.get("value") == CODE for t in (meta.get("sample_types") or [])),
       "`/api/rnd/meta` (dipakai layar Spesifikasi) ikut memuat jenis baru")
    ok(len(after) == len(before) + 1,
       f"jumlah jenis bertambah TEPAT satu ({len(before)} → {len(after)})")
finally:
    if created_id:
        d = s.delete(f"{BASE}/api/entity-masters/sample-types/{created_id}", timeout=30)
        if d.status_code not in (200, 204):
            from pymongo import MongoClient
            cli = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017")
                              .strip('"'))
            cli[(os.environ.get("DB_NAME") or "test_database").strip('"')]["sample_types"] \
                .delete_one({"id": created_id})
    final = s.get(f"{BASE}/api/rnd/sample-types", timeout=30).json()
    ok(len(final) == len(before) and all(t.get("value") != CODE for t in final),
       "NOL RESIDU: master jenis kembali persis seperti sebelum pemeriksaan",
       f"{len(before)} → {len(final)}")

print(f"\nFASE S · bukti master→layar: {PASS} PASS / {FAIL} FAIL")
sys.exit(1 if FAIL else 0)
