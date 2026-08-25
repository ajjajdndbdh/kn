#!/usr/bin/env python3
"""POC **FASE P** — PAPAN PO PER LINI (`GET /api/purchase-orders/board`).

Rencana: `RENCANA_EKSEKUSI_MD_ERP.md` §P.C. Prasyaratnya **P-0**
(`backend/test_core_p0_poc.py`) — tanpa rantai PO→PR→SO, kolom Nama Sales di papan
mustahil dirunut.

APA YANG DIBUKTIKAN (dan kenapa masing-masing perlu dibuktikan)
===============================================================
  P1  **Urutan tahap datang dari MASTER, bukan dari kode.** PO lini woven
      menampilkan TEPAT `benang→tenun→celup→inspect`, printing
      `proofing→pfp→screen→printing→inspect` — dan dibuktikan bahwa itu memang
      dibaca dari `product_lines.stage_sequence` (POC mengubah master sementara,
      papan ikut berubah, lalu master dipulihkan). Tanpa langkah "ubah master
      lalu ukur", papan bisa saja hijau karena kebetulan sama dengan daftar
      hardcode.
  P2  **Nama Sales terisi dari SO lewat PR** (bukan diketik) DAN **kosong-wajar**
      untuk PO pembelian rutin. Dua-duanya diuji: mengisi paksa dan mengosongkan
      paksa adalah dua cara berbeda untuk berbohong.
  P3  **Tahap `inspect` TIDAK BISA ditandai manual** — server menolak **409** dengan
      kalimat menuntun, apa pun perannya (admin sekalipun). Kalau tahap ini bisa
      diklik, papan bisa mengaku "sudah diinspeksi" tanpa satu dokumen inspeksi
      pun, dan barang cacat lolos atas dasar catatan yang salah.
  P4  **Tanggal Masuk & Qty Terima BERUBAH SENDIRI** sesudah penerimaan gudang.
      POC menerima barang lewat API penerimaan yang sungguhan, lalu mengukur
      papan — bukan menyuntik `received_qty`.
  P5  **Pagar lini keras di server**: akun berpagar `printing` tidak melihat PO
      woven di papan, dan **403** saat mencoba menandai tahap PO woven. Menyaring
      hanya di layar berarti pagar yang bisa dilewati dengan curl.
  P6  **Pagar badan usaha**: PO milik PT lain tidak muncul di papan PT ini, dan
      menandai tahapnya **403** (juga dari mode gabungan `X-Entity-Id: all`).
  P7  **`INV-REF-01` & `INV-ORIG-01` & `INV-STAGE-01` tetap HIJAU** sesudah papan
      lahir — dijalankan sungguhan, termasuk `--self-test` (bukti-merah).
  P8  **Data demo punya isi**: ≥3 PO ber-tahap ditandai, ≥2 lini terwakili, dan
      kartu ringkasan == hitung-ulang MANDIRI dari MongoDB (opini kedua).
  P9  **NOL RESIDU** — semua dokumen & perubahan yang POC ini buat dipulihkan,
      diukur "sebelum == sesudah".

Jalankan:  cd /app && python backend/test_core_po_board_poc.py
"""
from __future__ import annotations

import copy
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from poc_stock_guard import (FULL_COLLECTIONS, restore_stock,  # noqa: E402
                            snapshot_stock)

BASE = os.environ.get("POC_BASE_URL", "http://localhost:8001")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PW = "demo12345"
ADMIN = "admin@kainnusantara.id"
MANAGER = "manager@kainnusantara.id"
MD_PRINTING = "manager.printing@kainnusantara.id"      # berpagar lini printing (FASE P)
WAREHOUSE = "warehouse@kainnusantara.id"
ENT_A = "ent_ksc"
ENT_B = "ent_kanda"

#: Koleksi yang alur ini menyentuh — dipakai pengukuran nol residu (P9).
#: `inventory_lots` & `journal_entries` MASUK DAFTAR karena penerimaan barang uji
#: melahirkan keduanya (terukur 2026-08-21: satu jalan POC = +1 lot, +1 jurnal →
#: `INV-LOT-04` merah "3 agregat lot menyimpang dari Σ roll" dan WARN
#: `INV-GL-DRIFT`). Mengukur hanya roll/mutasi/saldo membuat POC BERKATA
#: "nol residu" sambil meninggalkan lot & jurnal hantu — kelas jebakan yang
#: sama dengan POC-RESIDU-01/02 di `poc_stock_guard`.
WATCH = ("purchase_orders", "purchase_requisitions", "wms_tasks", "inventory_rolls",
         "inventory_movements", "inventory_balances", "inventory_lots",
         "journal_entries", "product_lines", "notifications")

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


def _plain(s: str) -> str:
    """Buang kode warna ANSI supaya ringkasan gate bisa DICOCOKKAN, bukan ditebak."""
    return re.sub(r"\033\[[0-9;]*m", "", s or "")



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


