"""FASE D — **PERMINTAAN DESAIN** (`<ENT>/DSR-#####`) + rapor desainer.

## Lubang nyata yang ditutup
Galeri desain (`design_gallery`) menyimpan **artwork**-nya, dan KPI Desainer menilai
putaran sample. Yang tidak pernah ada: **penugasannya**. Praktiknya MD meminta desain
lewat WhatsApp, jadi tidak ada satu pun angka yang bisa menjawab pertanyaan pemilik:

  * desain ini diminta siapa, untuk pesanan mana, kapan tenggatnya?
  * berapa lama desainer menyelesaikan satu permintaan?
  * berapa yang harus direvisi — dan revisi karena apa?

Karena itu dokumen ini SENGAJA hanya mengurus **pekerjaan**: siapa mengerjakan, kapan
selesai, dan keputusan atasannya. Artwork tetap hidup di `design_gallery`
(satu permintaan boleh punya beberapa versi), angka teknis tetap di `md_specs`.
Melanggar batas itu berarti membuat dokumen ke-4 yang saling menimpa.

## Aturan yang dijaga di sini (bukan di layar)
1. **Alasan revisi/tolak WAJIB.** Revisi tanpa alasan adalah cara paling murah untuk
   membuat desainer mengulang pekerjaan tanpa tahu apa yang salah.
2. **Serah hasil (`deliver`) harus menunjuk artwork yang NYATA** di galeri badan usaha
   yang sama — bukan catatan bebas "sudah dikirim lewat email".
3. **Rapor dihitung dari dokumen**, bukan diketik: `report_by_designer()` membaca
   koleksi ini + nilai bintang di `design_gallery`, sehingga angka rapor tidak bisa
   berbeda dengan isi layar (POC memeriksanya dengan hitung-ulang mandiri).
4. **Papan tidak boleh bocor antar badan usaha** — semua daftar lewat
   `resolve_list_scope` di router, dan setiap tulisan menstempel `entity_id`.
5. **Pagar lini** (`line_scope`): permintaan desain lini printing bukan urusan staf
   woven; kode lini disnapshot di dokumen supaya riwayat tidak bergeser saat master
   produk diubah.
"""
from typing import Any, Dict, List, Optional, Tuple

from db import db
from core_utils import new_id, next_doc_number, now_iso, safe_doc, timeline_entry
from services import line_scope

COLL = "design_requests"

# ─── Status (mesin keadaan yang sengaja pendek) ───────────────────────────────
STATUS_DRAFT = "draft"
STATUS_SUBMITTED = "submitted"
STATUS_ASSIGNED = "assigned"
STATUS_IN_PROGRESS = "in_progress"
STATUS_DELIVERED = "delivered"
STATUS_APPROVED = "approved"
STATUS_REVISION = "revision"
STATUS_CANCELLED = "cancelled"

STATUS_LABEL: Dict[str, str] = {
    STATUS_DRAFT: "Draf",
    STATUS_SUBMITTED: "Menunggu penugasan",
    STATUS_ASSIGNED: "Ditugaskan",
    STATUS_IN_PROGRESS: "Dikerjakan",
    STATUS_DELIVERED: "Menunggu keputusan",
    STATUS_APPROVED: "Disetujui (ACC)",
    STATUS_REVISION: "Minta revisi",
    STATUS_CANCELLED: "Dibatalkan",
}
#: Urutan kolom papan (kanban) — dipakai layar & POC supaya keduanya tidak bercabang.
BOARD_ORDER: Tuple[str, ...] = (
    STATUS_DRAFT, STATUS_SUBMITTED, STATUS_ASSIGNED, STATUS_IN_PROGRESS,
    STATUS_DELIVERED, STATUS_REVISION, STATUS_APPROVED,
)
OPEN_STATUSES: Tuple[str, ...] = (
    STATUS_DRAFT, STATUS_SUBMITTED, STATUS_ASSIGNED, STATUS_IN_PROGRESS,
    STATUS_DELIVERED, STATUS_REVISION,
)
TERMINAL_STATUSES: Tuple[str, ...] = (STATUS_APPROVED, STATUS_CANCELLED)

