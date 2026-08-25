"""Special Order Service - Sub-fase 1.12

Handles business logic for Special Orders (custom products not in catalog).
Simple approval: amount > threshold requires manager approval.
"""
from datetime import datetime, timezone
from typing import Dict, Any, List
from db import db
from core_utils import new_id, now_iso, safe_doc, parse_decimal
import domain_registry as _dr        # Fase A · R7 — SSOT domain (stamp defaults)
from services import status_history as sh

# Gambar default produk custom (sama dengan default ProductPayload)
_DEFAULT_PRODUCT_IMAGE = (
    "https://images.unsplash.com/photo-1774679817333-decf0d988dd5"
    "?crop=entropy&cs=srgb&fm=jpg&ixlib=rb-4.1.0&q=85"
)

# Simple approval threshold (IDR)
APPROVAL_THRESHOLD = 10_000_000

# Status constants (aligned with SO)
STATUS_DRAFT = "draft"
STATUS_PENDING_APPROVAL = "pending_approval"
STATUS_APPROVED = "approved"
STATUS_CONFIRMED = "confirmed"
STATUS_IN_PRODUCTION = "in_production"
STATUS_READY = "ready"
STATUS_SHIPPED = "shipped"
STATUS_DONE = "done"
STATUS_CANCELLED = "cancelled"


async def generate_special_order_number(on_date: Any = None) -> str:
    """Nomor Special Order unik: `SORD-YYMMDD-XXXX`.

    `on_date` (opsional) — TANGGAL yang dipakai di nomor, boleh `datetime` atau teks
    ISO. B6 DIBAYAR (2026-08-25): data demo membuat dokumen "berumur 9 hari" tetapi
    menomorinya dengan tanggal HARI INI (`SORD-260824-0002`), sehingga data demo tidak
    konsisten dengan dirinya sendiri dan siapa pun yang memeriksa penomoran vs tanggal
    akan mengira ada bug penomoran. Bawaannya tetap hari ini (jalur produksi tak
    berubah); penyemai memberikan tanggal dokumennya.
    """
    if on_date is None:
        stamp = datetime.now(timezone.utc)
    elif isinstance(on_date, datetime):
        stamp = on_date
    else:
        try:
            stamp = datetime.fromisoformat(str(on_date).replace("Z", "+00:00"))
        except ValueError:
            stamp = datetime.now(timezone.utc)
    today = stamp.strftime("%y%m%d")
    prefix = f"SORD-{today}"
    
    # Get highest sequence for today
    latest = await db.special_orders.find_one(
        {"number": {"$regex": f"^{prefix}"}},
        sort=[("number", -1)]
    )
    
    if latest:
        last_num = int(latest["number"].split("-")[-1])
        seq = last_num + 1
    else:
        seq = 1
    
    return f"{prefix}-{seq:04d}"


async def evaluate_special_order_approval(total_amount: float, current_status: str) -> str:
    """Determine initial status based on amount.
    
    Returns:
        - 'draft' if amount <= threshold
        - 'pending_approval' if amount > threshold
    """
    if current_status != STATUS_DRAFT:
        return current_status
    
    if total_amount > APPROVAL_THRESHOLD:
        return STATUS_PENDING_APPROVAL
    
    return STATUS_DRAFT


#: Kunci waktu satu entri `status_history[]` — SATU nama, ditetapkan di
#: `services/status_history.py` dan dijaga pagar statik INV-HIST-01.


def waiting_since(so: Dict[str, Any]) -> str:
    """KAPAN dokumen ini mulai menunggu keputusan — dibaca dari dokumennya sendiri.

    B1 (2026-08-25): kebenaran itu sudah lama ADA di `status_history[]`
    (`{"status": "pending_approval", "timestamp": …}`); yang salah adalah papan yang
    membaca field `submitted_at`/`approval_requested_at` yang tak pernah diisi. Entri
    TERAKHIR yang berstatus menunggu dipakai (dokumen bisa masuk-keluar antrean),
    dan bila riwayatnya tidak menyebutnya sama sekali → `created_at`.

    2026-06: kunci waktunya tinggal SATU (`services/status_history.TIME_KEY`). Dulu
    fungsi ini membaca empat nama kunci sekaligus karena `inventory_lots` menulis
    `at` alih-alih `timestamp` — membaca banyak nama hanya menyembunyikan bahwa
    bentuknya belum diselesaikan. Sekarang bentuknya satu, jalur tulisnya satu, dan
    pagar `INV-HIST-01` melarang bentuk ke-dua lahir kembali.
    """
    hist = [h for h in (so.get("status_history") or [])
            if isinstance(h, dict) and h.get("status") == STATUS_PENDING_APPROVAL
            and sh.time_of(h)]
    if hist:
        return sh.time_of(hist[-1])
    return str(so.get("created_at") or "")


