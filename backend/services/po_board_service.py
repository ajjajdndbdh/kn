"""FASE P — **PAPAN PO PER LINI** (progres tahap seperti kertas kerja MD).

MASALAH NYATA PEMILIK
---------------------
MD memegang **kertas kerja**: satu baris per PO, kolomnya *Nama Sales · No PO ·
Nama Item · Qty · Warna · Tanggal Order · Estimasi Ready · tahap berjalan ·
Tanggal Masuk · Qty Terima · Keterangan*. Kertas itu diperbarui tangan, jadi
angkanya selalu tertinggal dari kenyataan gudang — dan tiap lini (woven · knit ·
printing) punya urutan tahap yang berbeda.

TIGA ATURAN YANG MEMBUAT PAPAN INI TIDAK BISA BERBOHONG
=======================================================
1. **Urutan tahap datang dari MASTER, bukan dari kode.**
   `product_lines.stage_sequence` (FASE L) + label `process_stages` (FASE T).
   Pemilik menambah lini/tahap di Pengaturan → Master; papan ini ikut **tanpa satu
   baris kode berubah**. Kalau urutannya ditulis di sini, lini ke-4 akan tampil
   dengan chip lini pertama dan tidak ada yang tahu.
2. **Tahap `inspect` TIDAK PERNAH diklik manusia — ia DITURUNKAN dari bukti.**
   Kalau tahap ini bisa ditandai tangan, papan bisa mengaku "sudah diinspeksi"
   tanpa satu dokumen inspeksi pun. Hari ini buktinya adalah hasil QC yang menempel
   di roll (`inventory_rolls.inspection`) + status tugas gudang (`qc_pending`);
   **saat FASE I mendarat**, sumber itu berpindah ke koleksi `inspections`
   (`kind=po_receipt`) — cukup mengganti `inspect_state()`, karena hanya di situ
   aturannya ditulis.
3. **Tanggal Masuk & Qty Terima DIHITUNG, tidak diketik.** Sumbernya penerimaan
   nyata: `wms_tasks` (GRN) untuk tanggal, `purchase_orders.items[].received_qty`
   untuk ukuran, dan jumlah **roll** dari roll yang benar-benar lahir (FASE U).
   Tidak ada field kedua untuk "Estimasi Ready": dipakai
   `expected_delivery_date` yang **sudah ada** (§P.A rencana: jangan bikin field
   kedua untuk satu fakta).

APA YANG *TIDAK* DISIMPAN (dan kenapa)
--------------------------------------
Hanya `stage_progress[]` yang disimpan — itu **keputusan manusia** ("celup sudah
selesai"), fakta yang tidak bisa dihitung dari mana pun. Semua kolom lain adalah
**turunan**: menyimpannya berarti membuat sumber kedua yang harus disinkronkan,
dan sumber kedua di repo ini selalu berakhir sebagai angka yang berbeda tanpa ada
yang tahu mana yang benar (kelas bug KN-G6-ICA-CLOBBER).

Dijaga: `INV-STAGE-01` (`scripts/guardrails/verify_po_board.py`) &
POC `backend/test_core_po_board_poc.py`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core_utils import now_iso, safe_doc, timeline_entry
from db import db
from services import line_scope

#: Status tahap yang sah. SENGAJA hanya tiga: papan kertas MD pun hanya mengenal
#: "belum · sedang · selesai". Menambah status keempat (mis. "ditunda") tanpa
#: permintaan pemilik hanya menambah kolom yang tak pernah dipakai.
STAGE_STATUSES = ("pending", "in_progress", "done")

STAGE_STATUS_LABEL = {
    "pending": "Belum mulai",
    "in_progress": "Sedang dikerjakan",
    "done": "Selesai",
}

#: Tahap yang **DITURUNKAN dari dokumen/bukti**, bukan diklik manusia (aturan 2).
DERIVED_STAGES = ("inspect",)

#: Bentuk AWAL papan pada SETIAP PO baru — field-nya **ADA tetapi kosong**.
#:
#: Alasannya sama dengan `pr_sourcing_service.PO_ORIGIN_EMPTY` dan bukan kerapian:
#: papan harus bisa membedakan **"belum ada tahap yang ditandai"** dari **"dokumen
#: ini lahir sebelum papan ada"**. Dua keadaan itu tampak identik di layar (semua
#: chip abu-abu) tetapi berbeda artinya saat menelusuri kenapa satu PO tidak
#: pernah bergerak. Di-spread oleh KEEMPAT pintu lahirnya PO; dijaga gate
#: `INV-STAGE-01` supaya pintu ke-5 tidak lahir tanpa field ini, dan
#: `scripts/migrate_po_stage_progress.py` mengisinya untuk dokumen lama.
PO_BOARD_EMPTY: Dict[str, Any] = {"stage_progress": []}

#: Status PO yang dianggap "sudah tutup" — dipakai kartu ringkasan "terlambat"
#: supaya PO yang memang sudah selesai tidak dihitung terlambat.
CLOSED_PO_STATUSES = {"completed", "cancelled", "rejected", "closed_short"}

#: Batas aman enrichment satu permintaan papan. Kartu ringkasan dihitung dari
#: SELURUH hasil filter (bukan dari halaman aktif — pelajaran FASE P5: lencana
#: yang dihitung dari halaman diam-diam menyusut), jadi batas ini melindungi
#: memori bila kelak PO-nya puluhan ribu. Bila tercapai, papan mengatakannya
#: (`summary.capped=true`) alih-alih diam-diam menampilkan angka yang salah.
MAX_ENRICH = 2000


class BoardError(ValueError):
    """Pelanggaran aturan papan PO (dipetakan ke HTTP 400/409 di router)."""


# ═══════════════════════════════════════════════════════════════════════════
# 1. MASTER (lini & tahap) — satu-satunya sumber urutan tahap
# ═══════════════════════════════════════════════════════════════════════════
async def stage_master() -> Dict[str, Dict[str, Any]]:
    rows = await db.process_stages.find(
        {}, {"_id": 0, "code": 1, "name": 1, "seq": 1, "active": 1}).to_list(500)
    return {str(r.get("code") or "").strip().lower(): r for r in rows if r.get("code")}


async def line_master() -> Dict[str, Dict[str, Any]]:
    rows = await db.product_lines.find(
        {}, {"_id": 0, "code": 1, "name": 1, "stage_sequence": 1, "active": 1,
             # `sort` adalah field urutan master (FASE L); `seq` hanya alias lama.
             # Keduanya diambil supaya tab papan mengikuti urutan yang pemilik atur
             # — tanpa `sort` di proyeksi, tab jatuh ke urutan abjad kode dan
             # "Knit" muncul sebelum "Woven" tanpa alasan yang bisa dijelaskan.
             "sort": 1, "seq": 1}
    ).to_list(500)
    return {str(r.get("code") or "").strip().lower(): r for r in rows if r.get("code")}


def sequence_for(po: Dict[str, Any], lines: Dict[str, Dict[str, Any]]) -> List[str]:
    """Urutan tahap untuk satu PO — dari master lini dokumen itu.

    PO **boleh** memuat lebih dari satu lini (baris woven + baris printing dalam
    satu pesanan pembelian). Urutan gabungan ditulis berurutan per lini tanpa
    duplikat, sehingga papan tetap menampilkan seluruh langkah yang relevan —
    bukan memilih salah satu lini dan menyembunyikan pekerjaan lini lainnya.
    """
    out: List[str] = []
    for code in (po.get(line_scope.LINES_FIELD) or []):
        row = lines.get(str(code or "").strip().lower()) or {}
        for st in (row.get("stage_sequence") or []):
            st = str(st or "").strip().lower()
            if st and st not in out:
                out.append(st)
    return out


# ═══════════════════════════════════════════════════════════════════════════
# 2. TAHAP `inspect` — DITURUNKAN dari bukti (aturan 2)
# ═══════════════════════════════════════════════════════════════════════════
#: Status tugas gudang yang menandakan pemeriksaan mutu sedang berjalan.
QC_TASK_STATUSES = {"qc_pending", "qc_check", "qc_hold"}


def inspect_state(tasks: Sequence[Dict[str, Any]],
                  rolls: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Keadaan tahap `inspect` untuk SATU PO — fungsi murni supaya bisa diuji.

    Hari ini bukti inspeksi PO tinggal di dua tempat yang memang sudah ada:
      · `inventory_rolls.inspection` — hasil QC 4-point per gulungan;
      · `wms_tasks.status` — `qc_pending`/`qc_check` = petugas sedang memeriksa.
    Keduanya BUKAN dokumen inspeksi; FASE I akan melahirkan koleksi `inspections`
    dan fungsi ini yang berpindah sumber (satu tempat, satu perubahan).
    """
    inspected = [r for r in rolls if (r.get("inspection") or None)]
    if rolls and len(inspected) == len(rolls):
        latest = max(inspected, key=lambda r: str((r.get("inspection") or {}).get("at")
                                                  or r.get("updated_at") or ""))
        insp = latest.get("inspection") or {}
        return {"status": "done", "at": insp.get("at") or latest.get("updated_at") or "",
                "by": insp.get("by") or insp.get("inspector") or "",
                "note": f"{len(inspected)} roll diperiksa (QC 4-point)",
                "source": "inventory_rolls.inspection"}
    if inspected:
        insp = (inspected[-1].get("inspection") or {})
        return {"status": "in_progress", "at": insp.get("at") or "",
                "by": insp.get("by") or insp.get("inspector") or "",
                "note": f"{len(inspected)} dari {len(rolls)} roll sudah diperiksa",
                "source": "inventory_rolls.inspection"}
    qc = [t for t in tasks if str(t.get("status") or "") in QC_TASK_STATUSES]
    if qc:
        return {"status": "in_progress", "at": qc[0].get("updated_at") or "",
                "by": "", "note": f"{len(qc)} tugas gudang menunggu pemeriksaan mutu",
                "source": "wms_tasks.status"}
    return {"status": "pending", "at": "", "by": "",
            "note": "belum ada hasil inspeksi", "source": ""}


