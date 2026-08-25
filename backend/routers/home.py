"""EPIC 1 — Home/landing endpoints per role."""
from typing import Any, Dict, Optional, Union

from fastapi import APIRouter, HTTPException, Request, Query

from dependencies import current_user, require_role
from entity_scope import entity_ctx
from services import home_service

router = APIRouter(prefix="/api/home")


async def _own_entity(request: Request,
                      entity_id: Optional[str],
                      allow_combined: bool = False) -> Union[str, Dict[str, Any]]:
    """Badan usaha yang BOLEH dibaca pemanggil — jangan pernah "semua" diam-diam.

    KEBOCORAN NYATA yang ditutup (2026-06, ditemukan `audit_entity_isolation`):
    `/api/home/sales` & `/api/home/warehouse` dulu meneruskan `entity_id=None` apa
    adanya ke layanan, dan `None` berarti **tanpa saringan** — sales PT-B yang tidak
    mengirim header entitas ikut melihat dokumen PT-A di papan antrean. Tidak ada
    galat, tidak ada tanda: hanya isolasi yang bocor. Karena itu kosong = badan usaha
    AKTIF pengguna, dan `entity_id` yang diminta wajib termasuk penugasannya.
    """
    ctx = await entity_ctx(request)
    minta = (entity_id or "").strip()
    if minta and minta != "all":
        if not ctx.can_access(minta):
            raise HTTPException(403, "Anda tidak ditugaskan di badan usaha itu.")
        return minta
    if allow_combined and (ctx.view_all or (minta == "all" and ctx.can_view_combined)):
        return {"$in": list(ctx.allowed_entity_ids)}
    return ctx.active_entity_id


@router.get("/sales")
async def home_sales(request: Request, entity_id: Optional[str] = Query(None),
                     sales_id: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Performa Saya. Sales melihat dirinya sendiri; admin/manager boleh pilih sales_id."""
    user = await current_user(request)
    target = sales_id if (sales_id and user["role"] in ("admin", "manager")) else user["id"]
    eid = await _own_entity(request, entity_id)
    return await home_service.sales_home(target, eid)


@router.get("/admin")
async def home_admin(request: Request, entity_id: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Control Tower. admin (auto) + manager."""
    await require_role(request, ["manager"])
    return await home_service.admin_home(entity_id)


@router.get("/manager")
async def home_manager(request: Request, entity_id: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Manager Home. admin (auto) + manager."""
    await require_role(request, ["manager"])
    return await home_service.manager_home(None, entity_id)


@router.get("/warehouse")
async def home_warehouse(request: Request,
                         entity_id: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Papan antrean gudang (transfer · stock opname · barang ditahan QC).

    Dipakai layar Operasi (WMS). Tidak dibatasi peran gudang: manajer & pemilik yang
    membuka layar yang sama harus melihat papan yang sama — dua angka untuk dokumen
    yang sama adalah kelas cacat yang justru diperangi INV-HOME-01. Yang MEMBATASI
    adalah penugasan badan usaha, bukan nama peran.
    """
    eid = await _own_entity(request, entity_id, allow_combined=True)
    return await home_service.warehouse_home(eid)
