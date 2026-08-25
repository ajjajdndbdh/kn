#!/usr/bin/env python3
"""POC FASE I — **INSPEKSI & QC SEBAGAI DOKUMEN** (`<ENT>/INS-#####`).

Rencana: `RENCANA_EKSEKUSI_MD_ERP.md` §I (I.A–I.I) + §3.4 ("anti pintu ke-3").
Keputusan pemilik #5 (dikonfirmasi ulang 2026-08-23): **warna beda = barang DITAHAN ·
handfeel beda = PERINGATAN · pelepas tahanan = MANAJER**.

APA YANG DIBUKTIKAN DI SINI (dan kenapa masing-masing perlu dibuktikan)
=======================================================================
  I1  **SPK LAHIR OTOMATIS** saat barang PO masuk antrean QC, berisi satu baris per
      ROLL fisik. Kalau ini tidak otomatis, kepala gudang harus membuat dokumen dari
      nol untuk setiap penerimaan — dan yang tidak dibuat menjadi barang yang masuk
      gudang tanpa satu pun catatan siapa memeriksanya. Sekaligus dibuktikan
      **idempotent**: menyelesaikan penerimaan dua kali tidak melahirkan SPK kedua
      atas barang yang sama.
  I2  **Mesin keadaan berjalan** draft → assigned → in_progress → done, dan setiap
      perpindahan meninggalkan baris `history`. Menutup dokumen tanpa satu baris pun
      diperiksa DITOLAK — tanggal keputusan yang tidak beralas adalah bukti palsu.
  I3  **BUKAN PINTU KE-3 UNTUK GRADE** (§3.4, inti fase ini). Cacat 24 poin →
      grade turun, `inventory_rolls.grade_history` bertambah **TEPAT SATU** baris
      ber-`source="qc_inspection"`, dan `points_snapshot` di dokumen **SAMA** dengan
      `inventory_rolls.inspection.points`. Kalau dokumen menghitung sendiri, akan ada
      dua angka untuk satu roll dan tidak ada cara memilih mana yang benar.
  I4  **Warna beda → barang DITAHAN, dan tahanannya BEKERJA**: `putaway` roll dijawab
      **400 ber-kalimat menuntun** (menyebut nomor SPK & siapa yang berwenang), lalu
      **gudang DITOLAK 403** saat mencoba melepas tahanan, **manajer BOLEH** dengan
      alasan wajib — sesudah itu putaway berhasil. Tanpa rangkaian ini, kebijakan
      "tahan" hanya kalimat di layar pengaturan.
  I5  **Acuan sample yang di-ACC ikut di dokumen** (nomor + warna) dan tertaut DUA
      ARAH lewat `rel="references"`. Tanpa menyebut NAMA acuannya, kolom "warna
      sesuai?" hanya berisi pendapat yang tidak bisa diperiksa ulang siapa pun.
  I6  **Retur pelanggan**: SPK `return_customer` + tonggak perjalanan (SJ Kirim Toko →
      Barang sampai) + dua satuan, **tanpa menduplikasi** `sales_returns.items[].
      inspection` (SSOT hasil per barang tetap milik `return_service`), dan
      `inspect_done_at` retur DITURUNKAN dari penutupan dokumen — bukan diketik.
  I7  **`tolak` WAJIB ber-alasan**, dan alasannya tersimpan **DI DOKUMEN**
      (`reject_reason`) — bukan hanya di jejak audit yang tidak pernah dibaca orang
      yang sedang bertanya. `reopen` juga wajib ber-alasan.
  I8  **Gate INV-QC-01..03 dijalankan SUNGGUHAN** dan dibuktikan **BISA MEMERAH**
      (satu angka dokumen digeser sepihak → gate merah → dipulihkan → hijau lagi).
      Invarian yang tidak pernah diperlihatkan memerah adalah hiasan.
  I9  **Pagar badan usaha**: mode gabungan (`X-Entity-Id: all`) MENOLAK `POST
      /api/inspections` dengan **409** ber-kalimat menuntun (INV-ENTITY-02),
      sementara aksi atas dokumen yang SUDAH ADA tetap boleh.
  I10 **IDOR**: pengguna ber-home PT-B tidak bisa membaca maupun menutup inspeksi
      milik PT-A (403/404).
  I11 **NOL RESIDU**: stok + buku besar + kas dipulihkan EKSAK lewat
      `poc_stock_guard`, dokumen POC dihapus, dan jumlah dokumen tiap koleksi
      tersentuh diukur "sebelum == sesudah". POC yang berakhir "0 FAIL" tidak
      membuktikan nol residu kalau ia tidak pernah mengukurnya (pelajaran FASE T).
  I12 **PEMILIH DOKUMEN SUMBER hidup untuk GUDANG tanpa melonggarkan izin.** Layar
      Inspeksi milik gudang juga, tetapi gudang tidak punya `sales_return.view`;
      versi pertama layar memanggil `/api/sales-returns` langsung sehingga pemilih
      dokumennya **403 tanpa penjelasan** (`audit_sales_roles_ux`: `warehouse →
      inspections → /sales-returns`). Diuji: `/sales-returns` **tetap 403** untuk
      gudang, `/inspections/meta/ref-docs` **200 berisi pilihan**, jawabannya hanya
      nomor+nama pihak, dokumen yang sudah ber-SPK **ditandai**, order makloon tanpa
      hasil **tidak ditawarkan** (dan ditolak menuntun bila dipaksa), SPK hasil
      makloon **berisi baris + nomor + nama mitra**, SPK kedua atas dokumen yang sama
      **ditolak**, dokumen PT lain **ditolak**, dan modul API layar ini tidak
      memanggil endpoint modul lain lagi (pagar statis anti-kambuh).

Jalankan:  cd /app && python backend/test_core_inspeksi_poc.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from poc_stock_guard import (FULL_COLLECTIONS, restore_stock,  # noqa: E402
                            snapshot_stock, sweep_ghost_refs)

BASE = os.environ.get("POC_BASE_URL", "http://localhost:8001")
API = f"{BASE}/api"
ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PW = "demo12345"
ADMIN = "admin@kainnusantara.id"
MANAGER = "manager@kainnusantara.id"     # pemisahan tugas (SoD): pembuat ≠ penyetuju
WAREHOUSE = "warehouse@kainnusantara.id"
WAREHOUSE_B = "warehouse2@kainnusantara.id"   # ber-home badan usaha lain (I10)
ENT_A = "ent_ksc"
ENT_B = "ent_kanda"
WH = "wh_jakarta"
BIN = "bin_jkt_a1_01"
P_WOVEN = "prod_tenun_ikat"              # base yard (lini woven)

TAG = f"POC-I-{uuid.uuid4().hex[:6].upper()}"
ROLLS = 2
YARD_PER_ROLL = 30.0
QTY_TOTAL = ROLLS * YARD_PER_ROLL

#: Koleksi yang alur ini boleh menyentuh — dipakai pengukuran nol residu (I11).
#: `sales_returns` ikut dipantau karena SPK retur MENYUNTING dokumen retur data demo
#: (mengisi `inspection_id`), dan `system_settings` karena bukti-merah I4 sempat
#: mengubah kebijakan bila kelak diperlukan.
WATCH = ("inspections", "purchase_orders", "wms_tasks", "audit_logs", "notifications",
         "sales_returns")

TOKENS: List[str] = []
PASS = 0
FAIL = 0
FAILED_LABELS: List[str] = []


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
    r = s.post(f"{API}/auth/login", json={"email": email, "password": PW}, timeout=30)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:300]}"
    tok = r.json()["token"]
    TOKENS.append(tok)
    s.headers.update({"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    return s


def h(entity: str) -> Dict[str, str]:
    return {"X-Entity-Id": entity}


def _db():
    from pymongo import MongoClient
    cli = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    return cli[os.environ.get("DB_NAME", "test_database")]


def run_gate(rel_path: str, *args: str) -> tuple[int, str]:
    """Jalankan gate SUNGGUHAN (bukan menirunya) → (exit code, SELURUH keluaran).

    Keluaran dikembalikan UTUH, bukan ekornya. Versi pertama POC ini memotong 500
    huruf terakhir, dan akibatnya nyata: blok BUKTI-MERAH mencari kata `INV-QC-01`
    di dalam potongan itu, tidak menemukannya (baris FAIL ada di tengah), lalu
    melaporkan gate "tidak memerah" padahal exit code-nya 1. Alat uji yang membaca
    sebagian keluaran akan menuduh kode yang benar.
    """
    p = subprocess.run([sys.executable, str(ROOT / rel_path), *args],
                       capture_output=True, text=True, cwd=str(ROOT), timeout=300)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


class PocStop(Exception):
    """Berhenti lebih awal — TETAPI bersih-bersih di `finally` tetap dijalankan.

    Pelajaran POC-RESIDU-01 / FASE S: POC yang CRASH di tengah jalan tidak menjalankan
    cleanup-nya, dan residunya memerahkan POC-POC BERIKUTNYA di gate yang sama —
    9 dari 13 kegagalan gate pada sesi FASE S adalah gema jenis ini.
    """


def supplier_id(db) -> str:
    s = db.suppliers.find_one({"entity_id": ENT_A, "status": {"$ne": "inactive"}},
                              {"_id": 0, "id": 1})
    return (s or {}).get("id", "")


def create_po(sess, approver, sup: str) -> Dict[str, Any]:
    """PO 2 roll × 30 yard, dibawa sampai `pending` (siap diterima gudang)."""
    body = {"supplier_id": sup, "warehouse_id": WH,
            "items": [{"product_id": P_WOVEN, "quantity": QTY_TOTAL, "unit": "yard",
                       "price": 150000, "qty_rolls": ROLLS, "expected_grade": "A"}],
            "notes": f"{TAG} penerimaan untuk SPK inspeksi"}
    r = sess.post(f"{API}/purchase-orders", json=body, headers=h(ENT_A), timeout=60)
    if r.status_code != 200:
        raise PocStop(f"PO gagal {r.status_code}: {r.text[:300]}")
    po = r.json()
    for _ in range(6):
        if po.get("status") != "waiting_approval":
            break
        ra = approver.post(f"{API}/purchase-orders/{po['id']}/approve",
                           json={"notes": f"{TAG} approve"}, headers=h(ENT_A), timeout=60)
        if ra.status_code != 200:
            raise PocStop(f"approve PO gagal {ra.status_code}: {ra.text[:300]}")
        po = ra.json()
    return sess.get(f"{API}/purchase-orders/{po['id']}", headers=h(ENT_A), timeout=30).json()


def inbound_task(sess, po_id: str) -> Optional[Dict[str, Any]]:
    rows = sess.get(f"{API}/inbound/tasks", headers=h(ENT_A), timeout=30).json()
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    for t in rows:
        if t.get("po_id") == po_id and t.get("product_id") == P_WOVEN:
            return t
    return None


# ═══════════════════════════════════════════════════════════════════════════
def run_stories(db, adm, mgr, wh, whb, state: Dict[str, List[str]]) -> None:  # noqa: C901
    sup = supplier_id(db)
    if not sup:
        raise PocStop("tidak ada supplier demo pada badan usaha uji")

    # ══ I9 — pagar badan usaha DULU (supaya sisa POC tak menulis ke buku salah) ══
    head("I9 · Pagar badan usaha: mode gabungan menolak MEMBUAT dokumen")
    r = adm.post(f"{API}/inspections", headers=h("all"), timeout=30,
                 json={"kind": "return_customer", "ref_doc_id": "apa-saja"})
    detail = str((r.json() or {}).get("detail", "")) if r.text else ""
    ok(r.status_code == 409 and "badan usaha" in detail.lower(),
       "mode “Semua Entitas” MENOLAK POST /api/inspections dengan 409 + kalimat menuntun",
       f"HTTP {r.status_code} · {detail[:110]}")

    # ══ I1 — SPK lahir otomatis dari penerimaan PO ═════════════════════════════
    head("I1 · Barang PO diterima → SPK Inspeksi LAHIR OTOMATIS (satu baris per roll)")
    po = create_po(adm, mgr, sup)
    state["pos"].append(po["id"])
    task = inbound_task(adm, po["id"])
    ok(bool(task), "tugas penerimaan gudang lahir dari PO", f"status PO {po.get('status')!r}")
    if not task:
        raise PocStop("tugas penerimaan tidak lahir — I1..I8 tidak bisa dilanjutkan")
    state["tasks"].append(task["id"])

    r = wh.post(f"{API}/inbound/tasks/{task['id']}/scan-receive", headers=h(ENT_A),
                json={"product_id": P_WOVEN, "actual_qty": QTY_TOTAL,
                      "lot": f"LOT-{TAG}", "bin_id": ""}, timeout=90)
    ok(r.status_code == 200, f"scan-receive {QTY_TOTAL:g} yard diterima gudang",
       f"HTTP {r.status_code} {r.text[:200]}")

    roll_lines = [{"length": YARD_PER_ROLL, "grade": "A", "dye_lot": f"DL-{TAG}"}
                  for _ in range(ROLLS)]
    r = wh.post(f"{API}/inbound/tasks/{task['id']}/complete", headers=h(ENT_A),
                json={"rolls": roll_lines, "lot_number": f"LOT-{TAG}"}, timeout=120)
    ok(r.status_code == 200, f"penerimaan diselesaikan dengan {ROLLS} baris roll",
       f"HTTP {r.status_code} {r.text[:250]}")
    body = r.json() if r.status_code == 200 else {}
    ok(not body.get("inspection_error"),
       "penerimaan TIDAK menelan kegagalan pembuatan SPK diam-diam",
       str(body.get("inspection_error") or "tidak ada galat"))
    spk_ref = body.get("inspection") or {}
    ok(bool(spk_ref.get("number")),
       "respons penerimaan menyebut nomor SPK yang baru lahir (bukan diam)",
       str(spk_ref))

    doc = db.inspections.find_one({"task_id": task["id"]}, {"_id": 0})
    ok(bool(doc), "dokumen `inspections` ADA untuk tugas penerimaan itu")
    if not doc:
        raise PocStop("SPK tidak lahir — inti FASE I tidak terbukti")
    state["inspections"].append(doc["id"])
    ok(str(doc.get("number", "")).startswith("KSC/INS-"),
       "nomor dokumen per badan usaha (`<ENT>/INS-#####`)", doc.get("number"))
    ok(doc.get("kind") == "po_receipt" and doc.get("status") == "draft",
       "jenis `po_receipt` & status `draft` (menunggu ditugaskan — user story I.1)",
       f"{doc.get('kind')} · {doc.get('status')}")
    ok(len(doc.get("lines") or []) == ROLLS,
       f"berisi {ROLLS} baris — satu baris per ROLL fisik, bukan satu baris per PO",
       f"{len(doc.get('lines') or [])} baris")
    ln0 = (doc.get("lines") or [{}])[0]
    ok(ln0.get("qty_rolls") == 1 and float(ln0.get("quantity") or 0) == YARD_PER_ROLL
       and ln0.get("unit"),
       "dua satuan FASE U pada baris: `qty_rolls` + `quantity` + `unit` (bentuk KANONIK)",
       f"{ln0.get('qty_rolls')} roll · {ln0.get('quantity')} {ln0.get('unit')}")
    ok((doc.get("summary") or {}).get("rolls") == ROLLS,
       "ringkasan dokumen menjumlahkan roll dari barisnya (DIHITUNG, bukan diketik)",
       str(doc.get("summary")))

    # idempotensi: selesaikan penerimaan sekali lagi → TIDAK ada SPK kedua
    wh.post(f"{API}/inbound/tasks/{task['id']}/complete", headers=h(ENT_A),
            json={"rolls": roll_lines, "lot_number": f"LOT-{TAG}"}, timeout=120)
    n_spk = db.inspections.count_documents({"task_id": task["id"]})
    ok(n_spk == 1, "IDEMPOTEN: penerimaan diselesaikan ulang tidak melahirkan SPK kedua",
       f"{n_spk} dokumen untuk satu tugas")

    ins_id = doc["id"]

    # ══ I5 — acuan sample & jejak dua arah ════════════════════════════════════
    head("I5 · Acuan penilaian & jejak dokumen dua arah")
    r = adm.get(f"{API}/inspections/{ins_id}", headers=h(ENT_A), timeout=30)
    dj = r.json() if r.status_code == 200 else {}
    ok(r.status_code == 200 and dj.get("ref_doc_number") == po.get("po_number"),
       "dokumen menyebut PO sumbernya (pertanyaan “inspeksi ini milik PO mana”)",
       f"HTTP {r.status_code} · {dj.get('ref_doc_number')}")
    refs = {(x.get("doc_type"), x.get("rel")) for x in (dj.get("refs") or [])}
    po_fresh = db.purchase_orders.find_one({"id": po["id"]}, {"_id": 0, "refs": 1}) or {}
    back = [x for x in (po_fresh.get("refs") or []) if x.get("doc_id") == ins_id]
    ok(("purchase_order", "parent") in refs and bool(back),
       "jejak DUA ARAH: inspeksi→PO (`parent`) dan PO→inspeksi (tautan balik)",
       f"{sorted(refs)} · balik={len(back)}")
    ok("baseline_sample_number" in dj,
       "dokumen SELALU punya kolom acuan sample (isi kosong = jujur “belum ada ACC”)",
       f"acuan={dj.get('baseline_sample_number') or '(belum ada sample ACC)'}")

    # ══ I2 — mesin keadaan ════════════════════════════════════════════════════
    head("I2 · Mesin keadaan: draft → assigned → in_progress → done")
    officers = (adm.get(f"{API}/inspections/meta", headers=h(ENT_A), timeout=30).json()
                or {}).get("officers") or []
    petugas = next((o for o in officers if "Eko" in str(o.get("label", ""))), None) \
        or (officers[0] if officers else None)
    ok(bool(petugas), "daftar petugas inspect datang dari server (layar tidak menebak)",
       str(petugas))
    if not petugas:
        raise PocStop("tidak ada petugas untuk ditugaskan")

    r = mgr.post(f"{API}/inspections/{ins_id}/finish", headers=h(ENT_A), timeout=30,
                 json={"decision": "terima", "remark": ""})
    ok(r.status_code == 400,
       "menutup SPK yang belum diperiksa DITOLAK 400 (tanggal keputusan tanpa "
       "pemeriksaan = bukti palsu)", f"HTTP {r.status_code} · {r.text[:120]}")

    r = mgr.post(f"{API}/inspections/{ins_id}/assign", headers=h(ENT_A), timeout=30,
                 json={"assigned_to": petugas["value"], "bagian": "Bagian Inspect"})
    ok(r.status_code == 200 and r.json().get("status") == "assigned",
       "manajer menugaskan petugas → status `assigned`",
       f"HTTP {r.status_code} · {r.json().get('assigned_name')}")

    r = wh.post(f"{API}/inspections/{ins_id}/start", headers=h(ENT_A), timeout=30, json={})
    ok(r.status_code == 200 and r.json().get("status") == "in_progress"
       and r.json().get("started_at"),
       "petugas menandai mulai → status `in_progress` + `started_at` terisi",
       f"HTTP {r.status_code} · {r.json().get('started_at')}")

    # ══ I3 — anti pintu ke-3: grade & poin ════════════════════════════════════
    head("I3 · Poin & grade DIHITUNG MESIN LAMA — dokumen hanya RINGKASAN (§3.4)")
    lines = (db.inspections.find_one({"id": ins_id}, {"_id": 0, "lines": 1}) or {}).get("lines") or []
    line_a, line_b = lines[0], lines[1]
    roll_a_id, roll_b_id = line_a.get("roll_id"), line_b.get("roll_id")
    hist_before = len((db.inventory_rolls.find_one({"id": roll_a_id},
                                                   {"_id": 0, "grade_history": 1}) or {}
                       ).get("grade_history") or [])

    r = wh.post(f"{API}/inspections/{ins_id}/lines/{line_a['id']}/inspect",
                headers=h(ENT_A), timeout=60,
                json={"defects": [{"point_value": 4, "count": 6}],
                      "gsm_actual": 148, "width_actual": 112,
                      "color_result": "beda_shade", "handfeel_result": "sesuai",
                      "handfeel_score": 4,
                      "remark": f"{TAG} shade lebih tua dari sample"})
    ok(r.status_code == 200, "petugas mengisi 6 cacat × 4 poin + hasil warna/handfeel",
       f"HTTP {r.status_code} {r.text[:200]}")
    fresh = r.json() if r.status_code == 200 else {}
    lna = next((x for x in (fresh.get("lines") or []) if x["id"] == line_a["id"]), {})
    roll_a = db.inventory_rolls.find_one({"id": roll_a_id}, {"_id": 0}) or {}
    insp_roll = roll_a.get("inspection") or {}

    ok(float(lna.get("points_snapshot") or -1) == 24.0,
       "poin 4-point = 24 (6 × 4) — dihitung server, tidak dikirim layar",
       str(lna.get("points_snapshot")))
    ok(float(lna.get("points_snapshot") or -1) == float(insp_roll.get("points") or -2),
       "ANTI-DUPLIKAT: `points_snapshot` dokumen == `inventory_rolls.inspection.points`",
       f"dok {lna.get('points_snapshot')} vs roll {insp_roll.get('points')}")
    ok(lna.get("grade_before") == "A" and lna.get("grade_after") not in ("", "A", None),
       "grade TURUN otomatis dari poin (petugas tidak memilih grade)",
       f"{lna.get('grade_before')} → {lna.get('grade_after')}")
    ok(lna.get("grade_after") == roll_a.get("grade"),
       "grade di dokumen == grade di roll (satu fakta, satu nilai)",
       f"dok {lna.get('grade_after')} vs roll {roll_a.get('grade')}")
    hist = [x for x in (roll_a.get("grade_history") or [])
            if x.get("source") == "qc_inspection"]
    ok(len(roll_a.get("grade_history") or []) == hist_before + 1 and len(hist) == 1,
       "`grade_history` roll bertambah TEPAT SATU baris ber-`source=\"qc_inspection\"`",
       f"{hist_before} → {len(roll_a.get('grade_history') or [])} · qc={len(hist)}")
    ok(insp_roll.get("inspection_doc_number") == doc.get("number"),
       "roll menyimpan NOMOR SPK-nya (jejak dari sisi roll juga terbaca)",
       str(insp_roll.get("inspection_doc_number")))
    ok(insp_roll.get("color_result") == "beda_shade"
       and insp_roll.get("handfeel_result") == "sesuai",
       "hasil warna & handfeel disimpan DI ROLL (tempat pagar putaway membacanya)",
       f"{insp_roll.get('color_result')} · {insp_roll.get('handfeel_result')}")

    # ══ I4 — tahanan warna: pagar putaway + siapa yang boleh melepas ══════════
    head("I4 · Warna beda → barang DITAHAN, dan tahanannya BENAR-BENAR menahan")
    ok(bool(lna.get("hold")) and bool((insp_roll.get("hold") or {}).get("held")),
       "baris & roll sama-sama ditandai DITAHAN (kebijakan pemilik #5: `tahan`)",
       f"baris={lna.get('hold')} roll={(insp_roll.get('hold') or {}).get('held')}")
    ok("warna" in str(lna.get("hold_reason", "")).lower(),
       "alasan tahanan menyebut SEBABNYA (bukan “ditahan” tanpa keterangan)",
       str(lna.get("hold_reason"))[:110])

    r = wh.post(f"{API}/inventory/putaway", headers=h(ENT_A), timeout=30,
                json={"roll_id": roll_a_id, "bin_id": BIN})
    pesan = str((r.json() or {}).get("detail", "")) if r.text else ""
    ok(r.status_code == 400 and "DITAHAN" in pesan and "MANAJER" in pesan.upper(),
       "putaway roll yang ditahan DITOLAK 400 + pesan menuntun (siapa yang berwenang)",
       f"HTTP {r.status_code} · {pesan[:140]}")
    ok(doc.get("number") in pesan or (insp_roll.get("inspection_doc_number") or "") in pesan,
       "pesan penolakan menyebut NOMOR SPK-nya (petugas tahu harus ke dokumen mana)",
       pesan[:140])

    r = wh.post(f"{API}/inspections/{ins_id}/lines/{line_a['id']}/release-hold",
                headers=h(ENT_A), timeout=30, json={"reason": "sudah saya lihat, aman"})
    ok(r.status_code == 403,
       "GUDANG mencoba melepas tahanan → 403 (wewenang manajer, dijaga server)",
       f"HTTP {r.status_code} · {r.text[:110]}")

    r = mgr.post(f"{API}/inspections/{ins_id}/lines/{line_a['id']}/release-hold",
                 headers=h(ENT_A), timeout=30, json={"reason": "ok"})
    ok(r.status_code == 400,
       "manajer melepas tahanan tanpa alasan memadai → 400 (alasan WAJIB)",
       f"HTTP {r.status_code} · {r.text[:110]}")

    alasan = "Pelanggan menerima shade ini dengan potongan 3% — disetujui lewat telepon."
    r = mgr.post(f"{API}/inspections/{ins_id}/lines/{line_a['id']}/release-hold",
                 headers=h(ENT_A), timeout=30, json={"reason": alasan})
    ok(r.status_code == 200, "MANAJER melepas tahanan ber-alasan → 200",
       f"HTTP {r.status_code} {r.text[:160]}")
    lna2 = next((x for x in ((r.json() or {}).get("lines") or [])
                 if x["id"] == line_a["id"]), {})
    ok(lna2.get("hold") is False and lna2.get("hold_release_reason") == alasan,
       "alasan pelepasan tersimpan DI DOKUMEN (satu-satunya catatan mengapa boleh masuk)",
       str(lna2.get("hold_release_reason"))[:80])
    roll_after = db.inventory_rolls.find_one({"id": roll_a_id}, {"_id": 0}) or {}
    ok(((roll_after.get("inspection") or {}).get("hold") or {}).get("held") is False,
       "tahanan di ROLL ikut dilepas (dokumen & roll tidak boleh berbeda pendapat)")
    r = wh.post(f"{API}/inventory/putaway", headers=h(ENT_A), timeout=30,
                json={"roll_id": roll_a_id, "bin_id": BIN})
    ok(r.status_code == 200, "sesudah dilepas, putaway BERHASIL (pagar bukan jalan buntu)",
       f"HTTP {r.status_code} {r.text[:140]}")

    # baris kedua: bersih → tidak ditahan (pagar tidak menahan semua barang)
    r = wh.post(f"{API}/inspections/{ins_id}/lines/{line_b['id']}/inspect",
                headers=h(ENT_A), timeout=60,
                json={"defects": [{"point_value": 1, "count": 2}],
                      "color_result": "sesuai", "handfeel_result": "sesuai",
                      "handfeel_score": 5, "remark": f"{TAG} sesuai sample"})
    lnb = next((x for x in ((r.json() or {}).get("lines") or [])
                if x["id"] == line_b["id"]), {})
    ok(r.status_code == 200 and not lnb.get("hold") and lnb.get("grade_after") == "A",
       "roll yang SESUAI sample tidak ditahan & grade tetap A (pagar tidak buta)",
       f"HTTP {r.status_code} · hold={lnb.get('hold')} grade={lnb.get('grade_after')}")
    r = wh.post(f"{API}/inventory/putaway", headers=h(ENT_A), timeout=30,
                json={"roll_id": roll_b_id, "bin_id": BIN})
    ok(r.status_code == 200, "roll bersih langsung boleh putaway", f"HTTP {r.status_code}")

    # ══ I10 — IDOR lintas badan usaha ════════════════════════════════════════
    head("I10 · IDOR: pengguna badan usaha lain tidak boleh membaca/menutup SPK ini")
    r = whb.get(f"{API}/inspections/{ins_id}", headers=h(ENT_B), timeout=30)
    ok(r.status_code in (403, 404), "GET inspeksi PT-A oleh pengguna PT-B → 403/404",
       f"HTTP {r.status_code}")
    r = whb.post(f"{API}/inspections/{ins_id}/start", headers=h(ENT_B), timeout=30, json={})
    ok(r.status_code in (403, 404), "aksi atas inspeksi PT-A oleh pengguna PT-B → 403/404",
       f"HTTP {r.status_code}")
    rows = whb.get(f"{API}/inspections", headers=h(ENT_B), timeout=30).json()
    ids = {x["id"] for x in (rows.get("items") or [])}
    ok(ins_id not in ids, "daftar inspeksi PT-B tidak memuat dokumen PT-A",
       f"{len(ids)} dokumen terlihat PT-B")

    # ══ I7 — tolak WAJIB ber-alasan, alasan tersimpan di DOKUMEN ══════════════
    head("I7 · Keputusan `tolak` wajib ber-alasan — dan alasannya ada DI DOKUMEN")
    r = mgr.post(f"{API}/inspections/{ins_id}/finish", headers=h(ENT_A), timeout=30,
                 json={"decision": "tolak", "remark": "jelek"})
    ok(r.status_code == 400 and "alasan" in r.text.lower(),
       "`tolak` dengan alasan sepotong → 400 (alasan ini dibaca supplier & jadi dasar klaim)",
       f"HTTP {r.status_code} · {r.text[:120]}")
    r = mgr.post(f"{API}/inspections/{ins_id}/finish", headers=h(ENT_A), timeout=30,
                 json={"decision": "aneh", "remark": "apa saja yang panjang sekali"})
    ok(r.status_code == 400, "keputusan di luar kosakata resmi → 400",
       f"HTTP {r.status_code} · {r.text[:110]}")

    alasan_tolak = ("Shade menyimpang pada 2 roll dan gramasi di bawah spesifikasi — "
                    "barang dikembalikan ke supplier untuk penggantian.")
    r = mgr.post(f"{API}/inspections/{ins_id}/finish", headers=h(ENT_A), timeout=30,
                 json={"decision": "tolak", "remark": alasan_tolak})
    ok(r.status_code == 200 and r.json().get("status") == "done"
       and r.json().get("decision") == "tolak",
       "manajer menutup SPK dengan keputusan `tolak` → status `done`",
       f"HTTP {r.status_code} · {r.json().get('decision_label')}")
    stored = db.inspections.find_one({"id": ins_id}, {"_id": 0}) or {}
    ok(stored.get("reject_reason") == alasan_tolak,
       "alasan penolakan tersimpan DI DOKUMEN (`reject_reason`), bukan hanya di audit",
       str(stored.get("reject_reason"))[:90])
    ok(any(x.get("event") == "finished" for x in (stored.get("history") or [])),
       "setiap perpindahan keadaan meninggalkan baris `history`",
       f"{len(stored.get('history') or [])} baris riwayat")

    r = mgr.post(f"{API}/inspections/{ins_id}/reopen", headers=h(ENT_A), timeout=30,
                 json={"reason": "x"})
    ok(r.status_code == 400, "`reopen` tanpa alasan memadai → 400 (jejak tanggung jawab)",
       f"HTTP {r.status_code}")
    r = mgr.post(f"{API}/inspections/{ins_id}/reopen", headers=h(ENT_A), timeout=30,
                 json={"reason": "Supplier mengirim bukti uji lab — periksa ulang."})
    ok(r.status_code == 200 and r.json().get("status") == "in_progress"
       and not r.json().get("decision"),
       "`reopen` ber-alasan mengembalikan status & MENGOSONGKAN keputusan lama",
       f"HTTP {r.status_code} · {r.json().get('status')}")
    # Alasan penolakan IKUT dikosongkan — kalau tidak, layar memampang "ALASAN
    # PENOLAKAN" pada dokumen yang kepalanya berkata "Belum diputuskan" (terukur di
    # peramban 2026-08-23). Yang WAJIB tetap ada adalah jejaknya di `history`.
    dibuka = db.inspections.find_one({"id": ins_id}, {"_id": 0}) or {}
    ok(not (dibuka.get("reject_reason") or ""),
       "…termasuk `reject_reason` (alasan milik keputusan yang baru dianulir)",
       f"reject_reason={dibuka.get('reject_reason')!r}")
    ok(any(alasan_tolak in str(x.get("note") or "") for x in (dibuka.get("history") or [])),
       "…tetapi alasan penolakan LAMA tetap terbaca di riwayat dokumen (tidak hilang)",
       f"{len(dibuka.get('history') or [])} baris riwayat")

    # ══ I6 — retur pelanggan: SPK + tonggak + tanpa duplikasi ═════════════════
    head("I6 · Retur pelanggan: SPK + tonggak perjalanan, tanpa menduplikasi hasil retur")
    ret = db.sales_returns.find_one({"entity_id": ENT_A}, {"_id": 0})
    ok(bool(ret), "ada dokumen retur jual di PT A untuk diperiksa")
    if ret:
        state["returns_touched"].append(ret["id"])
        before_items = ret.get("items") or []
        r = adm.post(f"{API}/inspections", headers=h(ENT_A), timeout=60,
                     json={"kind": "return_customer", "ref_doc_id": ret["id"],
                           "remark": f"{TAG} periksa keluhan pelanggan"})
        ok(r.status_code == 200, "SPK inspeksi retur dibuat dari dokumen retur",
           f"HTTP {r.status_code} {r.text[:200]}")
        if r.status_code == 200:
            rdoc = r.json()
            state["inspections"].append(rdoc["id"])
            ok(rdoc.get("kind") == "return_customer"
               and rdoc.get("ref_doc_number") == ret.get("number"),
               "dokumen menunjuk retur sumbernya", f"{rdoc.get('ref_doc_number')}")
            ok(len(rdoc.get("lines") or []) == len(before_items),
               "satu baris per barang retur (menunjuk, bukan menyalin hasilnya)",
               f"{len(rdoc.get('lines') or [])} vs {len(before_items)} barang")
            fresh_ret = db.sales_returns.find_one({"id": ret["id"]}, {"_id": 0}) or {}
            ok(fresh_ret.get("inspection_number") == rdoc.get("number"),
               "retur menyimpan NOMOR SPK yang memeriksanya (jejak dari sisi retur)",
               str(fresh_ret.get("inspection_number")))
            ok((fresh_ret.get("items") or [{}])[0].get("inspection")
               == (before_items or [{}])[0].get("inspection"),
               "hasil per barang retur TIDAK diduplikasi/ditimpa "
               "(SSOT tetap `sales_returns.items[].inspection`)")

            # tonggak perjalanan: urutan dijaga & masa depan ditolak
            r = adm.post(f"{API}/sales-returns/{ret['id']}/milestone", headers=h(ENT_A),
                         timeout=30, json={"milestone": "goods_arrived",
                                           "at": "2099-01-01T00:00:00"})
            ok(r.status_code == 400, "tonggak bertanggal MASA DEPAN → 400 "
               "(catatan kejadian, bukan ramalan)", f"HTTP {r.status_code}")
            r = adm.post(f"{API}/sales-returns/{ret['id']}/milestone", headers=h(ENT_A),
                         timeout=30, json={"milestone": "tanggal_ngawur"})
            ok(r.status_code == 400, "kode tonggak yang tidak dikenal → 400 "
               "(salah ketik tidak boleh melahirkan field baru)", f"HTTP {r.status_code}")
            r = adm.post(f"{API}/sales-returns/{ret['id']}/milestone", headers=h(ENT_A),
                         timeout=30, json={"milestone": "shipped_to_store",
                                           "note": f"{TAG}"})
            ok(r.status_code == 200 and r.json().get("shipped_to_store_at"),
               "tonggak “SJ Kirim Toko” tercatat + ber-jejak `milestones[]`",
               f"HTTP {r.status_code} · {len(r.json().get('milestones') or [])} jejak")

            # tutup SPK retur → `inspect_done_at` retur DITURUNKAN dari dokumen.
            # SPK ini lahir `draft` (tanpa petugas), jadi ia WAJIB ditugaskan &
            # dimulai dulu — persis pagar yang sama dengan SPK penerimaan PO:
            # dokumen tanpa nama petugas tidak bisa dipertanggungjawabkan.
            r = mgr.post(f"{API}/inspections/{rdoc['id']}/assign", headers=h(ENT_A),
                         timeout=30, json={"assigned_to": petugas["value"]})
            ok(r.status_code == 200, "SPK retur ditugaskan ke petugas",
               f"HTTP {r.status_code} {r.text[:120]}")
            r = adm.post(f"{API}/inspections/{rdoc['id']}/start", headers=h(ENT_A),
                         timeout=30, json={})
            ok(r.status_code == 200, "SPK retur dimulai", f"HTTP {r.status_code}")
            for ln in (rdoc.get("lines") or [])[:1]:
                r = adm.post(f"{API}/inspections/{rdoc['id']}/lines/{ln['id']}/inspect",
                             headers=h(ENT_A), timeout=60,
                             json={"color_result": "sesuai", "handfeel_result": "sesuai",
                                   "remark": f"{TAG} keluhan tidak terbukti"})
                ok(r.status_code == 200,
                   "baris retur diperiksa (tanpa poin cacat — barangnya bukan roll gudang)",
                   f"HTTP {r.status_code} {r.text[:140]}")
            r = mgr.post(f"{API}/inspections/{rdoc['id']}/finish", headers=h(ENT_A),
                         timeout=30, json={"decision": "terima", "remark": ""})
            ok(r.status_code == 200, "SPK retur ditutup dengan keputusan",
               f"HTTP {r.status_code} {r.text[:140]}")
            fresh_ret2 = db.sales_returns.find_one({"id": ret["id"]}, {"_id": 0}) or {}
            ok(bool(fresh_ret2.get("inspect_done_at")),
               "`sales_returns.inspect_done_at` DITURUNKAN dari penutupan dokumen "
               "(tidak ada endpoint manual → mustahil ada dua tanggal berbeda)",
               str(fresh_ret2.get("inspect_done_at")))

    # ══ I12 — pemilih dokumen sumber: satu pintu, dan yang ditawarkan BISA dipakai ══
    head("I12 · Pemilih dokumen sumber pop-up “Buat SPK” — panel mati ditutup di akarnya")
    # Kenapa ini wajib diuji: layar Inspeksi juga milik **gudang**, tetapi peran gudang
    # TIDAK punya `sales_return.view`. Versi pertama layar memanggil `/api/sales-returns`
    # langsung, jadi pemilih dokumennya dijawab **403** tanpa satu kalimat penjelasan —
    # terukur oleh `audit_sales_roles_ux` sebagai `warehouse → inspections →
    # /sales-returns`. Blok ini menjaga DUA hal sekaligus, dan yang kedua justru yang
    # paling mudah dirusak sesi berikutnya: pemilihnya HIDUP untuk gudang, sementara
    # izin `sales_return.view` tetap TERTUTUP — karena "obat" yang salah untuk panel
    # mati adalah melonggarkan izin, dan gate-nya akan sama-sama menghijau.
    from services.inspection_service import makloon_output_lot_ids  # noqa: PLC0415

    r = wh.get(f"{API}/sales-returns", headers=h(ENT_A), params={"page": 1}, timeout=30)
    ok(r.status_code == 403,
       "gudang tetap DITOLAK membaca daftar retur jual (izin TIDAK dilonggarkan)",
       f"HTTP {r.status_code}")
    r = wh.get(f"{API}/inspections/meta/ref-docs", headers=h(ENT_A),
               params={"kind": "return_customer"}, timeout=30)
    body = r.json() if r.status_code == 200 else {}
    items = body.get("items") or []
    ok(r.status_code == 200 and len(items) > 0,
       "…tetapi pemilih dokumen SPK dijawab 200 BERISI pilihan (panel tidak mati)",
       f"HTTP {r.status_code} · {len(items)} pilihan")
    ok(body.get("can_create") is False,
       "jawabannya jujur soal wewenang: gudang boleh MEMILIH, tidak boleh menerbitkan",
       f"can_create={body.get('can_create')}")
    kunci = sorted({k for x in items for k in x})
    ok(set(kunci) <= {"value", "label", "spk_number", "spk_status"},
       "pilihan hanya berisi nomor + nama pihak — nilai transaksi tidak dibocorkan "
       "ke peran yang tidak berhak melihatnya", f"kunci: {kunci}")
    ok(any(x.get("spk_number") for x in items),
       "dokumen yang SUDAH punya SPK ditandai di pemilih (penolakan bisa diduga "
       "sebelum tombol ditekan)",
       "; ".join(x["label"] for x in items if x.get("spk_number"))[:110])

    r = adm.get(f"{API}/inspections/meta/ref-docs", headers=h(ENT_A),
                params={"kind": "makloon_output"}, timeout=30)
    mk_items = (r.json() or {}).get("items") or [] if r.status_code == 200 else []
    ok(r.status_code == 200 and len(mk_items) > 0,
       "pemilih hasil makloon berisi order yang sudah menyerahkan hasil",
       f"HTTP {r.status_code} · {len(mk_items)} pilihan")
    ok(all(" · " in x["label"] for x in mk_items),
       "label menyebut NOMOR + NAMA MITRA — dua fakta yang hidup di tempat berbeda "
       "(`mko_number` di akar, `makloon_name` di `steps[]`)",
       "; ".join(x["label"] for x in mk_items)[:120])
    kosong = [m for m in db.makloon_orders.find(
        {"entity_id": ENT_A}, {"_id": 0, "id": 1, "mko_number": 1, "steps": 1})
        if not makloon_output_lot_ids(m)]
    ok(all(k["id"] not in {x["value"] for x in mk_items} for k in kosong),
       "order makloon yang BELUM menyerahkan hasil TIDAK ditawarkan "
       "(SPK-nya akan lahir nol baris)",
       f"{len(kosong)} tanpa hasil: {[k['mko_number'] for k in kosong]}")
    if kosong:
        r = adm.post(f"{API}/inspections", headers=h(ENT_A), timeout=30,
                     json={"kind": "makloon_output", "ref_doc_id": kosong[0]["id"]})
        ok(r.status_code == 400 and "belum menyerahkan hasil" in r.text,
           "…dan bila dipaksa lewat API: 400 ber-kalimat menuntun, bukan dokumen kosong",
           f"HTTP {r.status_code} · {str((r.json() or {}).get('detail'))[:100]}")

    bebas = [x for x in mk_items if not x.get("spk_number")]
    ok(bool(bebas), "ada order makloon yang belum ber-SPK untuk diuji", f"{len(bebas)}")
    if bebas:
        pilih = bebas[0]
        r = adm.post(f"{API}/inspections", headers=h(ENT_A), timeout=60,
                     json={"kind": "makloon_output", "ref_doc_id": pilih["value"],
                           "remark": f"{TAG} periksa hasil makloon"})
        ok(r.status_code == 200, "SPK hasil makloon diterbitkan dari pilihan itu",
           f"HTTP {r.status_code} {r.text[:200]}")
        if r.status_code == 200:
            mdoc = r.json()
            state["inspections"].append(mdoc["id"])
            ok(bool(mdoc.get("ref_doc_number"))
               and str(mdoc["ref_doc_number"]) in pilih["label"],
               "dokumen menyebut NOMOR order makloonnya, sama dengan yang tertulis "
               "di pemilih (satu definisi, dua permukaan)",
               f"{mdoc.get('ref_doc_number')} ⊂ “{pilih['label']}”")
            ok(bool(mdoc.get("supplier_name"))
               and str(mdoc["supplier_name"]) in pilih["label"],
               "…dan NAMA MITRA yang menyerahkan hasil akhirnya",
               f"{mdoc.get('supplier_name')}")
            ok(len(mdoc.get("lines") or []) > 0,
               "…dan BERISI BARIS: satu baris per gulungan hasil "
               "(SPK nol baris = dokumen mati yang tidak bisa diperiksa siapa pun)",
               f"{len(mdoc.get('lines') or [])} baris")
            ok(all(ln.get("roll_id") for ln in (mdoc.get("lines") or [])),
               "setiap baris menunjuk roll fisik yang nyata",
               f"{len([ln for ln in mdoc['lines'] if ln.get('roll_id')])} baris ber-roll")
            r2 = adm.post(f"{API}/inspections", headers=h(ENT_A), timeout=30,
                          json={"kind": "makloon_output", "ref_doc_id": pilih["value"]})
            ok(r2.status_code == 400 and str(mdoc.get("number")) in r2.text,
               "SPK KEDUA atas dokumen yang sama DITOLAK & menyebut nomor SPK yang "
               "sudah ada (satu barang, satu pemeriksa)",
               f"HTTP {r2.status_code} · {str((r2.json() or {}).get('detail'))[:110]}")

    pret_b = db.purchase_returns.find_one({"entity_id": ENT_B},
                                          {"_id": 0, "id": 1, "number": 1})
    if pret_b:
        r = adm.post(f"{API}/inspections", headers=h(ENT_A), timeout=30,
                     json={"kind": "return_supplier", "ref_doc_id": pret_b["id"]})
        ok(r.status_code == 400 and "badan usaha lain" in r.text,
           "dokumen sumber milik PT lain DITOLAK meski id-nya ditebak lewat API — "
           "pagarnya di LAYANAN, bukan hanya di pemilih",
           f"HTTP {r.status_code} · {pret_b['number']}")

    fe = (ROOT / "frontend/src/features/inspections/inspectionsApi.js").read_text(
        encoding="utf-8")
    tercela = [p for p in ("/sales-returns", "/purchase-returns", "/makloon-orders")
               if f"${{API}}{p}" in fe]
    ok(not tercela,
       "modul API layar inspeksi TIDAK memanggil endpoint modul lain — kalau kembali, "
       "panel gudang mati lagi dan `audit_sales_roles_ux` memerah",
       f"terlarang muncul: {tercela}" if tercela else "nol pemanggilan lintas modul")

    # ══ I8 — gate INV-QC dijalankan sungguhan + BUKTI-MERAH ═══════════════════
    head("I8 · Gate INV-QC-01..03 dijalankan sungguhan — dan dibuktikan BISA MEMERAH")
    rc, tail = run_gate("scripts/verify_data_integrity.py", "--only", "inspection")
    ok(rc == 0, "keadaan sekarang: invarian INV-QC HIJAU", f"exit {rc} · {tail[-200:]}")
    asli = db.inspections.find_one({"id": ins_id}, {"_id": 0, "lines": 1}) or {}
    lines_asli = asli.get("lines") or []
    rusak = [dict(x) for x in lines_asli]
    rusak[0]["points_snapshot"] = float(rusak[0].get("points_snapshot") or 0) + 7
    db.inspections.update_one({"id": ins_id}, {"$set": {"lines": rusak}})
    rc_bad, tail_bad = run_gate("scripts/verify_data_integrity.py", "--only", "inspection")
    ok(rc_bad != 0 and "INV-QC-01" in tail_bad and "FAIL" in tail_bad,
       "poin dokumen digeser sepihak → INV-QC-01 MEMERAH (invarian bukan hiasan)",
       f"exit {rc_bad} · {tail_bad[-260:]}")
    db.inspections.update_one({"id": ins_id}, {"$set": {"lines": lines_asli}})
    rc_ok, _ = run_gate("scripts/verify_data_integrity.py", "--only", "inspection")
    ok(rc_ok == 0, "dipulihkan → INV-QC kembali HIJAU", f"exit {rc_ok}")

    rc, tail = run_gate("scripts/guardrails/verify_approval_queues.py")
    ok(rc == 0, "gate `INV-APPR-01` HIJAU (pintu keputusan inspeksi punya antreannya)",
       f"exit {rc} · {tail[-160:]}")
    rc, tail = run_gate("scripts/guardrails/verify_home_kpi.py")
    ok(rc == 0, "gate `INV-HOME-01` HIJAU (KPI beranda punya opini kedua untuk tahanan)",
       f"exit {rc} · {tail[-160:]}")
    rc, tail = run_gate("scripts/guardrails/verify_qty_dual.py")
    ok(rc == 0, "gate `INV-QTY-01` HIJAU (dua satuan sampai ke dokumen inspeksi)",
       f"exit {rc} · {tail[-160:]}")


# ═══════════════════════════════════════════════════════════════════════════
def main() -> int:
    db = _db()
    before = {c: db[c].count_documents({}) for c in WATCH}
    # Sidik jari audit DIAMBIL SEBELUM login: `POST /auth/login` menulis satu baris
    # `login` + satu `sessions` per akun. POC yang lupa ini akan "0 FAIL" tetapi
    # menggelembungkan data demo setiap kali gate dijalankan (pelajaran E-8).
    audit_before = {d["id"] for d in db.audit_logs.find({}, {"_id": 0, "id": 1})}
    notif_before = {d["id"] for d in db.notifications.find({}, {"_id": 0, "id": 1})}
    ret_before = {r["id"]: r for r in db.sales_returns.find({}, {"_id": 0})}
    snap = snapshot_stock(FULL_COLLECTIONS)

    state: Dict[str, List[str]] = {"pos": [], "tasks": [], "inspections": [],
                                   "returns_touched": []}

    print("\033[1m" + "=" * 78)
    print("  POC FASE I — INSPEKSI & QC SEBAGAI DOKUMEN (SPK · tahanan warna · grade)")
    print("=" * 78 + "\033[0m")

    adm = login(ADMIN)
    mgr = login(MANAGER)
    wh = login(WAREHOUSE)
    whb = login(WAREHOUSE_B)

    try:
        run_stories(db, adm, mgr, wh, whb, state)
    except PocStop as exc:
        ok(False, f"POC berhenti lebih awal: {exc}")
    finally:
        head("I11 · CLEANUP + NOL RESIDU (diukur, bukan diklaim)")
        # 1. dokumen POC
        db.inspections.delete_many({"id": {"$in": state["inspections"]}})
        db.purchase_orders.delete_many({"id": {"$in": state["pos"]}})
        db.wms_tasks.delete_many({"id": {"$in": state["tasks"]}})
        # 2. retur data demo yang DISUNTING (inspection_id/milestone) dipulihkan
        #    ke bentuk aslinya — bukan dihapus: dokumennya milik data demo.
        for rid in set(state["returns_touched"]):
            asli = ret_before.get(rid)
            if asli:
                db.sales_returns.replace_one({"id": rid}, asli)
        # 3. stok + buku besar + kas dipulihkan EKSAK (dua sisi satu peristiwa)
        pulih = restore_stock(snap)
        ok(bool(pulih), "stok · buku besar · kas dipulihkan EKSAK (poc_stock_guard)")
        # 4. relasi hantu ke dokumen POC yang sudah dihapus
        sweep_ghost_refs(verbose=False)
        # 5. jejak audit · notifikasi · sesi yang lahir SELAMA POC
        db.sessions.delete_many({"token": {"$in": TOKENS}})
        baru_audit = {d["id"] for d in db.audit_logs.find({}, {"_id": 0, "id": 1})} - audit_before
        if baru_audit:
            db.audit_logs.delete_many({"id": {"$in": list(baru_audit)}})
        baru_notif = {d["id"] for d in db.notifications.find({}, {"_id": 0, "id": 1})} - notif_before
        if baru_notif:
            db.notifications.delete_many({"id": {"$in": list(baru_notif)}})

        after = {c: db[c].count_documents({}) for c in WATCH}
        drift = {c: (before[c], after[c]) for c in WATCH if before[c] != after[c]}
        ok(not drift, "nol residu: jumlah dokumen tiap koleksi SAMA sebelum & sesudah POC",
           f"drift={drift}" if drift else f"{len(WATCH)} koleksi identik")
        rc, tail = run_gate("scripts/verify_data_integrity.py", "--only", "inspection")
        ok(rc == 0, "invarian INV-QC tetap HIJAU sesudah pembersihan",
           f"exit {rc} · {tail[-200:]}")

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
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    except Exception:  # noqa: BLE001
        pass
    sys.exit(main())