# ═══════════════════════════════════════════════════════════════════════════
# 3. Tanggal Masuk & Qty Terima — DIHITUNG dari penerimaan nyata (aturan 3)
# ═══════════════════════════════════════════════════════════════════════════
def _task_time(t: Dict[str, Any]) -> str:
    if t.get("completed_at"):
        return str(t["completed_at"])
    scans = t.get("scan_log") or []
    times = [str(s.get("scan_time") or "") for s in scans if s.get("scan_time")]
    if times:
        return max(times)
    return str(t.get("updated_at") or "")


def receipt_facts(po: Dict[str, Any], tasks: Sequence[Dict[str, Any]],
                  rolls: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Tanggal masuk & jumlah diterima — semuanya TURUNAN, tak satu pun diketik."""
    items = po.get("items") or []
    received = round(sum(float(it.get("received_qty") or 0) for it in items), 3)
    # Satuan yang dipakai kolom: satuan baris yang BENAR-BENAR diterima; PO
    # bercampur satuan (knit kg + woven yard) menampilkan satuan baris pertama
    # yang punya penerimaan — bukan menjumlahkan satuan berbeda menjadi satu angka
    # yang terlihat sah tetapi tidak berarti apa-apa.
    unit = ""
    for it in items:
        if float(it.get("received_qty") or 0) > 0:
            unit = str(it.get("unit") or "")
            break
    if not unit and items:
        unit = str(items[0].get("unit") or "")

    # Jumlah ROLL diterima: `wms_tasks.qty_rolls` (dihitung saat penerimaan selesai,
    # FASE U) lebih dipercaya daripada menghitung dokumen roll, karena roll bisa
    # dipecah/digabung sesudahnya. Bila tak satu pun tugas menyebutnya, dipakai
    # jumlah roll yang lahir dari PO ini; bila itu pun nol → **None** ("—"), bukan 0.
    task_rolls = [int(t["qty_rolls"]) for t in tasks
                  if t.get("qty_rolls") not in (None, "")]
    rolls_received: Optional[int] = sum(task_rolls) if task_rolls else (
        len(rolls) if rolls else None)

    times = sorted(_task_time(t) for t in tasks
                   if float(t.get("received_qty") or 0) > 0 and _task_time(t))
    return {
        "first_receipt_at": times[0] if times else "",
        "last_receipt_at": times[-1] if times else "",
        "received_measure": received if received > 0 else None,
        "received_unit": unit,
        "received_rolls": rolls_received if received > 0 or rolls_received else None,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 4. Baris papan
# ═══════════════════════════════════════════════════════════════════════════
def _progress_map(po: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in (po.get("stage_progress") or []):
        code = str((row or {}).get("stage_code") or "").strip().lower()
        if code:
            out[code] = row
    return out


def stages_of(po: Dict[str, Any], lines: Dict[str, Dict[str, Any]],
              stages: Dict[str, Dict[str, Any]],
              inspect: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Chip tahap untuk satu PO — urut sesuai master, `inspect` selalu turunan."""
    prog = _progress_map(po)
    out: List[Dict[str, Any]] = []
    for code in sequence_for(po, lines):
        master = stages.get(code) or {}
        derived = code in DERIVED_STAGES
        if derived:
            st = dict(inspect)
            out.append({
                "code": code, "label": master.get("name") or code.title(),
                "status": st.get("status", "pending"),
                "at": st.get("at", ""), "by": st.get("by", ""),
                "note": st.get("note", ""),
                "derived": True, "locked": True,
                "locked_reason": ("Tahap inspeksi tidak ditandai manual — ia mengikuti "
                                  "hasil pemeriksaan mutu barang yang diterima."),
                "source": st.get("source", ""),
            })
            continue
        row = prog.get(code) or {}
        status = str(row.get("status") or "pending")
        out.append({
            "code": code, "label": master.get("name") or code.title(),
            "status": status if status in STAGE_STATUSES else "pending",
            "at": row.get("at", ""), "by": row.get("by", ""),
            "note": row.get("note", ""),
            "derived": False, "locked": False, "locked_reason": "", "source": "manual",
        })
    return out


def _items_label(items: Sequence[Dict[str, Any]]) -> str:
    names = [str(it.get("product_name") or it.get("sku") or "").strip()
             for it in items if (it.get("product_name") or it.get("sku"))]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return f"{names[0]} +{len(names) - 1} lainnya"


def _colors_label(items: Sequence[Dict[str, Any]],
                  products: Dict[str, Dict[str, Any]]) -> str:
    """Kolom **Warna** kertas kerja MD.

    Warna hari ini tinggal di **master produk** (`color_name`), bukan di baris PO —
    jadi ia dibaca dari master saat papan dibuka, dan itu ditulis apa adanya di
    sini supaya tidak ada yang menyangka ini snapshot historis. (Kalau kelak warna
    per baris pesanan dibutuhkan, tempatnya di baris dokumen — bukan salinan kedua
    di kepala PO.)
    """
    seen: List[str] = []
    for it in items:
        prod = products.get(str(it.get("product_id") or "")) or {}
        name = str(prod.get("color_name") or prod.get("color") or "").strip()
        if name and name not in seen:
            seen.append(name)
    if not seen:
        return ""
    if len(seen) <= 2:
        return " · ".join(seen)
    return f"{seen[0]} +{len(seen) - 1} warna"


def _planned_rolls(items: Sequence[Dict[str, Any]]) -> Optional[int]:
    """Rencana jumlah roll — `None` bila dokumen tidak pernah menyebutnya (FASE U:
    tampil "—", BUKAN "0 roll" yang menyatakan hal yang salah)."""
    total: Optional[int] = None
    for it in items:
        v = it.get("qty_rolls")
        if v in (None, ""):
            continue
        total = (total or 0) + int(v)
    return total


def current_stage(stage_rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Tahap BERJALAN = yang sedang dikerjakan; kalau tak ada, tahap belum-mulai
    paling awal. Semua selesai → tanda selesai."""
    for row in stage_rows:
        if row["status"] == "in_progress":
            return {"code": row["code"], "label": row["label"], "status": "in_progress"}
    for row in stage_rows:
        if row["status"] == "pending":
            return {"code": row["code"], "label": row["label"], "status": "pending"}
    if stage_rows:
        return {"code": stage_rows[-1]["code"], "label": stage_rows[-1]["label"],
                "status": "done"}
    return {"code": "", "label": "", "status": ""}


def build_row(po: Dict[str, Any], *, lines: Dict[str, Dict[str, Any]],
              stages: Dict[str, Dict[str, Any]], products: Dict[str, Dict[str, Any]],
              tasks: Sequence[Dict[str, Any]],
              rolls: Sequence[Dict[str, Any]],
              so_numbers: Dict[str, str]) -> Dict[str, Any]:
    """Satu baris kertas kerja MD — kolomnya PERSIS urutan di §P.B rencana."""
    items = po.get("items") or []
    insp = inspect_state(tasks, rolls)
    stage_rows = stages_of(po, lines, stages, insp)
    facts = receipt_facts(po, tasks, rolls)
    eta = str(po.get("expected_delivery_date") or "")
    late = bool(eta and eta[:10] < datetime.now(timezone.utc).strftime("%Y-%m-%d")
                and str(po.get("status") or "") not in CLOSED_PO_STATUSES)
    return {
        "po_id": po.get("id", ""),
        "po_number": po.get("po_number", ""),
        "entity_id": po.get("entity_id", ""),
        "status": po.get("status", ""),
        # ── asal dokumen (P-0): dirunut, tidak diketik. Kosong = memang tidak ada.
        "sales_name": po.get("sales_name", "") or "",
        "sales_user_id": po.get("sales_user_id", "") or "",
        "pr_id": po.get("pr_id", "") or "",
        "pr_number": po.get("pr_number", "") or "",
        "source": po.get("source", "") or "",
        "source_so_ids": po.get("source_so_ids") or [],
        "so_numbers": [so_numbers.get(i, "") for i in (po.get("source_so_ids") or [])
                       if so_numbers.get(i)],
        "supplier_name": po.get("supplier_name", ""),
        "warehouse_name": po.get("warehouse_name", ""),
        "line_codes": po.get(line_scope.LINES_FIELD) or [],
        # ── kolom kertas kerja
        "items_label": _items_label(items),
        "item_count": len(items),
        "qty_rolls": _planned_rolls(items),
        "quantity": round(sum(float(it.get("quantity") or 0) for it in items), 3),
        "unit": str((items[0].get("unit") if items else "") or ""),
        "colors": _colors_label(items, products),
        "order_date": po.get("created_at", ""),
        "eta_ready": eta,
        "late": late,
        "stages": stage_rows,
        "current_stage": current_stage(stage_rows),
        "notes": po.get("notes", ""),
        **facts,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 5. PAPAN (daftar berhalaman + kartu ringkasan dari SELURUH hasil filter)
# ═══════════════════════════════════════════════════════════════════════════
def summarize(rows: Sequence[Dict[str, Any]], capped: bool = False) -> Dict[str, Any]:
    """Kartu ringkasan — dihitung dari SELURUH hasil filter, bukan halaman aktif."""
    belum = berjalan = selesai = terlambat = tanpa_sales = 0
    for r in rows:
        st = [s for s in r["stages"]]
        done = [s for s in st if s["status"] == "done"]
        moving = [s for s in st if s["status"] == "in_progress"]
        if st and len(done) == len(st):
            selesai += 1
        elif moving or done:
            berjalan += 1
        else:
            belum += 1
        if r.get("late"):
            terlambat += 1
        if not r.get("sales_name"):
            tanpa_sales += 1
    return {"total": len(rows), "belum_mulai": belum, "berjalan": berjalan,
            "selesai": selesai, "terlambat": terlambat,
            "tanpa_sales": tanpa_sales, "capped": capped}


async def _fetch_context(pos: Sequence[Dict[str, Any]]) -> Tuple[
        Dict[str, List[Dict[str, Any]]], Dict[str, List[Dict[str, Any]]],
        Dict[str, Dict[str, Any]], Dict[str, str]]:
    """Ambil tugas gudang · roll · produk · nomor SO untuk SEMUA baris sekaligus.

    Satu query per jenis (bukan per baris): papan dengan 200 baris kalau tidak
    di-batch akan menembak Mongo 800 kali dan terasa lambat justru di layar yang
    paling sering dibuka."""
    po_ids = [p["id"] for p in pos if p.get("id")]
    tasks_by_po: Dict[str, List[Dict[str, Any]]] = {i: [] for i in po_ids}
    rolls_by_po: Dict[str, List[Dict[str, Any]]] = {i: [] for i in po_ids}
    if po_ids:
        async for t in db.wms_tasks.find(
            {"po_id": {"$in": po_ids}, "flow_type": "inbound"},
            {"_id": 0, "po_id": 1, "status": 1, "received_qty": 1, "qty_rolls": 1,
             "completed_at": 1, "updated_at": 1, "scan_log": 1},
        ):
            tasks_by_po.setdefault(t["po_id"], []).append(t)
        async for r in db.inventory_rolls.find(
            {"acquired.ref_id": {"$in": po_ids}},
            {"_id": 0, "acquired": 1, "inspection": 1, "updated_at": 1},
        ):
            rolls_by_po.setdefault((r.get("acquired") or {}).get("ref_id", ""), []).append(r)

    prod_ids = {str(it.get("product_id") or "") for p in pos
                for it in (p.get("items") or []) if it.get("product_id")}
    products: Dict[str, Dict[str, Any]] = {}
    if prod_ids:
        async for p in db.products.find(
            {"id": {"$in": list(prod_ids)}},
            {"_id": 0, "id": 1, "color_name": 1, "color": 1, "color_hex": 1},
        ):
            products[p["id"]] = p

    so_ids = {i for p in pos for i in (p.get("source_so_ids") or [])}
    so_numbers: Dict[str, str] = {}
    if so_ids:
        async for s in db.sales_orders.find({"id": {"$in": list(so_ids)}},
                                            {"_id": 0, "id": 1, "number": 1}):
            so_numbers[s["id"]] = s.get("number", "")
    return tasks_by_po, rolls_by_po, products, so_numbers


async def board(*, query: Dict[str, Any], page: int = 1, page_size: int = 50,
                search: str = "", status: str = "",
                actor: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Papan PO: baris ter-enrich + kartu ringkasan + tab lini DARI MASTER."""
    lines = await line_master()
    stages = await stage_master()

    q = dict(query or {})
    q.setdefault("po_type", {"$ne": "blanket"})   # kontrak payung punya layar sendiri
    if status:
        if status == "open":
            q["status"] = {"$nin": sorted(CLOSED_PO_STATUSES)}
        else:
            q["status"] = status
    if search:
        rx = {"$regex": search.strip(), "$options": "i"}
        q["$or"] = [{"po_number": rx}, {"supplier_name": rx}, {"sales_name": rx},
                    {"pr_number": rx}, {"items.product_name": rx}]

    pos = await db.purchase_orders.find(q, {"_id": 0}).sort(
        "created_at", -1).to_list(MAX_ENRICH)
    capped = len(pos) >= MAX_ENRICH
    tasks_by_po, rolls_by_po, products, so_numbers = await _fetch_context(pos)
    rows = [build_row(po, lines=lines, stages=stages, products=products,
                      tasks=tasks_by_po.get(po["id"], []),
                      rolls=rolls_by_po.get(po["id"], []),
                      so_numbers=so_numbers)
            for po in pos]

    total = len(rows)
    start = max(page - 1, 0) * page_size
    page_rows = rows[start:start + page_size]
    # Tab lini: hanya lini yang boleh dilihat akun ini (akun berpagar lini tidak
    # ditawari tab yang PASTI kosong — bukan menyembunyikan kebenaran, melainkan
    # tidak memasang jebakan; pola yang sama dengan `LineFilter`).
    allowed = set(line_scope.allowed_lines(actor))
    line_tabs = [{"code": c, "name": r.get("name") or c.title(),
                  "stage_sequence": r.get("stage_sequence") or [],
                  # Urutan tab MENGIKUTI master (`sort`, alias lama `seq`) supaya
                  # woven→knit→printing tampil seperti yang pemilik atur — bukan
                  # urutan abjad kode yang tak berarti apa pun bagi orang pabrik.
                  "sort": int(r.get("sort") or r.get("seq") or 0)}
                 for c, r in lines.items()
                 if (not allowed or c in allowed) and r.get("active", True)]
    line_tabs.sort(key=lambda t: (t["sort"] or 99, t["code"]))
    return {
        "items": page_rows, "total": total, "page": page, "page_size": page_size,
        "has_more": start + page_size < total,
        "summary": summarize(rows, capped),
        "lines": line_tabs,
        # Akun berpagar lini perlu TAHU bahwa papannya disaring (bukan menyangka
        # data hilang) — layar menampilkannya sebagai lencana kecil.
        "line_restricted": sorted(allowed),
        "stage_labels": {c: (r.get("name") or c) for c, r in stages.items()},
        "stage_statuses": [{"code": s, "label": STAGE_STATUS_LABEL[s]}
                           for s in STAGE_STATUSES],
        "derived_stages": list(DERIVED_STAGES),
    }


async def row_of(po_id: str, actor: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Satu baris papan (dipakai sesudah tahap diperbarui — layar menyegarkan
    baris itu saja, bukan memuat ulang seluruh papan)."""
    po = await db.purchase_orders.find_one({"id": po_id}, {"_id": 0})
    if not po:
        raise BoardError("PO tidak ditemukan.")
    lines = await line_master()
    stages = await stage_master()
    tasks_by_po, rolls_by_po, products, so_numbers = await _fetch_context([po])
    return build_row(po, lines=lines, stages=stages, products=products,
                     tasks=tasks_by_po.get(po_id, []), rolls=rolls_by_po.get(po_id, []),
                     so_numbers=so_numbers)


# ═══════════════════════════════════════════════════════════════════════════
# 6. TULIS: tandai tahap (satu-satunya hal yang disimpan papan ini)
# ═══════════════════════════════════════════════════════════════════════════
async def set_stage(po_id: str, *, stage_code: str, status: str, note: str = "",
                    actor: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Tandai satu tahap PO (`pending`/`in_progress`/`done`).

    Tiga penolakan yang SENGAJA — semuanya dengan kalimat menuntun, bukan 500:
      1. tahap di luar urutan lini dokumen ini (salah papan / salah ketik);
      2. **tahap turunan** (`inspect`) — tidak boleh ditandai manual, apa pun
         perannya. Ini pagar terpenting fase ini: tanpa dia papan bisa mengaku
         sudah diinspeksi tanpa satu dokumen inspeksi pun;
      3. status di luar tiga status yang dikenal.
    """
    actor = actor or {}
    code = str(stage_code or "").strip().lower()
    status = str(status or "").strip().lower()
    po = await db.purchase_orders.find_one({"id": po_id}, {"_id": 0})
    if not po:
        raise BoardError("PO tidak ditemukan.")
    # Pagar lini: staf printing tidak boleh menyentuh pekerjaan lini woven.
    line_scope.assert_can_touch(actor, po, what=f"PO {po.get('po_number', '')}",
                                field=line_scope.LINES_FIELD)
    lines = await line_master()
    seq = sequence_for(po, lines)
    if not seq:
        raise BoardError(
            f"PO {po.get('po_number', '')} belum punya lini produk, jadi urutan "
            "tahapnya tidak diketahui. Isi lini pada produk yang dipesan (Produk & "
            "Harga → Produk) atau tambahkan lini di Pengaturan → Master → Lini Produk.")
    if code in DERIVED_STAGES:
        stages = await stage_master()
        label = (stages.get(code) or {}).get("name") or code
        raise BoardError(
            f"Tahap \"{label}\" tidak bisa ditandai manual: statusnya mengikuti hasil "
            "pemeriksaan mutu barang yang diterima (QC penerimaan). Lakukan inspeksi "
            "di Gudang → Inspeksi QC; papan akan berubah sendiri.")
    if code not in seq:
        raise BoardError(
            f"Tahap \"{code}\" bukan bagian dari urutan lini PO ini. Tahap yang sah: "
            f"{', '.join(seq)}.")
    if status not in STAGE_STATUSES:
        raise BoardError(f"Status tahap \"{status}\" tidak dikenal. Pilihan: "
                         f"{', '.join(STAGE_STATUSES)}.")

    stages = await stage_master()
    label = (stages.get(code) or {}).get("name") or code
    rows = [r for r in (po.get("stage_progress") or [])
            if str((r or {}).get("stage_code") or "").strip().lower() != code]
    entry = {"stage_code": code, "status": status, "note": note or "",
             "at": now_iso(), "by": actor.get("name", "") or "Sistem",
             "by_id": actor.get("id", "")}
    if status != "pending":
        rows.append(entry)
    # `pending` = MEMBATALKAN tanda (mis. keliru klik "selesai"): barisnya dibuang
    # supaya papan tidak menyimpan "belum mulai, ditandai oleh X jam 10" — jejak
    # yang membingungkan karena tidak ada yang dikerjakan.
    rows.sort(key=lambda r: seq.index(r["stage_code"]) if r["stage_code"] in seq else 99)
    await db.purchase_orders.update_one({"id": po_id}, {
        "$set": {"stage_progress": rows, "updated_at": now_iso()},
        "$push": {"timeline": timeline_entry(
            f"stage_{status}", f"Tahap {label}: {STAGE_STATUS_LABEL[status]}",
            actor.get("name", "") or "Sistem", note or "")},
    })
    return await row_of(po_id, actor)


async def po_for_scope(po_id: str) -> Dict[str, Any]:
    """PO mentah untuk pemeriksaan pagar entitas di router (tanpa enrichment)."""
    po = await db.purchase_orders.find_one({"id": po_id}, {"_id": 0})
    if not po:
        raise BoardError("PO tidak ditemukan.")
    return safe_doc(po)


# ═══════════════════════════════════════════════════════════════════════════
# 7. MIGRASI — satu pintu untuk basis data lama & data demo
# ═══════════════════════════════════════════════════════════════════════════
async def ensure_stage_field(dbx: Any = None, *, dry_run: bool = False) -> Dict[str, Any]:
    """Beri `stage_progress: []` kepada PO yang belum punya field-nya.

    KENAPA FUNGSI INI DI SERVICE, BUKAN DI SKRIP MIGRASI
    ----------------------------------------------------
    Ada DUA pemanggil: CLI `scripts/migrate_po_stage_progress.py` (basis data lama)
    dan `seed_realistic.py` (data demo). Kalau logikanya ditulis di skrip, seeder
    harus menyalinnya — dan salinan kedua adalah tempat arti mulai menyimpang:
    satu basis data bisa "hijau" sementara yang lain merah tanpa ada yang tahu
    mana yang benar (pelajaran FASE L: `line_scope.backfill` dipakai kedua pintu).

    **Tidak pernah menimpa** progres yang sudah ada: migrasi yang bisa menghapus
    keputusan manusia adalah migrasi yang berbahaya.
    """
    target = dbx if dbx is not None else db
    total = await target.purchase_orders.count_documents({})
    missing = await target.purchase_orders.count_documents({"stage_progress": {"$exists": False}})
    written = 0
    if missing and not dry_run:
        res = await target.purchase_orders.update_many(
            {"stage_progress": {"$exists": False}}, {"$set": {"stage_progress": []}})
        written = res.modified_count
    with_progress = await target.purchase_orders.count_documents(
        {"stage_progress": {"$exists": True, "$ne": []}})
    return {"total": total, "missing_before": missing, "written": written,
            "with_progress": with_progress, "dry_run": bool(dry_run)}