async def ensure_approval_requested_at(dbx: Any = None, *,
                                       dry_run: bool = False) -> Dict[str, int]:
    """Beri `approval_requested_at` kepada PO custom LAMA yang menunggu (idempotent).

    Dokumen baru mendapatkannya di jalur pengajuan (`routers/special_orders.py`).
    Yang lahir SEBELUM B1 dibayar tidak punya field itu; tanpa backfill, papan &
    pengingat tetap jatuh ke `created_at` untuk dokumen-dokumen tersebut — perbaikan
    yang hanya berlaku untuk dokumen masa depan bukan perbaikan.
    """
    target = dbx if dbx is not None else db
    rows = await target.special_orders.find(
        {"status": STATUS_PENDING_APPROVAL,
         "approval_requested_at": {"$in": [None, ""]}},
        {"_id": 0, "id": 1, "status_history": 1, "created_at": 1},
    ).to_list(2000)
    rows += await target.special_orders.find(
        {"status": STATUS_PENDING_APPROVAL,
         "approval_requested_at": {"$exists": False}},
        {"_id": 0, "id": 1, "status_history": 1, "created_at": 1},
    ).to_list(2000)
    seen, written = set(), 0
    for so in rows:
        if not so.get("id") or so["id"] in seen:
            continue
        seen.add(so["id"])
        if dry_run:
            continue
        await target.special_orders.update_one(
            {"id": so["id"]},
            {"$set": {"approval_requested_at": waiting_since(so)}})
        written += 1
    total = await target.special_orders.count_documents(
        {"status": STATUS_PENDING_APPROVAL})
    return {"total_pending": int(total), "missing_before": len(seen),
            "written": written}


async def can_approve_special_order(special_order: Dict[str, Any], user_role: str) -> bool:
    """Apakah pengguna boleh memutuskan PO custom ini (manager/admin).

    Args:
        special_order: Special order document
        user_role: Current user's role
    
    Returns:
        True if user can approve (manager/admin)
    """
    if special_order["status"] != STATUS_PENDING_APPROVAL:
        return False
    
    return user_role in ["manager", "admin"]


async def approve_special_order(special_order_id: str, approved_by: str) -> Dict[str, Any]:
    """Approve special order and transition to confirmed status.
    
    Args:
        special_order_id: Special order ID
        approved_by: User email who approved
    
    Returns:
        Updated special order document
    """
    result = await db.special_orders.find_one_and_update(
        {"id": special_order_id, "status": STATUS_PENDING_APPROVAL},
        {
            "$set": {
                "status": STATUS_CONFIRMED,
                "approved_by": approved_by,
                "approved_at": now_iso(),
                "updated_at": now_iso()
            }
        },
        return_document=True
    )
    
    if not result:
        raise ValueError("Special order not found or not in pending_approval status")
    
    result.pop("_id", None)
    # F3 (2.a) — auto-create Product SKU saat approve (best-effort, idempotent).
    # Kegagalan pembuatan SKU TIDAK boleh menggagalkan approval (status sudah confirmed).
    try:
        await create_sku_from_special_order(special_order_id, created_by=approved_by)
    except Exception:  # noqa: BLE001 — SKU best-effort; manual fallback tersedia via endpoint
        pass
    # Re-fetch agar field linkage (linked_product_id/sku) ikut terkirim ke FE.
    refreshed = await db.special_orders.find_one({"id": special_order_id}, {"_id": 0})
    return refreshed or result


async def reject_special_order(special_order_id: str, rejected_by: str, reason: str) -> Dict[str, Any]:
    """Reject special order.
    
    Args:
        special_order_id: Special order ID
        rejected_by: User email who rejected
        reason: Rejection reason
    
    Returns:
        Updated special order document
    """
    result = await db.special_orders.find_one_and_update(
        {"id": special_order_id, "status": STATUS_PENDING_APPROVAL},
        {
            "$set": {
                "status": STATUS_CANCELLED,
                "rejected_by": rejected_by,
                "rejected_at": now_iso(),
                "reject_reason": reason,
                "updated_at": now_iso()
            }
        },
        return_document=True
    )
    
    if not result:
        raise ValueError("Special order not found or not in pending_approval status")
    
    result.pop("_id", None)
    return result


async def _generate_custom_sku(base: str) -> str:
    """Hasilkan SKU unik untuk produk custom MTO. `base` mis. nomor SORD.
    Tambah suffix angka bila bentrok dengan produk yang sudah ada."""
    candidate = base
    suffix = 0
    while await db.products.find_one({"sku": candidate}, {"_id": 0, "id": 1}):
        suffix += 1
        candidate = f"{base}-{suffix}"
    return candidate


