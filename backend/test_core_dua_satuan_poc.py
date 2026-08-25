#!/usr/bin/env python3
"""POC FASE U — DUA SATUAN (jumlah roll + yard/kg/panel) di semua dokumen.

Permintaan pemilik (sesi 2026-08-19): *"catat roll dan yard/kg dan panel — jadi ada
2 satuan yang ditulis... dan ini seharusnya sudah ada di semuanya, di WMS, di sales,
di SO dll."* Keputusan pemilik yang dieksekusi di sini:
  · **PANEL berbeda per pesanan** → faktor konversi disimpan di BARIS DOKUMEN
    (`unit_factor` + `unit_factor_to`), bukan di master produk; hak itu datang dari
    master satuan (`uoms.factor_per_document`) supaya tidak lahir pintu ke-3.
  · **PDF & CSV = DUA KOLOM terpisah** (`Roll` | `Jumlah`), bukan satu kolom
    gabungan — kolom yang berdiri sendiri bisa dijumlah.
  · **Dokumen lama** tampil **"—"** di layar & PDF, dan **sel KOSONG** di CSV
    (sel "—" mematikan SUM Excel pada kolom itu).

ENAM HAL YANG DIBUKTIKAN DI SINI (RENCANA_EKSEKUSI_MD_ERP.md §U.F)
=================================================================
  U1  SATU angka yang diketik admin muncul SAMA di ENAM tampilan: PO · tugas gudang ·
      papan PO (turunan) · kartu stok · PDF (PO & GRN) · CSV. 12 roll × 45 yard = 540
      yard dipesan, 12 roll benar-benar lahir, dan tak satu pun tampilan menghitung
      ulang sendiri.
  U2  RETUR 2 roll → semua angka turun SERENTAK (12→10 roll · 540→450 yard), dan
      jumlah roll retur DIHITUNG dari roll yang dipilih (bukan diketik).
  U3  Satuan datang dari MASTER: lini knit memakai **kg**, printing memakai
      **panel** dengan faktor per dokumen; satuan yang TIDAK berhak membawa faktor
      (yard) ditolak 400 dengan kalimat menuntun.
  U4  Dokumen LAMA (tanpa `qty_rolls`) tampil **"—"** di PDF dan **sel kosong** di
      CSV — BUKAN "0 roll" yang menyatakan "tidak ada gulungan".
  U5  Gate `INV-UOM-02` benar-benar memerah untuk satuan asing (`hasta`) yang
      tersimpan di dokumen, lalu hijau lagi setelah dibereskan.
  U6  Roll ber-yard yang JUGA ditimbang menyimpan `secondary_measures={"kg":…}`
      dan kartu roll menampilkan kedua ukuran.
  U7  NOL RESIDU: dokumen uji dihapus, stok + buku besar dipulihkan EKSAK (pola
      T9 FASE T), DAN jumlah jejak (`audit_logs` · `notifications` · `sessions`)
      sebelum == sesudah — POC ini membuktikan sendiri bahwa ia tidak menitipkan
      pekerjaan bersih-bersih ke gate di ujung (POC-RESIDU-03).

Jalankan:  cd /app && python backend/test_core_dua_satuan_poc.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from poc_stock_guard import (FULL_COLLECTIONS, restore_stock,  # noqa: E402
                            snapshot_stock)

BASE = os.environ.get("POC_BASE_URL", "http://localhost:8001")
API = f"{BASE}/api"
ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FE_UTILS = ROOT / "frontend" / "src" / "utils"
PW = "demo12345"
ADMIN = "admin@kainnusantara.id"
MANAGER = "manager@kainnusantara.id"   # pemisahan tugas (SoD): pembuat ≠ penyetuju
WAREHOUSE = "warehouse@kainnusantara.id"
ENTITY = "ent_ksc"
WH = "wh_jakarta"

# Produk demo — dipilih karena mewakili tiga satuan yang diminta pemilik.
P_WOVEN = "prod_tenun_ikat"          # base yard  (lini woven)
P_YARN = "prod_benang_katun"         # base kg    (lini woven, tahap yarn)
P_PRINT = "prod_batik_mega"          # base yard  (lini printing → dipesan per PANEL)

TAG = f"POC-U-{uuid.uuid4().hex[:6].upper()}"
ROLLS_ORDERED = 12
YARD_PER_ROLL = 45.0
QTY_TOTAL = ROLLS_ORDERED * YARD_PER_ROLL      # 540 yard
ROLLS_RETURNED = 2

PASS = 0
FAIL = 0

# ── POC-RESIDU-03 (terukur 2026-08-20, sesi FASE U) ──────────────────────────
# Koleksi JEJAK yang ikut diperiksa "sebelum == sesudah" (pola T9 FASE T, satu
# lapis lebih dalam lagi). Dua residu nyata yang ditemukan gate `INV-GATE-01`
# setelah POC ini melaporkan "0 FAIL":
#   · `audit_logs` +3 — `audit_before` dulu diambil SESUDAH tiga kali `login()`,
#     sementara `POST /api/auth/login` menulis satu jejak audit per login
#     (`routers/auth.py`: `await audit(user["name"], "login", …)`). Tiga jejak itu
#     masuk ke dalam "keadaan sebelum", jadi tidak pernah ikut terhapus.
#   · `notifications` +4 — pembersihnya menembak field yang TIDAK ADA
#     (`{"message": {"$regex": TAG}}`); koleksi `notifications` memakai
#     `title`/`body`/`ref`. Baris itu selalu menghapus 0 dokumen tanpa bersuara.
#   · `sessions` +3 — tiga sesi login POC tidak pernah dihapus siapa pun.
# Pelajarannya sama dengan POC-RESIDU-01/02: **"0 FAIL" bukan bukti nol residu**
# kalau POC-nya tidak pernah MEMERIKSA residu itu sendiri. Karena itu jumlah
# ketiga koleksi ini kini dibandingkan sebelum vs sesudah di dalam POC — jadi
# pembersih yang salah sasaran memerahkan POC-nya SENDIRI, bukan gate di ujung.
TRAIL_COLLECTIONS = ["audit_logs", "notifications", "sessions"]

# Token sesi yang dilahirkan `login()` — dihapus di CLEANUP supaya POC tidak
# menumbuhkan `sessions` setiap kali dijalankan.
SESSION_TOKENS: List[str] = []


def ok(cond: Any, label: str, extra: str = "") -> bool:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         → {extra}" if extra else ""))
    return bool(cond)


def head(t: str):
    print(f"\n── {t} " + "─" * max(0, 80 - len(t)))


def login(email: str) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": PW}, timeout=30)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:300]}"
    token = r.json()["token"]
    SESSION_TOKENS.append(token)          # POC-RESIDU-03 — dihapus di CLEANUP
    s.headers.update({"Authorization": f"Bearer {token}",
                      "Content-Type": "application/json",
                      "X-Entity-Id": ENTITY})
    return s


def _db():
    from pymongo import MongoClient
    cli = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017").strip('"'))
    return cli[os.environ.get("DB_NAME", "test_database").strip('"')]


# ═══════════════════════════════════════════════════════════════════════════
# HELPER — alur PO → terima → roll
# ═══════════════════════════════════════════════════════════════════════════
def supplier_id(db) -> str:
    s = db.suppliers.find_one({"entity_id": ENTITY, "status": {"$ne": "inactive"}},
                              {"_id": 0, "id": 1})
    return (s or {}).get("id", "")


def create_po(sess, items: List[Dict[str, Any]], note: str,
              expect_error: bool = False, approver=None):
    """Buat PO lalu bawa sampai `pending` (siap diterima gudang).

    Persetujuan WAJIB dipakai sesi lain: repo ini memaksa pemisahan tugas
    (`Pemisahan tugas (SoD): pembuat PO tidak boleh menyetujui PO sendiri`),
    jadi POC yang menyetujui dengan sesi pembuatnya akan macet di
    `waiting_approval` dan tugas gudang tidak pernah lahir.
    """
    body = {"supplier_id": SUP, "warehouse_id": WH, "items": items,
            "notes": f"{TAG} {note}".strip()}
    r = sess.post(f"{API}/purchase-orders", json=body, timeout=60)
    if expect_error:
        return r
    if r.status_code != 200:
        raise RuntimeError(f"PO gagal {r.status_code}: {r.text[:400]}")
    po = r.json()
    apv = approver or sess
    for _ in range(6):
        if po.get("status") != "waiting_approval":
            break
        ra = apv.post(f"{API}/purchase-orders/{po['id']}/approve",
                      json={"notes": f"{TAG} approve"}, timeout=60)
        if ra.status_code != 200:
            raise RuntimeError(f"approve PO gagal {ra.status_code}: {ra.text[:300]}")
        po = ra.json()
    return sess.get(f"{API}/purchase-orders/{po['id']}", timeout=30).json()


def inbound_task(sess, po_id: str, product_id: str) -> Optional[Dict[str, Any]]:
    rows = sess.get(f"{API}/inbound/tasks", timeout=30).json()
    rows = rows if isinstance(rows, list) else rows.get("items", [])
    hits = [t for t in rows if t.get("po_id") == po_id and t.get("product_id") == product_id]
    return hits[0] if hits else None


def kg_per_base(product: Dict[str, Any]) -> float:
    """Cermin `uom_service.kg_per_base_unit` — dipakai agar berat roll yang dikirim
    POC tidak memicu blokir selisih timbang/ukur (yang justru bukan yang diuji)."""
    gsm = float(product.get("gramasi") or 0)
    lebar = float(product.get("lebar") or 0)
    kg_per_m = float(product.get("kg_per_meter") or 0) or (gsm * lebar / 1000)
    if kg_per_m <= 0:
        return 0.0
    base = str(product.get("base_unit") or "meter").lower()
    return kg_per_m * (0.9144 if base in ("yard", "yd", "yrd") else 1.0)


def pdf_table(sess, doc_type: str, source_id: str) -> Dict[str, Any]:
    """Render HTML dokumen → {'columns': [...], 'rows': [[...]], 'totals': 'teks'}."""
    r = sess.get(f"{API}/pdf/render/{doc_type}/{source_id}?format=html", timeout=90)
    if r.status_code != 200:
        return {"error": f"{r.status_code} {r.text[:200]}", "columns": [], "rows": [],
                "totals": ""}
    html = r.text
    cols = [re.sub(r"<[^>]+>", "", c).strip()
            for c in re.findall(r"<th[^>]*>(.*?)</th>", html, re.S)]
    rows = []
    for tr in re.findall(r"<tr>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"<[^>]+>", "", c).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if cells:
            rows.append(cells)
    return {"columns": cols, "rows": rows, "totals": _pdf_totals(html), "html": html}


def _pdf_totals(html: str) -> str:
    """Baris TOTAL dokumen = `<div class="totals">` berisi `<div class="row">`
    dengan DUA `<span>` (label · nilai) — bukan `<table>`. Versi pertama penjaga
    ini mencari `</table>` sesudah `class="totals"` sehingga selalu kosong dan
    menuduh PDF tidak menyebut total roll (padahal menyebut)."""
    i = html.find('class="totals"')
    if i < 0:
        return ""
    seg = html[i:i + 4000]
    pairs = re.findall(r"<span>(.*?)</span>\s*<span>(.*?)</span>", seg, re.S)
    return " · ".join(
        f"{re.sub(r'<[^>]+>', '', a).strip()} {re.sub(r'<[^>]+>', '', b).strip()}"
        for a, b in pairs)


def pdf_cell(tab: Dict[str, Any], col_label: str, row: int = 0) -> str:
    try:
        i = tab["columns"].index(col_label)
        return tab["rows"][row][i]
    except (ValueError, IndexError):
        return f"<kolom '{col_label}' tidak ada: {tab['columns']}>"


# ═══════════════════════════════════════════════════════════════════════════
# HELPER — CSV DIJALANKAN SUNGGUHAN dengan helper FRONTEND (Node)
# ═══════════════════════════════════════════════════════════════════════════
# Kenapa lewat Node dan bukan meniru logikanya di Python: yang harus dibuktikan
# adalah bahwa berkas yang BENAR-BENAR dipakai layar (`utils/qtyDualCsv.js` +
# `utils/csvExport.js`) menghasilkan angka yang sama dengan dokumen sungguhan.
# Tiruan Python hanya membuktikan tiruannya benar.
_NODE_TPL = r"""
import * as q from "./qtyDualCsv.mjs";
import * as csv from "./csvExport.mjs";
import { readFileSync } from "node:fs";

