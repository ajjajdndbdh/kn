"""FASE I — **INSPEKSI & QC SEBAGAI DOKUMEN** (`<ENT>/INS-#####`).

## Lubang nyata yang ditutup
Angka cacat & grade sudah dihitung `qc_inspection_service` (4-point) dan tersimpan di
roll. Yang TIDAK pernah ada: **SPK-nya**. Praktik pemilik memakai lembar kertas
"Inspect PO", "Inspect Retur (per PT)", "Inspect retur & replacement" — berisi petugas,
tanggal, milestone, hasil **warna** & **handfeel** dibanding sample yang di-ACC, lalu
keputusan. Tanpa dokumennya, tiga pertanyaan pemilik tak terjawab: siapa memeriksa,
kapan, dan atas dasar apa barang diterima/ditolak.

## Aturan yang dijaga di sini (BUKAN di layar) — §3.4 rencana MD-ERP
1. **Bukan pintu ke-3 untuk grade.** Poin cacat & grade tetap dihitung
   `qc_inspection_service.inspect_roll()`, dan grade tetap hanya berubah lewat
   `grade_service.set_roll_grade(source="qc_inspection")`. `lines[]` di dokumen ini
   adalah **RINGKASAN + keputusan**; `points_snapshot`/`grade_after` disalin dari hasil
   pemanggilan itu, tidak dihitung ulang. Kalau ia menghitung sendiri, dua angka akan
   berbeda dan tak ada cara memilih mana yang benar.
2. **Warna & handfeel disimpan DI ROLL** (`inventory_rolls.inspection`), karena
   pertanyaannya ("roll ini warnanya beda dari sample — boleh masuk gudang?")
   ditanyakan di roll, dan di sanalah pagar putaway membacanya.
3. **Melengkapi, bukan menggantikan** tugas `qc_pending`: dokumen `po_receipt` LAHIR
   OTOMATIS saat tugas penerimaan masuk antrean QC (`ensure_for_qc_task`), idempotent.
4. **Retur**: SSOT hasil per barang tetap `sales_returns.items[].inspection`
   (`return_service`). Dokumen `inspections(kind=return_customer)` adalah SPK +
   milestone + ringkasan — lines-nya menunjuk barang retur, tidak menyalin hasilnya.
5. **Keputusan `tolak` WAJIB ber-alasan** dan alasannya tersimpan di DOKUMEN (bukan
   hanya di audit log, yang tidak pernah dibaca orang yang sedang bertanya).

## Kebijakan selisih (keputusan pemilik #5)
`qc.color_mismatch_action` bawaan **tahan** · `qc.handfeel_mismatch_action` bawaan
**peringatkan** (`abaikan|peringatkan|tahan`). Roll yang DITAHAN tidak boleh putaway
sampai **manajer** melepasnya ber-alasan (`release_hold`).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from core_utils import new_id, next_doc_number, now_iso, safe_doc, timeline_entry
from db import db
from services import line_scope

COLL = "inspections"

# ─── Jenis dokumen (pembeda `kind`, satu koleksi) ────────────────────────────
KIND_PO_RECEIPT = "po_receipt"
KIND_MAKLOON_OUTPUT = "makloon_output"
KIND_RETURN_CUSTOMER = "return_customer"
KIND_RETURN_SUPPLIER = "return_supplier"
KIND_REPLACEMENT = "replacement"

KIND_LABEL: Dict[str, str] = {
    KIND_PO_RECEIPT: "Inspeksi Penerimaan PO",
    KIND_MAKLOON_OUTPUT: "Inspeksi Hasil Makloon",
    KIND_RETURN_CUSTOMER: "Inspeksi Retur Pelanggan",
    KIND_RETURN_SUPPLIER: "Inspeksi Retur ke Supplier",
    KIND_REPLACEMENT: "Inspeksi Barang Pengganti",
}

# ─── Mesin keadaan (sengaja pendek) ──────────────────────────────────────────
STATUS_DRAFT = "draft"
STATUS_ASSIGNED = "assigned"
STATUS_IN_PROGRESS = "in_progress"
STATUS_DONE = "done"
STATUS_CLOSED = "closed"

STATUS_LABEL: Dict[str, str] = {
    STATUS_DRAFT: "Draf (belum ditugaskan)",
    STATUS_ASSIGNED: "Ditugaskan",
    STATUS_IN_PROGRESS: "Sedang diperiksa",
    STATUS_DONE: "Selesai (sudah diputuskan)",
    STATUS_CLOSED: "Ditutup",
}
BOARD_ORDER: Tuple[str, ...] = (STATUS_DRAFT, STATUS_ASSIGNED, STATUS_IN_PROGRESS,
                               STATUS_DONE, STATUS_CLOSED)
OPEN_STATUSES: Tuple[str, ...] = (STATUS_DRAFT, STATUS_ASSIGNED, STATUS_IN_PROGRESS)

DECISIONS: Dict[str, str] = {
    "terima": "Diterima seluruhnya",
    "terima_sebagian": "Diterima sebagian",
    "turun_grade": "Diterima dengan turun grade",
    "tolak": "Ditolak",
}
COLOR_RESULTS: Dict[str, str] = {
    "sesuai": "Sesuai sample",
    "beda_shade": "Beda shade (warna menyimpang)",
    "tolak": "Warna tidak bisa diterima",
}
HANDFEEL_RESULTS: Dict[str, str] = {
    "sesuai": "Sesuai sample",
    "beda": "Beda rasa/konstruksi",
    "tolak": "Handfeel tidak bisa diterima",
}
MISMATCH_ACTIONS: Dict[str, str] = {
    "abaikan": "Diabaikan",
    "peringatkan": "Diberi peringatan",
    "tahan": "Barang DITAHAN sampai ada keputusan",
}
#: Panjang MINIMUM alasan wajib (tolak · buka kembali · lepas tahanan).
#:
#: Angkanya bukan selera: rencana §I.E menuntut "alasan wajib (minimal satu kalimat)",
#: dan ambang lama (5 huruf) meloloskan "jelek" — kata yang secara teknis mengisi kolom
#: tetapi tidak menjawab apa pun bagi supplier yang menerima klaimnya, maupun bagi
#: manajer yang setahun kemudian bertanya "kenapa barang ini dulu ditolak?". Alasan
#: yang tidak bisa dipakai orang lain sama saja dengan kolom kosong yang terisi.
MIN_REASON = 15
#: Peran yang boleh melepas tahanan (keputusan pemilik #5: **manajer**).
HOLD_RELEASE_ROLES: Tuple[str, ...] = ("admin", "manager")


class InspectionError(ValueError):
    """Kesalahan ber-kalimat siap tampil (Bahasa Indonesia)."""


# ═════════════════════════════════════════════════════════════════════════════
#  Util
# ═════════════════════════════════════════════════════════════════════════════
def _today() -> str:
    return now_iso()[:10]


async def _policy(entity_id: str) -> Dict[str, str]:
    """Kebijakan selisih warna & handfeel yang BERLAKU (config, bukan `if` di kode)."""
    from services.config_resolver import value_of
    ctx = {"entity_id": entity_id or ""}
    color = str(await value_of("qc.color_mismatch_action", ctx) or "tahan").lower()
    hand = str(await value_of("qc.handfeel_mismatch_action", ctx) or "peringatkan").lower()
    if color not in MISMATCH_ACTIONS:
        color = "tahan"
    if hand not in MISMATCH_ACTIONS:
        hand = "peringatkan"
    return {"color": color, "handfeel": hand}


async def get_one(ins_id: str) -> Optional[Dict[str, Any]]:
    doc = await db[COLL].find_one({"id": ins_id}, {"_id": 0})
    return safe_doc(doc) if doc else None


async def _load(ins_id: str) -> Dict[str, Any]:
    doc = await db[COLL].find_one({"id": ins_id}, {"_id": 0})
    if not doc:
        raise InspectionError("Dokumen inspeksi tidak ditemukan.")
    return doc


def _line_of(doc: Dict[str, Any], line_id: str) -> Dict[str, Any]:
    for ln in (doc.get("lines") or []):
        if ln.get("id") == line_id:
            return ln
    raise InspectionError("Baris inspeksi tidak ditemukan di dokumen ini.")


def _assert_status(doc: Dict[str, Any], allowed: Tuple[str, ...], what: str) -> None:
    if str(doc.get("status") or "") not in allowed:
        raise InspectionError(
            f"Inspeksi berstatus \u201c{STATUS_LABEL.get(doc.get('status'), doc.get('status'))}\u201d "
            f"tidak bisa {what}.")


def summarize(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Ringkasan dokumen — DIHITUNG dari `lines[]`, tidak pernah dikirim klien.

    Dua satuan (FASE U) memakai bentuk KANONIK repo ini: `qty_rolls` + `quantity` +
    `unit` **datar** di setiap baris — bukan objek `qty{}` tersendiri. Alasannya bukan
    selera: `dual_qty_service.stamp()`, `core_utils.qty_dual()`, `<QtyDual/>`,
    `qtyDualCsv`, mesin PDF, dan penjaga `INV-QTY-01` semuanya membaca nama field itu.
    Bentuk ketiga untuk fakta yang sama = tepat kelas bug yang FASE U tutup.

    `rolls` dijumlahkan dari `qty_rolls` (None = "belum diisi", jadi tidak ikut dan
    tidak dipalsukan menjadi 0). `measure` dijumlahkan HANYA bila satuan seluruh baris
    sama — mencampur meter dengan kilogram menghasilkan angka yang terlihat benar dan
    menyesatkan.
    """
    lines = doc.get("lines") or []
    units = {str(ln.get("unit") or "") for ln in lines}
    units.discard("")
    measure = None
    if len(units) == 1:
        measure = round(sum(float(ln.get("quantity") or 0) for ln in lines), 2)
    roll_vals = [ln.get("qty_rolls") for ln in lines
                 if ln.get("qty_rolls") not in (None, "")]
    grades: Dict[str, int] = {}
    for ln in lines:
        g = str(ln.get("grade_after") or "").strip()
        if g:
            grades[g] = grades.get(g, 0) + 1
    return {
        "lines": len(lines),
        "rolls": (int(sum(float(v) for v in roll_vals)) if roll_vals else None),
        "measure": measure,
        "unit": (list(units)[0] if len(units) == 1 else ""),
        "points_total": round(sum(float(ln.get("points_snapshot") or 0)
                                  for ln in lines), 2),
        "grade_after_counts": grades,
        "inspected": sum(1 for ln in lines if ln.get("inspected_at")),
        "color_mismatch": sum(1 for ln in lines
                              if str(ln.get("color_result") or "") not in ("", "sesuai")),
        "handfeel_mismatch": sum(1 for ln in lines
                                 if str(ln.get("handfeel_result") or "") not in ("", "sesuai")),
        "hold": sum(1 for ln in lines if ln.get("hold")),
        "rejected": sum(1 for ln in lines if str(ln.get("decision") or "") == "tolak"),
    }