async def create_sku_from_special_order(special_order_id: str,
                                        created_by: str = "system") -> Dict[str, Any]:
    """F3 (2.a) — Materialisasi Product SKU dari Special Order MTO (idempotent).

    Dipanggil otomatis saat approve (status → confirmed) dan dapat dipicu manual.
    Bila special order sudah punya `linked_product_id`, kembalikan produk existing.
    """
    so = await db.special_orders.find_one({"id": special_order_id}, {"_id": 0})
    if not so:
        raise ValueError("Special order tidak ditemukan")

    # Idempotent — sudah pernah dibuat SKU-nya.
    if so.get("linked_product_id"):
        existing = await db.products.find_one({"id": so["linked_product_id"]}, {"_id": 0})
        if existing:
            return safe_doc(existing)

    # Hanya boleh setelah disetujui (confirmed) atau tahap setelahnya.
    if so.get("status") not in (STATUS_CONFIRMED, STATUS_IN_PRODUCTION,
                                STATUS_READY, STATUS_SHIPPED, STATUS_DONE):
        raise ValueError(
            "SKU hanya dapat dibuat untuk special order yang sudah disetujui (confirmed).")

    ci = so.get("custom_item", {}) or {}
    specs = ci.get("specifications", {}) or {}

    def _spec(*keys, default=""):
        """Ambil nilai spesifikasi case-insensitive (mis. 'color'/'Warna')."""
        for k in keys:
            for variant in (k, k.lower(), k.capitalize(), k.upper()):
                val = specs.get(variant)
                if val not in (None, ""):
                    return str(val)
        return default

    number = so.get("number", "") or ""
    sku_base = f"MTO-{number.replace('SORD-', '')}" if number else f"MTO-{new_id('x')[-8:]}"
    sku = await _generate_custom_sku(sku_base)

    # Fase A · PS-02/PS-03 — SKU custom WAJIB tetap membawa field domain tekstil.
    # Nilai diambil dari spesifikasi special order bila ada; TIDAK dikarang bila
    # tidak ada (produk ditandai needs_review + domain_gaps agar dilengkapi user).
    def _spec_num(*keys) -> float:
        try:
            return parse_decimal(_spec(*keys, default="") or 0)
        except ValueError:
            return 0.0

    product = {
        "id": new_id("prod"),
        "sku": sku,
        "name": ci.get("description") or f"Custom {number}".strip(),
        "category": _spec("category", "kategori", default="Custom"),
        "variant": _spec("variant", "varian", default="Custom"),
        "color": _spec("color", "warna", default="Natural"),
        "motif": _spec("motif", default="Polos"),
        "grade": _spec("grade", default="A"),
        "supplier": _spec("supplier", default="Internal"),
        "base_unit": ci.get("unit") or "meter",
        "price": float(ci.get("target_price", 0) or 0),
        "harga_pokok": 0.0,
        "gramasi": _spec_num("gramasi", "gsm"),
        "lebar": _spec_num("lebar", "width"),
        "stage": _spec("stage", "tahap", default=""),
        "fabric_type": _spec("fabric_type", "jenis_kain", "jeniskain", default=""),
        "yarn_count": _spec("yarn_count", "nomor_benang", default=""),
        "kg_per_meter": 0.0,
        "reorder_point": 0.0,
        "reorder_qty": 0.0,
        "image": _DEFAULT_PRODUCT_IMAGE,
        "status": "active",
        "uom_conversions": [],
        "template_id": "",
        "variant_attrs": specs if isinstance(specs, dict) else {},
        "batch_lot_rolls": [],
        # F3 — metadata MTO (jejak asal special order)
        "is_custom": True,
        "source_special_order_id": so["id"],
        "source_special_order_number": number,
        "entity_id": so.get("entity_id", ""),
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    _dr.stamp_domain_defaults(product, source="special_order")
    await db.products.insert_one(product)

    await db.special_orders.update_one(
        {"id": special_order_id},
        {"$set": {
            "linked_product_id": product["id"],
            "linked_product_sku": sku,
            "linked_product_name": product["name"],
            "sku_created_at": now_iso(),
            "sku_created_by": created_by,
            "updated_at": now_iso(),
        }})
    return safe_doc(product)


async def transition_special_order_status(
    special_order_id: str,
    new_status: str,
    updated_by: str
) -> Dict[str, Any]:
    """Transition special order to new status.
    
    Valid transitions:
    - confirmed → in_production (purchasing started)
    - in_production → ready (item produced/received)
    - ready → shipped (dispatched to customer)
    - shipped → done (delivered)
    
    Args:
        special_order_id: Special order ID
        new_status: Target status
        updated_by: User email
    
    Returns:
        Updated special order document
    """
    VALID_TRANSITIONS = {
        STATUS_CONFIRMED: [STATUS_IN_PRODUCTION],
        STATUS_IN_PRODUCTION: [STATUS_READY],
        STATUS_READY: [STATUS_SHIPPED],
        STATUS_SHIPPED: [STATUS_DONE],
    }
    
    special_order = await db.special_orders.find_one({"id": special_order_id})
    if not special_order:
        raise ValueError("Special order not found")
    
    current_status = special_order["status"]
    
    if new_status not in VALID_TRANSITIONS.get(current_status, []):
        raise ValueError(
            f"Invalid status transition: {current_status} → {new_status}"
        )
    
    result = await db.special_orders.find_one_and_update(
        {"id": special_order_id},
        {
            "$set": {
                "status": new_status,
                "updated_at": now_iso(),
                "updated_by": updated_by
            },
            "$push": {
                "status_history": {
                    "status": new_status,
                    "timestamp": now_iso(),
                    "user": updated_by
                }
            }
        },
        return_document=True
    )
    
    result.pop("_id", None)
    return result