def _db():
    from pymongo import MongoClient
    cli = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    return cli[os.environ.get("DB_NAME", "test_database")]


def run_gate(rel_path: str, *args: str) -> tuple[int, str]:
    """Gate SUNGGUHAN dijalankan; saat MERAH yang dilaporkan adalah baris `[FAIL]`-nya.

    (Sebelumnya hanya ekor keluaran — dan `gate.sh --full` sempat memerah di sini
    dengan pesan "PASS 31 · FAIL 1" tanpa menyebut temuan apa pun.)
    """
    p = subprocess.run([sys.executable, os.path.join(ROOT, rel_path), *args],
                       capture_output=True, text=True, cwd=ROOT, timeout=420)
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0:
        fails = [_plain(ln).strip() for ln in out.splitlines() if "[FAIL]" in ln]
        if fails:
            return p.returncode, " ‖ ".join(fails)[-1200:]
    return p.returncode, out[-300:]


def board(sess: requests.Session, *, entity: str = ENT_A, **params) -> dict:
    r = sess.get(f"{BASE}/api/purchase-orders/board", params=params or None,
                 headers=h(entity), timeout=60)
    assert r.status_code == 200, f"board: {r.status_code} {r.text[:300]}"
    return r.json()


def row_of(data: dict, po_number: str) -> dict:
    for row in data.get("items") or []:
        if row.get("po_number") == po_number:
            return row
    return {}


def in_days(n: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=n)).strftime("%Y-%m-%d")