async def _save(doc: Dict[str, Any], event: str, label: str, actor: Dict[str, Any],
                note: str = "", **fields: Any) -> Dict[str, Any]:
    """Satu pintu simpan: ringkasan selalu ikut dihitung, riwayat selalu bertambah."""
    merged = {**doc, **fields}
    fields["summary"] = summarize(merged)
    fields["updated_at"] = now_iso()
    await db[COLL].update_one(
        {"id": doc["id"]},
        {"$set": fields,
         "$push": {"history": timeline_entry(event, label, actor.get("name", ""), note)}})
    return safe_doc(await db[COLL].find_one({"id": doc["id"]}, {"_id": 0}))


# ═════════════════════════════════════════════════════════════════════════════
#  Baris dokumen — dibangun dari kenyataan (roll / barang retur), bukan diketik
# ═════════════════════════════════════════════════════════════════════════════
async def _lines_from_rolls(rolls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    pids = list({r.get("product_id") for r in rolls if r.get("product_id")})
    prods = {p["id"]: p for p in await db.products.find(
        {"id": {"$in": pids}},
        {"_id": 0, "id": 1, "sku": 1, "name": 1, "gramasi": 1, "lebar": 1,
         "color_id": 1, "color_code": 1, "line_code": 1}).to_list(2000)}
    out: List[Dict[str, Any]] = []
    for r in sorted(rolls, key=lambda x: str(x.get("roll_no") or "")):
        p = prods.get(r.get("product_id"), {})
        insp = r.get("inspection") or {}
        out.append({
            "id": new_id("insl"),
            "roll_id": r.get("id", ""), "roll_no": r.get("roll_no", ""),
            "lot": r.get("lot", ""), "dye_lot": r.get("dye_lot", ""),
            "product_id": r.get("product_id", ""), "sku": p.get("sku", ""),
            "article": p.get("name", ""),
            "color_id": p.get("color_id", ""), "color_code": p.get("color_code", ""),
            "gsm_standard": p.get("gramasi"), "width_standard": p.get("lebar"),
            # FASE U — dua satuan dalam bentuk KANONIK & datar: satu baris = satu roll
            # fisik (`qty_rolls`) + ukurannya (`quantity` + `unit`). Nama field ini
            # dibaca `<QtyDual/>`, `qtyDualCsv`, mesin PDF, dan INV-QTY-01.
            "qty_rolls": 1,
            "quantity": float(r.get("length_remaining") or r.get("length_initial") or 0),
            "unit": r.get("unit", "meter"),
            "points_snapshot": insp.get("points"),
            "grade_before": r.get("grade", ""), "grade_after": "",
            "gsm_actual": insp.get("gsm_actual"), "width_actual": insp.get("width_actual"),
            "color_result": "", "handfeel_result": "", "handfeel_score": None,
            "delta_e": None, "decision": "", "remark": "",
            "hold": False, "hold_reason": "",
            "inspected_by": "", "inspected_at": "",
        })
    return out


def _lines_from_return_items(ret: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Baris untuk retur — MENUNJUK barang retur, tidak menyalin hasil inspeksinya.

    SSOT hasil per barang tetap `sales_returns.items[].inspection` (`return_service`).
    Yang hidup di sini hanya pekerjaan pemeriksaannya (siapa, kapan, keputusan).
    """
    out: List[Dict[str, Any]] = []
    for idx, it in enumerate(ret.get("items") or []):
        out.append({
            "id": new_id("insl"),
            "roll_id": "", "roll_no": "",
            "return_item_index": idx,
            "lot": it.get("lot", ""), "dye_lot": it.get("dye_lot", ""),
            "product_id": it.get("product_id", ""), "sku": it.get("sku", ""),
            "article": it.get("product_name", "") or it.get("name", ""),
            "color_id": "", "color_code": "",
            "gsm_standard": None, "width_standard": None,
            # FASE U — bentuk kanonik & datar. `qty_rolls` boleh None: retur LAMA
            # memang tidak menyebut jumlah gulungan, dan "—" lebih jujur dari "0 roll".
            "qty_rolls": (None if it.get("qty_rolls") in (None, "")
                          else int(it.get("qty_rolls"))),
            "quantity": float(it.get("quantity") or 0),
            "unit": it.get("unit", "meter"),
            "points_snapshot": None,
            "grade_before": (it.get("inspection") or {}).get("grade", ""),
            "grade_after": "",
            "gsm_actual": None, "width_actual": None,
            "color_result": "", "handfeel_result": "", "handfeel_score": None,
            "delta_e": None, "decision": "", "remark": "",
            "hold": False, "hold_reason": "",
            "inspected_by": "", "inspected_at": "",
        })
    return out


# ═════════════════════════════════════════════════════════════════════════════
#  Order makloon — SATU definisi untuk "nomor · mitra · barang hasilnya"
# ═════════════════════════════════════════════════════════════════════════════
# Ketiga fakta ini dibaca DUA permukaan: pemilih dokumen di pop-up "Buat SPK"
# (`GET /api/inspections/meta/ref-docs`) dan pembuat dokumennya (`create`). Ditulis
# SEKALI di sini supaya label yang dilihat kepala gudang sama dengan isi dokumen yang
# lahir — kalau dua tempat menghitungnya masing-masing, pemilih bisa berkata
# "MKO-00003 · CV Celup Warna Abadi" sementara SPK-nya lahir tanpa nama mitra.
#
# TERUKUR 2026-08-23 (kenapa helper ini ada, bukan selera gaya): versi pertama
# `create()` membaca `mko["number"]`, `mko["makloon_name"]`, dan mencari roll lewat
# `inventory_rolls.makloon_order_id`. **Ketiganya tidak ada:**
#   * nomor order makloon disimpan di **`mko_number`** (`number` = 0 dokumen);
#   * `makloon_id`/`makloon_name` hidup di **`steps[]`** — mitra bisa berbeda per tahap
#     (MKO-00004 lewat 3 mitra);
#   * `inventory_rolls` **tidak punya** `makloon_order_id` (0 dari 66 roll). Penaut yang
#     nyata: `steps[].output_lot_ids` → `inventory_rolls.lot_id`.
# Akibatnya SPK hasil makloon lahir tanpa nomor acuan, tanpa nama mitra, dan **NOL
# BARIS** (diukur: `KSC/INS-00005` lahir `lines=[]`) — dokumen yang tidak bisa
# diperiksa siapa pun, dan tidak ada galat yang memberi tahu. Persis kelas cacat yang
# paling mahal di repo ini: bukan error, tetapi dokumen yang tenang-tenang kosong.
def makloon_ref_number(mko: Dict[str, Any]) -> str:
    """Nomor order makloon: **`mko_number`** (`number` hanya cadangan dokumen lama)."""
    return str(mko.get("mko_number") or mko.get("number") or "")


def makloon_output_lot_ids(mko: Dict[str, Any]) -> List[str]:
    """Lot HASIL order makloon — satu-satunya penaut nyata ke roll fisiknya."""
    out: List[str] = []
    for s in (mko.get("steps") or []):
        out.extend(str(x) for x in (s.get("output_lot_ids") or []) if x)
        if s.get("output_lot_id"):
            out.append(str(s["output_lot_id"]))
    return sorted(set(out))


def makloon_vendor(mko: Dict[str, Any]) -> Tuple[str, str]:
    """Mitra yang MENYERAHKAN hasil akhir (tahap ber-output dengan `seq` terbesar).

    Order makloon berantai bisa melewati beberapa mitra. Yang diinspeksi adalah barang
    yang DISERAHKAN, jadi nama yang wajib tercetak di SPK adalah mitra tahap terakhir
    yang benar-benar mengeluarkan hasil — bukan mitra tahap pertama (yang mungkin hanya
    menenun bahan setengah jadi dan sudah dinilai di SPK sebelumnya).
    """
    steps = sorted((mko.get("steps") or []), key=lambda s: int(s.get("seq") or 0))
    pilih: Dict[str, Any] = {}
    for s in steps:
        if (s.get("output_lot_ids") or s.get("output_lot_id")) and s.get("makloon_name"):
            pilih = s
    if not pilih:
        for s in steps:
            if s.get("makloon_name"):
                pilih = s
    return (str(pilih.get("makloon_id") or ""), str(pilih.get("makloon_name") or ""))


async def spk_for_ref(kind: str, ref_id: str,
                      statuses: Optional[Tuple[str, ...]] = None) -> Dict[str, Any]:
    """SPK yang SUDAH ADA untuk dokumen sumber ini (dict kosong bila belum ada).

    Dipakai dua arah: pemilih dokumen MENANDAINYA ("sudah ada SPK …") dan `create()`
    MENOLAK menerbitkan SPK kedua selama SPK lamanya masih terbuka. Tanpa pagar ini
    `sales_returns.inspection_id` — satu field, satu nilai — akan menunjuk SPK terbaru
    dan SPK lama jadi yatim yang tetap mengaku memeriksa retur itu; garis waktu retur
    lalu menyebut nomor yang salah tanpa satu pun galat muncul.
    """
    if not (kind and ref_id):
        return {}
    q: Dict[str, Any] = {"kind": kind, "ref_doc_id": ref_id}
    if statuses:
        q["status"] = {"$in": list(statuses)}
    return await db[COLL].find_one(
        q, {"_id": 0, "id": 1, "number": 1, "status": 1, "kind": 1}) or {}


async def _baseline_for(product_ids: List[str], entity_id: str) -> Dict[str, str]:
    """Acuan sample yang di-ACC untuk produk ini (FASE S → `md_samples` + kontraknya).

    Petugas inspect butuh tahu "dibandingkan dengan apa". Tanpa acuan yang disebut
    NAMANYA, kolom "warna sesuai?" hanya jadi pendapat.
    """
    if not product_ids:
        return {}
    q = {"status": "decided", "entity_id": entity_id}
    rows = await db.md_samples.find(
        q, {"_id": 0, "id": 1, "number": 1, "product_id": 1, "spec_id": 1,
            "color_target": 1, "decision": 1, "sample_types": 1}
    ).sort("created_at", -1).to_list(300)
    specs = {}
    spec_ids = [r.get("spec_id") for r in rows if r.get("spec_id")]
    if spec_ids:
        specs = {s["id"]: s for s in await db.md_specs.find(
            {"id": {"$in": spec_ids}},
            {"_id": 0, "id": 1, "product_id": 1}).to_list(300)}
    for r in rows:
        pid = r.get("product_id") or (specs.get(r.get("spec_id"), {}) or {}).get("product_id")
        if pid and pid in product_ids:
            color = r.get("color_target") or {}
            return {
                "baseline_sample_id": r.get("id", ""),
                "baseline_sample_number": r.get("number", ""),
                "baseline_contract_id": (r.get("decision") or {}).get("contract_id", ""),
                "baseline_color": (f"{color.get('name', '')}"
                                   f"{' (' + color.get('code', '') + ')' if color.get('code') else ''}"
                                   ).strip(),
            }
    return {}


# ═══════════════════════════════════════════════════════════════════════════════
#  LAHIR: manual (SPK) & OTOMATIS (penerimaan PO masuk antrean QC)
# ═══════════════════════════════════════════════════════════════════════════════
async def _new_doc(*, kind: str, entity_id: str, actor: Dict[str, Any],
                   ref_doc_type: str = "", ref_doc_id: str = "", ref_doc_number: str = "",
                   task_id: str = "", supplier: Tuple[str, str] = ("", ""),
                   customer: Tuple[str, str] = ("", ""), line_code: str = "",
                   lines: Optional[List[Dict[str, Any]]] = None,
                   spk_date: str = "", assigned: Tuple[str, str, str] = ("", "", ""),
                   remark: str = "") -> Dict[str, Any]:
    """Rakit + simpan satu dokumen inspeksi (satu jalan lahir, dipakai kedua pintu)."""
    if not entity_id or entity_id == "all":
        raise InspectionError(
            "Pilih satu badan usaha dulu — dokumen inspeksi selalu milik satu badan usaha.")
    if kind not in KIND_LABEL:
        raise InspectionError(f"Jenis inspeksi harus salah satu: {', '.join(KIND_LABEL)}.")
    rows = list(lines or [])
    baseline = await _baseline_for([r.get("product_id") for r in rows if r.get("product_id")],
                                  entity_id)
    now = now_iso()
    assigned_id, assigned_name, bagian = assigned
    doc: Dict[str, Any] = {
        "id": new_id("ins"),
        "number": await next_doc_number(COLL, "number", "INS-", entity_id=entity_id),
        "entity_id": entity_id,
        # FASE L — snapshot lini: papan printing tidak boleh menampilkan pekerjaan woven.
        "line_code": line_scope.norm(line_code),
        "kind": kind,
        "ref_doc_type": ref_doc_type, "ref_doc_id": ref_doc_id,
        "ref_doc_number": ref_doc_number,
        "task_id": task_id,
        "supplier_id": supplier[0], "supplier_name": supplier[1],
        "customer_id": customer[0], "customer_name": customer[1],
        "spk_date": (spk_date or "").strip() or _today(),
        "assigned_to": assigned_id, "assigned_name": assigned_name,
        "bagian": (bagian or "").strip() or "Bagian Inspect",
        "started_at": "", "finished_at": "",
        "status": STATUS_ASSIGNED if assigned_id else STATUS_DRAFT,
        **{"baseline_sample_id": "", "baseline_sample_number": "",
           "baseline_contract_id": "", "baseline_color": ""},
        **baseline,
        "lines": rows,
        "decision": "", "decision_label": "", "remark": (remark or "").strip(),
        "reject_reason": "", "reopen_reason": "",
        "created_by": actor.get("name", ""), "created_by_id": actor.get("id", ""),
        "created_at": now, "updated_at": now,
        "history": [timeline_entry("created", f"{KIND_LABEL[kind]} dibuat",
                                   actor.get("name", ""),
                                   ref_doc_number or task_id or "")],
    }
    doc["summary"] = summarize(doc)
    if assigned_id:
        doc["history"].append(timeline_entry(
            "assigned", f"Ditugaskan ke {assigned_name}", actor.get("name", ""),
            doc["bagian"]))
    await db[COLL].insert_one(dict(doc))
    # FASE G-4 — jejak dua arah ke dokumen sumbernya, supaya "inspeksi ini milik PO
    # mana" bisa dijawab dari dua sisi (dan `INV-REF-01` tidak menuduh yatim).
    if ref_doc_type and ref_doc_id:
        try:
            from services import doc_refs_service as _refs
            await _refs.safe_link(("inspection", doc["id"]), (ref_doc_type, ref_doc_id),
                                  "parent", note="inspeksi atas dokumen ini")
        except Exception:  # noqa: BLE001 — relasi hilang tak boleh menggagalkan SPK
            import logging
            logging.getLogger(__name__).warning(
                "INS: gagal menaut %s -> %s/%s", doc["number"], ref_doc_type, ref_doc_id)
    # Acuan sample yang di-ACC ikut tertaut — supaya pertanyaan "atas dasar apa warna
    # ini dinilai?" bisa dijawab dari DUA sisi (dokumen inspeksi ⇄ sample). Relasinya
    # `references`, BUKAN `parent`: inspeksi tidak lahir dari sample.
    if doc.get("baseline_sample_id"):
        try:
            from services import doc_refs_service as _refs
            await _refs.safe_link(("inspection", doc["id"]),
                                  ("md_sample", doc["baseline_sample_id"]),
                                  "references",
                                  note=f"acuan {doc.get('baseline_sample_number') or 'sample'}")
        except Exception:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning(
                "INS: gagal menaut acuan sample %s", doc.get("baseline_sample_number"))
    return safe_doc(doc)


async def _resolve_assignee(user_id: str) -> Tuple[str, str, str]:
    if not (user_id or "").strip():
        return "", "", ""
    u = await db.users.find_one({"id": user_id},
                                {"_id": 0, "id": 1, "name": 1, "division": 1, "role": 1})
    if not u:
        raise InspectionError("Petugas yang dipilih tidak ditemukan.")
    return u.get("id", ""), u.get("name", ""), u.get("division", "") or ""


async def create(payload: Dict[str, Any], actor: Dict[str, Any],
                 entity_id: str) -> Dict[str, Any]:
    """SPK inspeksi manual (mis. inspeksi retur, barang pengganti, hasil makloon)."""
    kind = str(payload.get("kind") or "").strip().lower()
    ref_type = str(payload.get("ref_doc_type") or "").strip()
    ref_id = str(payload.get("ref_doc_id") or "").strip()
    task_id = str(payload.get("task_id") or "").strip()
    lines: List[Dict[str, Any]] = []
    ref_number = supplier = customer = None
    supplier = ("", "")
    customer = ("", "")
    ref_number = ""
    line_code = str(payload.get("line_code") or "")

    if kind == KIND_PO_RECEIPT:
        if not task_id:
            raise InspectionError(
                "Inspeksi penerimaan PO lahir dari TUGAS penerimaan — sebutkan tugasnya "
                "(biasanya dokumen ini dibuat otomatis saat barang masuk antrean QC).")
        task = await db.wms_tasks.find_one({"id": task_id}, {"_id": 0})
        if not task:
            raise InspectionError("Tugas penerimaan tidak ditemukan.")
        return await ensure_for_qc_task(task, actor, force=True)

    if kind in (KIND_RETURN_CUSTOMER, KIND_REPLACEMENT):
        if not ref_id:
            raise InspectionError("Sebutkan nomor retur yang mau diperiksa.")
        ret = await db.sales_returns.find_one({"id": ref_id}, {"_id": 0})
        if not ret:
            raise InspectionError("Dokumen retur tidak ditemukan.")
        if (ret.get("entity_id") or "") != entity_id:
            raise InspectionError(
                "Retur itu milik badan usaha lain — inspeksinya harus dibuat dari badan "
                "usaha pemilik returnya.")
        ref_type, ref_number = "sales_return", ret.get("number", "")
        customer = (ret.get("customer_id", ""), ret.get("customer_name", ""))
        lines = _lines_from_return_items(ret)
        line_code = line_code or str(ret.get("line_code") or "")
    elif kind == KIND_RETURN_SUPPLIER:
        if not ref_id:
            raise InspectionError("Sebutkan nomor retur pembelian yang mau diperiksa.")
        pret = await db.purchase_returns.find_one({"id": ref_id}, {"_id": 0})
        if not pret:
            raise InspectionError("Dokumen retur pembelian tidak ditemukan.")
        # Pagar badan usaha yang SAMA dengan jalur retur jual di atas. Sempat hanya ada
        # di satu dari tiga jalur — dan pagar yang berlubang di satu jalur bukan pagar:
        # payload bisa menyebut id dokumen PT lain meski pemilihnya sudah ter-scope.
        if (pret.get("entity_id") or "") != entity_id:
            raise InspectionError(
                "Retur pembelian itu milik badan usaha lain — inspeksinya harus dibuat "
                "dari badan usaha pemilik dokumennya.")
        ref_type, ref_number = "purchase_return", pret.get("number", "")
        supplier = (pret.get("supplier_id", ""), pret.get("supplier_name", ""))
        lines = _lines_from_return_items(pret)
        line_code = line_code or str(pret.get("line_code") or "")
    elif kind == KIND_MAKLOON_OUTPUT:
        if not ref_id:
            raise InspectionError("Sebutkan order makloon yang hasilnya mau diperiksa.")
        mko = await db.makloon_orders.find_one({"id": ref_id}, {"_id": 0})
        if not mko:
            raise InspectionError("Order makloon tidak ditemukan.")
        if (mko.get("entity_id") or "") != entity_id:
            raise InspectionError(
                "Order makloon itu milik badan usaha lain — inspeksinya harus dibuat "
                "dari badan usaha pemilik dokumennya.")
        ref_type = "makloon_order"
        ref_number = makloon_ref_number(mko)
        supplier = makloon_vendor(mko)
        lot_ids = makloon_output_lot_ids(mko)
        rolls = (await db.inventory_rolls.find(
            {"lot_id": {"$in": lot_ids}}, {"_id": 0}).to_list(500)) if lot_ids else []
        if not rolls:
            # SPK tanpa barang adalah dokumen yang tidak bisa diperiksa siapa pun.
            # Lebih baik menolak dengan kalimat menuntun daripada menerbitkan dokumen
            # kosong yang baru terasa salah saat petugas membukanya di gudang.
            raise InspectionError(
                f"Order makloon {ref_number or '(tanpa nomor)'} belum menyerahkan hasil "
                "apa pun — belum ada gulungan yang bisa diperiksa. Terima dulu hasilnya "
                "di layar Order Makloon, lalu terbitkan SPK inspeksinya.")
        lines = await _lines_from_rolls(rolls)
        line_code = line_code or str(mko.get("line_code") or "")
    else:
        raise InspectionError(f"Jenis inspeksi harus salah satu: {', '.join(KIND_LABEL)}.")

    # ─── SPK kedua atas dokumen yang sama: DITOLAK selama yang lama masih terbuka ──
    # Pemeriksaan ulang punya pintunya sendiri (`reopen`, ber-alasan wajib). Tanpa pagar
    # ini dua SPK memeriksa barang yang sama, dan `sales_returns.inspection_id` (satu
    # field) hanya bisa menunjuk satu di antaranya — yang lain menjadi yatim yang tetap
    # mengaku memeriksa retur itu.
    lama = await spk_for_ref(kind, ref_id, OPEN_STATUSES)
    if lama:
        raise InspectionError(
            f"Dokumen ini sudah punya SPK yang masih berjalan: {lama.get('number')} "
            f"({STATUS_LABEL.get(str(lama.get('status')), '-')}). Lanjutkan SPK itu — "
            "atau buka kembali (reopen) bila sudah diputuskan — supaya tidak ada dua "
            "SPK memeriksa barang yang sama.")

    assigned = await _resolve_assignee(str(payload.get("assigned_to") or ""))
    doc = await _new_doc(kind=kind, entity_id=entity_id, actor=actor,
                         ref_doc_type=ref_type, ref_doc_id=ref_id,
                         ref_doc_number=ref_number, supplier=supplier,
                         customer=customer, line_code=line_code, lines=lines,
                         spk_date=str(payload.get("spk_date") or ""),
                         assigned=assigned, remark=str(payload.get("remark") or ""))
    # FASE I.F — retur menyimpan SPK yang memeriksanya supaya garis waktu retur bisa
    # menyebut nomornya. Ditulis dari SINI saja (satu penulis untuk satu fakta).
    #
    # HANYA untuk `return_customer`: field `sales_returns.inspection_id` berarti "SPK
    # yang memeriksa BARANG RETURNYA", dan tonggak `inspect_done_at` diturunkan darinya.
    # SPK `replacement` memeriksa barang PENGGANTI — kejadian fisik yang lain — jadi
    # menulisinya ke field yang sama akan menggeser garis waktu retur ke dokumen yang
    # bukan pemeriksa returnya. Jejak dua arahnya tidak hilang: `_new_doc` sudah
    # menautkannya lewat `doc_refs_service` (terlihat di Jejak Dokumen).
    if kind == KIND_RETURN_CUSTOMER and ref_type == "sales_return" and ref_id:
        from services import return_service as _ret
        await _ret.attach_inspection(ref_id, doc["id"], doc.get("number", ""))
    return doc


async def ensure_for_qc_task(task: Dict[str, Any], actor: Dict[str, Any],
                             force: bool = False) -> Dict[str, Any]:
    """**IDEMPOTENT**: pastikan tugas penerimaan yang masuk antrean QC punya SPK-nya.

    Dipanggil dari jalur penerimaan (`inbound_receiving`) tepat saat tugas menjadi
    `qc_pending`. Kepala gudang tidak perlu membuat dokumen dari nol — user story I.1.
    Idempotent karena penerimaan bisa diselesaikan ulang / dipanggil ulang oleh POC;
    dokumen kedua untuk tugas yang sama akan membuat dua SPK atas barang yang sama.
    """
    task_id = str(task.get("id") or "")
    if not task_id:
        raise InspectionError("Tugas penerimaan tanpa id — tidak bisa dibuat SPK.")
    existing = await db[COLL].find_one({"task_id": task_id}, {"_id": 0})
    if existing and not force:
        return safe_doc(existing)
    if existing and force:
        return safe_doc(existing)

    po = None
    if task.get("po_id"):
        po = await db.purchase_orders.find_one(
            {"id": task["po_id"]},
            {"_id": 0, "id": 1, "po_number": 1, "supplier_id": 1, "supplier_name": 1,
             "entity_id": 1, "line_code": 1})
    entity_id = (po or {}).get("entity_id") or task.get("owner_entity_id") \
        or task.get("entity_id") or ""
    rolls = await db.inventory_rolls.find({"qc_task_id": task_id}, {"_id": 0}).to_list(500)
    lines = await _lines_from_rolls(rolls)
    return await _new_doc(
        kind=KIND_PO_RECEIPT, entity_id=entity_id, actor=actor,
        ref_doc_type="purchase_order" if po else "", ref_doc_id=(po or {}).get("id", ""),
        ref_doc_number=(po or {}).get("po_number", "") or task.get("po_number", ""),
        task_id=task_id,
        supplier=((po or {}).get("supplier_id", ""), (po or {}).get("supplier_name", "")),
        line_code=(po or {}).get("line_code", "") or task.get("line_code", ""),
        lines=lines,
        remark="SPK lahir otomatis saat barang masuk antrean QC.")


# ═══════════════════════════════════════════════════════════════════════════════
#  Alur: tugaskan → mulai → periksa baris → tutup dengan keputusan
# ═══════════════════════════════════════════════════════════════════════════════
async def assign(ins_id: str, payload: Dict[str, Any],
                 actor: Dict[str, Any]) -> Dict[str, Any]:
    doc = await _load(ins_id)
    _assert_status(doc, OPEN_STATUSES, "ditugaskan ulang")
    aid, aname, _div = await _resolve_assignee(str(payload.get("assigned_to") or ""))
    if not aid:
        raise InspectionError("Pilih petugas inspect-nya dulu.")
    bagian = str(payload.get("bagian") or "").strip() or doc.get("bagian") or "Bagian Inspect"
    spk = str(payload.get("spk_date") or "").strip() or doc.get("spk_date") or _today()
    status = doc.get("status")
    if status == STATUS_DRAFT:
        status = STATUS_ASSIGNED
    saved = await _save(doc, "assigned", f"Ditugaskan ke {aname}", actor, bagian,
                        assigned_to=aid, assigned_name=aname, bagian=bagian,
                        spk_date=spk, status=status)
    # FASE N butir 4 — "SPK inspeksi ditugaskan ke SAYA". Sampai FASE I ditutup,
    # penugasan hanya terlihat bila petugasnya kebetulan membuka layar SPK Inspeksi;
    # tidak ada satu pun pemberitahuan. Alamatnya jelas dan tunggal (orang yang
    # ditugaskan), jadi ini justru contoh peristiwa yang TIDAK boleh ber-`recipient_role`
    # sama sekali — cukup `recipient_user`.
    try:
        from services import notification_service as notif
        await notif.create_notification(
            notif_type="inspection_assigned",
            title=f"SPK Inspeksi untuk Anda: {saved.get('number', '')}",
            body=(f"{KIND_LABEL.get(str(saved.get('kind') or ''), 'Inspeksi')} · "
                  f"{len(saved.get('lines') or [])} baris · bagian {bagian}. "
                  f"Ditugaskan oleh {actor.get('name', '')}."),
            severity="info", link="inspections",
            entity_id=saved.get("entity_id"),
            recipient_role="", recipient_user=aid,
            ref=f"ins_assigned:{saved.get('id', '')}:{aid}")
    except Exception:  # noqa: BLE001
        pass          # penugasan tetap sah walau pemberitahuannya gagal
    return saved


async def start(ins_id: str, actor: Dict[str, Any]) -> Dict[str, Any]:
    doc = await _load(ins_id)
    _assert_status(doc, (STATUS_DRAFT, STATUS_ASSIGNED), "dimulai")
    if not doc.get("assigned_to"):
        raise InspectionError(
            "Tugaskan petugasnya dulu — SPK tanpa nama tidak bisa dipertanggungjawabkan.")
    return await _save(doc, "started", "Pemeriksaan dimulai", actor,
                       status=STATUS_IN_PROGRESS, started_at=now_iso())


async def inspect_line(ins_id: str, line_id: str, payload: Dict[str, Any],
                       actor: Dict[str, Any]) -> Dict[str, Any]:
    """Isi hasil SATU baris. Angka cacat & grade DIHITUNG mesin lama, bukan di sini."""
    doc = await _load(ins_id)
    _assert_status(doc, (STATUS_ASSIGNED, STATUS_IN_PROGRESS), "diisi hasilnya")
    line = _line_of(doc, line_id)
    color = str(payload.get("color_result") or "").strip().lower()
    hand = str(payload.get("handfeel_result") or "").strip().lower()
    if color and color not in COLOR_RESULTS:
        raise InspectionError(f"Hasil warna harus salah satu: {', '.join(COLOR_RESULTS)}.")
    if hand and hand not in HANDFEEL_RESULTS:
        raise InspectionError(f"Hasil handfeel harus salah satu: {', '.join(HANDFEEL_RESULTS)}.")
    decision = str(payload.get("decision") or "").strip().lower()
    if decision and decision not in DECISIONS:
        raise InspectionError(f"Keputusan baris harus salah satu: {', '.join(DECISIONS)}.")
    score = payload.get("handfeel_score")
    if score not in (None, "") and not (1 <= float(score) <= 5):
        raise InspectionError("Skor handfeel di luar batas wajar (1–5). Periksa angkanya.")

    pol = await _policy(doc.get("entity_id", ""))
    patch: Dict[str, Any] = {
        "color_result": color or line.get("color_result", ""),
        "handfeel_result": hand or line.get("handfeel_result", ""),
        "handfeel_score": (float(score) if score not in (None, "") else line.get("handfeel_score")),
        "delta_e": (float(payload["delta_e"]) if payload.get("delta_e") not in (None, "")
                    else line.get("delta_e")),
        "decision": decision or line.get("decision", ""),
        "remark": str(payload.get("remark") or line.get("remark", "")),
        "inspected_by": actor.get("name", ""), "inspected_at": now_iso(),
    }
    warnings: List[str] = []

    if line.get("roll_id"):
        roll = await db.inventory_rolls.find_one({"id": line["roll_id"]}, {"_id": 0})
        if not roll:
            raise InspectionError("Roll pada baris ini sudah tidak ada di gudang.")
        from services import qc_inspection_service as qc
        result = await qc.inspect_roll(
            safe_doc(roll), [d for d in (payload.get("defects") or [])],
            payload.get("gsm_actual"), payload.get("width_actual"),
            str(payload.get("remark") or ""), actor,
            supplier_lot=str(payload.get("supplier_lot") or ""),
            dye_lot=str(payload.get("dye_lot") or ""),
            shade_ref=str(payload.get("shade_ref") or ""),
            color_result=patch["color_result"], handfeel_result=patch["handfeel_result"],
            handfeel_score=patch["handfeel_score"], delta_e=patch["delta_e"],
            baseline_sample_id=doc.get("baseline_sample_id", ""),
            baseline_sample_number=doc.get("baseline_sample_number", ""),
            color_action=pol["color"], handfeel_action=pol["handfeel"],
            inspection_id=doc.get("id", ""), inspection_number=doc.get("number", ""))
        # RINGKASAN, bukan sumber angka: disalin dari hasil pemanggilan di atas.
        patch.update({
            "points_snapshot": result.get("points"),
            "grade_before": result.get("grade_before", line.get("grade_before", "")),
            "grade_after": result.get("grade", ""),
            "gsm_actual": (result.get("roll") or {}).get("inspection", {}).get("gsm_actual"),
            "width_actual": (result.get("roll") or {}).get("inspection", {}).get("width_actual"),
            "hold": bool((result.get("hold") or {}).get("held")),
            "hold_reason": (result.get("hold") or {}).get("reason", ""),
        })
        warnings = list(result.get("qc_warnings") or [])
    else:
        # Baris retur: tidak ada roll → tidak ada grade. Warna/handfeel tetap dicatat
        # sebagai pekerjaan pemeriksaan; hasil per barang tetap milik `sales_returns`.
        if patch["color_result"] not in ("", "sesuai") and pol["color"] == "tahan":
            patch["hold"] = True
            patch["hold_reason"] = ("Warna beda dari sample yang di-ACC — barang ditahan "
                                    "sampai manajer memutuskan.")
            warnings.append(patch["hold_reason"])
        elif patch["handfeel_result"] not in ("", "sesuai") and pol["handfeel"] == "tahan":
            patch["hold"] = True
            patch["hold_reason"] = ("Handfeel beda dari sample yang di-ACC — barang ditahan "
                                    "sampai manajer memutuskan.")
            warnings.append(patch["hold_reason"])

    lines = [({**ln, **patch} if ln.get("id") == line_id else ln)
             for ln in (doc.get("lines") or [])]
    note_bits = [b for b in (
        f"warna {COLOR_RESULTS.get(patch['color_result'], patch['color_result'] or '—')}",
        f"handfeel {HANDFEEL_RESULTS.get(patch['handfeel_result'], patch['handfeel_result'] or '—')}",
        (f"grade {patch.get('grade_after')}" if patch.get("grade_after") else ""),
    ) if b]
    status = doc.get("status")
    if status in (STATUS_DRAFT, STATUS_ASSIGNED):
        status = STATUS_IN_PROGRESS
    out = await _save(doc, "line_inspected",
                      f"Baris {line.get('roll_no') or line.get('sku') or '—'} diperiksa",
                      actor, " · ".join(note_bits), lines=lines, status=status,
                      started_at=doc.get("started_at") or now_iso())
    out["warnings"] = warnings
    return out


async def finish(ins_id: str, decision: str, remark: str,
                 actor: Dict[str, Any]) -> Dict[str, Any]:
    """Tutup inspeksi dengan KEPUTUSAN. `tolak` wajib ber-alasan (tersimpan di dokumen)."""
    doc = await _load(ins_id)
    _assert_status(doc, (STATUS_ASSIGNED, STATUS_IN_PROGRESS), "ditutup")
    dec = str(decision or "").strip().lower()
    if dec not in DECISIONS:
        raise InspectionError(f"Keputusan harus salah satu: {', '.join(DECISIONS)}.")
    note = (remark or "").strip()
    if dec == "tolak" and len(note) < MIN_REASON:
        raise InspectionError(
            "Menolak hasil inspeksi WAJIB ber-alasan — tulis satu kalimat utuh "
            f"(minimal {MIN_REASON} huruf). Alasan ini dibaca supplier/mitra dan "
            "menjadi dasar klaim, jadi “jelek” tidak cukup.")
    lines = doc.get("lines") or []
    if lines and not any(ln.get("inspected_at") for ln in lines):
        raise InspectionError(
            "Belum ada satu baris pun yang diperiksa — keputusan tanpa pemeriksaan "
            "membuat tanggalnya jadi bukti palsu.")
    out = await _save(doc, "finished", f"Keputusan: {DECISIONS[dec]}", actor, note,
                      status=STATUS_DONE, decision=dec, decision_label=DECISIONS[dec],
                      remark=note, reject_reason=(note if dec == "tolak" else ""),
                      finished_at=now_iso(),
                      decided_by=actor.get("name", ""), decided_at=now_iso())
    # FASE I.F — `sales_returns.inspect_done_at` DITURUNKAN dari sini, tidak pernah
    # diketik: dua tanggal "inspeksi selesai" yang bisa berbeda adalah kelas bug
    # yang paling sering menipu di repo ini.
    if doc.get("ref_doc_type") == "sales_return" and doc.get("ref_doc_id"):
        from services import return_service as _ret
        await _ret.mark_inspected_by_document(doc["ref_doc_id"],
                                              out.get("finished_at", ""))
    return out


async def reopen(ins_id: str, reason: str, actor: Dict[str, Any]) -> Dict[str, Any]:
    doc = await _load(ins_id)
    _assert_status(doc, (STATUS_DONE,), "dibuka kembali")
    why = (reason or "").strip()
    if len(why) < MIN_REASON:
        raise InspectionError(
            "Membuka kembali inspeksi WAJIB ber-alasan — tulis satu kalimat utuh "
            f"(minimal {MIN_REASON} huruf). Keputusan yang dianulir tanpa alasan "
            "menghapus jejak tanggung jawab.")
    return await _save(doc, "reopened", "Dibuka kembali", actor, why,
                       status=STATUS_IN_PROGRESS, reopen_reason=why,
                       decision="", decision_label="", finished_at="",
                       # `reject_reason` IKUT dikosongkan — ia milik keputusan yang baru
                       # saja dianulir. Terukur 2026-08-23 di peramban: sesudah dibuka
                       # kembali, panel "ALASAN PENOLAKAN" tetap terpampang sementara
                       # kepala dokumen berkata "Belum diputuskan" — dua pernyataan yang
                       # bertentangan pada satu layar, dan pembaca tidak punya cara tahu
                       # mana yang berlaku. Alasannya TIDAK hilang: baris riwayat
                       # "Keputusan: Ditolak … — <alasan>" tetap ada selamanya.
                       reject_reason="")


async def release_hold(ins_id: str, line_id: str, reason: str,
                       actor: Dict[str, Any]) -> Dict[str, Any]:
    """Lepas tahanan satu baris — hanya **manajer/admin** (keputusan pemilik #5)."""
    doc = await _load(ins_id)
    line = _line_of(doc, line_id)
    if (actor or {}).get("role") not in HOLD_RELEASE_ROLES:
        raise PermissionError(
            "Hanya MANAJER yang boleh melepas tahanan barang yang warnanya beda dari "
            "sample. Mintakan keputusannya lewat papan inspeksi.")
    if not line.get("hold"):
        raise InspectionError("Baris ini tidak sedang ditahan.")
    why = (reason or "").strip()
    if len(why) < MIN_REASON:
        raise InspectionError(
            "Melepas tahanan WAJIB ber-alasan — tulis satu kalimat utuh (minimal "
            f"{MIN_REASON} huruf). Inilah satu-satunya catatan mengapa barang yang "
            "menyimpang tetap masuk gudang.")
    if line.get("roll_id"):
        await db.inventory_rolls.update_one(
            {"id": line["roll_id"]},
            {"$set": {"inspection.hold.held": False,
                      "inspection.hold.released_by": actor.get("name", ""),
                      "inspection.hold.released_at": now_iso(),
                      "inspection.hold.release_reason": why,
                      "updated_at": now_iso()}})
    lines = [({**ln, "hold": False, "hold_released_by": actor.get("name", ""),
               "hold_released_at": now_iso(), "hold_release_reason": why}
              if ln.get("id") == line_id else ln) for ln in (doc.get("lines") or [])]
    return await _save(doc, "hold_released",
                       f"Tahanan baris {line.get('roll_no') or line.get('sku') or '—'} dilepas",
                       actor, why, lines=lines)


# ═══════════════════════════════════════════════════════════════════════════════
#  Daftar & statistik
# ═══════════════════════════════════════════════════════════════════════════════
async def list_inspections(scope: Dict[str, Any], *, kind: str = "", status: str = "",
                           assigned_to: str = "", q: str = "", hold_only: bool = False,
                           skip: int = 0, limit: int = 200) -> Tuple[List[Dict[str, Any]], int]:
    flt: Dict[str, Any] = dict(scope or {})
    if kind:
        flt["kind"] = kind
    if status:
        flt["status"] = status
    if assigned_to:
        flt["assigned_to"] = assigned_to
    if hold_only:
        flt["lines.hold"] = True
    if q:
        rx = {"$regex": q.strip(), "$options": "i"}
        flt["$or"] = [{"number": rx}, {"ref_doc_number": rx}, {"supplier_name": rx},
                      {"customer_name": rx}, {"assigned_name": rx}]
    total = await db[COLL].count_documents(flt)
    rows = await db[COLL].find(flt, {"_id": 0}).sort("created_at", -1) \
        .skip(int(skip)).limit(int(limit)).to_list(int(limit))
    return [safe_doc(r) for r in rows], int(total)


async def stats(scope: Dict[str, Any]) -> Dict[str, Any]:
    flt = dict(scope or {})
    out: Dict[str, Any] = {}
    for st in BOARD_ORDER:
        out[st] = await db[COLL].count_documents({**flt, "status": st})
    out["total"] = await db[COLL].count_documents(flt)
    out["hold"] = await db[COLL].count_documents({**flt, "lines.hold": True})
    out["rejected"] = await db[COLL].count_documents({**flt, "decision": "tolak"})
    return out


async def meta(entity_id: str = "") -> Dict[str, Any]:
    """Kosakata + kebijakan yang BERLAKU — layar tidak boleh menebak keduanya."""
    pol = await _policy(entity_id)
    return {
        "kinds": [{"value": k, "label": v} for k, v in KIND_LABEL.items()],
        "statuses": [{"value": s, "label": STATUS_LABEL[s]} for s in BOARD_ORDER],
        "decisions": [{"value": k, "label": v} for k, v in DECISIONS.items()],
        "color_results": [{"value": k, "label": v} for k, v in COLOR_RESULTS.items()],
        "handfeel_results": [{"value": k, "label": v} for k, v in HANDFEEL_RESULTS.items()],
        "policy": {
            "color_mismatch_action": pol["color"],
            "color_mismatch_label": MISMATCH_ACTIONS[pol["color"]],
            "handfeel_mismatch_action": pol["handfeel"],
            "handfeel_mismatch_label": MISMATCH_ACTIONS[pol["handfeel"]],
            "hold_release_roles": list(HOLD_RELEASE_ROLES),
            # Panjang MINIMUM alasan wajib — dikirim supaya layar tidak menebaknya.
            # Terukur 2026-08-23 di peramban: pop-up alasan hanya menolak isian
            # KOSONG, jadi alasan "pendek" (6 huruf) lolos di layar lalu dijawab
            # **400** oleh server. Pengguna melihat galat merah untuk aturan yang
            # seharusnya sudah terlihat SEBELUM tombolnya bisa ditekan. Ambangnya
            # tetap milik server (`MIN_REASON`); layar hanya menampilkannya.
            "min_reason_length": MIN_REASON,
        },
    }