TARGET_TYPES: Dict[str, str] = {
    "motif": "Motif",
    "pattern": "Pattern / Pola",
    "artwork": "Artwork Printing",
}
SOURCES: Dict[str, str] = {
    "so": "Dari pesanan pelanggan",
    "customer": "Permintaan pelanggan",
    "internal": "Inisiatif internal",
}


class DesignRequestError(ValueError):
    """Kesalahan ber-kalimat siap tampil (Bahasa Indonesia)."""


# ─── Util kecil ──────────────────────────────────────────────────────────────
def _today() -> str:
    return now_iso()[:10]


def _clean_colors(rows: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        row = dict(r or {})
        code = (row.get("code") or "").strip()
        name = (row.get("name") or "").strip()
        if not (code or name):
            continue
        out.append({"color_id": (row.get("color_id") or "").strip(),
                    "code": code, "name": name,
                    "hex": (row.get("hex") or "").strip()})
    return out


async def get_one(req_id: str) -> Optional[Dict[str, Any]]:
    doc = await db[COLL].find_one({"id": req_id}, {"_id": 0})
    return safe_doc(doc) if doc else None


async def _load(req_id: str) -> Dict[str, Any]:
    doc = await db[COLL].find_one({"id": req_id}, {"_id": 0})
    if not doc:
        raise DesignRequestError("Permintaan desain tidak ditemukan.")
    return doc


async def _save(doc: Dict[str, Any], event: str, label: str, actor: Dict[str, Any],
                note: str = "", **fields: Any) -> Dict[str, Any]:
    """Simpan perubahan + satu baris riwayat. Satu pintu supaya setiap perpindahan
    status selalu meninggalkan jejak (tanpa ini, papan bergerak tanpa cerita)."""
    patch = dict(fields)
    patch["updated_at"] = now_iso()
    entry = timeline_entry(event, label, actor.get("name", ""), note)
    await db[COLL].update_one({"id": doc["id"]},
                              {"$set": patch, "$push": {"history": entry}})
    return await get_one(doc["id"])  # type: ignore[return-value]


def _assert_status(doc: Dict[str, Any], allowed: Tuple[str, ...], aksi: str) -> None:
    if doc.get("status") not in allowed:
        boleh = " / ".join(STATUS_LABEL.get(s, s) for s in allowed)
        raise DesignRequestError(
            f"Permintaan berstatus \u201c{STATUS_LABEL.get(doc.get('status'), doc.get('status'))}\u201d "
            f"tidak bisa {aksi}. Status yang bisa: {boleh}.")


# ─── Kandidat desainer (dari akun ber-peran `designer` + divisi R&D) ─────────
async def designers() -> List[Dict[str, Any]]:
    """Daftar orang yang bisa ditugaskan.

    Sumbernya AKUN ber-peran `designer` (supaya orang yang ditugaskan benar-benar
    bisa masuk & mengunggah karyanya sendiri) ditambah nama pada divisi desain di HR
    yang belum punya akun — nama itu tetap boleh ditugaskan supaya data lapangan yang
    sudah ada tidak hilang, tetapi ditandai `has_account=false` di layar.
    """
    out: List[Dict[str, Any]] = []
    seen = set()
    async for u in db.users.find({"role": "designer"},
                                {"_id": 0, "id": 1, "name": 1, "email": 1, "status": 1}):
        if (u.get("status") or "active") != "active":
            continue
        out.append({"id": u["id"], "name": u.get("name", ""), "email": u.get("email", ""),
                    "division": "design", "has_account": True})
        seen.add((u.get("name") or "").strip().lower())
    async for p in db.rnd_person_divisions.find({}, {"_id": 0, "person": 1, "division": 1}):
        nama = (p.get("person") or "").strip()
        if not nama or nama.lower() in seen:
            continue
        seen.add(nama.lower())
        out.append({"id": f"hr:{nama}", "name": nama, "email": "",
                    "division": p.get("division", ""), "has_account": False})
    return sorted(out, key=lambda r: r["name"].lower())


async def _resolve_assignee(assigned_to: str) -> Tuple[str, str, str]:
    """`assigned_to` → (id, nama, divisi). Menolak orang yang tidak dikenal supaya
    penugasan tidak pernah mendarat di nama yang salah ketik."""
    key = (assigned_to or "").strip()
    if not key:
        raise DesignRequestError("Pilih desainer yang ditugaskan.")
    for row in await designers():
        if row["id"] == key or row["name"].lower() == key.lower():
            return row["id"], row["name"], row.get("division", "")
    raise DesignRequestError(
        "Desainer itu tidak dikenal. Pilih dari daftar desainer (akun ber-peran Desainer "
        "atau nama pada divisi desain di HR).")


# ─── Membuat ─────────────────────────────────────────────────────────────────
async def create(payload: Dict[str, Any], actor: Dict[str, Any],
                 entity_id: str) -> Dict[str, Any]:
    if not entity_id or entity_id == "all":
        raise DesignRequestError(
            "Pilih satu badan usaha dulu \u2014 permintaan desain selalu milik satu badan usaha.")
    brief = (payload.get("brief") or "").strip()
    if len(brief) < 5:
        raise DesignRequestError(
            "Tulis brief-nya dulu (minimal satu kalimat) \u2014 desainer tidak bisa mulai "
            "dari permintaan kosong.")
    target = (payload.get("target_type") or "motif").strip().lower()
    if target not in TARGET_TYPES:
        raise DesignRequestError(
            f"Jenis target harus salah satu: {', '.join(TARGET_TYPES)}.")
    source = (payload.get("source") or "internal").strip().lower()
    if source not in SOURCES:
        raise DesignRequestError(f"Sumber permintaan harus salah satu: {', '.join(SOURCES)}.")

    so_id = (payload.get("so_id") or "").strip()
    so_number = customer_id = customer_name = ""
    if source == "so" and not so_id:
        raise DesignRequestError(
            "Sumber \u201cDari pesanan pelanggan\u201d wajib menyebut pesanannya.")
    if so_id:
        so = await db.sales_orders.find_one(
            {"id": so_id}, {"_id": 0, "id": 1, "number": 1, "order_number": 1,
                            "customer_id": 1, "customer_name": 1, "entity_id": 1})
        if not so:
            raise DesignRequestError("Pesanan penjualan tidak ditemukan.")
        if (so.get("entity_id") or "") != entity_id:
            raise DesignRequestError(
                "Pesanan itu milik badan usaha lain \u2014 permintaan desain harus dibuat "
                "dari badan usaha pemilik pesanannya.")
        so_number = so.get("number") or so.get("order_number") or ""
        customer_id = so.get("customer_id") or ""
        customer_name = so.get("customer_name") or ""
    if not customer_id and (payload.get("customer_id") or "").strip():
        customer_id = payload["customer_id"].strip()
        cust = await db.customers.find_one({"id": customer_id}, {"_id": 0, "name": 1})
        customer_name = (cust or {}).get("name", "")

    assigned_id = assigned_name = division = ""
    if (payload.get("assigned_to") or "").strip():
        assigned_id, assigned_name, division = await _resolve_assignee(payload["assigned_to"])

    submit_now = bool(payload.get("submit_now"))
    status = STATUS_DRAFT
    if assigned_id:
        status = STATUS_ASSIGNED
    elif submit_now:
        status = STATUS_SUBMITTED

    now = now_iso()
    doc: Dict[str, Any] = {
        "id": new_id("dsr"),
        "number": await next_doc_number(COLL, "number", "DSR-", entity_id=entity_id),
        "entity_id": entity_id,
        # FASE L — snapshot lini: papan lini printing tidak boleh menampilkan pekerjaan woven.
        "line_code": line_scope.norm(payload.get("line_code")),
        "source": source,
        "so_id": so_id, "so_number": so_number,
        "customer_id": customer_id, "customer_name": customer_name,
        "requested_by": actor.get("name", ""), "requested_by_id": actor.get("id", ""),
        "requested_at": now,
        "assigned_to": assigned_id, "assigned_name": assigned_name, "division": division,
        "assigned_at": now if assigned_id else "",
        "due_date": (payload.get("due_date") or "").strip(),
        "brief": brief, "target_type": target,
        "color_targets": _clean_colors(payload.get("color_targets")),
        "status": status,
        "gallery_ids": [], "delivered_at": "",
        "decided_by": "", "decided_at": "",
        "reject_reason": "", "revision_count": 0,
        "cancelled_reason": "",
        "history": [timeline_entry("created", "Permintaan desain dibuat",
                                   actor.get("name", ""), TARGET_TYPES[target])],
        "created_at": now, "updated_at": now,
    }
    if status == STATUS_SUBMITTED:
        doc["history"].append(timeline_entry("submitted", "Diajukan", actor.get("name", "")))
    if status == STATUS_ASSIGNED:
        doc["history"].append(timeline_entry(
            "assigned", f"Ditugaskan ke {assigned_name}", actor.get("name", ""),
            f"tenggat {doc['due_date']}" if doc["due_date"] else ""))
    await db[COLL].insert_one(dict(doc))

    # FASE G-4 — jejak dua arah ke pesanan sumbernya (kalau ada).
    if so_id:
        from services import doc_refs_service as _refs
        await _refs.safe_link(("design_request", doc["id"]), ("sales_order", so_id),
                              "parent", note="permintaan desain untuk pesanan ini")
    return safe_doc(doc)


async def update(req_id: str, payload: Dict[str, Any], actor: Dict[str, Any]) -> Dict[str, Any]:
    doc = await _load(req_id)
    _assert_status(doc, (STATUS_DRAFT, STATUS_SUBMITTED, STATUS_ASSIGNED,
                         STATUS_IN_PROGRESS, STATUS_REVISION), "diubah")
    fields: Dict[str, Any] = {}
    if payload.get("brief") is not None:
        brief = (payload["brief"] or "").strip()
        if len(brief) < 5:
            raise DesignRequestError("Brief tidak boleh dikosongkan.")
        fields["brief"] = brief
    if payload.get("due_date") is not None:
        fields["due_date"] = (payload["due_date"] or "").strip()
    if payload.get("target_type") is not None:
        target = (payload["target_type"] or "").strip().lower()
        if target not in TARGET_TYPES:
            raise DesignRequestError(f"Jenis target harus salah satu: {', '.join(TARGET_TYPES)}.")
        fields["target_type"] = target
    if payload.get("line_code") is not None:
        fields["line_code"] = line_scope.norm(payload["line_code"])
    if payload.get("color_targets") is not None:
        fields["color_targets"] = _clean_colors(payload["color_targets"])
    if not fields:
        return safe_doc(doc)
    return await _save(doc, "updated", "Permintaan diperbarui", actor,
                       note=" · ".join(sorted(fields)), **fields)


# ─── Perpindahan status ──────────────────────────────────────────────────────
async def submit(req_id: str, actor: Dict[str, Any]) -> Dict[str, Any]:
    doc = await _load(req_id)
    _assert_status(doc, (STATUS_DRAFT,), "diajukan")
    return await _save(doc, "submitted", "Diajukan", actor, status=STATUS_SUBMITTED)


async def assign(req_id: str, actor: Dict[str, Any], assigned_to: str,
                 due_date: str = "") -> Dict[str, Any]:
    doc = await _load(req_id)
    _assert_status(doc, (STATUS_DRAFT, STATUS_SUBMITTED, STATUS_ASSIGNED,
                         STATUS_IN_PROGRESS, STATUS_REVISION), "ditugaskan")
    aid, aname, division = await _resolve_assignee(assigned_to)
    due = (due_date or doc.get("due_date") or "").strip()
    status = doc.get("status")
    if status in (STATUS_DRAFT, STATUS_SUBMITTED):
        status = STATUS_ASSIGNED
    return await _save(doc, "assigned", f"Ditugaskan ke {aname}", actor,
                       note=f"tenggat {due}" if due else "tanpa tenggat",
                       assigned_to=aid, assigned_name=aname, division=division,
                       assigned_at=now_iso(), due_date=due, status=status)


async def start(req_id: str, actor: Dict[str, Any]) -> Dict[str, Any]:
    doc = await _load(req_id)
    _assert_status(doc, (STATUS_ASSIGNED, STATUS_REVISION), "mulai dikerjakan")
    return await _save(doc, "in_progress", "Mulai dikerjakan", actor,
                       status=STATUS_IN_PROGRESS, started_at=now_iso())


async def deliver(req_id: str, actor: Dict[str, Any], gallery_id: str,
                  note: str = "") -> Dict[str, Any]:
    """Serah hasil: menunjuk **artwork nyata** di galeri desain (bukan catatan bebas)."""
    doc = await _load(req_id)
    _assert_status(doc, (STATUS_ASSIGNED, STATUS_IN_PROGRESS, STATUS_REVISION,
                         STATUS_DELIVERED), "diserahkan")
    gid = (gallery_id or "").strip()
    art = await db.design_gallery.find_one({"id": gid}, {"_id": 0}) if gid else None
    if not art:
        raise DesignRequestError(
            "Artwork tidak ditemukan di Galeri Desain. Unggah dulu karyanya di Galeri, "
            "lalu pilih entrinya di sini.")
    if (art.get("entity_id") or "") != (doc.get("entity_id") or ""):
        raise DesignRequestError("Artwork itu milik badan usaha lain.")
    ids = list(doc.get("gallery_ids") or [])
    if gid not in ids:
        ids.append(gid)
    # Tautan balik di galeri: dari artwork bisa dilacak permintaan yang melahirkannya.
    await db.design_gallery.update_one(
        {"id": gid}, {"$set": {"request_id": doc["id"], "request_number": doc["number"],
                               "updated_at": now_iso()}})
    label = art.get("code") or art.get("title") or gid
    return await _save(doc, "delivered", f"Hasil diserahkan ({label})", actor,
                       note=note, status=STATUS_DELIVERED, delivered_at=now_iso(),
                       gallery_ids=ids)


async def approve(req_id: str, actor: Dict[str, Any], note: str = "") -> Dict[str, Any]:
    doc = await _load(req_id)
    _assert_status(doc, (STATUS_DELIVERED,), "disetujui")
    return await _save(doc, "approved", "Disetujui (ACC)", actor, note=note,
                       status=STATUS_APPROVED, decided_by=actor.get("name", ""),
                       decided_at=now_iso(), reject_reason="")


async def reject(req_id: str, actor: Dict[str, Any], reason: str) -> Dict[str, Any]:
    """Minta revisi. **Alasan wajib** — revisi tanpa alasan membuat desainer menebak."""
    doc = await _load(req_id)
    _assert_status(doc, (STATUS_DELIVERED,), "diminta revisi")
    why = (reason or "").strip()
    if len(why) < 3:
        raise DesignRequestError(
            "Tulis alasannya \u2014 desainer perlu tahu apa yang harus diubah.")
    return await _save(doc, "revision", "Minta revisi", actor, note=why,
                       status=STATUS_REVISION, reject_reason=why,
                       decided_by=actor.get("name", ""), decided_at=now_iso(),
                       revision_count=int(doc.get("revision_count") or 0) + 1)


async def cancel(req_id: str, actor: Dict[str, Any], reason: str) -> Dict[str, Any]:
    doc = await _load(req_id)
    if doc.get("status") in TERMINAL_STATUSES:
        raise DesignRequestError("Permintaan ini sudah selesai/dibatalkan.")
    why = (reason or "").strip()
    if len(why) < 3:
        raise DesignRequestError("Sebutkan alasan pembatalan.")
    return await _save(doc, "cancelled", "Dibatalkan", actor, note=why,
                       status=STATUS_CANCELLED, cancelled_reason=why)


# ─── Daftar & ringkasan ──────────────────────────────────────────────────────
def overdue(doc: Dict[str, Any], today: str = "") -> bool:
    """Lewat tenggat = ada tenggat, sudah lewat, dan pekerjaannya belum selesai."""
    due = (doc.get("due_date") or "").strip()
    if not due or doc.get("status") in TERMINAL_STATUSES:
        return False
    return due < (today or _today())


def shape(doc: Dict[str, Any], today: str = "") -> Dict[str, Any]:
    """Bentuk baris untuk layar: field turunan dihitung SERVER (INV-UI-04 — layar
    tidak boleh menghitung sendiri lalu berbeda dengan papan)."""
    out = safe_doc(dict(doc))
    out["status_label"] = STATUS_LABEL.get(doc.get("status"), doc.get("status", ""))
    out["target_label"] = TARGET_TYPES.get(doc.get("target_type"), doc.get("target_type", ""))
    out["source_label"] = SOURCES.get(doc.get("source"), doc.get("source", ""))
    out["is_overdue"] = overdue(doc, today)
    out["versions"] = len(doc.get("gallery_ids") or [])
    return out


async def summary(query: Dict[str, Any]) -> Dict[str, Any]:
    """Kartu ringkasan dihitung dari SELURUH hasil filter (bukan dari isi halaman).

    Pelajaran FASE P5: begitu daftar dipaginasi, lencana yang dihitung dari halaman
    aktif diam-diam menyusut (\u201ckartu bilang 12, daftar berisi 3\u201d).
    """
    out: Dict[str, int] = {s: 0 for s in STATUS_LABEL}
    total = 0
    late = 0
    today = _today()
    async for d in db[COLL].find(query, {"_id": 0, "status": 1, "due_date": 1}):
        total += 1
        out[d.get("status", "")] = out.get(d.get("status", ""), 0) + 1
        if overdue(d, today):
            late += 1
    out["total"] = total
    out["overdue"] = late
    out["open"] = sum(out.get(s, 0) for s in OPEN_STATUSES)
    return out


# ─── Rapor desainer (dihitung dari dokumen, bukan diketik) ───────────────────
def _days_between(a: str, b: str) -> Optional[float]:
    from datetime import datetime
    try:
        d1 = datetime.fromisoformat((a or "").replace("Z", "+00:00"))
        d2 = datetime.fromisoformat((b or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return round(abs((d2 - d1).total_seconds()) / 86400.0, 2)


async def report_by_designer(query: Dict[str, Any]) -> Dict[str, Any]:
    """Rapor per desainer: diminta · dikerjakan · diserahkan · ACC · revisi ·
    rata-rata hari kerja · rata-rata bintang · lewat tenggat.

    Bintang dibaca dari `design_gallery.ratings` pada artwork yang diserahkan —
    satu sumber dengan layar Galeri, jadi angkanya tidak bisa berbeda.
    """
    today = _today()
    rows: Dict[str, Dict[str, Any]] = {}
    gallery_needed: List[str] = []
    docs: List[Dict[str, Any]] = []
    async for d in db[COLL].find(query, {"_id": 0}):
        docs.append(d)
        gallery_needed.extend(d.get("gallery_ids") or [])

    stars: Dict[str, List[float]] = {}
    if gallery_needed:
        async for g in db.design_gallery.find({"id": {"$in": list(set(gallery_needed))}},
                                              {"_id": 0, "id": 1, "ratings": 1}):
            vals = [float(r.get("stars") or 0) for r in (g.get("ratings") or [])
                    if float(r.get("stars") or 0) > 0]
            if vals:
                stars[g["id"]] = vals

    for d in docs:
        key = d.get("assigned_to") or "__unassigned__"
        row = rows.setdefault(key, {
            "designer_id": d.get("assigned_to", ""),
            "designer": d.get("assigned_name") or "Belum ditugaskan",
            "division": d.get("division", ""),
            "assigned": 0, "in_progress": 0, "delivered": 0, "approved": 0,
            "revision": 0, "overdue": 0, "_days": [], "_stars": [],
        })
        row["assigned"] += 1
        if d.get("status") == STATUS_IN_PROGRESS:
            row["in_progress"] += 1
        if d.get("delivered_at"):
            row["delivered"] += 1
            hari = _days_between(d.get("assigned_at") or d.get("requested_at", ""),
                                 d.get("delivered_at", ""))
            if hari is not None:
                row["_days"].append(hari)
        if d.get("status") == STATUS_APPROVED:
            row["approved"] += 1
        row["revision"] += int(d.get("revision_count") or 0)
        if overdue(d, today):
            row["overdue"] += 1
        for gid in d.get("gallery_ids") or []:
            row["_stars"].extend(stars.get(gid, []))

    out: List[Dict[str, Any]] = []
    for row in rows.values():
        days = row.pop("_days")
        st = row.pop("_stars")
        row["avg_days"] = round(sum(days) / len(days), 2) if days else None
        row["avg_stars"] = round(sum(st) / len(st), 2) if st else None
        row["acc_rate_pct"] = (round(row["approved"] * 100.0 / row["assigned"], 1)
                               if row["assigned"] else 0.0)
        out.append(row)
    out.sort(key=lambda r: (-r["assigned"], r["designer"].lower()))
    return {"items": out,
            "totals": {
                "requests": len(docs),
                "delivered": sum(r["delivered"] for r in out),
                "approved": sum(r["approved"] for r in out),
                "revision": sum(r["revision"] for r in out),
                "overdue": sum(r["overdue"] for r in out),
            }}


async def report_mine(query: Dict[str, Any], *, user_id: str,
                      display_name: str = "") -> Dict[str, Any]:
    """Rapor **milik satu desainer** — angka dirinya + pembanding tim yang AGREGAT.

    KENAPA ADA (FASE D, keputusan pemilik): rapor lintas desainer
    (`report_by_designer`) menilai ORANG, jadi wewenangnya atasan — desainer yang
    membukanya hanya mendapat 403 yang ditelan `.catch`, yaitu **panel mati**. Tetapi
    "tidak boleh melihat rekan" tidak sama dengan "tidak boleh melihat dirinya".
    Fungsi ini memberi desainer angkanya sendiri **tanpa** membocorkan satu nama rekan
    pun — pola privasi yang sama dengan `rnd_kpi_service.my_kpi` (PS-18).

    `query` WAJIB berupa lingkup badan usaha/lini SAJA — **tanpa** `assigned_to`.
    Kalau ia sudah disaring ke satu orang, `total_designers` selalu 1 dan `rank`
    selalu 1: angka yang terlihat masuk akal tetapi tidak berarti apa-apa. Penyaringan
    ke "punya saya" dilakukan DI SINI (memilih satu baris), dan hanya baris itu yang
    dikirim keluar.
    """
    rep = await report_by_designer(query)
    items = rep["items"]
    me = next((r for r in items if r.get("designer_id") == user_id), None)
    # Peringkat dihitung hanya di antara desainer NYATA (baris "Belum ditugaskan"
    # bukan orang, jadi ia tidak boleh menggeser posisi siapa pun).
    peers = [r for r in items if r.get("designer_id")]
    rank = (peers.index(me) + 1) if me in peers else None

    def _avg(key: str) -> Optional[float]:
        return round(sum(r[key] for r in peers) / len(peers), 2) if peers else None

    return {
        "designer": (me or {}).get("designer") or display_name,
        "me": me,                       # None = belum ada permintaan yang ditugaskan
        "rank": rank,
        "total_designers": len(peers),
        # HANYA angka gabungan — sengaja TANPA daftar/nama rekan (PS-18).
        "team": {
            "designers": len(peers),
            "avg_assigned": _avg("assigned"),
            "avg_delivered": _avg("delivered"),
            "avg_approved": _avg("approved"),
        },
        "totals": {
            "requests": (me or {}).get("assigned", 0),
            "delivered": (me or {}).get("delivered", 0),
            "approved": (me or {}).get("approved", 0),
            "revision": (me or {}).get("revision", 0),
            "overdue": (me or {}).get("overdue", 0),
        },
    }