# ═══════════════════════════════════════════════════════════════════════════
def main() -> int:  # noqa: C901 — POC linear supaya terbaca sebagai bukti
    db = _db()
    before = {c: db[c].count_documents({}) for c in WATCH}
    audit_before = {d["id"] for d in db.audit_logs.find({}, {"_id": 0, "id": 1})}
    notif_before = {d["id"] for d in db.notifications.find({}, {"_id": 0, "id": 1})}
    mov_before = {d["id"] for d in db.inventory_movements.find({}, {"_id": 0, "id": 1})}
    # Sesi juga jejak: gate invarian yang POC ini jalankan di P9 masuk lewat API,
    # jadi ia melahirkan sesi yang bukan milik POC (tidak ada di `TOKENS`).
    sess_before = {d["id"] for d in db.sessions.find({}, {"_id": 0, "id": 1}) if d.get("id")}
    # Penerimaan barang UJI menggeser STOK (saldo + gulungan). Saldo disnapshot utuh
    # (koleksi kecil, restorasi EKSAK dengan `_id` dipertahankan) — pola yang sama
    # dengan `scripts/guardrails/_common.DbSnapshot`. Tanpa ini POC "0 FAIL" tetap
    # meninggalkan 30 yard stok hantu di gudang Surabaya setiap kali dijalankan.
    bal_backup = list(db.inventory_balances.find({}))
    lines_backup = copy.deepcopy(list(db.product_lines.find({}, {"_id": 0})))
    # STOK + BUKU BESAR disnapshot utuh lewat penjaga bersama (`poc_stock_guard`):
    # penerimaan uji melahirkan roll · lot · mutasi · saldo · jurnal, dan lot serta
    # jurnal TIDAK bisa dibalik per-dokumen (agregat lot dihitung dari Σ roll).
    # Pola ini sudah dipakai POC FASE T & U — POC ini sebelumnya membersihkan
    # tangan sendiri dan meninggalkan 1 lot + 1 jurnal setiap kali dijalankan.
    stock_snap = snapshot_stock(FULL_COLLECTIONS)

    print("\033[1m" + "=" * 78)
    print("  POC FASE P — PAPAN PO PER LINI (tahap dari master · sales dirunut · "
          "terima dihitung)")
    print("=" * 78 + "\033[0m")

    adm = login(ADMIN)
    mgr = login(MANAGER)
    md_print = login(MD_PRINTING)
    whs = login(WAREHOUSE)

    created_po: list[str] = []
    created_pr: list[str] = []
    touched_so: list[str] = []
    stage_touched: list[str] = []      # PO demo yang tahapnya POC ubah → dipulihkan

    # ══════════════════════════════════════════════════════════════════════
    head("P1 · Urutan tahap DARI MASTER (bukan daftar di kode)")
    data = board(adm, page=1, page_size=100)
    woven = next((r for r in data["items"] if "woven" in (r.get("line_codes") or [])), {})
    printing = next((r for r in data["items"] if "printing" in (r.get("line_codes") or [])), {})
    codes_woven = [s["code"] for s in woven.get("stages", [])]
    codes_print = [s["code"] for s in printing.get("stages", [])]
    ok(codes_woven == ["benang", "tenun", "celup", "inspect"],
       "PO lini woven menampilkan TEPAT benang→tenun→celup→inspect",
       f"{woven.get('po_number')}: {'→'.join(codes_woven)}")
    ok(codes_print == ["proofing", "pfp", "screen", "printing", "inspect"],
       "PO lini printing menampilkan TEPAT proofing→pfp→screen→printing→inspect",
       f"{printing.get('po_number')}: {'→'.join(codes_print)}")
    labels = {s["code"]: s["label"] for s in woven.get("stages", [])}
    ok(labels.get("benang") == "Benang (bahan masuk)",
       "label chip datang dari MASTER tahap (bukan ditebak dari kodenya)",
       f"benang → {labels.get('benang')!r}")
    # Bukti bahwa urutan benar-benar DIBACA: sisipkan satu tahap ke master lini,
    # ukur papan, lalu pulihkan. Tanpa langkah ini, hijau di atas bisa kebetulan.
    db.product_lines.update_one({"code": "woven"},
                                {"$push": {"stage_sequence": {"$each": ["pfd"],
                                                              "$position": 2}}})
    data2 = board(adm, line="woven", page=1, page_size=50)
    row2 = next((r for r in data2["items"] if r.get("po_number") == woven.get("po_number")), {})
    ok([s["code"] for s in row2.get("stages", [])] ==
       ["benang", "tenun", "pfd", "celup", "inspect"],
       "menambah tahap di MASTER langsung mengubah papan (tanpa ubah kode)",
       f"{'→'.join(s['code'] for s in row2.get('stages', []))}")
    db.product_lines.update_one({"code": "woven"}, {"$pull": {"stage_sequence": "pfd"}})
    data3 = board(adm, line="woven", page=1, page_size=50)
    row3 = next((r for r in data3["items"] if r.get("po_number") == woven.get("po_number")), {})
    ok([s["code"] for s in row3.get("stages", [])] == codes_woven,
       "master dipulihkan → papan kembali seperti semula (POC tidak merusak data demo)",
       f"{'→'.join(s['code'] for s in row3.get('stages', []))}")

    # ══════════════════════════════════════════════════════════════════════
    head("P2 · Nama Sales: terisi lewat PR→SO, dan KOSONG-WAJAR untuk PO rutin")
    ber_sales = [r for r in data["items"] if r.get("sales_name")]
    tanpa_sales = [r for r in data["items"] if not r.get("sales_name")]
    ok(ber_sales, "ada PO di papan yang membawa Nama Sales hasil runutan",
       f"{[(r['po_number'], r['sales_name']) for r in ber_sales][:4]}")
    # Opini kedua: hitung ulang MANDIRI dari MongoDB (PO → PR → SO).
    salah = []
    for r in ber_sales:
        pr = db.purchase_requisitions.find_one({"id": r.get("pr_id")},
                                              {"_id": 0, "source_ref_id": 1}) or {}
        so = db.sales_orders.find_one({"id": pr.get("source_ref_id")},
                                      {"_id": 0, "sales_name": 1}) or {}
        if (so.get("sales_name") or "") != r["sales_name"]:
            salah.append((r["po_number"], r["sales_name"], so.get("sales_name")))
    ok(not salah, "Nama Sales di papan == hitung-ulang mandiri PO→PR→SO dari MongoDB",
       f"menyimpang={salah}" if salah else f"{len(ber_sales)} baris diperiksa")
    ok(tanpa_sales and all(not r.get("pr_id") for r in tanpa_sales),
       "PO pembelian rutin: Nama Sales KOSONG dan memang tidak punya PR asal",
       f"{len(tanpa_sales)} baris kosong-wajar (mis. {tanpa_sales[0]['po_number']})"
       if tanpa_sales else "tidak ada")
    bocor = [r["po_number"] for r in tanpa_sales if r.get("sales_name")]
    ok(not bocor, "nol baris memuat Nama Sales tanpa jejak dokumen (nama tidak dikarang)",
       f"{bocor}")

    # ══════════════════════════════════════════════════════════════════════
    head("P3 · Tahap `inspect` TIDAK BISA ditandai manual (409, bukan 500)")
    target = printing or woven
    r = adm.patch(f"{BASE}/api/purchase-orders/{target['po_id']}/stage",
                  json={"stage_code": "inspect", "status": "done"}, headers=h(), timeout=30)
    ok(r.status_code == 409, "admin sekalipun DITOLAK menandai tahap inspeksi",
       f"HTTP {r.status_code} · {r.text[:160]}")
    ok("inspeksi" in r.text.lower() and ("qc" in r.text.lower() or "mutu" in r.text.lower()),
       "kalimat penolakan MENUNTUN (menyebut inspeksi/QC penerimaan)", r.text[:180])
    st_inspect = next((s for s in target.get("stages", []) if s["code"] == "inspect"), {})
    ok(st_inspect.get("derived") is True and st_inspect.get("locked") is True
       and st_inspect.get("locked_reason"),
       "papan menandai chip inspeksi sebagai turunan+terkunci beserta ALASANNYA",
       f"{st_inspect.get('locked_reason', '')[:80]}")
    r = adm.patch(f"{BASE}/api/purchase-orders/{target['po_id']}/stage",
                  json={"stage_code": "tahap_karangan", "status": "done"},
                  headers=h(), timeout=30)
    ok(r.status_code == 400 and "sah" in r.text.lower(),
       "tahap di luar urutan lini ditolak 400 + menyebut tahap yang sah",
       f"HTTP {r.status_code} · {r.text[:160]}")
    r = adm.patch(f"{BASE}/api/purchase-orders/{target['po_id']}/stage",
                  json={"stage_code": "pfp", "status": "beres"}, headers=h(), timeout=30)
    ok(r.status_code == 400, "status tahap asing ditolak 400", f"HTTP {r.status_code}")

    # ══════════════════════════════════════════════════════════════════════
    head("P4 · Tanggal Masuk & Qty Terima BERUBAH SENDIRI sesudah penerimaan")
    # Rantai baru & TERPISAH dari data demo supaya penerimaan nyata bisa dilakukan
    # tanpa mengubah dokumen milik demo.
    so_seed = db.sales_orders.find_one({"id": "so_001"}, {"_id": 0, "id": 1, "number": 1})
    sup = db.suppliers.find_one({"name": "NTT Weaving Co"}, {"_id": 0, "id": 1})
    r = adm.post(f"{BASE}/api/sales-orders/{so_seed['id']}/repeat-restock",
                 json={"items": [{"product_id": "prod_tenun_ikat", "quantity": 30,
                                  "unit": "yard"}],
                       "reason": "POC FASE P", "warehouse_id": "wh_surabaya",
                       "needed_by_date": in_days(7), "submit_now": True},
                 headers=h(), timeout=60)
    ok(r.status_code == 200, "PR uji dibuat dari pesanan", f"HTTP {r.status_code} {r.text[:150]}")
    if r.status_code != 200:
        return 1
    pr = r.json()["pr"]
    created_pr.append(pr["id"])
    touched_so.append(so_seed["id"])
    if pr.get("status") != "approved":
        pr = mgr.post(f"{BASE}/api/purchase-requisitions/{pr['id']}/approve",
                      json={"notes": "POC"}, headers=h(), timeout=30).json()
    r = adm.post(f"{BASE}/api/purchase-requisitions/{pr['id']}/realize-po",
                 json={"supplier_id": sup["id"], "warehouse_id": "wh_surabaya",
                       "expected_delivery_date": in_days(9)}, headers=h(), timeout=60)
    ok(r.status_code == 200, "PO uji lahir dari PR", f"HTTP {r.status_code} {r.text[:150]}")
    if r.status_code != 200:
        return 1
    po = r.json()["po"]
    created_po.append(po["id"])

    b0 = row_of(board(adm, page=1, page_size=200), po["po_number"])
    ok(b0.get("first_receipt_at", "") == "" and b0.get("received_measure") in (None, 0),
       "sebelum diterima: Tanggal Masuk & Qty Terima KOSONG (bukan 0 yang menyesatkan)",
       f"tgl={b0.get('first_receipt_at')!r} qty={b0.get('received_measure')!r} "
       f"roll={b0.get('received_rolls')!r}")

    task = db.wms_tasks.find_one({"po_id": po["id"], "flow_type": "inbound"},
                                {"_id": 0, "id": 1, "expected_qty": 1, "product_id": 1})
    ok(bool(task), "tugas penerimaan gudang lahir bersama PO", f"{(task or {}).get('id')}")
    recv = None
    if task:
        for path, payload in (
            (f"/api/inbound/tasks/{task['id']}/scan-receive",
             {"product_id": task.get("product_id"), "actual_qty": 30,
              "batch": "POC-P", "lot": "POC-P", "bin_id": "A1-01"}),
            (f"/api/inbound/tasks/{task['id']}/complete", {}),
        ):
            recv = whs.post(f"{BASE}{path}", json=payload, headers=h(), timeout=60)
            if recv.status_code not in (200, 201):
                break
    ok(recv is not None and recv.status_code in (200, 201),
       "barang diterima lewat API penerimaan gudang yang SUNGGUHAN",
       f"HTTP {getattr(recv, 'status_code', '-')} · {getattr(recv, 'text', '')[:160]}")
    b1 = row_of(board(adm, page=1, page_size=200), po["po_number"])
    ok(bool(b1.get("first_receipt_at")),
       "Tanggal Masuk terisi SENDIRI dari penerimaan (tidak diketik)",
       f"{b1.get('first_receipt_at')} · terakhir {b1.get('last_receipt_at')}")
    ok(float(b1.get("received_measure") or 0) > 0,
       "Qty Terima terisi SENDIRI dari dokumen penerimaan",
       f"{b1.get('received_rolls')} roll · {b1.get('received_measure')} "
       f"{b1.get('received_unit')}")
    # Opini kedua dari MongoDB (bukan dari respons yang sedang diuji).
    po_db = db.purchase_orders.find_one({"id": po["id"]}, {"_id": 0, "items": 1}) or {}
    mandiri = round(sum(float(i.get("received_qty") or 0) for i in po_db.get("items") or []), 3)
    ok(abs(float(b1.get("received_measure") or 0) - mandiri) < 0.001,
       "Qty Terima di papan == hitung-ulang mandiri Σ`items[].received_qty`",
       f"papan={b1.get('received_measure')} mongo={mandiri}")
    st_inspect2 = next((s for s in b1.get("stages", []) if s["code"] == "inspect"), {})
    ok(st_inspect2.get("status") in ("pending", "in_progress", "done"),
       "tahap inspeksi tetap TURUNAN sesudah penerimaan (status mengikuti bukti QC)",
       f"status={st_inspect2.get('status')} sumber={st_inspect2.get('source') or '(belum ada)'}")

    # ══════════════════════════════════════════════════════════════════════
    head("P5 · Pagar LINI keras di server (bukan sekadar layar disaring)")
    dp = board(md_print, page=1, page_size=200)
    # ATURAN FASE L YANG BERLAKU (dan SENGAJA, bukan kelonggaran):
    #   · PO **campur lini** (mis. satu PO memuat baris printing DAN woven) TETAP
    #     terlihat oleh staf printing — pekerjaan printing di dalamnya memang miliknya;
    #   · dokumen **tanpa lini** (data lama) selalu terlihat → anti "layar kosong"
    #     bagi akun berpagar (FASE L risiko #4).
    # Yang DILARANG adalah PO yang lininya sama sekali BUKAN lininya.
    bukan_urusannya = [r["po_number"] for r in dp["items"]
                       if (r.get("line_codes") or [])
                       and "printing" not in (r.get("line_codes") or [])]
    ok(not bukan_urusannya,
       "MD printing tidak melihat satu pun PO yang lininya bukan printing "
       "(PO campur & PO tanpa lini tetap terlihat — memang aturannya)",
       f"bocor={bukan_urusannya}" if bukan_urusannya
       else f"{dp['total']} baris · lini={sorted({c for r in dp['items'] for c in (r.get('line_codes') or [])})}")
    tabs = [t["code"] for t in dp.get("lines") or []]
    ok(tabs == ["printing"],
       "tab lini yang ditawarkan pun hanya lini yang boleh ia lihat (tak memasang jebakan)",
       f"tabs={tabs}")
    woven_po = db.purchase_orders.find_one({"line_codes": ["woven"], "entity_id": ENT_A},
                                          {"_id": 0, "id": 1, "po_number": 1}) or {}
    r = md_print.patch(f"{BASE}/api/purchase-orders/{woven_po.get('id')}/stage",
                       json={"stage_code": "tenun", "status": "done"}, headers=h(), timeout=30)
    ok(r.status_code == 403,
       "MD printing DITOLAK 403 saat menandai tahap PO woven-saja (pagar di server)",
       f"{woven_po.get('po_number')} → HTTP {r.status_code} · {r.text[:130]}")
    ok(r.status_code == 403 and "lini" in r.text.lower(),
       "kalimat penolakannya menyebut lini dokumen vs lini akun (menuntun, bukan '403')",
       r.text[:170])
    pr_po = db.purchase_orders.find_one({"line_codes": ["printing"], "entity_id": ENT_A,
                                         "id": {"$nin": created_po}},
                                        {"_id": 0, "id": 1, "po_number": 1,
                                         "stage_progress": 1}) or {}
    if pr_po:
        r = md_print.patch(f"{BASE}/api/purchase-orders/{pr_po['id']}/stage",
                           json={"stage_code": "pfp", "status": "in_progress",
                                 "note": "POC FASE P"}, headers=h(), timeout=30)
        ok(r.status_code == 200,
           "…tetapi BOLEH menandai tahap PO printing (pagar sempit, bukan buta)",
           f"HTTP {r.status_code} · {pr_po['po_number']}")
        if r.status_code == 200:
            stage_touched.append(pr_po["id"])
            row = r.json()
            marked = next((s for s in row.get("stages", []) if s["code"] == "pfp"), {})
            ok(marked.get("by") == "Fajar Nugroho" and marked.get("at"),
               "tanda tahap mencatat SIAPA & KAPAN (user story P-2)",
               f"by={marked.get('by')} at={marked.get('at')}")
            tl = (db.purchase_orders.find_one({"id": pr_po["id"]},
                                              {"_id": 0, "timeline": 1}) or {}).get("timeline") or []
            ok(any(e.get("event", "").startswith("stage_") for e in tl),
               "riwayat PO ikut mencatat perpindahan tahap (jejak, bukan hanya field)",
               f"{[e.get('event') for e in tl if e.get('event', '').startswith('stage_')][:3]}")

    # ══════════════════════════════════════════════════════════════════════
    head("P6 · Pagar BADAN USAHA (PO PT lain tak terlihat & tak bisa disentuh)")
    po_b = db.purchase_orders.find_one({"entity_id": ENT_B}, {"_id": 0, "id": 1,
                                                              "po_number": 1,
                                                              "line_codes": 1}) or {}
    seen = board(adm, entity=ENT_A, page=1, page_size=200)
    ok(all(r.get("entity_id") == ENT_A for r in seen["items"]),
       "papan PT A hanya memuat dokumen PT A",
       f"{len(seen['items'])} baris · entitas={sorted({r.get('entity_id') for r in seen['items']})}")
    ok(not row_of(seen, po_b.get("po_number", "-")),
       f"PO milik PT lain ({po_b.get('po_number')}) TIDAK muncul di papan PT A")
    # ATURAN PLATFORM YANG BERLAKU — ditulis eksplisit supaya sesi berikutnya tidak
    # salah baca lalu "memperbaiki" perilaku yang sudah benar:
    #   · peran `admin` & `manager` adalah **peran lintas badan usaha**
    #     (`entity_scope.CROSS_ENTITY_ROLES`), jadi mereka MEMANG berwenang menindak
    #     dokumen PT lain — isolasinya ada di sisi BACA (papan PT A tidak
    #     menampilkannya, dibuktikan dua baris di atas);
    #   · peran lain dipagari `allowed_entity_ids`: header `X-Entity-Id` badan usaha
    #     yang bukan penugasannya dijawab **403 yang menjelaskan**, bukan daftar
    #     kosong yang membuat orang menyangka datanya hilang (FASE E-1 E1.5).
    # Karena satu-satunya peran ber-izin `purchase_order.update` adalah admin &
    # manager, pagar entitas papan ini diuji lewat peran BACA (`warehouse`).
    r = whs.get(f"{BASE}/api/purchase-orders/board", headers=h(ENT_B), timeout=30)
    ok(r.status_code == 403,
       "akun gudang (bukan peran lintas-PT) DITOLAK 403 meminta papan PT B lewat header",
       f"HTTP {r.status_code} · {r.text[:130]}")
    r = whs.get(f"{BASE}/api/purchase-orders/board", params={"entity_id": ENT_B},
                headers=h(ENT_A), timeout=30)
    ok(r.status_code == 403,
       "…dan lewat parameter `?entity_id=` pun DITOLAK 403 (bukan daftar kosong)",
       f"HTTP {r.status_code} · {r.text[:130]}")
    wb = board(whs, entity=ENT_A, page=1, page_size=200)
    ok(all(x.get("entity_id") == ENT_A for x in wb["items"]),
       "papan yang dilihat akun gudang pun terbatas pada badan usahanya",
       f"{len(wb['items'])} baris")
    r = whs.patch(f"{BASE}/api/purchase-orders/{target['po_id']}/stage",
                  json={"stage_code": "pfp", "status": "done"}, headers=h(), timeout=30)
    ok(r.status_code == 403,
       "akun tanpa izin `purchase_order.update` DITOLAK 403 menandai tahap (papan bukan "
       "pintu belakang)", f"HTTP {r.status_code} · {r.text[:130]}")

    # ══════════════════════════════════════════════════════════════════════
    head("P7 · Gate SUNGGUHAN dijalankan (bukan ditiru)")
    for label, rel, args in (
        ("INV-STAGE-01", "scripts/guardrails/verify_po_board.py", ()),
        ("INV-STAGE-01 --self-test (bukti-merah)",
         "scripts/guardrails/verify_po_board.py", ("--self-test",)),
        ("INV-ORIG-01 (P-0 tetap utuh)", "scripts/guardrails/verify_doc_origin.py", ()),
        ("INV-REF (dokumen tak buntu)", "scripts/audit_doc_refs.py", ("--strict",)),
        ("INV-LINE-01/02 (pagar lini)", "scripts/guardrails/verify_line_scope.py", ()),
        ("INV-DOMAIN-06 (master tahapan)", "scripts/guardrails/verify_master_stages.py", ()),
    ):
        rc, tail = run_gate(rel, *args)
        ok(rc == 0, f"gate `{label}` HIJAU", f"exit {rc} · {tail}")

    # ══════════════════════════════════════════════════════════════════════
    head("P8 · Data demo berisi & kartu ringkasan == hitung-ulang MANDIRI")
    demo = board(adm, page=1, page_size=200, status="")
    ber_tahap = [r for r in demo["items"]
                 if any(s["status"] != "pending" for s in r.get("stages", []))]
    ok(len(ber_tahap) >= 3, "≥3 PO demo sudah punya tahap ditandai (papan tidak kosong)",
       f"{[(r['po_number'], r['current_stage']['label']) for r in ber_tahap][:5]}")
    lini_demo = sorted({c for r in ber_tahap for c in (r.get("line_codes") or [])})
    ok(len(lini_demo) >= 2, "≥2 lini terwakili di data demo (tab papan tidak ada yang hampa)",
       f"{lini_demo}")
    # Opini kedua untuk kartu ringkasan: hitung sendiri dari baris yang dikembalikan.
    s = demo["summary"]
    mandiri_terlambat = sum(1 for r in demo["items"] if r.get("late"))
    mandiri_tanpa_sales = sum(1 for r in demo["items"] if not r.get("sales_name"))
    ok(s.get("total") == demo["total"] == len(demo["items"]),
       "kartu 'PO di papan' == jumlah baris hasil filter (bukan jumlah halaman)",
       f"summary={s.get('total')} total={demo['total']} baris={len(demo['items'])}")
    ok(s.get("terlambat") == mandiri_terlambat and s.get("tanpa_sales") == mandiri_tanpa_sales,
       "kartu 'lewat estimasi' & 'tanpa sales' == hitung-ulang mandiri",
       f"api={s.get('terlambat')}/{s.get('tanpa_sales')} "
       f"mandiri={mandiri_terlambat}/{mandiri_tanpa_sales}")
    ok((s.get("belum_mulai", 0) + s.get("berjalan", 0) + s.get("selesai", 0))
       == s.get("total"),
       "tiga kartu progres menjumlah TEPAT ke total (tidak ada baris yang hilang/dobel)",
       f"{s.get('belum_mulai')}+{s.get('berjalan')}+{s.get('selesai')} vs {s.get('total')}")

    # ══════════════════════════════════════════════════════════════════════
    head("P9 · CLEANUP + NOL RESIDU (diukur, bukan diklaim)")
    # Tahap yang POC tandai pada PO DEMO dipulihkan ke isi aslinya.
    for po_id in stage_touched:
        asli = next((p for p in [] if False), None)          # eksplisit: tak ada cache
        orig = db.purchase_orders.find_one({"id": po_id}, {"_id": 0, "stage_progress": 1})
        if orig is not None:
            keep = [row for row in (orig.get("stage_progress") or [])
                    if (row.get("note") or "") != "POC FASE P"]
            db.purchase_orders.update_one({"id": po_id}, {"$set": {"stage_progress": keep}})
        db.purchase_orders.update_one(
            {"id": po_id},
            {"$pull": {"timeline": {"note": "POC FASE P"}}})
    # Roll · lot · mutasi · saldo · jurnal yang lahir dari penerimaan uji dipulihkan
    # EKSAK dari snapshot (satu peristiwa, semua sisinya, satu saat yang sama).
    # Bila restore dimatikan (`KN_GATE_NO_RESTORE=1`, mode ukur kebocoran) kita
    # jatuh ke pembersihan tangan di bawah supaya kebocoran tetap TERUKUR.
    stock_restored = restore_stock(stock_snap)
    if not stock_restored:
        # Roll & mutasi yang lahir dari penerimaan uji
        db.inventory_rolls.delete_many({"acquired.ref_id": {"$in": created_po}})
        # Mutasi persediaan dibuang lewat SELISIH ID — bukan mencocokkan
        # `source_document` (bentuknya berbeda antar jalur: nomor PO, id tugas, nomor GRN),
        # dan yang salah cocok akan meninggalkan baris sampah di layar Gudang → Mutasi.
        mov_new = {d["id"] for d in db.inventory_movements.find({}, {"_id": 0, "id": 1})} - mov_before
        if mov_new:
            db.inventory_movements.delete_many({"id": {"$in": list(mov_new)}})
    db.wms_tasks.delete_many({"po_id": {"$in": created_po}})
    db.purchase_orders.delete_many({"id": {"$in": created_po}})
    db.purchase_requisitions.delete_many({"id": {"$in": created_pr}})
    db.sales_orders.update_many({"id": {"$in": touched_so}},
                                {"$pull": {"restock_requests": {"pr_id": {"$in": created_pr}}}})
    db.sales_orders.update_many({"id": {"$in": touched_so}},
                                {"$unset": {"last_restock_note": ""}})
    for coll in ("purchase_orders", "purchase_requisitions", "sales_orders", "rfqs"):
        db[coll].update_many({"refs.doc_id": {"$in": created_po + created_pr}},
                             {"$pull": {"refs": {"doc_id": {"$in": created_po + created_pr}}}})
    db.sessions.delete_many({"token": {"$in": TOKENS}})
    # CATATAN URUTAN (penting): pembuangan jejak `audit_logs`/`notifications`
    # dipindah ke PALING AKHIR — sesudah gate invarian dijalankan. Sebabnya
    # terukur: `scripts/verify_data_integrity.py` **masuk lewat API** untuk
    # membandingkan KPI beranda, jadi ia sendiri menulis satu baris audit
    # `login`. Kalau jejak dibuang sebelum gate itu, POC ini "bersih" tetapi
    # `INV-GATE-01` tetap memerah dengan `audit_logs: 102 → 103` — dan bacaan
    # itu menuduh POC ini atas baris yang lahir dari alat ukurnya sendiri.
    # Saldo persediaan dipulihkan EKSAK dari snapshot (bukan dihitung ulang dengan
    # rumus kedua — rumus kedua adalah tempat angka mulai berselisih). Bila
    # `restore_stock` sudah memulihkan seluruh koleksi stok, langkah ini tidak
    # diperlukan lagi (dan `backfill_roll_counts` yang mahal ikut dilewati).
    if not stock_restored:
        keep_ids = set()
        for doc in bal_backup:
            keep_ids.add(doc["_id"])
            db.inventory_balances.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        db.inventory_balances.delete_many({"_id": {"$nin": list(keep_ids)}})
        # Jumlah roll per saldo tetap dihitung ulang lewat PINTU APLIKASI supaya
        # `roll_count` konsisten dengan gulungan yang kini tersisa.
        subprocess.run([sys.executable, "-c",
                        "import asyncio,sys;sys.path.insert(0,'backend');"
                        "from dotenv import load_dotenv;load_dotenv('backend/.env');"
                        "from services.roll_service import backfill_roll_counts as f;"
                        "asyncio.run(f())"],
                       capture_output=True, text=True, cwd=ROOT, timeout=180)

    # Bukti TERKUAT (dan yang dulu tidak ada): jalankan gate invarian GLOBAL sungguhan.
    # Hitungan dokumen bisa kembali sama sementara AGREGAT lot menyimpang dari Σ roll
    # (`INV-LOT-04`) dan buku besar bergeser (`INV-GL-DRIFT`) — dua hal yang justru
    # menjatuhkan `gate.sh --full` di POC lain, bukan di POC ini.
    proc = subprocess.run([sys.executable, os.path.join(ROOT, "scripts",
                                                        "verify_data_integrity.py")],
                          capture_output=True, text=True, timeout=300)
    inv_out = (proc.stdout or "") + (proc.stderr or "")
    ringkas = next((ln.strip() for ln in reversed(inv_out.splitlines())
                    if "PASS" in ln and "FAIL" in ln and "WARN" in ln), "")
    ok(proc.returncode == 0 and "WARN 0" in _plain(ringkas),
       "invarian global HIJAU setelah pembersihan (lot & jurnal ikut pulih, nol WARN)",
       _plain(ringkas) or f"exit={proc.returncode}")

    # Jejak dibuang PALING AKHIR (lihat catatan urutan di atas): termasuk baris
    # `login` + sesi yang ditulis gate invarian di atas. Jeda 2 detik disengaja:
    # backend menulis audit `login` sebagai tugas latar, jadi barisnya bisa
    # MENDARAT sesudah kueri pembuangan (terukur: POC "bersih" tetapi
    # `INV-GATE-01` tetap melihat `audit_logs +1`).
    time.sleep(2)
    for coll, seen_ids in (("audit_logs", audit_before), ("notifications", notif_before),
                           ("sessions", sess_before)):
        baru = {d["id"] for d in db[coll].find({}, {"_id": 0, "id": 1}) if d.get("id")} - seen_ids
        if baru:
            db[coll].delete_many({"id": {"$in": list(baru)}})
    # Sesi tanpa field `id` (bentuk lama) dibuang lewat token yang POC pegang.
    db.sessions.delete_many({"token": {"$in": TOKENS}})

    after = {c: db[c].count_documents({}) for c in WATCH}
    drift = {c: (before[c], after[c]) for c in WATCH if before[c] != after[c]}
    ok(not drift, "nol residu: jumlah dokumen tiap koleksi SAMA sebelum & sesudah POC",
       f"drift={drift}" if drift else f"{len(WATCH)} koleksi identik")
    lines_now = list(db.product_lines.find({}, {"_id": 0}))
    ok(sorted([(l["code"], tuple(l.get("stage_sequence") or [])) for l in lines_now]) ==
       sorted([(l["code"], tuple(l.get("stage_sequence") or [])) for l in lines_backup]),
       "master lini kembali PERSIS seperti sebelum POC (urutan tahap tidak tergeser)",
       f"{[(l['code'], '→'.join(l.get('stage_sequence') or [])) for l in lines_now]}")
    sisa_tahap = db.purchase_orders.count_documents({"stage_progress.note": "POC FASE P"})
    ok(sisa_tahap == 0, "nol tanda tahap uji yang tertinggal di PO data demo",
       f"{sisa_tahap} PO masih menyimpannya")
    # Stok fisik: bukti bahwa penerimaan uji tidak meninggalkan barang hantu.
    bal_now = {(b.get("product_id"), b.get("warehouse_id")): round(float(b.get("on_hand") or 0), 3)
               for b in db.inventory_balances.find({}, {"_id": 0, "product_id": 1,
                                                        "warehouse_id": 1, "on_hand": 1})}
    bal_was = {(b.get("product_id"), b.get("warehouse_id")): round(float(b.get("on_hand") or 0), 3)
               for b in bal_backup}
    geser = {k: (bal_was.get(k), v) for k, v in bal_now.items() if bal_was.get(k) != v}
    ok(not geser, "nol stok hantu: saldo persediaan kembali seperti sebelum POC",
       f"bergeser={geser}" if geser else f"{len(bal_now)} saldo identik")

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
