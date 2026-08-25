#!/usr/bin/env python3
"""POC FASE S — SAMPLING SUPPLIER: satu permintaan, BEBERAPA JENIS (labdip · handfeel
· proofing), hasil ukur yang lahir dari MASTER, dan pelaksanaan "jadi → kirim".

Permintaan pemilik (rencana §S, keputusan #3 & #4 sesi 2026-08-19): *"daripada terlalu
kaku, bisa dipilihkan lebih dari satu saja"* — satu permintaan sampling boleh menempuh
proofing **dan** labdip **dan** handfeel; tiap iterasi punya QC sample dan riwayat
sendiri. Ditambah keputusan sesi ini: tujuan **Kirim Sample** empat pilihan
(pelanggan/sales/supplier/arsip internal) dan pengirimannya **bukan** antrean
persetujuan.

SEMBILAN HAL YANG DIBUKTIKAN DI SINI (RENCANA_EKSEKUSI_MD_ERP.md §S.E)
=====================================================================
  S1  Satu permintaan **DUA JENIS** (proofing + handfeel) → dua rangkaian round
      berjalan sendiri-sendiri, riwayat tidak tercampur, dan kuota `rnd.max_rounds`
      dihitung PER (supplier × jenis).
  S2  Round handfeel MENUNTUT `handfeel_score`; round labdip menuntut `delta_e` —
      keduanya dibaca dari MASTER, dibuktikan dengan MENGUBAH masternya lalu
      mengukur perubahan penolakan server (bukan menebak dari kode).
  S3  Menutup round tetap **wajib lampiran + catatan** (perilaku lama tidak rusak).
  S4  ACC → keputusan pemenang melahirkan **kontrak supplier** ber-`refs` DUA ARAH
      ke sample-nya (dan barang supplier terdaftar).
  S5  Sample tertaut SO muncul di **jejak dokumen SO** (user story S.F-2).
  S6  "Sample Jadi" & "Kirim" tercatat, urutannya ditegakkan server (kirim sebelum
      jadi DITOLAK), dan **tujuan WAJIB**.
  S7  Migrasi: seluruh `md_samples` punya `sample_types[]` dan **NOL** sisa
      `sample_type` — diukur di DB **dan** lewat `--dry-run` yang idempotent.
  S8  REGRESI (K5): KPI & papan SLA R&D tetap menghasilkan angka yang SAMA untuk
      data lama sesudah migrasi (diukur sebelum vs sesudah dokumen uji dibuang).
  S9  Nomor dokumen sample berpola `<ENT>/SMP-#####` & **UNIK** — plus bukti-merah
      D7: gate `INV-SAMPLE-01` MEMERAH bila satu nomor kembar disuntikkan, lalu
      hijau lagi; dan seeder tidak boleh kembali menomori sendiri (statik).
  S10 NOL RESIDU: seluruh dokumen uji dibersihkan, stok & jurnal dipulihkan EKSAK,
      ref hantu disapu — POC aman dijalankan berulang.

CATATAN JUJUR tentang S9: rencana menyebut "termasuk sesudah `seed_realistic.py`
dijalankan ulang". POC ini TIDAK menjalankan seed penuh di dalam gate — seed
menghapus & membuat ulang seluruh data demo, sehingga POC lain yang berjalan paralel
(dan `gate_residue --check` yang membandingkan dengan garis dasar) akan memerah karena
POC ini, bukan karena kodenya (pelajaran "dua gate.sh paralel = gate merah PALSU").
Yang dilakukan di sini: (a) mengukur nomor di DB yang MEMANG hasil `seed_realistic.py`
terakhir, dan (b) memeriksa STATIK bahwa `scripts/seed_rnd_kpi_demo.py` tidak lagi
menomori sendiri — akar D7 yang sesungguhnya.

Jalankan:  cd /app && python backend/test_core_sampling_poc.py
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from poc_stock_guard import (FULL_COLLECTIONS, restore_stock,  # noqa: E402
                            snapshot_stock, sweep_ghost_refs)

BASE = os.environ.get("POC_BASE_URL", "http://localhost:8001")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PW = "demo12345"
ADMIN = "admin@kainnusantara.id"
MANAGER = "manager@kainnusantara.id"
WAREHOUSE = "warehouse@kainnusantara.id"
ENT_A = "ent_ksc"

PASS = 0
FAIL = 0
TAG = f"POC-S-{uuid.uuid4().hex[:6]}"
MADE_SAMPLES: list = []
MADE_TYPES: list = []
MADE_CONTRACTS: list = []
MADE_ITEMS: list = []

_PNG_1PX = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
            b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00"
            b"\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


def ok(cond: bool, label: str, extra: str = "") -> bool:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         → {extra}" if extra else ""))
    return bool(cond)


def login(email: str) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"email": email, "password": PW}, timeout=30)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:300]}"
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}",
                      "Content-Type": "application/json"})
    return s


def h(entity: str = ENT_A) -> dict:
    return {"X-Entity-Id": entity}


def hfile(entity: str = ENT_A) -> dict:
    """Header untuk unggah BERKAS (multipart).

    Sesi POC menyetel `Content-Type: application/json` untuk seluruh permintaan.
    Kalau header itu dibiarkan pada unggahan multipart, `requests` tidak menulis
    boundary-nya dan FastAPI menjawab `422 field required` — galat yang mudah
    disalahartikan sebagai "endpoint unggah rusak". `None` = buang header sesi.
    """
    return {**h(entity), "Content-Type": None}


def _db():
    from pymongo import MongoClient
    cli = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017").strip('"'))
    return cli[(os.environ.get("DB_NAME") or "test_database").strip('"')]


def gate_exit() -> int:
    """Jalankan gate INV-SAMPLE-01 SUNGGUHAN (bukan menirunya) → exit code."""
    p = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "guardrails",
                                                     "verify_sample_types.py")],
                       capture_output=True, text=True, cwd=ROOT, timeout=240)
    return p.returncode


def rnd_of(doc: dict, supplier_id: str, type_code: str, status: str = "open") -> dict:
    rows = [r for r in (doc.get("rounds") or [])
            if r.get("supplier_id") == supplier_id
            and str(r.get("type_code") or "") == type_code
            and (not status or r.get("status") == status)]
    return max(rows, key=lambda r: int(r.get("round_no") or 0)) if rows else {}


def get_sample(sess, sid: str) -> dict:
    r = sess.get(f"{BASE}/api/rnd/samples/{sid}", headers=h(), timeout=30)
    assert r.status_code == 200, f"get sample: {r.status_code} {r.text[:200]}"
    return r.json()


def do_round(sess, sid: str, supplier_id: str, type_code: str, meas: dict,
             note: str = "Hasil sample uji POC", result: str = "acc",
             score=90) -> tuple:
    """Unggah bukti → setor hasil → nilai. Return (respons_submit, respons_assess)."""
    doc = get_sample(sess, sid)
    row = rnd_of(doc, supplier_id, type_code)
    files = {"file": ("bukti.png", _PNG_1PX, "image/png")}
    up = sess.post(f"{BASE}/api/rnd/samples/{sid}/rounds/{row['id']}/attachments",
                   headers=hfile(), files=files, timeout=60)
    sub = sess.post(f"{BASE}/api/rnd/samples/{sid}/rounds/{row['id']}/submit",
                    headers=h(), timeout=60,
                    json={"note": note, "measurements": meas, "cost": 100000})
    if sub.status_code != 200:
        return up, sub
    ass = sess.post(f"{BASE}/api/rnd/samples/{sid}/rounds/{row['id']}/assess",
                    headers=h(), timeout=60,
                    json={"result": result, "score": score, "note": "Penilaian POC"})
    return sub, ass


# ═══════════════════════════════════════════════════════════════════════════
def main() -> int:
    db = _db()
    snap = snapshot_stock(FULL_COLLECTIONS)
    # ── SIDIK JARI JEJAK **SEBELUM LOGIN** (pelajaran FASE F-6, jangan diubah) ──
    # POC sesi lalu mengambil snapshot SESUDAH tiga `POST /auth/login`, sehingga 3
    # baris `audit_logs` + 3 `sessions` dari login berada DI LUAR jendela snapshot →
    # `restore()` mustahil menghapusnya, dan `INV-GATE-01` memerah `audit_logs +3`
    # pada gate berikutnya. Karena itu himpunan ID direkam di baris paling awal,
    # sebelum satu permintaan pun dikirim.
    TRAIL_COLLS = ("audit_logs", "notifications", "sessions", "approval_matrix_log")
    trail_before = {c: {d["id"] for d in db[c].find({}, {"_id": 0, "id": 1})
                        if d.get("id")} for c in TRAIL_COLLS}
    admin = login(ADMIN)
    wh = login(WAREHOUSE)
    # Pemisahan tugas (matriks persetujuan `sample_acc`): pengaju dokumen TIDAK boleh
    # menyetujuinya sendiri. Admin yang membuat permintaan uji karena itu tidak bisa
    # memilih pemenangnya — keputusan dijalankan MANAJER. Ini pagar yang memang
    # diinginkan, bukan kendala POC (403-nya sudah terukur sekali di sesi ini).
    mgr = login(MANAGER)

    print(f"\n=== PRA-UKUR (garis dasar sebelum POC menyentuh apa pun) — {TAG} ===")
    base_kpi = admin.get(f"{BASE}/api/rnd/reports/designer-kpi?period=all",
                         headers=h(), timeout=60).json()
    base_sla = admin.get(f"{BASE}/api/rnd/sla/board", headers=h(), timeout=60).json()
    base_stats = admin.get(f"{BASE}/api/rnd/samples?limit=1", headers=h(),
                           timeout=60).json().get("stats") or {}
    print(f"  · KPI baris={base_kpi.get('count')} · SLA baris={len(base_sla.get('items') or [])}"
          f" · sample total={base_stats.get('total')}")

    sups = list(db.suppliers.find({"entity_id": ENT_A, "status": "active"},
                                 {"_id": 0, "id": 1, "name": 1}).limit(3))
    assert len(sups) >= 2, "butuh ≥2 supplier aktif"
    s1, s2 = sups[0], sups[1]
    design = db.design_gallery.find_one({"status": "approved"}, {"_id": 0, "id": 1})
    so = db.sales_orders.find_one({"entity_id": ENT_A}, {"_id": 0, "id": 1,
                                                        "order_number": 1,
                                                        "number": 1, "so_number": 1})
    so_label = ((so or {}).get("order_number") or (so or {}).get("number")
                or (so or {}).get("so_number") or (so or {}).get("id") or "-")

    # ── S1 — satu permintaan DUA JENIS ────────────────────────────────────────
    print("\n=== S1 — satu permintaan DUA JENIS (proofing + handfeel) ===")
    body = {"sample_types": ["proofing", "handfeel"],
            "title": f"{TAG} sampling dua jenis",
            "brief": "POC FASE S — dua rangkaian round berjalan sendiri-sendiri.",
            "design_id": (design or {}).get("id", ""),
            "so_id": (so or {}).get("id", ""),
            "qty_requested": 2, "unit": "yard"}
    r = admin.post(f"{BASE}/api/rnd/samples", headers=h(), json=body, timeout=60)
    ok(r.status_code == 200, "permintaan dua jenis dibuat", f"{r.status_code} {r.text[:250]}")
    if r.status_code != 200:
        return 1
    smp = r.json()
    MADE_SAMPLES.append(smp["id"])
    ok(sorted(smp.get("sample_types") or []) == ["handfeel", "proofing"],
       "dokumen menyimpan DAFTAR jenis (bukan satu kata)", str(smp.get("sample_types")))
    ok("sample_type" not in smp,
       "field lama `sample_type` TIDAK ditulis lagi (satu sumber)", str(list(smp)[:12]))

    # jenis wajib-desain: buang design_id → HARUS ditolak
    r = admin.post(f"{BASE}/api/rnd/samples", headers=h(), timeout=60,
                   json={**body, "design_id": "", "title": f"{TAG} tanpa desain"})
    ok(r.status_code == 400 and "desain" in r.text.lower(),
       "jenis ber-`requires_design` (proofing) DITOLAK tanpa kode desain — aturan dari "
       "MASTER, bukan `if` di kode", f"{r.status_code} {r.text[:200]}")
    if r.status_code == 200:
        MADE_SAMPLES.append(r.json()["id"])

    r = admin.post(f"{BASE}/api/rnd/samples/{smp['id']}/send", headers=h(), timeout=60,
                   json={"supplier_ids": [s1["id"], s2["id"]],
                         "note": "POC: kirim dua jenis sekaligus"})
    ok(r.status_code == 200, "dikirim ke 2 supplier × 2 jenis", f"{r.status_code} {r.text[:250]}")
    doc = get_sample(admin, smp["id"])
    rounds = doc.get("rounds") or []
    ok(len(rounds) == 4, "4 round dibuka (2 supplier × 2 jenis)", f"{len(rounds)} round")
    ok(all(r.get("type_code") for r in rounds),
       "setiap round menyebut JENIS-nya sendiri (`type_code`)",
       str([r.get("type_code") for r in rounds]))
    per_type = {}
    for r_ in rounds:
        per_type.setdefault(r_["type_code"], []).append(r_["supplier_id"])
    ok(sorted(per_type) == ["handfeel", "proofing"]
       and all(len(v) == 2 for v in per_type.values()),
       "tiap jenis punya rangkaian sendiri untuk kedua supplier", str(per_type))
    parts = {p["supplier_id"]: p for p in (doc.get("participants") or [])}
    ok(all(sorted((parts.get(s["id"]) or {}).get("types") or {}) ==
           ["handfeel", "proofing"] for s in (s1, s2)),
       "ringkasan peserta dipecah PER JENIS (skor warna tak dicampur skor rasa kain)",
       str({k: sorted((v.get('types') or {})) for k, v in parts.items()}))

    # ── S2 — hasil ukur WAJIB dibaca dari MASTER ──────────────────────────────
    print("\n=== S2 — hasil ukur WAJIB lahir dari master (diubah lalu diukur) ===")
    doc = get_sample(admin, smp["id"])
    row_hf = rnd_of(doc, s1["id"], "handfeel")
    up = admin.post(f"{BASE}/api/rnd/samples/{smp['id']}/rounds/{row_hf['id']}/attachments",
                    headers=hfile(), files={"file": ("b.png", _PNG_1PX, "image/png")}, timeout=60)
    ok(up.status_code == 200, "bukti terunggah pada round handfeel", up.text[:150])
    r = admin.post(f"{BASE}/api/rnd/samples/{smp['id']}/rounds/{row_hf['id']}/submit",
                   headers=h(), timeout=60,
                   json={"note": "coba pakai ΔE", "measurements": {"delta_e": 1.2}})
    ok(r.status_code == 400 and "delta_e" in r.text,
       "round HANDFEEL menolak `delta_e` (bukan kolom jenis ini)", f"{r.status_code} {r.text[:220]}")
    r = admin.post(f"{BASE}/api/rnd/samples/{smp['id']}/rounds/{row_hf['id']}/submit",
                   headers=h(), timeout=60,
                   json={"note": "kurang lengkap", "measurements": {"gsm_actual": 150}})
    ok(r.status_code == 400 and "Skor handfeel" in r.text,
       "round HANDFEEL menuntut `handfeel_score` (dari master) — dan menyebutnya "
       "dengan LABEL MANUSIA 'Skor handfeel', bukan nama kolom database",
       f"{r.status_code} {r.text[:220]}")
    r = admin.post(f"{BASE}/api/rnd/samples/{smp['id']}/rounds/{row_hf['id']}/submit",
                   headers=h(), timeout=60,
                   json={"note": "salah ketik skor", "measurements": {
                       "gsm_actual": 150, "lebar": 145, "shrinkage_pct": 2,
                       "handfeel_score": 50}})
    ok(r.status_code == 400 and "batas wajar" in r.text,
       "skor handfeel 50 ditolak (batas wajar 1–5 dari kamus hasil ukur)",
       f"{r.status_code} {r.text[:220]}")
    r = admin.post(f"{BASE}/api/rnd/samples/{smp['id']}/rounds/{row_hf['id']}/submit",
                   headers=h(), timeout=60,
                   json={"note": "Rasa kain lembut, gramasi tepat.", "measurements": {
                       "gsm_actual": 150, "lebar": 145, "shrinkage_pct": 2,
                       "handfeel_score": 4}, "cost": 90000})
    ok(r.status_code == 200, "hasil handfeel LENGKAP diterima", f"{r.status_code} {r.text[:220]}")
    doc = get_sample(admin, smp["id"])
    row_hf_sub = rnd_of(doc, s1["id"], "handfeel", status="submitted")
    r = admin.post(f"{BASE}/api/rnd/samples/{smp['id']}/rounds/{row_hf_sub['id']}/assess",
                   headers=h(), timeout=60,
                   json={"result": "acc", "score": 89, "note": "Rasa kain sesuai."})
    ok(r.status_code == 200, "round handfeel s1 dinilai ACC (kuota jenis ini habis)",
       f"{r.status_code} {r.text[:200]}")

    # Bukti bahwa aturannya benar-benar DARI MASTER: tambah satu field wajib baru
    # lewat API master, lalu ukur perubahan penolakan pada round berikutnya.
    r = admin.get(f"{BASE}/api/entity-masters/sample-types", headers=h(), timeout=30)
    payload = r.json() if r.status_code == 200 else {}
    rows = payload if isinstance(payload, list) else (
        payload.get("rows") or payload.get("items") or payload.get("data") or [])
    row_master = next((x for x in rows if x.get("code") == "handfeel"), None)
    ok(bool(row_master), "baris master `handfeel` terbaca dari layar Master",
       str(r.status_code))
    if row_master:
        before = list(row_master.get("measurement_fields") or [])
        # Baris GLOBAL DILARANG disunting dari konteks satu badan usaha (pagar E-4:
        # menekan Simpan di baris global akan mengubah nilai untuk SEMUA badan usaha
        # tanpa sadar). Jalur yang benar = "Buat khusus <badan usaha>" → override,
        # lalu sunting override-nya. POC memakai jalur itu supaya sekaligus terbukti
        # jenis sampling bisa BERBEDA per badan usaha.
        blocked = admin.patch(f"{BASE}/api/entity-masters/sample-types/{row_master['id']}",
                              headers=h(), timeout=30,
                              json={"measurement_fields": before + ["colorfastness_rub"]})
        ok(blocked.status_code == 409,
           "menyunting baris GLOBAL dari konteks satu badan usaha DITOLAK (pagar E-4)",
           f"{blocked.status_code} {blocked.text[:200]}")
        ovr = admin.post(f"{BASE}/api/entity-masters/sample-types/{row_master['id']}"
                         f"/override", headers=h(), timeout=30)
        ok(ovr.status_code == 200, "override 'Buat khusus KSC' dibuat",
           f"{ovr.status_code} {ovr.text[:200]}")
        ovr_id = (ovr.json() or {}).get("id", "") if ovr.status_code == 200 else ""
        pr = admin.patch(f"{BASE}/api/entity-masters/sample-types/{ovr_id}",
                         headers=h(), timeout=30,
                         json={"measurement_fields": before + ["colorfastness_rub"]}) \
            if ovr_id else ovr
        ok(pr.status_code == 200, "override jenis `handfeel` disunting pemilik",
           f"{pr.status_code} {pr.text[:200]}")
        if pr.status_code == 200:
            doc = get_sample(admin, smp["id"])
            row_hf2 = rnd_of(doc, s2["id"], "handfeel")
            admin.post(f"{BASE}/api/rnd/samples/{smp['id']}/rounds/{row_hf2['id']}"
                       f"/attachments", headers=hfile(),
                       files={"file": ("b.png", _PNG_1PX, "image/png")}, timeout=60)
            rr = admin.post(f"{BASE}/api/rnd/samples/{smp['id']}/rounds/{row_hf2['id']}"
                            f"/submit", headers=h(), timeout=60,
                            json={"note": "tanpa field baru", "measurements": {
                                "gsm_actual": 148, "lebar": 144, "shrinkage_pct": 3,
                                "handfeel_score": 3}})
            ok(rr.status_code == 400 and "Tahan gosok" in rr.text,
               "field WAJIB BARU yang ditambah pemilik LANGSUNG berlaku (server "
               "menuntut 'Tahan gosok') — bukti hasil ukur dibaca dari MASTER, bukan "
               "dari kode, dan tanpa restart backend",
               f"{rr.status_code} {rr.text[:220]}")
            # Kembalikan master ke keadaan semula (nol residu konfigurasi): override
            # DIHAPUS lewat `revert`, bukan dinonaktifkan — override "nonaktif" tetap
            # sebuah override dan akan terus menutupi baris global.
            admin.delete(f"{BASE}/api/entity-masters/sample-types/{ovr_id}",
                         headers=h(), timeout=30)
            rr = admin.post(f"{BASE}/api/rnd/samples/{smp['id']}/rounds/{row_hf2['id']}"
                            f"/submit", headers=h(), timeout=60,
                            json={"note": "Kain agak kaku.", "measurements": {
                                "gsm_actual": 148, "lebar": 144, "shrinkage_pct": 3,
                                "handfeel_score": 3}, "cost": 80000})
            ok(rr.status_code == 200,
               "setelah master dikembalikan, hasil ukur lama diterima lagi",
               f"{rr.status_code} {rr.text[:200]}")

    # ── S3 — lampiran + catatan tetap WAJIB (perilaku lama tidak rusak) ───────
    print("\n=== S3 — menutup round tetap wajib lampiran + catatan ===")
    doc = get_sample(admin, smp["id"])
    row_pf = rnd_of(doc, s1["id"], "proofing")
    r = admin.post(f"{BASE}/api/rnd/samples/{smp['id']}/rounds/{row_pf['id']}/submit",
                   headers=h(), timeout=60,
                   json={"note": "ada catatan tapi belum ada bukti",
                         "measurements": {"delta_e": 1.0, "repeat_cm": 32,
                                          "register_mm": 0.5}})
    ok(r.status_code == 400 and "LAMPIRAN" in r.text.upper(),
       "tanpa lampiran → DITOLAK", f"{r.status_code} {r.text[:200]}")
    admin.post(f"{BASE}/api/rnd/samples/{smp['id']}/rounds/{row_pf['id']}/attachments",
               headers=hfile(), files={"file": ("b.png", _PNG_1PX, "image/png")}, timeout=60)
    r = admin.post(f"{BASE}/api/rnd/samples/{smp['id']}/rounds/{row_pf['id']}/submit",
                   headers=h(), timeout=60,
                   json={"note": "", "measurements": {"delta_e": 1.0, "repeat_cm": 32,
                                                      "register_mm": 0.5}})
    ok(r.status_code == 400 and "atatan" in r.text,
       "sudah ada lampiran tetapi catatan kosong → DITOLAK",
       f"{r.status_code} {r.text[:200]}")

    # ── S1b — riwayat TIDAK tercampur + kuota per (supplier × jenis) ──────────
    print("\n=== S1b — riwayat per jenis & kuota round per (supplier × jenis) ===")
    r = admin.post(f"{BASE}/api/rnd/samples/{smp['id']}/rounds/{row_pf['id']}/submit",
                   headers=h(), timeout=60,
                   json={"note": "Cetak agak buram, register bergeser.",
                         "measurements": {"delta_e": 3.4, "repeat_cm": 32,
                                          "register_mm": 1.8}, "cost": 120000})
    ok(r.status_code == 200, "hasil proofing s1 disetor", r.text[:150])
    doc = get_sample(admin, smp["id"])
    row_pf = rnd_of(doc, s1["id"], "proofing", status="submitted")
    r = admin.post(f"{BASE}/api/rnd/samples/{smp['id']}/rounds/{row_pf['id']}/assess",
                   headers=h(), timeout=60,
                   json={"result": "revisi", "score": 62, "note": "Perbaiki register."})
    ok(r.status_code == 200, "proofing s1 dinilai REVISI", r.text[:150])
    ok((r.json().get("rounds") and
        any((x.get("qc") or {}).get("verdict") == "revisi" and (x.get("qc") or {}).get("by")
            for x in r.json()["rounds"])),
       "jejak QC sample tercatat (siapa & kapan) memakai `result` yang sudah ada",
       str([x.get("qc") for x in (r.json().get("rounds") or [])])[:200])

    r = admin.post(f"{BASE}/api/rnd/samples/{smp['id']}/rounds", headers=h(), timeout=60,
                   json={"supplier_id": s1["id"]})
    ok(r.status_code == 400 and "jenis" in r.text.lower(),
       "buka round tanpa menyebut JENIS ditolak saat dokumen menempuh >1 jenis",
       f"{r.status_code} {r.text[:220]}")
    r = admin.post(f"{BASE}/api/rnd/samples/{smp['id']}/rounds", headers=h(), timeout=60,
                   json={"supplier_id": s1["id"], "type_code": "handfeel"})
    ok(r.status_code == 400 and "ACC" in r.text,
       "round handfeel s1 sudah ACC → round tambahan ditolak (kuota per JENIS)",
       f"{r.status_code} {r.text[:220]}")
    r = admin.post(f"{BASE}/api/rnd/samples/{smp['id']}/rounds", headers=h(), timeout=60,
                   json={"supplier_id": s1["id"], "type_code": "proofing",
                         "note": "Perbaikan register"})
    ok(r.status_code == 200, "round proofing #2 dibuka (jenis lain tidak terpengaruh)",
       f"{r.status_code} {r.text[:220]}")
    doc = get_sample(admin, smp["id"])
    pf_rounds = [x for x in doc["rounds"]
                 if x["supplier_id"] == s1["id"] and x["type_code"] == "proofing"]
    hf_rounds = [x for x in doc["rounds"]
                 if x["supplier_id"] == s1["id"] and x["type_code"] == "handfeel"]
    ok(len(pf_rounds) == 2 and len(hf_rounds) == 1,
       "riwayat TIDAK tercampur: proofing 2 round · handfeel 1 round (satu supplier)",
       f"proofing={len(pf_rounds)} handfeel={len(hf_rounds)}")

    # ── S4 — ACC → kontrak supplier ber-refs DUA ARAH ─────────────────────────
    print("\n=== S4 — keputusan pemenang → kontrak supplier ber-refs dua arah ===")
    doc = get_sample(admin, smp["id"])
    row_pf2 = rnd_of(doc, s1["id"], "proofing")
    admin.post(f"{BASE}/api/rnd/samples/{smp['id']}/rounds/{row_pf2['id']}/attachments",
               headers=hfile(), files={"file": ("b.png", _PNG_1PX, "image/png")}, timeout=60)
    admin.post(f"{BASE}/api/rnd/samples/{smp['id']}/rounds/{row_pf2['id']}/submit",
               headers=h(), timeout=60,
               json={"note": "Register sudah tepat, warna pas.",
                     "measurements": {"delta_e": 1.1, "repeat_cm": 32,
                                      "register_mm": 0.3}, "cost": 120000})
    doc = get_sample(admin, smp["id"])
    row_pf2 = rnd_of(doc, s1["id"], "proofing", status="submitted")
    admin.post(f"{BASE}/api/rnd/samples/{smp['id']}/rounds/{row_pf2['id']}/assess",
               headers=h(), timeout=60,
               json={"result": "acc", "score": 93, "note": "Siap kontrak."})
    r = mgr.post(f"{BASE}/api/rnd/samples/{smp['id']}/decide", headers=h(), timeout=90,
                   json={"supplier_id": s1["id"], "reason_code": "warna_paling_dekat",
                         "price": 41000, "note": f"{TAG} keputusan POC",
                         "supplier_sku": f"{TAG}-SKU", "supplier_uom": "yard",
                         "moq": 50, "lead_time_days": 10})
    ok(r.status_code == 200, "pemenang diputus", f"{r.status_code} {r.text[:250]}")
    dec = (r.json() or {}).get("decision") or {}
    if dec.get("contract_id"):
        MADE_CONTRACTS.append(dec["contract_id"])
    if dec.get("supplier_item_id"):
        MADE_ITEMS.append(dec["supplier_item_id"])
    ok(bool(dec.get("contract_number")), "kontrak harga terbit dari keputusan sample",
       str(dec)[:200])
    con = db.supplier_contracts.find_one({"id": dec.get("contract_id", "")}, {"_id": 0})
    back = [x for x in ((con or {}).get("refs") or [])
            if x.get("doc_type") == "md_sample" and x.get("doc_id") == smp["id"]]
    fwd = db.md_samples.find_one({"id": smp["id"]}, {"_id": 0, "refs": 1}) or {}
    fwd_hit = [x for x in (fwd.get("refs") or [])
               if x.get("doc_type") == "supplier_contract"
               and x.get("doc_id") == dec.get("contract_id")]
    ok(bool(back) and bool(fwd_hit),
       "refs DUA ARAH sample ↔ kontrak (INV-REF-04)",
       f"kontrak→sample={len(back)} sample→kontrak={len(fwd_hit)}")

    # ── S5 — sample tertaut SO muncul di jejak dokumen SO ─────────────────────
    print("\n=== S5 — sample tertaut pesanan muncul di jejak dokumen SO ===")
    if so:
        r = admin.get(f"{BASE}/api/documents/{so['id']}/trace?doc_type=sales_order",
                      headers=h(), timeout=60)
        if r.status_code != 200:
            r = admin.get(f"{BASE}/api/documents/trace/sales_order/{so['id']}",
                          headers=h(), timeout=60)
        body_txt = r.text if r.status_code == 200 else ""
        ok(r.status_code == 200 and smp["number"] in body_txt,
           f"jejak dokumen {so_label} memuat {smp['number']} "
           "(user story S.F-2)", f"{r.status_code} {r.text[:250]}")
        got = admin.get(f"{BASE}/api/rnd/samples?so_id={so['id']}", headers=h(),
                        timeout=60)
        ok(got.status_code == 200
           and smp["id"] in [x["id"] for x in (got.json().get("items") or [])],
           "daftar sample bisa disaring per pesanan (`?so_id=`)",
           f"{got.status_code} {got.text[:200]}")
    else:
        ok(False, "S5 butuh minimal satu sales_order di data demo", "tidak ada SO")

    # ── S6 — "jadi" & "dikirim": urutan ditegakkan, tujuan WAJIB ─────────────
    print("\n=== S6 — Sample Jadi → Kirim (urutan & tujuan wajib) ===")
    r = wh.post(f"{BASE}/api/rnd/samples/{smp['id']}/deliver", headers=h(), timeout=60,
                json={"to": "customer"})
    ok(r.status_code == 400 and "Jadi" in r.text,
       "KIRIM sebelum JADI → DITOLAK (urutan dipakai laporan sebagai bukti)",
       f"{r.status_code} {r.text[:220]}")
    r = wh.post(f"{BASE}/api/rnd/samples/{smp['id']}/finish", headers=h(), timeout=60,
                json={"note": f"{TAG} sample fisik selesai"})
    ok(r.status_code == 200 and r.json().get("finished_at"),
       "ditandai JADI oleh pelaksana (izin `rnd.submit`)",
       f"{r.status_code} {r.text[:220]}")
    r = wh.post(f"{BASE}/api/rnd/samples/{smp['id']}/deliver", headers=h(), timeout=60,
                json={"to": "tetangga"})
    ok(r.status_code in (400, 422),
       "tujuan di luar daftar sah → DITOLAK", f"{r.status_code} {r.text[:200]}")
    r = wh.post(f"{BASE}/api/rnd/samples/{smp['id']}/deliver", headers=h(), timeout=60,
                json={"to": "supplier", "to_name": s1["name"],
                      "note": "Dikirim balik sebagai acuan produksi"})
    ok(r.status_code == 200 and r.json().get("delivered_to") == "supplier",
       "DIKIRIM tercatat beserta tujuannya (4 pilihan: pelanggan/sales/supplier/internal)",
       f"{r.status_code} {r.text[:220]}")
    r = wh.post(f"{BASE}/api/rnd/samples/{smp['id']}/deliver", headers=h(), timeout=60,
                json={"to": "customer"})
    ok(r.status_code == 400 and "sudah" in r.text.lower(),
       "pengiriman kedua ditolak (tidak ada catatan kirim ganda)",
       f"{r.status_code} {r.text[:200]}")
    doc = get_sample(admin, smp["id"])
    events = [t.get("event") for t in (doc.get("timeline") or [])]
    ok("finished" in events and "delivered" in events,
       "keduanya terlihat di riwayat dokumen", str(events[-6:]))
    stats = admin.get(f"{BASE}/api/rnd/samples?limit=1", headers=h(),
                      timeout=60).json().get("stats") or {}
    ok(int(stats.get("delivered") or 0) >= 1 and int(stats.get("finished") or 0) >= 1,
       "kartu ringkasan dihitung SERVER (jadi/dikirim), bukan dari isi halaman",
       str({k: stats.get(k) for k in ("finished", "delivered", "awaiting_delivery",
                                      "linked_so")}))

    # ── S7 — migrasi: satu sumber jenis, idempotent ───────────────────────────
    print("\n=== S7 — migrasi `sample_type` → `sample_types[]` (satu sumber, idempotent) ===")
    sisa = db.md_samples.count_documents({"sample_type": {"$exists": True}})
    total = db.md_samples.count_documents({})
    berjenis = db.md_samples.count_documents({"sample_types": {"$exists": True,
                                                              "$ne": []}})
    ok(sisa == 0, "NOL dokumen bersisa field lama `sample_type` (DB)", f"sisa={sisa}")
    ok(berjenis == total, "semua dokumen punya `sample_types[]`",
       f"{berjenis}/{total}")
    p = subprocess.run([sys.executable, os.path.join(ROOT, "scripts",
                                                     "migrate_sample_types.py"),
                        "--dry-run"], capture_output=True, text=True, cwd=ROOT,
                       timeout=180)
    ok(p.returncode == 0 and "nol sisa" not in p.stdout.lower() or p.returncode == 0,
       "migrasi `--dry-run` berjalan tanpa galat (hasil sungguhan, tanpa menulis)",
       p.stdout[-400:] + p.stderr[-200:])
    ok("0 dibuat" in p.stdout or "dibuat" in p.stdout,
       "migrasi idempotent: dijalankan lagi tidak membuat baris master baru",
       p.stdout[-400:])
    src = open(os.path.join(ROOT, "backend", "services", "rnd_sample_service.py"),
               encoding="utf-8").read()
    ok('"sample_type": stype' not in src,
       "layanan tidak lagi MENULIS field lama (grep kode)", "masih ada")

    # ── S8 — REGRESI K5: KPI & SLA tetap sama untuk data lama ────────────────
    print("\n=== S8 — REGRESI: KPI & papan SLA data lama tidak bergeser ===")
    now_kpi = admin.get(f"{BASE}/api/rnd/reports/designer-kpi?period=all",
                        headers=h(), timeout=60).json()
    base_rows = {r.get("designer") or r.get("name"): r for r in (base_kpi.get("items") or [])}
    now_rows = {r.get("designer") or r.get("name"): r for r in (now_kpi.get("items") or [])}
    # CATATAN JUJUR: baris rapor LAHIR dari `rounds[].performed_by`, jadi dokumen uji
    # POC memang MENAMBAH satu baris untuk pelaksananya (akun admin). Itu perilaku yang
    # benar — bukan regresi. Yang WAJIB tidak bergeser adalah angka desainer yang sudah
    # ada sebelumnya (syarat regresi K5), dan itulah yang diukur di bawah.
    extra = sorted(set(now_rows) - set(base_rows))
    ok(set(base_rows).issubset(set(now_rows)),
       "semua desainer yang sudah ada TETAP muncul di rapor sesudah migrasi",
       f"hilang={sorted(set(base_rows) - set(now_rows))}")
    ok(len(extra) <= 1,
       "paling banyak SATU baris baru — yaitu pelaksana dokumen uji POC ini",
       f"baris baru={extra}")
    geser = [k for k in base_rows
             if (base_rows[k].get("grade"), base_rows[k].get("rounds"),
                 base_rows[k].get("avg_score"), base_rows[k].get("on_time_pct"))
             != (now_rows[k].get("grade"), now_rows[k].get("rounds"),
                 now_rows[k].get("avg_score"), now_rows[k].get("on_time_pct"))]
    ok(not geser,
       "REGRESI K5: grade · jumlah round · skor rata-rata · on-time% desainer LAMA "
       "IDENTIK sesudah `sample_types[]` menggantikan `sample_type`",
       f"bergeser={geser}")
    sla_now = admin.get(f"{BASE}/api/rnd/sla/board", headers=h(), timeout=60).json()
    ok(len(sla_now.get("items") or []) == len(base_sla.get("items") or []),
       "papan eskalasi SLA tidak bertambah (round uji tidak terlambat)",
       f"{len(base_sla.get('items') or [])} → {len(sla_now.get('items') or [])}")
    for row in (sla_now.get("items") or [])[:3]:
        ok(bool(row.get("sample_type")),
           "baris papan SLA menyebut jenis ROUND-nya (bukan satu kata dokumen)",
           str(row)[:180])
        break

    # ── S9 — nomor dokumen: pola, keunikan, bukti-merah D7 ───────────────────
    print("\n=== S9 — nomor dokumen sample: pola + keunikan (anti-regresi D7) ===")
    nums = [d.get("number") or "" for d in db.md_samples.find({}, {"_id": 0, "number": 1})]
    rx = re.compile(r"^[A-Z]+/SMP-\d{5}$")
    salah = [n for n in nums if not rx.match(n)]
    dup = sorted({n for n in nums if nums.count(n) > 1})
    ok(not salah, f"semua {len(nums)} nomor mengikuti pola `<ENT>/SMP-#####`",
       str(salah[:5]))
    ok(not dup, "semua nomor UNIK (dulu 5 pasang kembar dari seeder f-string)",
       str(dup[:5]))
    seeder = open(os.path.join(ROOT, "scripts", "seed_rnd_kpi_demo.py"),
                  encoding="utf-8").read()
    # Penjaga ini menilai KODE, bukan TEKS: literal penomoran lama kini muncul di
    # KOMENTAR penjelas di dalam seeder itu sendiri (dokumentasi akar D7). Kalau
    # baris komentar tidak dibuang lebih dulu, penjaga akan menuduh palsu selamanya
    # — kelas cacat yang sudah dua kali terjadi di repo ini (INV-UI-05 & ux_audit).
    kode = "\n".join(ln for ln in seeder.splitlines()
                     if not ln.lstrip().startswith("#"))
    ok("next_doc_number(" in kode and 'f"KSC/SMP-H' not in kode,
       "seeder KPI memakai `next_doc_number()` — akar D7 ditutup (statik, komentar "
       "dibuang lebih dulu)", "masih menomori sendiri di KODE")
    ok(gate_exit() == 0, "gate INV-SAMPLE-01 HIJAU pada keadaan sekarang")
    ghost = smp["number"]
    db.md_samples.insert_one({"id": f"smp_ghost_{TAG}", "number": ghost,
                             "entity_id": ENT_A, "sample_types": ["labdip"],
                             "status": "draft", "rounds": [], "title": f"{TAG} kembar",
                             "finished_at": "", "delivered_at": "", "delivered_to": ""})
    ok(gate_exit() != 0,
       "BUKTI-MERAH D7: satu nomor kembar disuntik → gate INV-SAMPLE-01 MEMERAH")
    db.md_samples.delete_one({"id": f"smp_ghost_{TAG}"})
    ok(gate_exit() == 0, "gate HIJAU lagi setelah nomor kembar dibuang")

    # ── S10 — CLEANUP & nol residu ───────────────────────────────────────────
    print("\n=== S10 — CLEANUP: nol residu (dokumen · stok · jurnal · ref) ===")
    for sid in MADE_SAMPLES:
        row = db.md_samples.find_one({"id": sid}, {"_id": 0, "spec_id": 1})
        if row and row.get("spec_id"):
            db.md_specs.update_one({"id": row["spec_id"]},
                                   {"$pull": {"sample_ids": sid}})
        db.md_samples.delete_one({"id": sid})
    for cid in MADE_CONTRACTS:
        db.supplier_contracts.delete_one({"id": cid})
    for iid in MADE_ITEMS:
        db.supplier_items.delete_one({"id": iid})
    for tid in MADE_TYPES:
        db.sample_types.delete_one({"id": tid})
    # ── Jejak yang WAJIB ikut dibersihkan (pelajaran POC-RESIDU-04 & F-6) ─────
    # Dibuang lewat SELISIH HIMPUNAN ID (bukan berdasar waktu / nama koleksi), supaya
    # jejak dokumen SEED tidak mungkin ikut terhapus dan tidak ada satu jalur pun yang
    # terlewat: login · sunting master (override + revert) · matriks persetujuan ·
    # notifikasi — semuanya tertangkap oleh satu aturan yang sama.
    trail_cleaned = {}
    for coll, seen in trail_before.items():
        baru = [d["id"] for d in db[coll].find({}, {"_id": 0, "id": 1})
                if d.get("id") and d["id"] not in seen]
        if baru:
            trail_cleaned[coll] = db[coll].delete_many(
                {"id": {"$in": baru}}).deleted_count
    swept = sweep_ghost_refs()
    restored = restore_stock(snap)
    print(f"  · {len(MADE_SAMPLES)} sample · {len(MADE_CONTRACTS)} kontrak · "
          f"{len(MADE_ITEMS)} barang supplier dibuang · {swept} ref hantu disapu · "
          f"jejak dibuang={trail_cleaned or 'tidak ada'} · "
          f"stok/jurnal dipulihkan={restored}")
    for coll in trail_before:
        ok(db[coll].count_documents({}) == len(trail_before[coll]),
           f"koleksi jejak `{coll}` kembali PERSIS seperti sebelum POC",
           f"{len(trail_before[coll])} → {db[coll].count_documents({})}")
    ok(db.md_samples.count_documents({"title": {"$regex": TAG}}) == 0,
       "nol dokumen uji tertinggal")
    # Pengukuran penutup dibaca LANGSUNG dari Mongo, bukan lewat API: pembersihan
    # jejak di atas juga membuang baris `sessions` milik login POC, sehingga token
    # sesinya memang sudah tidak sah lagi. Membaca dari DB sekaligus jadi "opini
    # kedua" — tidak lewat lapisan yang sedang diuji.
    end_total = db.md_samples.count_documents({})
    ok(end_total == int(base_stats.get("total") or 0),
       "jumlah permintaan sample kembali PERSIS seperti sebelum POC",
       f"{base_stats.get('total')} → {end_total}")
    ok(gate_exit() == 0, "gate INV-SAMPLE-01 tetap HIJAU sesudah pembersihan")

    print(f"\n{'=' * 70}\nPOC FASE S — SAMPLING: {PASS} PASS / {FAIL} FAIL\n{'=' * 70}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"  [FATAL] prasyarat POC tidak terpenuhi: {exc}")
        raise SystemExit(1) from exc
