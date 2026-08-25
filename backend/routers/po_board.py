"""FASE P — router **PAPAN PO PER LINI** (`GET /api/purchase-orders/board`).

KENAPA MODUL SENDIRI (bukan ditambahkan ke `routers/purchase_orders.py`)
-----------------------------------------------------------------------
Dua alasan, keduanya sudah pernah menggigit repo ini:

1. **Urutan pencocokan rute.** `GET /purchase-orders/{po_id}` akan menelan
   `/purchase-orders/board` bila board terdaftar sesudahnya — dan gejalanya bukan
   galat, melainkan 404 "PO tidak ditemukan" yang menyesatkan. Modul ini didaftarkan
   **SEBELUM** `purchase_orders` di `server.py`, pola yang sama dengan
   `purchase_orders_extra.py` (yang menjaga `/purchase-orders/blanket`).
2. **Batas ukuran berkas.** `routers/purchase_orders.py` sudah 815 baris (panduan
   guardrail: 800 untuk router). Menambah papan di sana membuat berkas yang sudah
   di atas panduan makin jauh, dan `validate_compliance` benar saat memperingatkan.

Seluruh logika papan ada di `services/po_board_service.py`; router hanya soal
**pagar**: izin (`purchase_order.view` / `.update`), badan usaha (`entity_scope`),
dan lini (`line_scope`).
"""
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from dependencies import audit, require_permission
from domain_registry import DomainValidationError
from entity_scope import assert_entity_access, entity_ctx, resolve_list_scope
from pagination import get_page_params
from schemas_purchasing import POStagePatch
from services import line_scope
from services import po_board_service as board

router = APIRouter(prefix="/api")


@router.get("/purchase-orders/board")
async def po_board(request: Request, entity_id: str = None, line: str = "",
                   status: str = "") -> Dict[str, Any]:
    """Papan PO per lini — kertas kerja MD dalam bentuk data.

    Menghormati TIGA pagar sekaligus: izin baca PO, badan usaha aktif
    (`resolve_list_scope`), dan lini (`line_scope.narrow` — akun berpagar lini
    hanya melihat lininya, dan chip `?line=` menyaring di dalam batas itu).
    """
    actor = await require_permission(request, "purchase_order", "view")
    ctx = await entity_ctx(request)
    query = resolve_list_scope("purchase_orders", {}, ctx, entity_id)
    query = line_scope.narrow(query, actor, line, field=line_scope.LINES_FIELD)
    page, page_size, q, _sort = get_page_params(request)
    return await board.board(query=query, page=page, page_size=page_size,
                             search=q or "", status=status or "", actor=actor)


@router.patch("/purchase-orders/{po_id}/stage")
async def patch_po_stage(po_id: str, payload: POStagePatch,
                         request: Request) -> Dict[str, Any]:
    """Tandai satu tahap PO (`pending` · `in_progress` · `done`).

    Tahap `inspect` **ditolak 409**: statusnya diturunkan dari hasil pemeriksaan
    mutu, bukan dari klik. Tanpa penolakan ini papan bisa mengaku "sudah
    diinspeksi" tanpa satu dokumen inspeksi pun — kelas kebohongan yang paling
    mahal, karena barang cacat lolos ke pelanggan atas dasar catatan yang salah.
    """
    actor = await require_permission(request, "purchase_order", "update")
    ctx = await entity_ctx(request)
    try:
        po = await board.po_for_scope(po_id)
    except board.BoardError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # Dokumen milik badan usaha lain tidak boleh disentuh — juga saat header
    # `X-Entity-Id: all` (mode gabungan) supaya papan gabungan tetap hanya-lihat
    # untuk dokumen PT lain.
    assert_entity_access(po, "purchase_orders", ctx)
    try:
        row = await board.set_stage(po_id, stage_code=payload.stage_code,
                                    status=payload.status, note=payload.note or "",
                                    actor=actor)
    except board.BoardError as exc:
        # 409 untuk tahap turunan (bentrok aturan), 400 untuk isian salah.
        code = 409 if "tidak bisa ditandai manual" in str(exc) else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    except DomainValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    # Pagar lini (`line_scope.assert_can_touch`) melempar HTTPException 403 sendiri
    # ber-kalimat Indonesia yang menyebut lini dokumen vs lini akun — dibiarkan
    # naik apa adanya supaya pesannya tidak kehilangan konteks di sini.
    await audit(actor.get("name", ""), "po_stage_updated", "purchase_order", po_id,
                {"stage": payload.stage_code, "status": payload.status,
                 "note": payload.note or "", "po_number": po.get("po_number", "")},
                "FASE P — papan PO per lini")
    return row
