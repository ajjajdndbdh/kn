"""FASE D — **PERMINTAAN DESAIN** (`/api/design-requests`) + rapor desainer.

Pembagian izin (modul `design_request`):
  * `view`   — admin · manajer · Admin Sales · **Desainer** (desainer: hanya tugasnya)
  * `create` — admin · manajer · Admin Sales (dari pesanan pelanggan)
  * `update` — admin · manajer (brief/tenggat/warna selama belum diputuskan)
  * `assign` — admin · manajer
  * `deliver`— admin · manajer · **Desainer** (menyerahkan artwork-nya sendiri)
  * `decide` — admin · manajer (ACC / minta revisi — **alasan wajib**)
  * `cancel` — admin · manajer
  * `report` — admin · manajer (rapor lintas desainer; desainer melihat angkanya
    sendiri lewat papan & Profil Saya, bukan rapor rekan)

Pagar yang ditegakkan di sini (bukan di layar):
  * badan usaha — `resolve_list_scope` pada daftar, `assert_entity_access` pada detail;
  * lini produk — `line_scope.narrow` (chip lini) supaya staf printing tidak melihat
    pekerjaan woven;
  * kepemilikan — peran `designer` hanya melihat & menyentuh permintaan yang
    ditugaskan kepadanya (pola E8.4 “Pesanan Saya”).
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request

import pagination as pg
from db import db
from dependencies import audit, require_permission
from entity_scope import assert_entity_access, entity_ctx, resolve_list_scope
from schemas_design_request import (
    DesignRequestAssign, DesignRequestCreate, DesignRequestDecision,
    DesignRequestDeliver, DesignRequestUpdate,
)
from services import design_request_service as svc
from services import line_scope

router = APIRouter(prefix="/api")

#: Peran yang melihat SEMUA permintaan badan usahanya (bukan hanya tugasnya sendiri).
FULL_VIEW_ROLES = ("admin", "manager", "sales_admin")


def _fail(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _own_only(actor: Dict[str, Any]) -> bool:
    """Desainer (dan peran lain yang tidak berwenang penuh) hanya melihat tugasnya."""
    return (actor or {}).get("role") not in FULL_VIEW_ROLES


async def _get_guarded(req_id: str, request: Request, actor: Dict[str, Any]) -> Dict[str, Any]:
    ctx = await entity_ctx(request)
    doc = await svc.get_one(req_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Permintaan desain tidak ditemukan.")
    assert_entity_access(doc, svc.COLL, ctx)
    if _own_only(actor) and doc.get("assigned_to") != actor.get("id", ""):
        raise HTTPException(
            status_code=403,
            detail="Anda hanya bisa membuka permintaan desain yang ditugaskan kepada Anda.")
    line_scope.assert_can_touch(actor, doc)
    return doc


@router.get("/design-requests/meta")
async def meta(request: Request) -> Dict[str, Any]:
    actor = await require_permission(request, "design_request", "view")
    return {
        "statuses": [{"id": s, "label": svc.STATUS_LABEL[s]} for s in svc.BOARD_ORDER],
        "all_statuses": [{"id": k, "label": v} for k, v in svc.STATUS_LABEL.items()],
        "target_types": [{"id": k, "label": v} for k, v in svc.TARGET_TYPES.items()],
        "sources": [{"id": k, "label": v} for k, v in svc.SOURCES.items()],
        "designers": await svc.designers(),
        "role": (actor or {}).get("role", ""),
        "own_only": _own_only(actor),
    }


@router.get("/design-requests")
async def list_requests(request: Request,
                        status: Optional[str] = Query(None),
                        assigned_to: Optional[str] = Query(None),
                        so_id: Optional[str] = Query(None),
                        mine: bool = Query(False),
                        line: str = Query("", description="FASE L — penyaring lini"),
                        entity_id: Optional[str] = Query(None)) -> Dict[str, Any]:
    actor = await require_permission(request, "design_request", "view")
    ctx = await entity_ctx(request)
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    if assigned_to:
        q["assigned_to"] = assigned_to
    if so_id:
        q["so_id"] = so_id
    if mine or _own_only(actor):
        q["assigned_to"] = actor.get("id", "")
    q = resolve_list_scope(svc.COLL, q, ctx, entity_id)
    q = line_scope.narrow(q, actor, line)
    page, page_size, text, _sort = pg.get_page_params(request)
    q = pg.merge_query(q, pg.build_search(text, ["number", "brief", "customer_name",
                                                 "so_number", "assigned_name"]))
    items, total = await pg.fetch_page(db[svc.COLL], q, page, page_size)
    shaped = [svc.shape(d) for d in items]
    summary = await svc.summary(q)
    if pg.is_paged(request):
        env = pg.envelope(shaped, total, page, page_size)
        env["summary"] = summary
        return env
    return {"items": shaped, "total": total, "summary": summary}


@router.post("/design-requests")
async def create_request(payload: DesignRequestCreate, request: Request) -> Dict[str, Any]:
    actor = await require_permission(request, "design_request", "create")
    ctx = await entity_ctx(request)
    try:
        doc = await svc.create(payload.model_dump(), actor, ctx.active_entity_id)
    except svc.DesignRequestError as exc:
        raise _fail(exc) from exc
    await audit(actor.get("name", ""), "design_request_created", "design_request",
                doc["id"], {"number": doc["number"], "target": doc["target_type"],
                            "assigned_to": doc.get("assigned_name", "")})
    return svc.shape(doc)


@router.get("/design-requests/{req_id}")
async def get_request(req_id: str, request: Request) -> Dict[str, Any]:
    actor = await require_permission(request, "design_request", "view")
    return svc.shape(await _get_guarded(req_id, request, actor))


@router.patch("/design-requests/{req_id}")
async def update_request(req_id: str, payload: DesignRequestUpdate,
                         request: Request) -> Dict[str, Any]:
    actor = await require_permission(request, "design_request", "update")
    doc = await _get_guarded(req_id, request, actor)
    try:
        res = await svc.update(req_id, payload.model_dump(exclude_unset=True), actor)
    except svc.DesignRequestError as exc:
        raise _fail(exc) from exc
    await audit(actor.get("name", ""), "design_request_updated", "design_request",
                req_id, {"number": doc["number"]})
    return svc.shape(res)


@router.post("/design-requests/{req_id}/submit")
async def submit_request(req_id: str, request: Request) -> Dict[str, Any]:
    actor = await require_permission(request, "design_request", "create")
    doc = await _get_guarded(req_id, request, actor)
    try:
        res = await svc.submit(req_id, actor)
    except svc.DesignRequestError as exc:
        raise _fail(exc) from exc
    await audit(actor.get("name", ""), "design_request_submitted", "design_request",
                req_id, {"number": doc["number"]})
    return svc.shape(res)


@router.post("/design-requests/{req_id}/assign")
async def assign_request(req_id: str, payload: DesignRequestAssign,
                         request: Request) -> Dict[str, Any]:
    actor = await require_permission(request, "design_request", "assign")
    doc = await _get_guarded(req_id, request, actor)
    try:
        res = await svc.assign(req_id, actor, payload.assigned_to, payload.due_date)
    except svc.DesignRequestError as exc:
        raise _fail(exc) from exc
    await audit(actor.get("name", ""), "design_request_assigned", "design_request",
                req_id, {"number": doc["number"], "assigned_to": res.get("assigned_name", ""),
                         "due_date": res.get("due_date", "")})
    return svc.shape(res)


@router.post("/design-requests/{req_id}/start")
async def start_request(req_id: str, request: Request) -> Dict[str, Any]:
    """Desainer menandai mulai mengerjakan (papan bergerak tanpa perlu atasan)."""
    actor = await require_permission(request, "design_request", "deliver")
    doc = await _get_guarded(req_id, request, actor)
    try:
        res = await svc.start(req_id, actor)
    except svc.DesignRequestError as exc:
        raise _fail(exc) from exc
    await audit(actor.get("name", ""), "design_request_started", "design_request",
                req_id, {"number": doc["number"]})
    return svc.shape(res)


@router.post("/design-requests/{req_id}/deliver")
async def deliver_request(req_id: str, payload: DesignRequestDeliver,
                          request: Request) -> Dict[str, Any]:
    actor = await require_permission(request, "design_request", "deliver")
    doc = await _get_guarded(req_id, request, actor)
    try:
        res = await svc.deliver(req_id, actor, payload.gallery_id, payload.note)
    except svc.DesignRequestError as exc:
        raise _fail(exc) from exc
    await audit(actor.get("name", ""), "design_request_delivered", "design_request",
                req_id, {"number": doc["number"], "gallery_id": payload.gallery_id})
    return svc.shape(res)


@router.post("/design-requests/{req_id}/approve")
async def approve_request(req_id: str, request: Request,
                          payload: DesignRequestDecision = DesignRequestDecision()
                          ) -> Dict[str, Any]:
    actor = await require_permission(request, "design_request", "decide")
    doc = await _get_guarded(req_id, request, actor)
    try:
        res = await svc.approve(req_id, actor, payload.note)
    except svc.DesignRequestError as exc:
        raise _fail(exc) from exc
    await audit(actor.get("name", ""), "design_request_approved", "design_request",
                req_id, {"number": doc["number"]})
    return svc.shape(res)


@router.post("/design-requests/{req_id}/reject")
async def reject_request(req_id: str, request: Request,
                         payload: DesignRequestDecision = DesignRequestDecision()
                         ) -> Dict[str, Any]:
    """Minta revisi — **alasan wajib** (dicatat & terbaca desainer)."""
    actor = await require_permission(request, "design_request", "decide")
    doc = await _get_guarded(req_id, request, actor)
    try:
        res = await svc.reject(req_id, actor, payload.reason)
    except svc.DesignRequestError as exc:
        raise _fail(exc) from exc
    await audit(actor.get("name", ""), "design_request_revision", "design_request",
                req_id, {"number": doc["number"]}, reason=payload.reason)
    return svc.shape(res)


@router.post("/design-requests/{req_id}/cancel")
async def cancel_request(req_id: str, request: Request,
                         payload: DesignRequestDecision = DesignRequestDecision()
                         ) -> Dict[str, Any]:
    actor = await require_permission(request, "design_request", "cancel")
    doc = await _get_guarded(req_id, request, actor)
    try:
        res = await svc.cancel(req_id, actor, payload.reason)
    except svc.DesignRequestError as exc:
        raise _fail(exc) from exc
    await audit(actor.get("name", ""), "design_request_cancelled", "design_request",
                req_id, {"number": doc["number"]}, reason=payload.reason)
    return svc.shape(res)


@router.get("/design/reports/by-designer")
async def report_by_designer(request: Request,
                             period: str = Query("", description="YYYY-MM (kosong = semua)"),
                             line: str = Query(""),
                             entity_id: Optional[str] = Query(None)) -> Dict[str, Any]:
    actor = await require_permission(request, "design_request", "report")
    ctx = await entity_ctx(request)
    q: Dict[str, Any] = {}
    if period:
        q["requested_at"] = {"$regex": f"^{period}"}
    q = resolve_list_scope(svc.COLL, q, ctx, entity_id)
    q = line_scope.narrow(q, actor, line)
    rep = await svc.report_by_designer(q)
    rep["period"] = period
    return rep


@router.get("/design/reports/mine")
async def report_mine(request: Request,
                      period: str = Query("", description="YYYY-MM (kosong = semua)"),
                      line: str = Query(""),
                      entity_id: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Rapor **SAYA** — dipagari `design_request.view`, bukan `report`.

    Alasannya sengaja dibedakan dari `/design/reports/by-designer`: izin `report`
    berarti "berwenang menilai ORANG" (atasan). Melihat angka DIRI SENDIRI bukan
    wewenang penilaian — setiap orang berhak atasnya, sama seperti
    `/rnd/reports/my-kpi` & `/hr/attendance/me`. Tanpa endpoint ini, tab rapor di
    layar Permintaan Desain hanya bisa 403 untuk desainer = **panel mati**, kelas
    cacat yang `audit_sales_roles_ux` memang dibuat untuk menangkap.

    Ruang lingkupnya dipaksa di server: `report_mine()` hanya mengirim BARIS MILIK
    pemanggil (plus rata-rata tim yang agregat, tanpa nama), jadi tidak ada parameter
    yang bisa dipakai mengintip rapor rekan.
    """
    actor = await require_permission(request, "design_request", "view")
    ctx = await entity_ctx(request)
    q: Dict[str, Any] = {}
    if period:
        q["requested_at"] = {"$regex": f"^{period}"}
    q = resolve_list_scope(svc.COLL, q, ctx, entity_id)
    q = line_scope.narrow(q, actor, line)
    rep = await svc.report_mine(q, user_id=actor.get("id", ""),
                                display_name=actor.get("name", ""))
    rep["period"] = period
    return rep


@router.get("/design-requests-for-so/{so_id}")
async def requests_for_so(so_id: str, request: Request) -> List[Dict[str, Any]]:
    """Panel “permintaan desain untuk pesanan ini” di layar Pesanan."""
    actor = await require_permission(request, "design_request", "view")
    ctx = await entity_ctx(request)
    q = resolve_list_scope(svc.COLL, {"so_id": so_id}, ctx, None)
    if _own_only(actor):
        q["assigned_to"] = actor.get("id", "")
    rows = await db[svc.COLL].find(q, {"_id": 0}).sort("created_at", -1).to_list(50)
    return [svc.shape(r) for r in rows]
