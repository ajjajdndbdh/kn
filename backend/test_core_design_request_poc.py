#!/usr/bin/env python3
"""POC FASE D — **PERMINTAAN DESAIN** (`<ENT>/DSR-#####`) + peran ke-7 `designer`.

Rencana: `RENCANA_EKSEKUSI_MD_ERP.md` §D.D. Keputusan pemilik yang mengikat:
desainer menjadi **peran ber-AKUN** supaya alur "Rina mengunggah artwork-nya sendiri"
nyata (bukan diwakilkan admin), dan wilayahnya SENGAJA sempit.

APA YANG DIBUKTIKAN DI SINI (dan kenapa masing-masing perlu dibuktikan)
=======================================================================
  D1  **Alur ujung-ke-ujung**: MD membuat permintaan dari SO pelanggan → menugaskan
      desainer + tenggat → desainer menandai mulai → mengunggah artwork ke Galeri →
      menyerahkan → manajer **minta revisi ber-ALASAN** → desainer menyerahkan lagi →
      manajer **ACC**. Setiap perpindahan meninggalkan baris `history`.
  D2  **Alasan revisi WAJIB** (dan batal juga). Revisi tanpa alasan adalah cara
      termurah membuat desainer mengulang kerja tanpa tahu apa yang salah — jadi
      server MENOLAK, bukan layar yang mengingatkan.
  D3  **Serah hasil harus menunjuk artwork NYATA** di galeri badan usaha yang SAMA.
      Tanpa pagar ini, "sudah dikirim lewat email" menjadi status resmi dan
      `gallery_ids[]` kosong selamanya (rapor bintang ikut kosong tanpa sebab).
  D4  **Rapor = hitung-ulang MANDIRI dari MongoDB.** Angka rapor dihitung ulang di
      POC ini dengan rumus yang ditulis TERPISAH (opini kedua). Kalau rapor diketik
      atau dihitung dua kali dengan dua rumus, keduanya tidak akan setuju.
  D5  **Masuk antrean keputusan & KPI beranda**: `status="delivered"` wajib terhitung
      di `/api/home/*` dan Pusat Persetujuan, DAN gate `INV-HOME-01`/`INV-APPR-01`
      tetap HIJAU (dijalankan sungguhan di sini, bukan ditiru).
  D6  **Jejak `refs` dua arah**: SO → permintaan (panel "permintaan desain untuk
      pesanan ini") dan permintaan → SO. Galeri menyimpan tautan balik
      `request_id`/`request_number`.
  D7  **Pagar badan usaha**: mode gabungan (`X-Entity-Id: all`) MENOLAK pembuatan
      dengan 409 + kalimat menuntun (INV-ENTITY-02), dan permintaan PT lain 403.
  D8  **PERAN KE-7 — wilayah sempit yang JUJUR**:
        a. desainer hanya melihat permintaan yang DITUGASKAN kepadanya (IDOR 403);
        b. desainer TIDAK boleh `assign` / `approve` / `reject` / `cancel` (403);
        c. rapor lintas desainer 403 untuk desainer (menilai orang = wewenang atasan);
        d. tetapi **`/design/reports/mine` 200** — angka DIRINYA, dan responsnya
           TIDAK memuat satu nama rekan pun (pola privasi PS-18).
      (d) lahir di sesi FASE D: tanpanya tab rapor hanya bisa 403 untuk desainer =
      **panel mati**, dan `audit_sales_roles_ux` memang memerah karenanya.
  D9  **Daftar peran tidak di-hardcode lagi.** `check_nav_map.py` pernah CRASH
      `KeyError: 'designer'` karena `ROLES` ditulis tangan (6 nama) sementara
      beranda peran dibaca dari SSOT. Di sini gate-nya dijalankan sungguhan DAN
      dibuktikan bahwa ia MEMBACA peran ke-7 (bukan kebetulan hijau).
  D10 **NOL RESIDU**: seluruh dokumen yang POC ini buat dihapus, dan jumlah dokumen
      tiap koleksi tersentuh diukur "sebelum == sesudah". POC yang berakhir "0 FAIL"
      tidak membuktikan nol residu kalau ia tidak pernah memeriksanya (pelajaran
      FASE T). POC ini aman dijalankan berulang.

Jalankan:  cd /app && python backend/test_core_design_request_poc.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone

import requests

BASE = os.environ.get("POC_BASE_URL", "http://localhost:8001")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PW = "demo12345"
ADMIN = "admin@kainnusantara.id"
MANAGER = "manager@kainnusantara.id"
DESIGNER = "designer@kainnusantara.id"
SALES = "sales@kainnusantara.id"
ENT_A = "ent_ksc"
ENT_B = "ent_kanda"

#: Koleksi yang alur ini boleh menyentuh — dipakai pengukuran nol residu (D10).
#: `sales_orders` ikut dipantau karena penautan `refs` dua arah MENYUNTING pesanan
#: sumbernya (menambah satu entri `refs[]`); tanpa memulihkannya, POC ini akan
#: menumpuk relasi hantu setiap kali dijalankan.
WATCH = ("design_requests", "design_gallery", "audit_logs", "notifications")

#: Token sesi yang POC ini buat — dihapus di CLEANUP (login menulis `sessions`).
TOKENS: list[str] = []

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
    s.headers.update({"Authorization": f"Bearer {tok}",
                      "Content-Type": "application/json"})
    return s


def h(entity: str) -> dict:
    return {"X-Entity-Id": entity}


def _db():
    from pymongo import MongoClient
    cli = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    return cli[os.environ.get("DB_NAME", "test_database")]


def run_gate(rel_path: str) -> tuple[int, str]:
    """Jalankan gate SUNGGUHAN (bukan menirunya) → (exit code, ekor keluaran)."""
    p = subprocess.run([sys.executable, os.path.join(ROOT, rel_path)],
                       capture_output=True, text=True, cwd=ROOT, timeout=300)
    return p.returncode, (p.stdout or "")[-400:]


def days_from_now(n: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=n)).strftime("%Y-%m-%d")


# ═══════════════════════════════════════════════════════════════════════════
def main() -> int:  # noqa: C901 — POC linear supaya terbaca sebagai bukti
    tag = uuid.uuid4().hex[:6]
    db = _db()
    before = {c: db[c].count_documents({}) for c in WATCH}
    # Sidik jari audit DIAMBIL SEBELUM login: `POST /auth/login` sendiri menulis satu
    # baris `login` + satu `sessions` per akun. POC yang lupa ini akan "0 FAIL" tetapi
    # menggelembungkan data demo +4 baris setiap kali gate dijalankan (pelajaran E-8).
    audit_before_ids = {d["id"] for d in db.audit_logs.find({}, {"_id": 0, "id": 1})}
    created_dsr: list[str] = []
    created_gallery: list[str] = []

    adm = login(ADMIN)
    mgr = login(MANAGER)
    dsg = login(DESIGNER)
    sal = login(SALES)

    print("\033[1m" + "=" * 78)
    print("  POC FASE D — PERMINTAAN DESAIN + peran ke-7 `designer`")
    print("=" * 78 + "\033[0m")

    # ── prasyarat: SO pelanggan di PT A + akun desainer ──────────────────────
    head("0 · Prasyarat (kalau ini gagal, sisanya hampa)")
    r = adm.get(f"{BASE}/api/sales-orders", headers=h(ENT_A), timeout=30)
    orders = r.json() if isinstance(r.json(), list) else (r.json().get("items") or [])
    so = next((o for o in orders if (o.get("entity_id") or "") == ENT_A), None)
    ok(so is not None, "ada pesanan pelanggan di PT A untuk jadi sumber permintaan",
       f"HTTP {r.status_code} · {len(orders)} pesanan")
    if not so:
        return 1
    so_id = so["id"]
    so_number = so.get("number") or so.get("order_number") or ""

    meta = dsg.get(f"{BASE}/api/design-requests/meta", headers=h(ENT_A), timeout=30)
    mj = meta.json() if meta.status_code == 200 else {}
    ok(meta.status_code == 200 and mj.get("role") == "designer" and mj.get("own_only") is True,
       "desainer membaca meta layar & ditandai `own_only` (hanya tugasnya)",
       f"HTTP {meta.status_code} · role={mj.get('role')} own_only={mj.get('own_only')}")
    designer_row = next((d for d in (mj.get("designers") or [])
                         if d.get("email") == DESIGNER), None)
    ok(designer_row is not None and designer_row.get("has_account") is True,
       "desainer ber-AKUN muncul di daftar orang yang bisa ditugaskan",
       str(designer_row))
    if not designer_row:
        return 1
    designer_id = designer_row["id"]

    # ══════════════════════════════════════════════════════════════════════
    head("D7 · Pagar badan usaha DULU (supaya sisa POC tidak menulis ke buku yang salah)")
    r = adm.post(f"{BASE}/api/design-requests", headers=h("all"), timeout=30, json={
        "source": "internal", "target_type": "motif",
        "brief": f"POC-{tag} percobaan di mode gabungan"})
    ok(r.status_code == 409 and "badan usaha" in str(r.json().get("detail", "")).lower(),
       "mode gabungan MENOLAK pembuatan dengan 409 + kalimat menuntun (INV-ENTITY-02)",
       f"HTTP {r.status_code} · {str(r.json().get('detail'))[:90]}")

    # ══════════════════════════════════════════════════════════════════════
    head("D1 · Alur ujung-ke-ujung — MD membuat permintaan dari pesanan pelanggan")
    due = days_from_now(3)
    r = adm.post(f"{BASE}/api/design-requests", headers=h(ENT_A), timeout=30, json={
        "source": "so", "so_id": so_id, "target_type": "artwork",
        "line_code": "printing", "due_date": due,
        "brief": f"POC-{tag} motif kawung modern untuk pesanan pelanggan",
        "color_targets": [{"code": "19-4052 TCX", "name": "Classic Blue", "hex": "#0F4C81"}],
        "submit_now": True})
    ok(r.status_code == 200, "permintaan desain dibuat dari SO", f"HTTP {r.status_code} {r.text[:160]}")
    if r.status_code != 200:
        return 1
    doc = r.json()
    dsr_id = doc["id"]
    created_dsr.append(dsr_id)
    ok(doc["number"].startswith("KSC/DSR-"),
       "nomor dokumen per badan usaha (`<ENT>/DSR-#####`)", doc["number"])
    ok(doc["status"] == "submitted" and doc["so_number"] == so_number
       and doc["customer_name"], "status `submitted` + pelanggan tersnapshot dari SO",
       f"{doc['status']} · {doc['so_number']} · {doc['customer_name']}")
    ok(doc.get("entity_id") == ENT_A and doc.get("line_code") == "printing",
       "badan usaha & lini tersnapshot di dokumen (FASE L)",
       f"{doc.get('entity_id')} · {doc.get('line_code')}")

    # brief kosong ditolak — permintaan tanpa brief tidak bisa dikerjakan siapa pun
    r = adm.post(f"{BASE}/api/design-requests", headers=h(ENT_A), timeout=30,
                 json={"source": "internal", "brief": "abc"})
    ok(r.status_code == 400 and "brief" in r.text.lower(),
       "brief kurang dari satu kalimat DITOLAK 400 (bukan draf kosong)",
       f"HTTP {r.status_code} · {r.text[:90]}")

    # ── penugasan + tenggat ─────────────────────────────────────────────────
    r = mgr.post(f"{BASE}/api/design-requests/{dsr_id}/assign", headers=h(ENT_A),
                 timeout=30, json={"assigned_to": designer_id, "due_date": due})
    ok(r.status_code == 200 and r.json()["status"] == "assigned"
       and r.json()["assigned_to"] == designer_id and r.json()["due_date"] == due,
       "manajer menugaskan desainer + tenggat → status `assigned`",
       f"HTTP {r.status_code} · {r.json().get('assigned_name')} · tenggat {r.json().get('due_date')}")

    # ── desainer: melihat tugasnya, menandai mulai ───────────────────────────
    r = dsg.get(f"{BASE}/api/design-requests", headers=h(ENT_A), timeout=30)
    mine = r.json().get("items") or []
    ok(any(x["id"] == dsr_id for x in mine),
       "desainer melihat permintaan yang ditugaskan kepadanya di papannya",
       f"{len(mine)} permintaan")
    ok(all(x.get("assigned_to") == designer_id for x in mine),
       "papan desainer HANYA memuat tugasnya (pagar kepemilikan di server)",
       str(sorted({x.get("assigned_name") for x in mine})))

    r = dsg.post(f"{BASE}/api/design-requests/{dsr_id}/start", headers=h(ENT_A),
                 timeout=30, json={})
    ok(r.status_code == 200 and r.json()["status"] == "in_progress",
       "desainer menandai mulai dikerjakan (papan bergerak tanpa atasan)",
       f"HTTP {r.status_code} · {r.json().get('status')}")

    # ══════════════════════════════════════════════════════════════════════
    head("D3 · Serah hasil WAJIB menunjuk artwork nyata di Galeri badan usaha yang sama")
    r = dsg.post(f"{BASE}/api/design-requests/{dsr_id}/deliver", headers=h(ENT_A),
                 timeout=30, json={"gallery_id": "dsgn_tidak_ada"})
    ok(r.status_code == 400 and "galeri" in r.text.lower(),
       "serah hasil dengan artwork FIKTIF ditolak 400 + menuntun ke Galeri",
       f"HTTP {r.status_code} · {r.text[:100]}")

    # desainer mengunggah karyanya SENDIRI (pintu `design_request.deliver` di galeri)
    r = dsg.post(f"{BASE}/api/design-gallery", headers=h(ENT_A), timeout=30, json={
        "title": f"POC-{tag} Kawung Modern", "design_type": "artwork",
        "code": f"DSG-POC{tag.upper()}-01", "line_code": "printing",
        "story": "Artwork POC FASE D — diunggah oleh desainer sendiri."})
    ok(r.status_code == 200, "desainer mengunggah artwork-nya SENDIRI ke Galeri Desain",
       f"HTTP {r.status_code} {r.text[:140]}")
    if r.status_code != 200:
        return 1
    art = r.json()
    created_gallery.append(art["id"])

    # artwork milik PT LAIN tidak boleh dipakai menyerahkan
    r = adm.post(f"{BASE}/api/design-gallery", headers=h(ENT_B), timeout=30, json={
        "title": f"POC-{tag} artwork PT lain", "design_type": "motif",
        "code": f"DSG-POC{tag.upper()}-B1"})
    if r.status_code == 200:
        art_b = r.json()
        created_gallery.append(art_b["id"])
        r2 = dsg.post(f"{BASE}/api/design-requests/{dsr_id}/deliver", headers=h(ENT_A),
                      timeout=30, json={"gallery_id": art_b["id"]})
        ok(r2.status_code == 400 and "badan usaha lain" in r2.text.lower(),
           "artwork milik badan usaha LAIN ditolak sebagai hasil serah",
           f"HTTP {r2.status_code} · {r2.text[:90]}")
    else:
        ok(False, "prasyarat: artwork PT B bisa dibuat untuk uji pagar",
           f"HTTP {r.status_code} {r.text[:120]}")

    r = dsg.post(f"{BASE}/api/design-requests/{dsr_id}/deliver", headers=h(ENT_A),
                 timeout=30, json={"gallery_id": art["id"], "note": "versi 1"})
    ok(r.status_code == 200 and r.json()["status"] == "delivered"
       and art["id"] in (r.json().get("gallery_ids") or []),
       "serah hasil sah → status `delivered` + artwork tercatat di `gallery_ids[]`",
       f"HTTP {r.status_code} · versi={r.json().get('versions')}")

    g = db.design_gallery.find_one({"id": art["id"]}, {"_id": 0})
    ok((g or {}).get("request_id") == dsr_id and (g or {}).get("request_number"),
       "D6 tautan balik di Galeri: dari artwork bisa dilacak permintaannya",
       f"request_id={(g or {}).get('request_id')} · {(g or {}).get('request_number')}")

    # ══════════════════════════════════════════════════════════════════════
    head("D5 · Masuk antrean keputusan & KPI beranda (bukan dokumen yang hilang di papan)")
    r = mgr.get(f"{BASE}/api/home/manager", headers=h(ENT_A), timeout=60)
    appr = (r.json() or {}).get("approvals") or {}
    # Bentuknya `approvals.items` (bukan `rows`) — `all_items` = tanpa saringan entitas.
    rows = appr.get("items") or []
    row = next((x for x in rows if x.get("key") == "design_request"), None)
    ok(row is not None and int(row.get("count") or 0) >= 1,
       "baris antrean `design_request` muncul di beranda manajer dengan hitungan ≥1",
       f"HTTP {r.status_code} · {row}")
    ok(row is not None and row.get("view") == "design-requests",
       "barisnya menunjuk LAYAR NYATA (`design-requests`), bukan layar hantu",
       str((row or {}).get("view")))

    mongo_delivered = db.design_requests.count_documents(
        {"entity_id": ENT_A, "status": "delivered"})
    ok(row is not None and int(row.get("count") or 0) == mongo_delivered,
       "angka antrean == hitung-ulang MANDIRI dari MongoDB (opini kedua)",
       f"beranda={(row or {}).get('count')} mongo={mongo_delivered}")

    # ══════════════════════════════════════════════════════════════════════
    head("D2 · Minta revisi — ALASAN WAJIB, dan desainer bisa membacanya")
    r = mgr.post(f"{BASE}/api/design-requests/{dsr_id}/reject", headers=h(ENT_A),
                 timeout=30, json={"reason": ""})
    ok(r.status_code == 400 and "alasan" in r.text.lower(),
       "minta revisi TANPA alasan ditolak 400 (server, bukan layar)",
       f"HTTP {r.status_code} · {r.text[:100]}")

    alasan = f"POC-{tag}: warna biru terlalu gelap, naikkan 2 tingkat & rapikan repeat."
    r = mgr.post(f"{BASE}/api/design-requests/{dsr_id}/reject", headers=h(ENT_A),
                 timeout=30, json={"reason": alasan})
    ok(r.status_code == 200 and r.json()["status"] == "revision"
       and r.json()["reject_reason"] == alasan and r.json()["revision_count"] == 1,
       "minta revisi ber-alasan → status `revision` + `revision_count` naik",
       f"HTTP {r.status_code} · putaran={r.json().get('revision_count')}")

    r = dsg.get(f"{BASE}/api/design-requests/{dsr_id}", headers=h(ENT_A), timeout=30)
    ok(r.status_code == 200 and r.json().get("reject_reason") == alasan,
       "DESAINER membaca alasan revisinya di dokumen (bukan lewat WhatsApp)",
       str(r.json().get("reject_reason"))[:80])
    hist = [x.get("event") for x in (r.json().get("history") or [])]
    ok({"created", "assigned", "in_progress", "delivered", "revision"} <= set(hist),
       "setiap perpindahan status meninggalkan jejak `history`", " → ".join(hist))

    # ── revisi diserahkan lagi → ACC ────────────────────────────────────────
    r = dsg.post(f"{BASE}/api/design-requests/{dsr_id}/deliver", headers=h(ENT_A),
                 timeout=30, json={"gallery_id": art["id"], "note": "versi 2 (revisi)"})
    ok(r.status_code == 200 and r.json()["status"] == "delivered",
       "desainer menyerahkan hasil revisi → kembali ke `delivered`",
       f"HTTP {r.status_code}")

    r = mgr.post(f"{BASE}/api/design-requests/{dsr_id}/approve", headers=h(ENT_A),
                 timeout=30, json={"note": "ACC POC"})
    ok(r.status_code == 200 and r.json()["status"] == "approved"
       and r.json().get("decided_by"),
       "manajer ACC → status `approved` + pemutus tercatat",
       f"HTTP {r.status_code} · {r.json().get('decided_by')}")

    r = mgr.post(f"{BASE}/api/design-requests/{dsr_id}/approve", headers=h(ENT_A),
                 timeout=30, json={})
    ok(r.status_code == 400,
       "ACC dua kali ditolak (mesin keadaan, bukan tombol yang bisa ditekan berulang)",
       f"HTTP {r.status_code} · {r.text[:80]}")

    # ══════════════════════════════════════════════════════════════════════
    head("D6 · Jejak dua arah ke pesanan sumbernya")
    r = adm.get(f"{BASE}/api/design-requests-for-so/{so_id}", headers=h(ENT_A), timeout=30)
    ok(r.status_code == 200 and any(x["id"] == dsr_id for x in (r.json() or [])),
       "dari PESANAN bisa melihat permintaan desainnya (panel di layar Pesanan)",
       f"HTTP {r.status_code} · {len(r.json() or [])} permintaan")
    # `doc_refs_service` menyimpan relasi DI DALAM dokumen (`refs[]`), bukan di koleksi
    # terpisah — jadi buktinya harus dicari di kedua dokumen, dua arah.
    dsr_doc = db.design_requests.find_one({"id": dsr_id}, {"_id": 0, "refs": 1}) or {}
    ref_ke_so = next((x for x in (dsr_doc.get("refs") or [])
                      if x.get("doc_type") == "sales_order" and x.get("doc_id") == so_id), None)
    ok(ref_ke_so is not None and ref_ke_so.get("rel") == "parent",
       "permintaan → PESANAN tercatat di `refs[]` sebagai `parent`", str(ref_ke_so))
    so_doc = db.sales_orders.find_one({"id": so_id}, {"_id": 0, "refs": 1}) or {}
    ref_balik = next((x for x in (so_doc.get("refs") or [])
                      if x.get("doc_type") == "design_request" and x.get("doc_id") == dsr_id), None)
    ok(ref_balik is not None and ref_balik.get("rel") == "child",
       "PESANAN → permintaan tercatat balik sebagai `child` (relasi DUA ARAH)",
       str(ref_balik))

    # ══════════════════════════════════════════════════════════════════════
    head("D4 · Rapor = hitung-ulang MANDIRI dari MongoDB (bukan angka yang diketik)")
    r = mgr.get(f"{BASE}/api/design/reports/by-designer", headers=h(ENT_A), timeout=30)
    rep = r.json() if r.status_code == 200 else {}
    baris = next((x for x in (rep.get("items") or [])
                  if x.get("designer_id") == designer_id), None)
    ok(baris is not None, "rapor memuat baris untuk desainer yang dipakai POC",
       f"HTTP {r.status_code} · {[x.get('designer') for x in (rep.get('items') or [])]}")

    # OPINI KEDUA — rumus ditulis ULANG di sini, sengaja tidak mengimpor service.
    docs = list(db.design_requests.find({"entity_id": ENT_A, "assigned_to": designer_id},
                                        {"_id": 0}))
    m_assigned = len(docs)
    m_delivered = sum(1 for d in docs if d.get("delivered_at"))
    m_approved = sum(1 for d in docs if d.get("status") == "approved")
    m_revision = sum(int(d.get("revision_count") or 0) for d in docs)
    ok(baris is not None and baris["assigned"] == m_assigned,
       "rapor `ditugaskan` == hitung-ulang mandiri",
       f"rapor={(baris or {}).get('assigned')} mongo={m_assigned}")
    ok(baris is not None and baris["delivered"] == m_delivered,
       "rapor `diserahkan` == hitung-ulang mandiri",
       f"rapor={(baris or {}).get('delivered')} mongo={m_delivered}")
    ok(baris is not None and baris["approved"] == m_approved,
       "rapor `ACC` == hitung-ulang mandiri",
       f"rapor={(baris or {}).get('approved')} mongo={m_approved}")
    ok(baris is not None and baris["revision"] == m_revision,
       "rapor `revisi` == hitung-ulang mandiri (putaran, bukan jumlah dokumen)",
       f"rapor={(baris or {}).get('revision')} mongo={m_revision}")
    ok(baris is not None and baris.get("avg_days") is not None,
       "rata-rata hari kerja terhitung (ditugaskan → diserahkan)",
       f"avg_days={(baris or {}).get('avg_days')}")
    ok(baris is not None and baris.get("acc_rate_pct") is not None,
       "% ACC terhitung server (layar tidak menghitung sendiri — INV-UI-04)",
       f"acc={(baris or {}).get('acc_rate_pct')}%")

    # ══════════════════════════════════════════════════════════════════════
    head("D8 · PERAN KE-7 `designer` — wilayah sempit yang JUJUR (bukan layar mati)")
    # a. IDOR: permintaan yang BUKAN tugasnya
    lain = db.design_requests.find_one(
        {"entity_id": ENT_A, "assigned_to": {"$nin": [designer_id]}}, {"_id": 0, "id": 1})
    if lain:
        r = dsg.get(f"{BASE}/api/design-requests/{lain['id']}", headers=h(ENT_A), timeout=30)
        ok(r.status_code == 403 and "ditugaskan kepada Anda" in r.text,
           "D8a IDOR: permintaan yang bukan tugasnya → 403 ber-kalimat jelas",
           f"HTTP {r.status_code} · {r.text[:90]}")
    else:
        ok(False, "prasyarat D8a: ada permintaan milik orang lain untuk diuji", "tidak ada")

    # b. wewenang yang TIDAK dimilikinya
    r = dsg.post(f"{BASE}/api/design-requests/{dsr_id}/assign", headers=h(ENT_A),
                 timeout=30, json={"assigned_to": designer_id})
    ok(r.status_code == 403, "D8b desainer TIDAK boleh menugaskan (403)", f"HTTP {r.status_code}")
    r = dsg.post(f"{BASE}/api/design-requests/{dsr_id}/approve", headers=h(ENT_A),
                 timeout=30, json={})
    ok(r.status_code == 403, "D8b desainer TIDAK boleh ACC karyanya sendiri (403 — "
       "pemisahan tugas)", f"HTTP {r.status_code}")
    r = dsg.post(f"{BASE}/api/design-requests/{dsr_id}/reject", headers=h(ENT_A),
                 timeout=30, json={"reason": "coba"})
    ok(r.status_code == 403, "D8b desainer TIDAK boleh memutuskan revisi (403)",
       f"HTTP {r.status_code}")
    r = dsg.post(f"{BASE}/api/design-requests", headers=h(ENT_A), timeout=30,
                 json={"source": "internal", "brief": "desainer coba membuat permintaan"})
    ok(r.status_code == 403, "D8b desainer TIDAK boleh membuat permintaan (403)",
       f"HTTP {r.status_code}")

    # c. rapor lintas desainer = wewenang atasan
    r = dsg.get(f"{BASE}/api/design/reports/by-designer", headers=h(ENT_A), timeout=30)
    ok(r.status_code == 403,
       "D8c rapor LINTAS desainer 403 untuk desainer (menilai orang = atasan)",
       f"HTTP {r.status_code}")

    # d. tetapi rapor DIRINYA 200, dan tanpa nama rekan
    r = dsg.get(f"{BASE}/api/design/reports/mine", headers=h(ENT_A), timeout=30)
    saya = r.json() if r.status_code == 200 else {}
    ok(r.status_code == 200 and (saya.get("me") or {}).get("designer_id") == designer_id,
       "D8d rapor SAYA 200 — desainer melihat angkanya sendiri (bukan panel mati)",
       f"HTTP {r.status_code} · {(saya.get('me') or {}).get('designer')}")
    ok((saya.get("me") or {}).get("assigned") == m_assigned,
       "D8d angka rapor-saya == hitung-ulang mandiri yang sama",
       f"mine={(saya.get('me') or {}).get('assigned')} mongo={m_assigned}")
    ok("items" not in saya,
       "D8d respons rapor-saya tidak membawa daftar baris rekan (`items` absen)",
       f"kunci={sorted(saya)}")
    # nama rekan NYATA tidak boleh muncul di mana pun dalam respons
    rekan = [x.get("designer") for x in (rep.get("items") or [])
             if x.get("designer_id") and x.get("designer_id") != designer_id]
    bocor = [n for n in rekan if n and n in str(saya)]
    ok(not bocor, "D8d nol nama rekan yang bocor di respons rapor-saya (privasi PS-18)",
       f"rekan diperiksa={rekan or '(tidak ada rekan lain di data demo)'} bocor={bocor}")

    # e. sales (peran lain tanpa izin desain) tetap tertutup
    r = sal.get(f"{BASE}/api/design-requests", headers=h(ENT_A), timeout=30)
    ok(r.status_code == 403, "D8e peran `sales` tetap tertutup atas permintaan desain",
       f"HTTP {r.status_code}")

    # ══════════════════════════════════════════════════════════════════════
    head("D9 · Daftar peran DIBACA dari SSOT — gate tidak boleh meledak lagi")
    rc, tail = run_gate("scripts/check_nav_map.py")
    ok(rc == 0, "gate `check_nav_map` PASS (dulu CRASH `KeyError: 'designer'`)",
       f"exit {rc} · {tail[-160:]}")
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "poc_nav", os.path.join(ROOT, "scripts", "check_nav_map.py"))
    nav = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(nav)
    ok("designer" in nav.ROLES,
       "gate MEMBACA peran ke-7 dari registry (hijau karena memeriksa, bukan karena buta)",
       f"ROLES={nav.ROLES}")

    rc, tail = run_gate("scripts/guardrails/verify_approval_queues.py")
    ok(rc == 0, "gate `INV-APPR-01` HIJAU (pintu ACC/revisi punya antreannya)",
       f"exit {rc} · {tail[-160:]}")
    rc, tail = run_gate("scripts/guardrails/verify_home_kpi.py")
    ok(rc == 0, "gate `INV-HOME-01` HIJAU (KPI beranda punya opini kedua)",
       f"exit {rc} · {tail[-160:]}")

    # ══════════════════════════════════════════════════════════════════════
    head("D10 · CLEANUP + NOL RESIDU (diukur, bukan diklaim)")
    # Batalkan/hapus dokumen yang POC ini buat. Dokumen `approved` bersifat terminal,
    # jadi dihapus langsung dari DB — POC tidak boleh meninggalkan jejak bisnis.
    db.design_requests.delete_many({"id": {"$in": created_dsr}})
    db.design_gallery.delete_many({"id": {"$in": created_gallery}})
    # Relasi `refs[]` yang POC tanam DI PESANAN LAMA wajib dicabut, kalau tidak setiap
    # jalan-ulang menambah satu relasi hantu ke dokumen milik data demo (dan
    # `INV-REF-02` akan menemukan target yang sudah tidak ada).
    db.sales_orders.update_many(
        {"refs.doc_id": {"$in": created_dsr}},
        {"$pull": {"refs": {"doc_id": {"$in": created_dsr}}}})
    # Jejak audit & sesi yang lahir SELAMA POC (termasuk 4 baris `login`) dibuang
    # dengan membandingkan sidik jari id — bukan menebak nama aksinya.
    db.sessions.delete_many({"token": {"$in": TOKENS}})
    baru = {d["id"] for d in db.audit_logs.find({}, {"_id": 0, "id": 1})} - audit_before_ids
    if baru:
        db.audit_logs.delete_many({"id": {"$in": list(baru)}})
    after = {c: db[c].count_documents({}) for c in WATCH}
    drift = {c: (before[c], after[c]) for c in WATCH if before[c] != after[c]}
    ok(not drift, "nol residu: jumlah dokumen tiap koleksi SAMA sebelum & sesudah POC",
       f"drift={drift}" if drift else f"{len(WATCH)} koleksi identik")
    sisa_refs = db.sales_orders.count_documents({"refs.doc_id": {"$in": created_dsr}})
    ok(sisa_refs == 0,
       "nol relasi hantu: pesanan demo tidak menyimpan `refs` ke dokumen POC yang dihapus",
       f"{sisa_refs} pesanan masih menyimpannya")

    # ══════════════════════════════════════════════════════════════════════
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