const cfg = JSON.parse(readFileSync(process.argv[2], "utf8"));
const cols = cfg.kind === "root"
  ? q.qtyDualRootCsvColumns(cfg.opts || {})
  : q.qtyDualCsvColumns(cfg.opts || {});
console.log(JSON.stringify({ csv: csv.buildCsv(cfg.rows, cols) }));
"""


def csv_from_frontend(rows: List[Dict[str, Any]], *, kind: str = "items",
                      opts: Dict[str, Any] = None) -> str:
    node = shutil.which("node")
    if not node:
        return "<node tidak tersedia>"
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        for name in ("qtyDualCsv", "csvExport"):
            (d / f"{name}.mjs").write_text((FE_UTILS / f"{name}.js").read_text("utf-8"),
                                           encoding="utf-8")
        (d / "run.mjs").write_text(_NODE_TPL, encoding="utf-8")
        (d / "cfg.json").write_text(json.dumps(
            {"rows": rows, "kind": kind, "opts": opts or {}}), encoding="utf-8")
        p = subprocess.run([node, str(d / "run.mjs"), str(d / "cfg.json")],
                           capture_output=True, text=True, timeout=60)
        if p.returncode != 0:
            return f"<node gagal: {(p.stderr or p.stdout)[:200]}>"
        try:
            return json.loads(p.stdout.strip().splitlines()[-1])["csv"]
        except Exception as exc:  # noqa: BLE001
            return f"<keluaran node tak terbaca: {exc} :: {p.stdout[:200]}>"


def _balance(db, product_id: str) -> Dict[str, float]:
    """Kartu saldo gudang untuk satu produk: ukuran (on_hand) + JUMLAH ROLL.

    Dua satuan hidup berdampingan di satu dokumen saldo: `on_hand_qty` (yard/kg)
    dan `on_hand_roll_count` (gulungan) — keduanya turunan dari roll yang sama,
    jadi tidak mungkin saling menyimpang.
    """
    doc = db.inventory_balances.find_one(
        {"product_id": product_id, "warehouse_id": WH, "owner_entity_id": ENTITY},
        {"_id": 0}) or {}
    return {"on_hand": round(float(doc.get("on_hand_qty") or 0), 2),
            "rolls": int(doc.get("on_hand_roll_count") or 0)}


def gate_exit(script: str) -> int:
    p = subprocess.run([sys.executable, f"scripts/guardrails/{script}"],
                       cwd=str(ROOT), capture_output=True, text=True, timeout=300)
    return p.returncode


# ═══════════════════════════════════════════════════════════════════════════
class PocStop(Exception):
    """Berhenti lebih awal — TETAPI bersih-bersih tetap dijalankan.

    Pelajaran FASE T (POC-RESIDU-01): POC yang keluar di tengah jalan
    meninggalkan dokumen & stok uji, lalu gate anti-residu di ujung sesi yang
    memerah — jauh dari penyebabnya. Karena itu setiap jalan keluar POC ini
    lewat `finally` yang membersihkan.
    """


def run_stories(db, admin, mgr, wh, state: Dict[str, List[str]]) -> None:
    from core_utils import qty_dual
    from services.pdf_resolvers import _rolls_cell, _sum_rolls

    made_pos = state["pos"]
    made_returns = state["returns"]
    made_uoms = state["uoms"]

    # ══ U1. Satu angka, enam tampilan ═══════════════════════════════════════
    head("U1. 12 roll × 45 yard = 540 yard → satu angka, ENAM tampilan")
    prod = db.products.find_one({"id": P_WOVEN}, {"_id": 0}) or {}
    po = create_po(admin, [{"product_id": P_WOVEN, "quantity": QTY_TOTAL, "unit": "yard",
                            "price": 200000, "qty_rolls": ROLLS_ORDERED,
                            "expected_grade": "A"}],
                   "U1 dua satuan", approver=mgr)
    made_pos.append(po["id"])
    it = (po.get("items") or [{}])[0]
    ok(it.get("qty_rolls") == ROLLS_ORDERED,
       f"(1) PO menyimpan jumlah roll yang DIKETIK admin = {ROLLS_ORDERED}",
       f"tersimpan: {it.get('qty_rolls')!r}")
    ok(float(it.get("quantity") or 0) == QTY_TOTAL,
       f"…dan ukurannya {QTY_TOTAL:g} yard (satu field, bukan field kembar)")

    task = inbound_task(admin, po["id"], P_WOVEN)
    ok(bool(task), f"tugas penerimaan gudang lahir dari PO (status {po.get('status')!r})",
       f"{task}")
    if not task:
        raise PocStop("tugas penerimaan tidak lahir — U1..U6 tidak bisa dilanjutkan")
    ok(task.get("qty_rolls") in (None, ""),
       "(2) tugas gudang BELUM menyebut jumlah roll sebelum barang datang "
       "(rencana ≠ kenyataan)", f"{task.get('qty_rolls')!r}")

    r = wh.post(f"{API}/inbound/tasks/{task['id']}/scan-receive",
                json={"product_id": P_WOVEN, "actual_qty": QTY_TOTAL,
                      "lot": f"LOT-{TAG}", "bin_id": ""}, timeout=90)
    ok(r.status_code == 200, "scan-receive 540 yard diterima gudang",
       f"{r.status_code} {r.text[:250]}")

    kgpb = kg_per_base(prod)
    roll_lines = [{"length": YARD_PER_ROLL,
                   "weight": round(YARD_PER_ROLL * kgpb, 3) if kgpb > 0 else 0,
                   "grade": "A", "dye_lot": f"DL-{TAG}"}
                  for _ in range(ROLLS_ORDERED)]
    r = wh.post(f"{API}/inbound/tasks/{task['id']}/complete",
                json={"rolls": roll_lines, "lot_number": f"LOT-{TAG}"}, timeout=120)
    ok(r.status_code == 200, f"selesaikan penerimaan dengan {ROLLS_ORDERED} baris roll",
       f"{r.status_code} {r.text[:300]}")

    task2 = db.wms_tasks.find_one({"id": task["id"]}, {"_id": 0}) or {}
    ok(task2.get("qty_rolls") == ROLLS_ORDERED,
       f"(2) tugas gudang kini {ROLLS_ORDERED} roll — DIHITUNG dari roll yang lahir, "
       f"bukan diketik", f"{task2.get('qty_rolls')!r}")

    rolls = list(db.inventory_rolls.find({"grn_task_id": task["id"]}, {"_id": 0}))
    ok(len(rolls) == ROLLS_ORDERED, f"{ROLLS_ORDERED} roll fisik lahir di gudang",
       f"lahir {len(rolls)}")
    total_yard = round(sum(float(x.get("length_remaining") or 0) for x in rolls), 2)
    ok(abs(total_yard - QTY_TOTAL) < 0.6,
       f"Σ panjang roll = {total_yard:g} yard ≈ {QTY_TOTAL:g} yard yang dipesan",
       f"{total_yard}")

    po2 = admin.get(f"{API}/purchase-orders/{po['id']}", timeout=30).json()
    it2 = (po2.get("items") or [{}])[0]
    ok(it2.get("received_rolls") == ROLLS_ORDERED,
       f"(3) papan PO: `received_rolls` = {ROLLS_ORDERED} (TURUNAN, tidak diketik "
       f"siapa pun)", f"{it2.get('received_rolls')!r}")

    movs = list(db.inventory_movements.find(
        {"reference_id": {"$in": [task["id"], po["id"]]}}, {"_id": 0})) or \
        list(db.inventory_movements.find({"roll_id": {"$in": [x["id"] for x in rolls]}},
                                        {"_id": 0}))
    ok(movs and all(m.get("qty_rolls") is not None for m in movs),
       f"(4) kartu stok: {len(movs)} baris mutasi membawa jumlah roll",
       f"{[m.get('qty_rolls') for m in movs][:6]}")

    ok(qty_dual(ROLLS_ORDERED, QTY_TOTAL, "yard") == "12 roll · 540 yard",
       "helper server menuliskannya sebagai \"12 roll · 540 yard\" (satu kalimat)",
       qty_dual(ROLLS_ORDERED, QTY_TOTAL, "yard"))

    tab = pdf_table(admin, "purchase_order", po["id"])
    ok("Roll Dipesan" in tab["columns"],
       "(5) PDF Pesanan Pembelian punya KOLOM ROLL tersendiri (keputusan pemilik)",
       f"{tab['columns']}")
    ok(pdf_cell(tab, "Roll Dipesan") == str(ROLLS_ORDERED),
       f"…berisi {ROLLS_ORDERED}", pdf_cell(tab, "Roll Dipesan"))
    ok(pdf_cell(tab, "Jumlah") == f"{QTY_TOTAL:g} yard",
       f"…dan kolom Jumlah berisi {QTY_TOTAL:g} yard", pdf_cell(tab, "Jumlah"))

    grn = pdf_table(admin, "goods_receipt", po["id"])
    ok("Roll Diterima" in grn["columns"] and "Roll Dipesan" in grn["columns"],
       "(5) PDF Bukti Terima (GRN) memisahkan Roll Dipesan vs Roll Diterima",
       f"{grn['columns']}")
    ok(pdf_cell(grn, "Roll Diterima") == str(ROLLS_ORDERED),
       f"…Roll Diterima = {ROLLS_ORDERED} tanpa petugas mengetik apa pun",
       pdf_cell(grn, "Roll Diterima"))
    ok(f"Roll Diterima {ROLLS_ORDERED}" in grn["totals"].replace("  ", " "),
       "…dan baris TOTAL GRN menyebutnya juga", grn["totals"][:160])

    csv_plan = csv_from_frontend([po2])
    ok(csv_plan.startswith("Roll;Jumlah") and f"\r\n{ROLLS_ORDERED};{QTY_TOTAL:g} yard" in csv_plan,
       f"(6) CSV dari helper FE yang sungguhan: dua kolom `{ROLLS_ORDERED};{QTY_TOTAL:g} yard`",
       repr(csv_plan))
    csv_recv = csv_from_frontend([po2], opts={"rollField": "received_rolls",
                                             "rollHeader": "Roll Diterima",
                                             "measureHeader": "Jumlah Diterima",
                                             "measureFields": ["received_qty"]})
    ok(f"{ROLLS_ORDERED};{QTY_TOTAL:g} yard" in csv_recv,
       "…dan kolom DITERIMA pada CSV papan PO ikut benar", repr(csv_recv))

    # ══ U2. Retur 2 roll → semua angka turun serentak ════════════════════════
    head(f"U2. Retur {ROLLS_RETURNED} roll → 12→10 roll · 540→450 yard (serentak)")
    bal_before = _balance(db, P_WOVEN)
    ret_ids = [x["id"] for x in rolls[:ROLLS_RETURNED]]
    ret_qty = ROLLS_RETURNED * YARD_PER_ROLL
    r = admin.post(f"{API}/purchase-returns", json={
        "supplier_id": SUP, "po_id": po["id"], "warehouse_id": WH,
        "items": [{"product_id": P_WOVEN, "quantity": ret_qty, "unit": "yard",
                   "price": 200000, "reason": "cacat", "condition": "damaged",
                   "roll_ids": ret_ids}],
        "reason": "cacat", "notes": f"{TAG} retur dua satuan",
        "submit_now": True, "supplier_flow": False}, timeout=90)
    ok(r.status_code in (200, 201), "nota retur beli dibuat dengan 2 roll dipilih",
       f"{r.status_code} {r.text[:300]}")
    ret = r.json() if r.status_code in (200, 201) else {}
    if ret.get("id"):
        made_returns.append(ret["id"])
    if not ret.get("id"):
        raise PocStop("nota retur tidak lahir — U2 tidak bisa dilanjutkan")
    rit = (ret.get("items") or [{}])[0]
    ok(rit.get("qty_rolls") == ROLLS_RETURNED,
       f"jumlah roll retur = {ROLLS_RETURNED} — DIHITUNG dari `roll_ids`, bukan diketik",
       f"{rit.get('qty_rolls')!r}")

    ra = mgr.post(f"{API}/purchase-returns/{ret['id']}/approve",
                  json={"notes": f"{TAG} setuju"}, timeout=90)
    ok(ra.status_code == 200, "retur disetujui → stok disesuaikan",
       f"{ra.status_code} {ra.text[:300]}")

    after = list(db.inventory_rolls.find({"grn_task_id": task["id"]}, {"_id": 0}))
    # Roll yang SUDAH kembali ke supplier berstatus terminal `returned_supplier`.
    # `length_remaining`-nya SENGAJA dibiarkan utuh oleh repo ini supaya alur
    # "barang ditolak supplier → kembali ke gudang" (`goods_back`) bisa memulihkan
    # roll dengan panjang aslinya. Jadi ukuran yang benar untuk "berapa yang masih
    # di gudang" adalah roll yang MASIH berstatus fisik — bukan Σ`length_remaining`
    # semua roll. (Versi pertama pemeriksaan ini salah di sini dan menuduh alur
    # retur tidak menurunkan stok.)
    sisa = [x for x in after
            if (x.get("status") or "") != "returned_supplier"
            and float(x.get("length_remaining") or 0) > 0]
    sisa_yard = round(sum(float(x.get("length_remaining") or 0) for x in sisa), 2)
    ok(len(sisa) == ROLLS_ORDERED - ROLLS_RETURNED,
       f"jumlah roll di gudang turun {ROLLS_ORDERED}→{ROLLS_ORDERED - ROLLS_RETURNED} "
       f"(2 roll berstatus `returned_supplier` = keluar ke supplier)",
       f"sisa {len(sisa)} roll · status: "
       f"{sorted({(x.get('status') or '?') for x in after})}")
    ok(abs(sisa_yard - (QTY_TOTAL - ret_qty)) < 0.6,
       f"ukuran turun {QTY_TOTAL:g}→{QTY_TOTAL - ret_qty:g} yard SERENTAK "
       f"(satu sumber, bukan dua angka yang harus disamakan)", f"{sisa_yard}")

    bal_after = _balance(db, P_WOVEN)
    ok(abs((bal_before["on_hand"] - bal_after["on_hand"]) - ret_qty) < 0.6,
       f"kartu saldo gudang ikut turun {ret_qty:g} yard pada saat yang sama "
       f"({bal_before['on_hand']:g} → {bal_after['on_hand']:g})",
       f"{bal_before} → {bal_after}")
    ok(bal_before["rolls"] - bal_after["rolls"] == ROLLS_RETURNED,
       f"…dan JUMLAH ROLL pada kartu saldo turun {ROLLS_RETURNED} "
       f"({bal_before['rolls']} → {bal_after['rolls']}) — dua satuan, satu peristiwa",
       f"{bal_before} → {bal_after}")

    rtab = pdf_table(admin, "purchase_return", ret["id"])
    ok("Roll Retur" in rtab["columns"], "PDF Nota Retur Pembelian punya kolom Roll Retur",
       f"{rtab['columns']}")
    ok(pdf_cell(rtab, "Roll Retur") == str(ROLLS_RETURNED),
       f"…berisi {ROLLS_RETURNED}", pdf_cell(rtab, "Roll Retur"))
    ret_doc = db.purchase_returns.find_one({"id": ret["id"]}, {"_id": 0}) or {}
    csv_ret = csv_from_frontend([ret_doc], opts={"rollHeader": "Roll Retur",
                                                "measureHeader": "Jumlah Retur"})
    ok(f"{ROLLS_RETURNED};{ret_qty:g} yard" in csv_ret,
       f"CSV daftar retur menyebut `{ROLLS_RETURNED};{ret_qty:g} yard` "
       f"(bukan lagi menghitung `roll_ids.length` sendiri)", repr(csv_ret))

    # ══ U3. Satuan dari MASTER: knit kg · printing panel + faktor per dokumen ═
    head("U3. Satuan dari MASTER — knit memakai kg, printing memakai PANEL")
    vocab = admin.get(f"{API}/uoms/vocab", timeout=30).json()
    words = vocab.get("words", {})
    ok(words.get("kg") == "KG", "kata `kg` dikenali master satuan (baris KG)",
       f"{words.get('kg')!r}")
    ok(words.get("panel") == "PANEL", "kata `panel` dikenali master satuan (baris PANEL)",
       f"{words.get('panel')!r}")
    ok(words.get("yard") == "YRD" and words.get("meter") == "MTR",
       "kata dokumen `yard`/`meter` juga dikenali LEWAT ALIAS (inilah D1 yang ditutup)",
       f"yard={words.get('yard')!r} meter={words.get('meter')!r}")
    per_doc = [row["code"] for row in vocab.get("rows", [])
               if row.get("factor_per_document")]
    ok(per_doc == ["PANEL"],
       "hanya PANEL yang berhak membawa faktor per dokumen (keputusan pemilik)",
       f"{per_doc}")

    cat = admin.get(f"{API}/uom-conversions/catalog", timeout=30).json()
    codes = [u["code"] for u in cat.get("units", [])]
    ok("panel" in codes,
       "katalog satuan LAYAR menawarkan `panel` (master → pemilih satuan, tanpa ubah kode)",
       f"{codes}")

    po_kg = create_po(admin, [{"product_id": P_YARN, "quantity": 300, "unit": "kg",
                               "price": 85000, "qty_rolls": 6,
                               "expected_grade": "A"}],
                      "U3 knit per kg", approver=mgr)
    made_pos.append(po_kg["id"])
    itk = (po_kg.get("items") or [{}])[0]
    ok(itk.get("unit") == "kg" and itk.get("qty_rolls") == 6,
       "lini knit/benang: 6 roll · 300 kg tersimpan apa adanya (layar tidak memaksa yard)",
       f"{itk.get('unit')!r} {itk.get('qty_rolls')!r}")
    ktab = pdf_table(admin, "purchase_order", po_kg["id"])
    ok(pdf_cell(ktab, "Jumlah") == "300 kg",
       "…dan PDF-nya menulis `300 kg`, bukan yard", pdf_cell(ktab, "Jumlah"))

    po_panel = create_po(admin, [{"product_id": P_PRINT, "quantity": 40, "unit": "panel",
                                  "price": 250000, "qty_rolls": 4,
                                  "expected_grade": "A",
                                  "unit_factor": 1.6, "unit_factor_to": "yard"}],
                         "U3 printing per panel", approver=mgr)
    made_pos.append(po_panel["id"])
    itp = (po_panel.get("items") or [{}])[0]
    ok(itp.get("unit") == "panel" and float(itp.get("unit_factor") or 0) == 1.6,
       "printing: 4 roll · 40 panel dengan faktor 1 panel = 1,6 yard DI BARIS DOKUMEN "
       "(keputusan pemilik: panjang panel beda tiap pesanan)",
       f"{itp.get('unit')!r} faktor={itp.get('unit_factor')!r} → {itp.get('unit_factor_to')!r}")
    # Bukti bahwa faktornya benar-benar DIPAKAI (bukan hanya disimpan): jejak
    # konversi D-07 baris ini harus menyebut sumber `document_line`, dan qty dasar
    # harus 40 × 1,6 = 64 yard. Tanpa pemeriksaan ini, "panel" hanya kosmetik.
    trail = itp.get("uom_trail") or {}
    prod_p = db.products.find_one({"id": P_PRINT}, {"_id": 0}) or {}
    base_p = str(prod_p.get("base_unit") or "meter").lower()
    expect_base = round(40 * 1.6 * (0.9144 if base_p in ("meter", "m") else 1.0), 2)
    ok(str(trail.get("source", "")).startswith("document_line"),
       "jejak konversi (D-07) menyebut sumber faktor = `document_line` — "
       "pesanan ini, bukan master", f"{trail!r}")
    ok(abs(float(itp.get("quantity_base") or 0) - expect_base) < 0.6,
       f"…dan qty dasar = 40 × 1,6 = {expect_base:g} {base_p} (faktor baris DIPAKAI "
       f"mesin konversi, bukan cuma disimpan)",
       f"{itp.get('quantity_base')!r} (base {base_p})")

    rbad = create_po(admin, [{"product_id": P_WOVEN, "quantity": 10, "unit": "yard",
                              "price": 200000, "expected_grade": "A",
                              "unit_factor": 2.0,
                              "unit_factor_to": "meter"}],
                     "U3 faktor terlarang", expect_error=True)
    ok(rbad.status_code == 400,
       "satuan yang TIDAK bertanda faktor-per-dokumen (yard) DITOLAK 400 — "
       "tidak lahir pintu ke-3 untuk konversi", f"{rbad.status_code} {rbad.text[:200]}")
    ok("Master Data" in rbad.text or "master" in rbad.text.lower(),
       "…dengan kalimat yang MENUNTUN ke Master Data → UOM", rbad.text[:220])

    # ══ U4. Dokumen lama: "—" di PDF, sel KOSONG di CSV ══════════════════════
    head("U4. Dokumen LAMA tanpa jumlah roll → \"—\" di PDF, sel KOSONG di CSV")
    po_old = create_po(admin, [{"product_id": P_WOVEN, "quantity": 100, "unit": "yard",
                                "price": 200000, "expected_grade": "A"}],
                       "U4 gaya lama tanpa jumlah roll", approver=mgr)
    made_pos.append(po_old["id"])
    ito = (po_old.get("items") or [{}])[0]
    ok(ito.get("qty_rolls") is None,
       "baris tanpa jumlah roll tersimpan `None` (bukan 0) — perbedaan itu dijaga di DATA",
       f"{ito.get('qty_rolls')!r}")
    otab = pdf_table(admin, "purchase_order", po_old["id"])
    ok(pdf_cell(otab, "Roll Dipesan") == "—",
       "PDF menulis \"—\", BUKAN \"0\" (0 roll = pernyataan salah bahwa tak ada gulungan)",
       pdf_cell(otab, "Roll Dipesan"))
    ok(pdf_cell(otab, "Jumlah") == "100 yard",
       "…sementara ukurannya tetap tercetak apa adanya", pdf_cell(otab, "Jumlah"))
    csv_old = csv_from_frontend([db.purchase_orders.find_one({"id": po_old["id"]},
                                                            {"_id": 0})])
    ok("\r\n;100 yard" in csv_old,
       "CSV mengosongkan sel Roll (bukan \"—\") supaya SUM Excel pada kolom itu "
       "tetap bekerja — keputusan pemilik: CSV ≠ PDF", repr(csv_old))
    ok(qty_dual(None, 100, "yard") == "100 yard" and _rolls_cell(None) == "—"
       and _sum_rolls([]) == "—",
       "layar, PDF, dan total memakai SATU aturan yang sama untuk \"belum diisi\"",
       f"{qty_dual(None, 100, 'yard')!r} {_rolls_cell(None)!r} {_sum_rolls([])!r}")

    # ══ U5. Bukti-merah gate INV-UOM-02 ═════════════════════════════════════
    head("U5. Gate INV-UOM-02 — satuan asing `hasta` WAJIB memerahkan gate")
    ok(gate_exit("verify_uom_vocab.py") == 0, "gate hijau sebelum disuntik")
    db.purchase_orders.update_one({"id": po_old["id"]},
                                 {"$set": {"items.0.unit": "hasta"}})
    ok(gate_exit("verify_uom_vocab.py") == 1,
       "satuan `hasta` disimpan di baris PO → gate MEMERAH (bukan lolos senyap)")
    db.purchase_orders.update_one({"id": po_old["id"]},
                                 {"$set": {"items.0.unit": "yard"}})
    ok(gate_exit("verify_uom_vocab.py") == 0, "hijau lagi setelah dibereskan")

    r = admin.post(f"{API}/uoms", json={"code": f"HST{TAG[-4:]}", "name": "Hasta uji",
                                        "base_type": "length", "precision": 2,
                                        "factor_to_base": 0.45,
                                        "aliases": ["yard"]}, timeout=30)
    ok(r.status_code in (400, 409),
       "menambah satuan dengan alias `yard` yang sudah dipakai baris lain → DITOLAK "
       "(satu kata satuan hanya boleh menunjuk satu baris master)",
       f"{r.status_code} {r.text[:200]}")
    if r.status_code in (200, 201):
        made_uoms.append(r.json().get("id", ""))

    # ══ U6. Roll ber-yard yang JUGA ditimbang ═══════════════════════════════
    head("U6. Roll ber-yard yang ditimbang menyimpan `secondary_measures` (kg)")
    if kgpb > 0:
        weighed = [x for x in rolls if (x.get("secondary_measures") or {}).get("kg")]
        ok(len(weighed) == ROLLS_ORDERED,
           f"{ROLLS_ORDERED} roll menyimpan ukuran kedua `secondary_measures.kg`",
           f"{len(weighed)} dari {len(rolls)}")
        contoh = (weighed[0].get("secondary_measures") or {}) if weighed else {}
        ok(abs(float(contoh.get("kg") or 0) - round(YARD_PER_ROLL * kgpb, 3)) < 0.05,
           f"…dan nilainya = berat timbangan yang dikirim gudang "
           f"({round(YARD_PER_ROLL * kgpb, 3)} kg)", f"{contoh}")
        ok(weighed and float(weighed[0].get("length_remaining") or 0) > 0
           and str(weighed[0].get("unit") or "").lower() == "yard",
           "roll yang sama tetap membawa PANJANG dalam yard — dua ukuran, satu roll",
           f"{weighed[0].get('length_remaining')!r} {weighed[0].get('unit')!r}")
    else:
        ok(False, "produk uji tidak punya gramasi/lebar — U6 tidak bisa diuji")

    api_rolls = admin.get(f"{API}/inventory/rolls", timeout=60)
    if api_rolls.status_code == 200:
        rows = api_rolls.json()
        rows = rows if isinstance(rows, list) else rows.get("items", [])
        hit = next((x for x in rows if x.get("grn_task_id") == task["id"]), None)
        ok(hit and (hit.get("secondary_measures") or {}).get("kg"),
           "kartu Roll di layar menerima kedua ukuran dari API (bukan hanya di basis data)",
           f"{(hit or {}).get('secondary_measures')!r}")
    else:
        ok(False, f"GET /api/inventory/rolls gagal: {api_rolls.status_code}")

    # ══ U7. NOL RESIDU ══════════════════════════════════════════════════════
    # (dijalankan di `finally` main() — lihat `cleanup()`)


def cleanup(db, state: Dict[str, List[str]], audit_before: set, notif_before: set,
            trail_before: Dict[str, int], stock_snap: Any,
            stock_before: Dict[str, int]) -> None:
    head("U7. Bersih-bersih — POC harus bisa dijalankan berulang")
    made_pos, made_returns, made_uoms = state["pos"], state["returns"], state["uoms"]
    removed = 0
    for rid in made_returns:
        removed += db.purchase_returns.delete_many({"id": rid}).deleted_count
        removed += db.debit_notes.delete_many({"return_id": rid}).deleted_count
        removed += db.journal_entries.delete_many(
            {"source_id": {"$regex": f"^{rid}"}}).deleted_count
        removed += db.document_relations.delete_many(
            {"$or": [{"from_id": rid}, {"to_id": rid}]}).deleted_count
    for pid in made_pos:
        removed += db.purchase_orders.delete_many({"id": pid}).deleted_count
        removed += db.wms_tasks.delete_many({"po_id": pid}).deleted_count
        removed += db.journal_entries.delete_many(
            {"source_id": {"$regex": f"^{pid}"}}).deleted_count
        removed += db.approval_requests.delete_many({"doc_id": pid}).deleted_count
        removed += db.document_relations.delete_many(
            {"$or": [{"from_id": pid}, {"to_id": pid}]}).deleted_count
    for uid in made_uoms:
        if uid:
            removed += db.uoms.delete_many({"id": uid}).deleted_count
    removed += db.purchase_orders.delete_many({"notes": {"$regex": TAG}}).deleted_count
    removed += db.purchase_returns.delete_many({"notes": {"$regex": TAG}}).deleted_count
    removed += db.uoms.delete_many({"code": {"$regex": TAG[-4:]}}).deleted_count

    # ── JEJAK yang LAHIR dari POC ini (POC-RESIDU-03) ────────────────────────
    # Dulu di sini ada `delete_many({"message": {"$regex": TAG}})` — dan itu KODE
    # MATI: koleksi `notifications` tidak punya field `message` (fieldnya `title`,
    # `body`, `ref`, `action_id`), jadi baris itu selalu menghapus 0 dokumen tanpa
    # bersuara sementara 4 notifikasi (`po_approval` ×2 · `po_arrival` ×2) tinggal
    # setiap kali POC dijalankan. Diganti dengan pola SELISIH yang sama seperti
    # `audit_logs` di bawahnya — tidak bergantung pada nama field mana pun, jadi
    # tidak bisa lagi "salah sasaran diam-diam". Notifikasi ini menunjuk PO uji
    # yang baru saja dihapus; membiarkannya = jejak yatim (kotak masuk pemakai
    # memuat "PO menunggu persetujuan" atas dokumen yang tak ada lagi).
    new_notif = {d["id"] for d in db.notifications.find({}, {"_id": 0, "id": 1})} - notif_before
    notif_removed = (db.notifications.delete_many(
        {"id": {"$in": list(new_notif)}}).deleted_count if new_notif else 0)
    new_audit = {d["id"] for d in db.audit_logs.find({}, {"_id": 0, "id": 1})} - audit_before
    audit_removed = (db.audit_logs.delete_many({"id": {"$in": list(new_audit)}}).deleted_count
                     if new_audit else 0)
    # Sesi login POC (3 akun) — tanpa ini `sessions` tumbuh tiap kali POC jalan.
    sess_removed = (db.sessions.delete_many(
        {"token": {"$in": SESSION_TOKENS}}).deleted_count if SESSION_TOKENS else 0)
    ok(removed >= len(made_pos),
       f"dokumen uji dibersihkan ({removed} dokumen · {audit_removed} jejak audit · "
       f"{notif_removed} notifikasi · {sess_removed} sesi)")
    ok(db.purchase_orders.count_documents({"notes": {"$regex": TAG}}) == 0,
       "tidak ada PO uji yang tertinggal")
    ok(db.purchase_returns.count_documents({"notes": {"$regex": TAG}}) == 0,
       "tidak ada nota retur uji yang tertinggal")

    # Roll/lot/mutasi lahir dari alur kain SUNGGUHAN → dipulihkan EKSAK, bukan
    # "dihapus yang baru" (menerima & mengonsumsi roll tidak bisa dibalik per-dokumen).
    # POC-RESIDU-02: BUKU BESAR ikut dipulihkan pada saat yang sama. Memulihkan stok
    # sambil menghapus jurnalnya membuat GL 1-1300 turun sementara subledger utuh →
    # `verify_data_integrity` memerah WARN `INV-GL-DRIFT` di ujung sesi, jauh dari
    # penyebabnya (itulah yang terukur Δ432.000.000 pada sesi ini).
    restore_stock(stock_snap)
    stock_after = {c: db[c].count_documents({}) for c in stock_before}
    drift = {c: (stock_before[c], stock_after[c]) for c in stock_before
             if stock_before[c] != stock_after[c]}
    ok(not drift,
       "stok DAN buku besar dipulihkan EKSAK — nol residu roll · lot · mutasi · "
       "saldo · jurnal",
       f"masih bergeser: {drift}")
    gl_before, gl_after = stock_before["journal_entries"], stock_after["journal_entries"]
    ok(gl_before == gl_after,
       f"jumlah jurnal sebelum == sesudah ({gl_before}) — dua sisi satu peristiwa "
       f"(stok & GL) kembali ke SATU saat yang sama",
       f"{gl_before} → {gl_after}")

    # POC-RESIDU-03 — POC MEMBUKTIKAN SENDIRI nol residu jejak (pola T9).
    # Tanpa baris ini, pembersih yang salah sasaran (mis. menembak field `message`
    # yang tidak ada) lolos senyap dan baru terlihat 300 detik kemudian sebagai
    # `INV-GATE-01` merah — jauh dari penyebabnya. Diletakkan PALING AKHIR (sesudah
    # kedua gate dijalankan) supaya jejak yang mungkin dilahirkan penjaga itu
    # sendiri pun ikut terukur — bukan disembunyikan oleh urutan pemeriksaan.
    ok(gate_exit("verify_uom_vocab.py") == 0, "INV-UOM-02 hijau di akhir POC")
    ok(gate_exit("verify_qty_dual.py") == 0, "INV-QTY-01 hijau di akhir POC")
    trail_after = {c: db[c].count_documents({}) for c in trail_before}
    trail_drift = {c: f"{trail_before[c]} → {trail_after[c]}" for c in trail_before
                   if trail_before[c] != trail_after[c]}
    ok(not trail_drift,
       f"JEJAK sebelum == sesudah ({' · '.join(f'{c} {trail_before[c]}' for c in trail_before)}) "
       f"— nol residu audit · notifikasi · sesi",
       f"masih bergeser: {trail_drift}")


# ═══════════════════════════════════════════════════════════════════════════
def main() -> int:
    global SUP
    db = _db()
    SUP = supplier_id(db)
    assert SUP, "tidak ada supplier demo pada entitas uji"

    # POC-RESIDU-03 — JEJAK diambil SEBELUM `login()`. Urutan ini BUKAN gaya:
    # login menulis satu `audit_logs` + satu `sessions` per pemanggilan, jadi
    # mengambil sidik jarinya sesudah login membuat ketiga jejak itu terhitung
    # sebagai "keadaan awal" dan lolos dari pembersihan (terukur: audit_logs +3).
    audit_before = {d["id"] for d in db.audit_logs.find({}, {"_id": 0, "id": 1})}
    notif_before = {d["id"] for d in db.notifications.find({}, {"_id": 0, "id": 1})}
    trail_before = {c: db[c].count_documents({}) for c in TRAIL_COLLECTIONS}

    admin = login(ADMIN)
    mgr = login(MANAGER)          # penyetuju (SoD: pembuat ≠ penyetuju)
    wh = login(WAREHOUSE)

    stock_snap = snapshot_stock(FULL_COLLECTIONS)
    stock_before = {c: db[c].count_documents({})
                    for c in ("inventory_rolls", "inventory_lots",
                              "inventory_movements", "inventory_balances",
                              "journal_entries", "gl_postings")}
    state: Dict[str, List[str]] = {"pos": [], "returns": [], "uoms": []}

    print("=" * 84)
    print(f"  POC FASE U — DUA SATUAN (roll + yard/kg/panel) · tanda uji {TAG}")
    print("=" * 84)

    try:
        run_stories(db, admin, mgr, wh, state)
    except PocStop as exc:
        print(f"\n  ⚠ POC berhenti lebih awal: {exc}")
    except Exception as exc:  # noqa: BLE001
        import traceback
        ok(False, f"POC berhenti karena galat tak terduga: {exc}",
           traceback.format_exc()[-1200:])
    finally:
        cleanup(db, state, audit_before, notif_before, trail_before,
                stock_snap, stock_before)

    print("\n" + "=" * 84)
    print(f"  HASIL: {PASS} PASS · {FAIL} FAIL")
    print("=" * 84)
    return 0 if FAIL == 0 else 1


SUP = ""

if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    except Exception:  # noqa: BLE001
        pass
    sys.exit(main())
