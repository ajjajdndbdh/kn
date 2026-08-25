"""FASE F · PS-12/13/14/18/19 — Layanan **PERMINTAAN SAMPLE** (`md_samples`),
diperluas **FASE S** (sampling boleh LEBIH DARI SATU jenis).

Satu entitas permintaan kerja untuk **labdip** (warna kain polos), **handfeel**
(rasa & konstruksi) dan **proofing** (printing) — sengaja BUKAN dokumen baru
"SO Design"/"Design PO" (KN_18 §A.4: menambah 2 jenis dokumen akan tumpang tindih
dengan SO/PR/PO).

Yang dijamin di sini:
  * satu permintaan bisa dikirim ke **beberapa supplier** sekaligus lalu dibandingkan;
  * **FASE S** satu permintaan bisa menempuh **beberapa jenis sampling sekaligus**;
    tiap (supplier × jenis) punya rangkaian round sendiri (`rounds[].type_code`)
    sehingga riwayat labdip tidak tercampur dengan handfeel — dan skor 90 pada
    labdip (warna tepat) tidak pernah dibandingkan dengan 90 pada handfeel;
  * setiap supplier punya **round bernomor** `rnd 1..n` (PS-18) dengan **lampiran +
    catatan WAJIB** saat ditutup — tidak ada "sudah dikerjakan" tanpa bukti;
  * **FASE S** hasil ukur yang WAJIB diisi **lahir dari master** jenis sampling
    (`sample_types.measurement_fields`), bukan dari `if` di dalam kode maupun 5
    field tetap di skema;
  * batas round & target SLA per round diatur lewat Pusat Pengaturan (FASE G-0);
    kuota round dihitung **per (supplier × jenis)**, karena revisi warna tidak
    boleh menghabiskan kuota perbaikan handfeel;
  * keputusan pemenang **melahirkan dokumen nyata**: kontrak harga (Fase E) +
    barang supplier, dengan `sample_ref` terisi — menutup placeholder Fase E;
  * pengambilan bahan sample = **mutasi stok nyata** `sample_issue` atas roll
    (PS-19: satu angka stok, bukan koleksi stok sample kedua);
  * **FASE S** pelaksanaan ditutup dua langkah berurutan: `finish` (sample JADI)
    lalu `deliver` (dikirim, **tujuan wajib**) — user story S.F-4.
"""
from typing import Any, Dict, List, Optional, Tuple

import domain_registry as dr
from core_utils import (new_id, next_doc_number, now_iso, parse_decimal, safe_doc,
                       timeline_entry)
from db import db
from services import contract_service, doc_refs_service as refs, rnd_gate
from services import master_registry as mreg        # FASE S — satu pembaca master jenis
from services import rnd_spec_service as specs
from services import storage_service as storage
from services import supplier_item_service
from services.rnd_spec_service import RndError
from services import line_scope as _lines      # FASE L — satu pintu normalisasi lini

COLL = "md_samples"
PREFIX = "smp"
EPS = 0.0001

SAMPLE_STATUSES = ("draft", "sent", "in_progress", "assessed", "decided", "cancelled")
ROUND_RESULTS = ("acc", "revisi", "tolak")
OPEN_STATUSES = ("draft", "sent", "in_progress", "assessed")

# FASE S — tujuan pengiriman sample jadi. Daftarnya di registry (satu sumber untuk
# server, layar, dan gate); di sini hanya diambil supaya validasi tidak menyalinnya.
DELIVER_TARGETS: Tuple[str, ...] = tuple(dr.values_of("sample_deliver_target"))

# Alasan keputusan pemenang — terkendali (bukan teks bebas) supaya bisa dilaporkan.
DECISION_REASONS: Tuple[Dict[str, str], ...] = (
    {"value": "warna_paling_dekat", "label": "Warna paling dekat dengan target"},
    {"value": "mutu_terbaik", "label": "Mutu/handfeel terbaik"},
    {"value": "harga_terbaik", "label": "Harga terbaik pada mutu setara"},
    {"value": "lead_time", "label": "Lead time paling cepat"},
    {"value": "kapasitas", "label": "Kapasitas produksi memadai"},
    {"value": "permintaan_pelanggan", "label": "Diminta pelanggan"},
)


def reasons() -> List[Dict[str, str]]:
    return [dict(r) for r in DECISION_REASONS]


def deliver_targets() -> List[Dict[str, Any]]:
    """Pilihan tujuan kirim sample (label manusia) untuk layar & POC."""
    return [dict(r) for r in dr.enum_items("sample_deliver_target")]


# ─── FASE S — jenis sampling pada satu dokumen ────────────────────────────────
def types_of(sample: Dict[str, Any]) -> List[str]:
    """Jenis sampling dokumen — SATU pembaca untuk seluruh layanan & laporan.

    Dokumen yang lahir SEBELUM migrasi memakai `sample_type` (tunggal). Fungsi ini
    tetap membacanya supaya laporan lama tidak nol selama migrasi belum dijalankan,
    **tetapi** `scripts/migrate_sample_types.py` MENGHAPUS field lama: dua sumber
    yang dibiarkan hidup adalah kelas bug termahal di repo ini (gate INV-SAMPLE-01
    aturan B memerah bila ada sisa).
    """
    out: List[str] = []
    for v in (sample.get("sample_types") or []):
        code = str(v or "").strip().lower()
        if code and code not in out:
            out.append(code)
    if not out:
        legacy = str(sample.get("sample_type") or "").strip().lower()
        if legacy:
            out.append(legacy)
    return out


def _type_of_round(rnd: Dict[str, Any], sample: Dict[str, Any]) -> str:
    """`type_code` round; round lama (sebelum FASE S) diikat ke jenis pertama."""
    code = str(rnd.get("type_code") or "").strip().lower()
    if code:
        return code
    kinds = types_of(sample)
    return kinds[0] if kinds else ""


async def _resolve_types(payload: Dict[str, Any], spec: Optional[Dict[str, Any]],
                         line_code: str, entity_id: str) -> List[str]:
    """Jenis sampling yang diminta — dari payload, spesifikasi, atau usulan LINI.

    Urutan sengaja begini: apa yang diminta pengguna → petunjuk spesifikasi →
    usulan master lini (`sample_types_default`, keputusan pemilik #3). Tidak ada
    bawaan `"labdip"` yang diketik di kode: bawaan yang tertanam di kode adalah
    alasan kenapa `sample_types_default` di master tidak pernah berpengaruh.
    """
    raw = payload.get("sample_types")
    want = [str(v).strip().lower() for v in (raw or []) if str(v or "").strip()]
    # Kompatibilitas pemanggil lama (`sample_type` tunggal) — API lama tidak boleh
    # mendadak menolak, tetapi hasilnya tetap ditulis sebagai daftar.
    legacy = str(payload.get("sample_type") or "").strip().lower()
    if not want and legacy:
        want = [legacy]
    if not want and spec:
        hint = str(spec.get("sample_type_hint") or "").strip().lower()
        if hint:
            want = [hint]
    if not want:
        want = await mreg.default_sample_types_for_line(line_code, entity_id)
    seen: List[str] = []
    for v in want:
        if v not in seen:
            seen.append(v)
    if not seen:
        raise RndError(
            "Pilih minimal satu JENIS sampling (mis. labdip / handfeel / proofing). "
            "Bila lini kerjanya sudah dipilih, usulan jenisnya bisa diatur di "
            "Pengaturan → Master → Lini Produk (kolom 'Jenis sampling usulan').")
    live = {r["value"]: r for r in await mreg.sample_types(entity_id)}
    active = {r["value"] for r in await mreg.active_sample_types(entity_id)}
    for code in seen:
        if code not in live:
            raise RndError(
                f"Jenis sampling '{code}' tidak dikenal. Pilihan aktif: "
                f"{', '.join(sorted(active)) or '(belum ada)'}. Jenis baru bisa "
                "ditambah di Pengaturan → Master → Jenis Sampling.")
        if code not in active:
            raise RndError(
                f"Jenis sampling '{code}' sedang DINONAKTIFKAN di master, jadi tidak "
                "bisa dipakai untuk permintaan baru. Aktifkan dulu di Pengaturan → "
                "Master → Jenis Sampling, atau pilih jenis lain.")
    return seen


# ─── Helper ───────────────────────────────────────────────────────
async def _get(sample_id: str) -> Dict[str, Any]:
    row = await db[COLL].find_one({"id": sample_id}, {"_id": 0})
    if not row:
        raise RndError("Permintaan sample tidak ditemukan.")
    return row


def _round_of(sample: Dict[str, Any], round_id: str) -> Dict[str, Any]:
    for r in (sample.get("rounds") or []):
        if r.get("id") == round_id:
            return r
    raise RndError("Round tidak ditemukan pada permintaan sample ini.")


def _plus_days(iso_date: str, days: int) -> str:
    from datetime import date, timedelta
    base = (iso_date or "")[:10]
    try:
        d = date.fromisoformat(base) if base else date.today()
    except ValueError:
        d = date.today()
    return (d + timedelta(days=int(days or 0))).isoformat()


def _is_overdue(due_date: str, done_at: str = "") -> bool:
    from datetime import date, datetime
    if not due_date:
        return False
    try:
        due = date.fromisoformat(due_date[:10])
    except ValueError:
        return False
    ref = date.today()
    if done_at:
        try:
            ref = datetime.fromisoformat(done_at.replace("Z", "+00:00")).date()
        except ValueError:
            ref = date.today()
    return ref > due


async def _supplier_snapshot(supplier_id: str) -> Dict[str, str]:
    row = await db.suppliers.find_one({"id": supplier_id}, {"_id": 0, "name": 1})
    if not row:
        raise RndError(f"Supplier '{supplier_id}' tidak ditemukan.")
    return {"supplier_id": supplier_id, "supplier_name": row.get("name", "")}


async def _recalc(sample_id: str) -> Dict[str, Any]:
    """Hitung ulang ringkasan per supplier + biaya + status dari rounds (SSOT tunggal).

    FASE S — ringkasan dipecah **per jenis** (`participants[].types[type_code]`).
    Alasannya bukan kosmetik: `best_score` gabungan mencampur skor warna (labdip)
    dengan skor rasa kain (handfeel), sehingga papan perbandingan supplier
    membandingkan dua hal berbeda dan tetap tampak masuk akal.
    """
    s = await _get(sample_id)
    rounds = s.get("rounds") or []
    kinds = types_of(s)
    parts: Dict[str, Dict[str, Any]] = {p["supplier_id"]: dict(p)
                                        for p in (s.get("participants") or [])}
    for p in parts.values():
        p.update({"rounds": 0, "best_score": None, "status": p.get("status") or "invited",
                  "last_result": "", "overdue": False, "types": {}})
    for r in rounds:
        p = parts.get(r.get("supplier_id"))
        if not p:
            continue
        tcode = _type_of_round(r, s)
        t = p["types"].setdefault(tcode, {"type_code": tcode, "rounds": 0,
                                          "best_score": None, "last_result": "",
                                          "status": "invited", "overdue": False,
                                          "last_round_no": 0, "open_rounds": 0})
        p["rounds"] = int(p["rounds"]) + 1
        t["rounds"] = int(t["rounds"]) + 1
        t["last_round_no"] = max(int(t["last_round_no"]), int(r.get("round_no") or 0))
        if r.get("status") == "open":
            t["open_rounds"] = int(t["open_rounds"]) + 1
        if r.get("score") is not None:
            p["best_score"] = max(float(r["score"]), float(p["best_score"] or 0))
            t["best_score"] = max(float(r["score"]), float(t["best_score"] or 0))
        if r.get("result"):
            p["last_result"] = r["result"]
            t["last_result"] = r["result"]
            state = {"acc": "acc", "tolak": "rejected"}.get(r["result"], "responded")
            p["status"] = state
            t["status"] = state
        elif r.get("status") == "submitted":
            p["status"] = "responded"
            t["status"] = "responded"
        if r.get("overdue"):
            p["overdue"] = True
            t["overdue"] = True
    # Jenis yang diminta tetapi belum punya round sama sekali WAJIB muncul sebagai
    # baris "diundang" — kalau tidak, jenis yang belum dikirim hilang dari layar dan
    # pekerjaan yang belum jalan jadi tak terlihat (kelas cacat FASE L: dokumen tanpa
    # lini tak muncul di chip mana pun).
    for p in parts.values():
        for tcode in kinds:
            p["types"].setdefault(tcode, {"type_code": tcode, "rounds": 0,
                                          "best_score": None, "last_result": "",
                                          "status": "invited", "overdue": False,
                                          "last_round_no": 0, "open_rounds": 0})
    cost = round(sum(float(r.get("cost") or 0) for r in rounds)
                 + sum(float(m.get("cost") or 0) for m in (s.get("material_issues") or [])), 2)
    status = s.get("status")
    if status in ("sent", "in_progress", "assessed"):
        if any(r.get("result") == "acc" for r in rounds):
            status = "assessed"
        elif any(r.get("status") in ("submitted", "assessed") for r in rounds):
            status = "in_progress"
        else:
            status = "sent"
    await db[COLL].update_one({"id": sample_id}, {"$set": {
        "participants": list(parts.values()), "cost_total": cost, "status": status,
        "updated_at": now_iso()}})
    return await _get(sample_id)


# ─── CRUD ──────────────────────────────────────────────────────
async def create_sample(payload: Dict[str, Any], *, entity_id: str,
                        actor: str = "") -> Dict[str, Any]:
    spec = None
    spec_id = (payload.get("spec_id") or "").strip()
    if spec_id:
        spec = await db.md_specs.find_one({"id": spec_id}, {"_id": 0})
        if not spec:
            raise RndError("Spesifikasi acuan tidak ditemukan.")
    # FASE L — lini kerja MD: dari payload, kalau tidak ada WARISI dari spesifikasi
    # acuannya (satu rantai pekerjaan = satu lini). Lini dihitung LEBIH DULU karena
    # usulan jenis sampling lahir darinya (keputusan pemilik #3).
    line_code = _lines.norm(payload.get("line_code") or (spec or {}).get("line_code"))
    stypes = await _resolve_types(payload, spec, line_code, entity_id)
    color = payload.get("color_target") or (spec or {}).get("color_target") or {}
    color = await specs._color_snapshot(color)  # noqa: SLF001 — satu jalur validasi warna
    design_id = (payload.get("design_id") or (spec or {}).get("design_id") or "").strip()
    design_version = int(payload.get("design_version") or (spec or {}).get("design_version") or 0)
    pol = await rnd_gate.policy(entity_id)
    # FASE S — "wajib kode desain" kini DATA di master jenis (`requires_design`),
    # bukan `if stype == "proofing"`. Kebijakan `require_design_for_proofing` tetap
    # jadi tombol mati/hidupnya supaya perilaku lama bisa dimatikan pemilik.
    if bool(pol.get("require_design_for_proofing", True)) and not design_id:
        for code in stypes:
            meta = await mreg.sample_type_meta(code, entity_id)
            if meta.get("requires_design"):
                raise RndError(
                    f"Jenis sampling '{meta.get('label') or code}' WAJIB merujuk kode "
                    "desain. Pilih desain dari Master Desain lebih dulu, atau buang "
                    "jenis itu dari permintaan ini.")
    design = await specs._design_snapshot(design_id, design_version)  # noqa: SLF001
    doc: Dict[str, Any] = {
        "id": new_id(PREFIX),
        "number": await next_doc_number(COLL, "number", "SMP-", entity_id=entity_id),
        "entity_id": entity_id or "",
        "spec_id": spec_id,
        "spec_number": (spec or {}).get("number", ""),
        "product_id": (spec or {}).get("product_id", ""),
        # FASE S — DAFTAR jenis (satu permintaan boleh menempuh labdip + handfeel).
        # Field tunggal `sample_type` sengaja TIDAK ditulis lagi: dua sumber untuk
        # satu fakta adalah kelas bug yang fase ini justru menutup.
        "sample_types": stypes,
        "line_code": line_code,
        "status": "draft",
        "title": (payload.get("title") or (spec or {}).get("title") or "").strip(),
        "brief": payload.get("brief") or "",
        "color_target": color,
        **design,
        "customer_id": (payload.get("customer_id") or (spec or {}).get("customer_id") or "").strip(),
        "so_id": (payload.get("so_id") or (spec or {}).get("so_id") or "").strip(),
        "target_date": (payload.get("target_date") or "")[:10],
        "qty_requested": parse_decimal(payload.get("qty_requested")),
        "unit": (payload.get("unit") or (spec or {}).get("base_unit") or "meter").strip(),
        "participants": [], "rounds": [], "material_issues": [],
        "cost_total": 0.0, "decision": {},
        # FASE S — penanda pelaksanaan (user story S.F-4). Ditulis sejak lahir supaya
        # kolom "Sample jadi / dikirim" tidak pernah "tidak ada field"-nya; bedakan
        # dari `null` yang berarti BELUM.
        "finished_at": "", "finished_by": "", "finish_note": "",
        "delivered_at": "", "delivered_to": "", "delivered_to_name": "",
        "delivered_by": "", "deliver_note": "",
        "refs": [],
        "timeline": [timeline_entry("created", "Permintaan sample dibuat (draft)", actor)],
        "created_by": actor, "created_at": now_iso(), "updated_at": now_iso(),
    }
    if not doc["title"]:
        raise RndError("Judul permintaan sample wajib diisi.")
    if doc["so_id"]:
        so = await db.sales_orders.find_one({"id": doc["so_id"]},
                                            {"_id": 0, "id": 1, "order_number": 1,
                                             "customer_id": 1})
        if not so:
            raise RndError("Pesanan yang ditautkan tidak ditemukan. Pilih pesanan dari "
                           "daftar, jangan diketik.")
        doc["so_number"] = so.get("order_number", "")
        # Pelanggan diturunkan dari pesanan, bukan diketik ulang — kalau dua-duanya
        # bisa diisi tangan, laporan "sample untuk pelanggan X" akan bercabang.
        doc["customer_id"] = doc["customer_id"] or so.get("customer_id", "")
    await db[COLL].insert_one(dict(doc))
    if spec_id:
        await refs.safe_link(("md_sample", doc["id"]), ("md_spec", spec_id), "parent",
                             note=f"permintaan {' + '.join(stypes)}")
        await db.md_specs.update_one({"id": spec_id},
                                     {"$addToSet": {"sample_ids": doc["id"]}})
        # Lifecycle produk mengikuti jenis yang punya arti tahap (labdip/proofing).
        for code in stypes:
            if code in ("labdip", "proofing"):
                await specs.set_lifecycle_stage(spec_id, code)
                break
    if doc["so_id"]:
        await refs.safe_link(("md_sample", doc["id"]), ("sales_order", doc["so_id"]),
                             "parent", note="permintaan pelanggan")
    return safe_doc(doc)


async def get_sample(sample_id: str) -> Optional[Dict[str, Any]]:
    return safe_doc(await db[COLL].find_one({"id": sample_id}, {"_id": 0}))


async def list_samples(query: Dict[str, Any], *, q: str = "", status: str = "",
                       sample_type: str = "", spec_id: str = "", so_id: str = "",
                       limit: int = 200) -> List[Dict[str, Any]]:
    flt = dict(query or {})
    if status:
        flt["status"] = status
    if sample_type:
        # FASE S — `sample_types` adalah ARRAY: kecocokan Mongo pada array berarti
        # KEANGGOTAAN, jadi satu penyaring melayani dokumen ber-satu-jenis maupun
        # ber-banyak-jenis. Dokumen lama (`sample_type` tunggal) ikut lewat `$or`
        # supaya daftar tidak mendadak kosong bila migrasi belum dijalankan.
        code = str(sample_type).strip().lower()
        flt["$and"] = (flt.get("$and") or []) + [
            {"$or": [{"sample_types": code}, {"sample_type": code}]}]
    if spec_id:
        flt["spec_id"] = spec_id
    if so_id:
        flt["so_id"] = so_id
    if q:
        rx = {"$regex": q.strip(), "$options": "i"}
        flt["$or"] = [{"number": rx}, {"title": rx}, {"spec_number": rx},
                      {"color_target.name": rx}, {"participants.supplier_name": rx},
                      {"so_number": rx}]
    rows = await db[COLL].find(flt, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return [safe_doc(r) for r in rows]


async def patch_sample(sample_id: str, payload: Dict[str, Any], actor: str = "") -> Dict[str, Any]:
    cur = await _get(sample_id)
    if cur.get("status") not in OPEN_STATUSES:
        raise RndError(f"Permintaan berstatus '{cur.get('status')}' tidak bisa diubah.")
    data: Dict[str, Any] = {}
    for key in ("title", "brief", "unit"):
        if payload.get(key) is not None:
            data[key] = payload[key]
    if payload.get("target_date") is not None:
        data["target_date"] = str(payload["target_date"])[:10]
    if payload.get("qty_requested") is not None:
        data["qty_requested"] = parse_decimal(payload["qty_requested"])
    if payload.get("color_target") is not None:
        data["color_target"] = await specs._color_snapshot(payload["color_target"])  # noqa: SLF001
    if payload.get("design_id") is not None:
        data.update(await specs._design_snapshot(  # noqa: SLF001
            payload["design_id"], int(payload.get("design_version") or 0)))
    # FASE S — jenis sampling boleh DITAMBAH selama permintaan masih terbuka
    # (mis. "labdip sudah jalan, sekarang minta handfeel juga"). Jenis yang SUDAH
    # punya round tidak boleh dibuang: riwayat & bukti yang sudah ada akan menjadi
    # round tanpa jenis — persis kelas cacat yang `type_code` ini menutup.
    if payload.get("sample_types") is not None:
        eid = cur.get("entity_id", "")
        want = await _resolve_types({"sample_types": payload["sample_types"]}, None,
                                    cur.get("line_code", ""), eid)
        used = {_type_of_round(r, cur) for r in (cur.get("rounds") or [])}
        lost = sorted(used - set(want))
        if lost:
            raise RndError(
                f"Jenis {', '.join(lost)} sudah punya round berjalan — tidak bisa "
                "dibuang dari permintaan ini. Batalkan permintaannya dan buat baru "
                "bila memang salah jenis.")
        pol = await rnd_gate.policy(eid)
        if bool(pol.get("require_design_for_proofing", True)) \
                and not (data.get("design_id", cur.get("design_id")) or ""):
            for code in want:
                meta = await mreg.sample_type_meta(code, eid)
                if meta.get("requires_design"):
                    raise RndError(
                        f"Jenis '{meta.get('label') or code}' WAJIB merujuk kode desain. "
                        "Pilih desainnya lebih dulu.")
        data["sample_types"] = want
    # FASE S — tautan pesanan bisa dipasang belakangan (permintaan sering lahir
    # sebelum pesanannya turun). Nomornya di-snapshot supaya pencarian tidak perlu
    # join, dan refs ditulis DUA ARAH lewat `safe_link` (INV-REF-04).
    if payload.get("so_id") is not None:
        so_id = str(payload["so_id"] or "").strip()
        if so_id:
            so = await db.sales_orders.find_one({"id": so_id},
                                                {"_id": 0, "order_number": 1,
                                                 "customer_id": 1})
            if not so:
                raise RndError("Pesanan yang ditautkan tidak ditemukan.")
            data["so_id"] = so_id
            data["so_number"] = so.get("order_number", "")
            if not cur.get("customer_id"):
                data["customer_id"] = so.get("customer_id", "")
        else:
            data["so_id"], data["so_number"] = "", ""
    if payload.get("customer_id") is not None:
        data["customer_id"] = str(payload["customer_id"] or "").strip()
    data["updated_at"] = now_iso()
    await db[COLL].update_one({"id": sample_id}, {
        "$set": data,
        "$push": {"timeline": timeline_entry("updated", "Permintaan diperbarui", actor)}})
    if data.get("so_id"):
        await refs.safe_link(("md_sample", sample_id), ("sales_order", data["so_id"]),
                             "parent", note="permintaan pelanggan")
    return await get_sample(sample_id)


async def cancel_sample(sample_id: str, reason: str, actor: str = "") -> Dict[str, Any]:
    cur = await _get(sample_id)
    if cur.get("status") == "decided":
        raise RndError("Permintaan yang sudah diputus tidak bisa dibatalkan — "
                       "jejaknya dipakai kontrak & barang supplier.")
    await db[COLL].update_one({"id": sample_id}, {
        "$set": {"status": "cancelled", "cancel_reason": reason, "updated_at": now_iso()},
        "$push": {"timeline": timeline_entry("cancelled", "Dibatalkan", actor, reason)}})
    return await get_sample(sample_id)


# ─── Kirim ke supplier + round ───────────────────────────────────────
def _new_round(no: int, snap: Dict[str, str], type_code: str, due: str,
               opened_by: str = "", over_limit_reason: str = "") -> Dict[str, Any]:
    """Satu baris round. `type_code` WAJIB ada sejak lahir (FASE S).

    Round tanpa jenis akan tampak di dua rangkaian sekaligus (atau tak tampak di
    mana pun) begitu satu permintaan menempuh lebih dari satu jenis — karena itu
    tidak ada jalur pembuatan round yang boleh melewatkannya.
    """
    return {
        "id": new_id("rnd"), "round_no": int(no), **snap,
        "type_code": str(type_code or "").strip().lower(),
        "status": "open", "sent_at": now_iso(), "due_date": due, "received_at": "",
        "note": "", "attachments": [], "measurements": {}, "cost": 0.0,
        "result": "", "score": None, "assessed_by": "", "assessed_at": "",
        "performed_by": "", "overdue": False, "opened_by": opened_by,
        # FASE S — jejak QC FISIK sample (siapa & kapan memegang kainnya). `verdict`
        # memakai `result` yang sudah ada supaya tidak lahir penilaian kedua.
        "qc": {},
        **({"over_limit_reason": over_limit_reason} if over_limit_reason else {}),
    }


async def send_sample(sample_id: str, supplier_ids: List[str], *, due_date: str = "",
                      note: str = "", type_codes: Optional[List[str]] = None,
                      actor: str = "") -> Dict[str, Any]:
    """Kirim permintaan ke ≥1 supplier × ≥1 JENIS sampling sekaligus.

    FASE S — round 1 dibuka untuk **tiap kombinasi** (supplier × jenis). Supplier
    yang sudah diundang tidak diundang ulang, tetapi JENIS baru untuk supplier lama
    tetap boleh ditambah: dulu pengecekan hanya melihat supplier, sehingga
    "tambahkan handfeel ke supplier yang sudah mengerjakan labdip" ditolak dengan
    kalimat "semua supplier sudah diundang" — pekerjaan sah yang tak bisa dicatat.
    """
    cur = await _get(sample_id)
    if cur.get("status") not in ("draft", "sent", "in_progress"):
        raise RndError(f"Permintaan berstatus '{cur.get('status')}' tidak bisa dikirim lagi.")
    ids = [s for s in dict.fromkeys(supplier_ids or []) if s]
    if not ids:
        raise RndError("Pilih minimal satu supplier tujuan permintaan sample.")
    kinds = types_of(cur)
    want = [str(t).strip().lower() for t in (type_codes or []) if str(t or "").strip()]
    for t in want:
        if t not in kinds:
            raise RndError(
                f"Jenis '{t}' bukan bagian permintaan {cur.get('number')} "
                f"(jenis yang diminta: {', '.join(kinds) or '—'}). Ubah permintaannya "
                "lebih dulu bila memang ingin menambah jenis.")
    kinds = want or kinds
    if not kinds:
        raise RndError("Permintaan ini belum punya jenis sampling — tidak ada yang "
                       "bisa dikirim. Ubah permintaannya lebih dulu.")
    pol = await rnd_gate.policy(cur.get("entity_id", ""))
    sla = int(pol.get("round_sla_days") or 7)
    due = (due_date or "")[:10] or _plus_days("", sla)
    existing_parts = {p["supplier_id"] for p in (cur.get("participants") or [])}
    have = {(r.get("supplier_id"), _type_of_round(r, cur)) for r in (cur.get("rounds") or [])}
    new_parts, new_rounds = [], []
    for sid in ids:
        snap = await _supplier_snapshot(sid)
        if sid not in existing_parts:
            new_parts.append({**snap, "status": "invited", "rounds": 0, "best_score": None,
                              "types": {}, "invited_at": now_iso()})
        for tcode in kinds:
            if (sid, tcode) in have:
                continue
            new_rounds.append(_new_round(1, snap, tcode, due, opened_by=actor))
    if not new_rounds:
        raise RndError("Semua kombinasi supplier × jenis yang dipilih sudah punya "
                       "round pada permintaan ini. Untuk iterasi berikutnya gunakan "
                       "\"Buka round berikutnya\" pada jenis yang bersangkutan.")
    push: Dict[str, Any] = {"rounds": {"$each": new_rounds},
                            "timeline": timeline_entry(
                                "sent",
                                f"Dikirim: {len(new_rounds)} round dibuka "
                                f"({len(ids)} supplier × {len(kinds)} jenis: "
                                f"{', '.join(kinds)}) · target {due}", actor, note)}
    if new_parts:
        push["participants"] = {"$each": new_parts}
    await db[COLL].update_one({"id": sample_id}, {
        "$set": {"status": "sent", "sent_at": cur.get("sent_at") or now_iso(),
                 "updated_at": now_iso()},
        "$push": push})
    return await _recalc(sample_id)


async def open_round(sample_id: str, supplier_id: str, *, type_code: str = "",
                     due_date: str = "", note: str = "",
                     reason: str = "", actor: Dict[str, Any]) -> Dict[str, Any]:
    """Buka round berikutnya (rnd 2, 3, …) untuk satu supplier **pada satu jenis**.

    Kuota `rnd.max_rounds` dihitung PER (supplier × jenis): revisi warna tidak boleh
    menghabiskan kuota perbaikan handfeel, karena keduanya pekerjaan yang berbeda.
    """
    cur = await _get(sample_id)
    if cur.get("status") not in OPEN_STATUSES:
        raise RndError(f"Permintaan berstatus '{cur.get('status')}' tidak bisa menambah round.")
    kinds = types_of(cur)
    tcode = str(type_code or "").strip().lower()
    if not tcode:
        if len(kinds) == 1:
            tcode = kinds[0]
        else:
            raise RndError(
                "Permintaan ini menempuh beberapa jenis sampling "
                f"({', '.join(kinds)}) — sebutkan JENIS mana yang minta round "
                "berikutnya, supaya riwayatnya tidak tercampur.")
    if tcode not in kinds:
        raise RndError(f"Jenis '{tcode}' bukan bagian permintaan ini "
                       f"(jenis yang diminta: {', '.join(kinds) or '—'}).")
    mine = [r for r in (cur.get("rounds") or [])
            if r.get("supplier_id") == supplier_id and _type_of_round(r, cur) == tcode]
    if not mine:
        raise RndError("Supplier ini belum diundang untuk jenis tersebut. Kirim "
                       "permintaannya lebih dulu (tombol Kirim ke supplier).")
    last = max(mine, key=lambda r: int(r.get("round_no") or 0))
    if not last.get("result"):
        raise RndError(f"Round {last.get('round_no')} ({tcode}) belum dinilai. "
                       "Selesaikan penilaiannya sebelum membuka round berikutnya.")
    if last.get("result") == "acc":
        raise RndError(f"Round terakhir jenis '{tcode}' sudah ACC — tidak perlu "
                       "round tambahan.")
    pol = await rnd_gate.policy(cur.get("entity_id", ""))
    max_rounds = int(pol.get("max_rounds") or 3)
    next_no = int(last.get("round_no") or 0) + 1
    if next_no > max_rounds:
        role = (actor or {}).get("role", "")
        if role not in ("admin", "manager") or not (reason or "").strip():
            raise RndError(
                f"Batas iterasi {max_rounds} round sudah tercapai untuk supplier ini "
                f"pada jenis '{tcode}'. Round tambahan hanya boleh dibuka "
                "manager/admin DENGAN alasan tertulis "
                "(ubah batas di Pusat Pengaturan → R&D & Desain).")
    sla = int(pol.get("round_sla_days") or 7)
    snap = await _supplier_snapshot(supplier_id)
    row = _new_round(next_no, snap, tcode,
                     (due_date or "")[:10] or _plus_days("", sla),
                     opened_by=(actor or {}).get("name", ""),
                     over_limit_reason=reason or "")
    await db[COLL].update_one({"id": sample_id}, {
        "$push": {"rounds": row, "timeline": timeline_entry(
            "round_opened", f"Round {next_no} ({tcode}) dibuka untuk "
                            f"{snap['supplier_name']}",
            (actor or {}).get("name", ""), note or reason)},
        "$set": {"status": "in_progress", "updated_at": now_iso()}})
    return await _recalc(sample_id)


async def add_attachment(sample_id: str, round_id: str, filename: str, content_type: str,
                         data: bytes, actor: str = "") -> Dict[str, Any]:
    cur = await _get(sample_id)
    rnd = _round_of(cur, round_id)
    if rnd.get("result"):
        raise RndError("Round sudah dinilai — lampiran tidak bisa ditambah lagi "
                       "(jejak tidak boleh diubah setelah dinilai).")
    ctype = storage.validate_upload(filename, content_type, len(data))
    path = storage.build_path("rnd_samples", storage.ext_of(filename))
    await storage.put_object(path, data, ctype)
    meta = {"id": new_id("file"), "filename": filename, "path": path,
            "content_type": ctype, "size": len(data), "uploaded_by": actor,
            "uploaded_at": now_iso()}
    await db[COLL].update_one(
        {"id": sample_id, "rounds.id": round_id},
        {"$push": {"rounds.$.attachments": meta}, "$set": {"updated_at": now_iso()}})
    return safe_doc(meta)


async def get_attachment(sample_id: str, round_id: str, file_id: str):
    cur = await _get(sample_id)
    rnd = _round_of(cur, round_id)
    for f in (rnd.get("attachments") or []):
        if f.get("id") == file_id:
            data, ctype = await storage.get_object(f["path"])
            return data, f.get("content_type") or ctype
    raise RndError("Lampiran tidak ditemukan.")


async def _validate_measurements(type_code: str, raw: Dict[str, Any],
                                 entity_id: str) -> Dict[str, Any]:
    """Hasil ukur round — **kolom & kewajibannya LAHIR DARI MASTER**, bukan dari `if`.

    Tiga hal yang dijaga di sini, dan tiga-tiganya pernah gagal senyap sebelum FASE S:
      1. field yang diminta master WAJIB terisi (dulu `RoundMeasurements` punya 5 field
         tetap, jadi `handfeel_score` tidak punya tempat dan `delta_e` diminta pada
         handfeel yang tidak mengukur warna);
      2. field yang TIDAK diminta jenis ini ditolak dengan menyebut kolom yang benar —
         kalau dibiarkan lewat, dokumen menyimpan angka yang tak pernah ditampilkan;
      3. angka di luar batas wajar (ΔE 120, skor handfeel 50) ditolak. Ini bukan
         penilaian mutu — hanya menangkap salah ketik yang tampak masuk akal.
    """
    want = await mreg.measurement_fields_of(type_code, entity_id)
    shape = {m["value"]: m for m in dr.enum_items("sample_measurement")}
    given: Dict[str, Any] = {}
    for k, v in (raw or {}).items():
        key = str(k or "").strip().lower()
        if not key:
            continue
        given[key] = None if v in (None, "") else parse_decimal(v)
    unknown = [k for k in given if k not in want]
    if unknown:
        raise RndError(
            f"Hasil ukur {', '.join(sorted(unknown))} tidak diminta untuk jenis "
            f"'{type_code}'. Kolom yang diminta: "
            f"{', '.join(shape.get(w, {}).get('label', w) for w in want) or '(tidak ada)'}. "
            "Ubah daftarnya di Pengaturan → Master → Jenis Sampling bila memang perlu.")
    missing = [w for w in want if given.get(w) is None]
    if missing:
        raise RndError(
            "Hasil ukur WAJIB diisi untuk jenis "
            f"'{type_code}': {', '.join(shape.get(m, {}).get('label', m) for m in missing)}. "
            "Nilai ini yang dipakai membandingkan supplier — tanpa angkanya, "
            "penilaian jadi selera.")
    for key, val in given.items():
        meta = shape.get(key) or {}
        lo, hi = meta.get("min"), meta.get("max")
        if lo is not None and float(val) < float(lo) - EPS:
            raise RndError(f"{meta.get('label', key)} = {val:g} di bawah batas wajar "
                           f"({lo}). Periksa angkanya.")
        if hi is not None and float(val) > float(hi) + EPS:
            raise RndError(f"{meta.get('label', key)} = {val:g} di atas batas wajar "
                           f"({hi}) {meta.get('unit', '')}. Periksa angkanya.")
    return given


async def submit_round(sample_id: str, round_id: str, payload: Dict[str, Any],
                       actor: str = "") -> Dict[str, Any]:
    """Setor hasil round — **lampiran + catatan WAJIB** (PS-18) + hasil ukur (FASE S)."""
    cur = await _get(sample_id)
    rnd = _round_of(cur, round_id)
    if rnd.get("status") != "open":
        raise RndError(f"Round {rnd.get('round_no')} sudah disetor "
                       f"(status '{rnd.get('status')}').")
    pol = await rnd_gate.policy(cur.get("entity_id", ""))
    need_proof = bool(pol.get("require_attachment_on_round", True))
    note = (payload.get("note") or "").strip()
    if need_proof and not (rnd.get("attachments") or []):
        raise RndError("Tidak bisa menutup round tanpa LAMPIRAN bukti "
                       "(foto hasil / artwork / hasil ukur). Unggah dulu minimal 1 berkas.")
    if need_proof and not note:
        raise RndError("Catatan/penjelasan hasil WAJIB diisi saat menutup round.")
    tcode = _type_of_round(rnd, cur)
    meas = await _validate_measurements(tcode, payload.get("measurements") or {},
                                        cur.get("entity_id", ""))
    at = now_iso()
    await db[COLL].update_one(
        {"id": sample_id, "rounds.id": round_id},
        {"$set": {
            "rounds.$.status": "submitted", "rounds.$.received_at": at,
            "rounds.$.note": note, "rounds.$.measurements": meas,
            "rounds.$.cost": parse_decimal(payload.get("cost"), 2),
            "rounds.$.performed_by": actor,
            "rounds.$.proof_required": need_proof,
            "rounds.$.overdue": _is_overdue(rnd.get("due_date", ""), at),
            "status": "in_progress", "updated_at": at}})
    await db[COLL].update_one({"id": sample_id}, {"$push": {"timeline": timeline_entry(
        "round_submitted", f"Hasil round {rnd.get('round_no')} ({tcode}) "
                           f"dari {rnd.get('supplier_name')} disetor", actor, note)}})
    return await _recalc(sample_id)


async def assess_round(sample_id: str, round_id: str, payload: Dict[str, Any],
                       actor: Dict[str, Any]) -> Dict[str, Any]:
    cur = await _get(sample_id)
    rnd = _round_of(cur, round_id)
    if rnd.get("status") != "submitted":
        raise RndError("Hanya round yang sudah disetor (dengan bukti) bisa dinilai.")
    result = (payload.get("result") or "").strip().lower()
    if result not in ROUND_RESULTS:
        raise RndError(f"Hasil penilaian harus salah satu: {', '.join(ROUND_RESULTS)}.")
    score = payload.get("score")
    score = None if score in (None, "") else parse_decimal(score, 2)
    if result == "acc" and score is None:
        raise RndError("Skor penilaian wajib diisi saat memberi ACC — supaya kinerja "
                       "pelaksana & supplier bisa dibandingkan antar periode.")
    if score is not None and not (0 <= score <= 100):
        raise RndError("Skor harus di antara 0 dan 100.")
    name = (actor or {}).get("name", "")
    at = now_iso()
    tcode = _type_of_round(rnd, cur)
    # FASE S — jejak QC FISIK sample: siapa memegang kainnya & kapan. `verdict`
    # SENGAJA memakai `result` yang sudah ada (bukan enum kedua): dua kosakata untuk
    # satu keputusan akan bercabang, dan laporan QC berhenti bisa dipercaya.
    qc = {"by": name, "at": at, "verdict": result,
          "note": payload.get("note") or "", "type_code": tcode}
    await db[COLL].update_one(
        {"id": sample_id, "rounds.id": round_id},
        {"$set": {"rounds.$.status": "assessed", "rounds.$.result": result,
                  "rounds.$.score": score, "rounds.$.assessed_by": name,
                  "rounds.$.assessed_at": at,
                  "rounds.$.assess_note": payload.get("note") or "",
                  "rounds.$.qc": qc,
                  "updated_at": at}})
    await db[COLL].update_one({"id": sample_id}, {"$push": {"timeline": timeline_entry(
        "round_assessed", f"Round {rnd.get('round_no')} ({tcode} · "
                          f"{rnd.get('supplier_name')}) → {result}"
                          + (f" · skor {score:g}" if score is not None else ""),
        name, payload.get("note") or "")}})
    return await _recalc(sample_id)


# ─── FASE S — PELAKSANAAN: sample JADI lalu DIKIRIM (user story S.F-4) ────────
async def finish_sample(sample_id: str, payload: Dict[str, Any],
                        actor: str = "") -> Dict[str, Any]:
    """Tandai sample **JADI** (fisiknya sudah ada di tangan).

    Prasyarat: minimal satu round ber-hasil `acc`. Tanpa itu, "jadi" berarti "sudah
    dibuat tetapi belum tentu benar" — dan kolom tanggalnya akan dipakai orang lain
    sebagai bukti bahwa sample-nya sah.
    """
    cur = await _get(sample_id)
    if cur.get("status") == "cancelled":
        raise RndError("Permintaan yang dibatalkan tidak bisa ditandai jadi.")
    if cur.get("finished_at"):
        raise RndError(f"Sample ini sudah ditandai jadi pada "
                       f"{str(cur['finished_at'])[:10]}.")
    if not any(r.get("result") == "acc" for r in (cur.get("rounds") or [])):
        raise RndError("Belum ada round yang ACC — nilai dulu hasil sample-nya. "
                       "Menandai 'jadi' tanpa ACC membuat tanggalnya jadi bukti palsu.")
    at = (str(payload.get("date") or "")[:10] or now_iso())
    note = (payload.get("note") or "").strip()
    await db[COLL].update_one({"id": sample_id}, {
        "$set": {"finished_at": at, "finished_by": actor, "finish_note": note,
                 "updated_at": now_iso()},
        "$push": {"timeline": timeline_entry(
            "finished", f"Sample ditandai JADI ({str(at)[:10]})", actor, note)}})
    return await get_sample(sample_id)


async def deliver_sample(sample_id: str, payload: Dict[str, Any],
                         actor: str = "") -> Dict[str, Any]:
    """Catat sample sudah **DIKIRIM** — tujuannya WAJIB.

    Kenapa tujuan wajib: laporan "sample sudah dikirim" tanpa tujuan tidak bisa
    dipakai menjawab pertanyaan yang benar-benar ditanyakan pemilik ("sample untuk
    pelanggan mana yang belum kembali?"). Pilihannya dari registry
    (`sample_deliver_target`), bukan teks bebas.
    """
    cur = await _get(sample_id)
    if cur.get("status") == "cancelled":
        raise RndError("Permintaan yang dibatalkan tidak bisa dicatat pengirimannya.")
    if not cur.get("finished_at"):
        raise RndError("Tandai **Sample Jadi** lebih dulu — pengiriman sample yang "
                       "belum jadi tidak mungkin terjadi, dan urutannya dipakai "
                       "laporan sebagai bukti.")
    if cur.get("delivered_at"):
        raise RndError(f"Sample ini sudah dicatat dikirim pada "
                       f"{str(cur['delivered_at'])[:10]} "
                       f"({cur.get('delivered_to') or '—'}).")
    to = str(payload.get("to") or payload.get("delivered_to") or "").strip().lower()
    if to not in DELIVER_TARGETS:
        raise RndError(
            "Tujuan pengiriman WAJIB dipilih. Pilihan: "
            + ", ".join(f"{t['value']} ({t['label']})"
                        for t in dr.enum_items("sample_deliver_target")) + ".")
    at = (str(payload.get("date") or "")[:10] or now_iso())
    note = (payload.get("note") or "").strip()
    to_name = (payload.get("to_name") or "").strip()
    label = next((t["label"] for t in dr.enum_items("sample_deliver_target")
                  if t["value"] == to), to)
    await db[COLL].update_one({"id": sample_id}, {
        "$set": {"delivered_at": at, "delivered_to": to, "delivered_to_name": to_name,
                 "delivered_by": actor, "deliver_note": note, "updated_at": now_iso()},
        "$push": {"timeline": timeline_entry(
            "delivered", f"Sample dikirim ke {label}"
                         + (f" — {to_name}" if to_name else "")
                         + f" ({str(at)[:10]})", actor, note)}})
    return await get_sample(sample_id)


# ─── Keputusan pemenang → kontrak + barang supplier ─────────────────────────
async def decide_sample(sample_id: str, payload: Dict[str, Any],
                        actor: Dict[str, Any]) -> Dict[str, Any]:
    cur = await _get(sample_id)
    if cur.get("status") == "decided":
        raise RndError("Permintaan sample ini sudah diputus.")
    if cur.get("status") not in ("in_progress", "assessed"):
        raise RndError(f"Permintaan berstatus '{cur.get('status')}' belum bisa diputus.")
    await specs._assert_role(actor, "sample_decision_roles",  # noqa: SLF001
                            cur.get("entity_id", ""), "memutus pemenang sample")
    supplier_id = (payload.get("supplier_id") or "").strip()
    reason_code = (payload.get("reason_code") or "").strip()
    if reason_code not in {r["value"] for r in DECISION_REASONS}:
        raise RndError("Alasan keputusan wajib dipilih dari daftar alasan "
                       "(supaya bisa dilaporkan, bukan teks bebas).")
    acc = [r for r in (cur.get("rounds") or [])
           if r.get("supplier_id") == supplier_id and r.get("result") == "acc"]
    if not acc:
        raise RndError("Supplier ini belum punya round yang ACC — tidak boleh dijadikan "
                       "pemenang. Nilai dulu hasil sample-nya.")
    price = parse_decimal(payload.get("price"), 2)
    if price <= 0:
        raise RndError("Harga kesepakatan wajib diisi — keputusan sample membentuk "
                       "kontrak harga yang akan dipakai PO.")
    snap = await _supplier_snapshot(supplier_id)
    name = (actor or {}).get("name", "")
    entity_id = cur.get("entity_id", "")
    pol = await rnd_gate.policy(entity_id)
    product_id = cur.get("product_id") or ""
    if not product_id and cur.get("spec_id"):
        spec = await db.md_specs.find_one({"id": cur["spec_id"]}, {"_id": 0, "product_id": 1})
        product_id = (spec or {}).get("product_id") or ""
    contract, item = None, None
    if bool(pol.get("auto_contract_on_decide", True)):
        prod = await db.products.find_one({"id": product_id}, {"_id": 0}) if product_id else None
        basis = (prod or {}).get("base_unit") or cur.get("unit") or "meter"
        if basis not in set(dr.values_of("tariff_basis")):
            basis = "lumpsum"
        contract = await contract_service.create_contract({
            "contract_type": "purchase", "partner_id": supplier_id,
            "title": f"Hasil {' + '.join(types_of(cur)) or 'sample'} "
                     f"{cur.get('number')} — {cur.get('title')}",
            "product_id": product_id,
            "tariff_basis": basis, "tariff_rate": price, "tariff_qty_source": "output",
            "moq": parse_decimal(payload.get("moq")),
            "lead_time_days": int(payload.get("lead_time_days") or 0),
            "valid_to": (payload.get("valid_to") or "")[:10],
            "sample_ref": cur.get("number", ""),
            "notes": payload.get("note") or "",
        }, entity_id=entity_id, actor=name)
        if product_id:
            sku_sup = (payload.get("supplier_sku") or "").strip() or \
                f"{(prod or {}).get('sku', 'ITEM')}-{supplier_id[-4:].upper()}"
            try:
                item = await supplier_item_service.create_item({
                    "supplier_id": supplier_id, "supplier_sku": sku_sup,
                    "product_id": product_id,
                    "supplier_uom": (payload.get("supplier_uom") or "").strip(),
                    "last_price": price,
                    "moq": parse_decimal(payload.get("moq")),
                    "lead_time_days": int(payload.get("lead_time_days") or 0),
                    "notes": f"Dari keputusan sample {cur.get('number')}",
                }, entity_id=entity_id, actor=name)
            except Exception as exc:  # noqa: BLE001 — duplikat kode supplier bukan alasan gagal putus
                item = {"skipped": str(exc)}
    decision = {
        "supplier_id": supplier_id, "supplier_name": snap["supplier_name"],
        "reason_code": reason_code,
        "reason_label": next((r["label"] for r in DECISION_REASONS if r["value"] == reason_code), ""),
        "note": payload.get("note") or "", "price": price,
        "decided_by": name, "decided_at": now_iso(),
        "contract_id": (contract or {}).get("id", ""),
        "contract_number": (contract or {}).get("contract_number", ""),
        "supplier_item_id": (item or {}).get("id", ""),
        "round_id": acc[-1].get("id", ""), "round_no": acc[-1].get("round_no"),
        "score": acc[-1].get("score"),
    }
    await db[COLL].update_one({"id": sample_id}, {
        "$set": {"status": "decided", "decision": decision, "updated_at": now_iso()},
        "$push": {"timeline": timeline_entry(
            "decided", f"Pemenang: {snap['supplier_name']}"
                       + (f" · kontrak {decision['contract_number']}"
                          if decision["contract_number"] else ""),
            name, decision["reason_label"])}})
    if decision["contract_id"]:
        await refs.safe_link(("supplier_contract", decision["contract_id"]),
                            ("md_sample", sample_id), "parent",
                            note="hasil keputusan sample")
    return await get_sample(sample_id)


# ─── PS-19 — pengambilan bahan sample = mutasi stok NYATA ────────────────────
async def issue_material(sample_id: str, payload: Dict[str, Any],
                         actor: str = "") -> Dict[str, Any]:
    """Ambil bahan dari roll untuk keperluan sample.

    Bukan koleksi stok kedua: roll berkurang, `inventory_movements` bertipe
    `sample_issue` (qty negatif) tercatat, balance dihitung ulang. Biaya sample
    terbawa dari `unit_cost` roll.
    """
    from services import roll_service
    cur = await _get(sample_id)
    if cur.get("status") not in OPEN_STATUSES:
        raise RndError(f"Permintaan berstatus '{cur.get('status')}' tidak bisa "
                       "mengambil bahan lagi.")
    pol = await rnd_gate.policy(cur.get("entity_id", ""))
    if not bool(pol.get("sample_material_from_stock", True)):
        raise RndError("Pengambilan bahan sample dari stok sedang dimatikan di "
                       "Pusat Pengaturan → R&D & Desain.")
    qty = parse_decimal(payload.get("qty"))
    if qty <= 0:
        raise RndError("Jumlah bahan yang diambil harus lebih dari 0.")
    roll = await db.inventory_rolls.find_one({"id": payload.get("roll_id") or ""}, {"_id": 0})
    if not roll:
        raise RndError("Roll tidak ditemukan.")
    if roll.get("status") != "available":
        raise RndError(f"Roll {roll.get('roll_no')} berstatus '{roll.get('status')}' — "
                       "hanya roll tersedia (available) yang boleh dipakai sample.")
    have = float(roll.get("length_remaining") or 0)
    if have + EPS < qty:
        raise RndError(f"Sisa roll {roll.get('roll_no')} hanya {have:g} "
                       f"{roll.get('unit', 'meter')} — kurang dari {qty:g}.")
    new_len = round(have - qty, 3)
    unit_cost = float(roll.get("unit_cost") or roll.get("base_unit_cost") or 0)
    cost = round(unit_cost * qty, 2)
    at = now_iso()
    await db.inventory_rolls.update_one({"id": roll["id"]}, {"$set": {
        "length_remaining": max(new_len, 0.0),
        "status": "consumed" if new_len <= EPS else roll.get("status"),
        "updated_at": at}})
    mov = {
        "id": new_id("mov"), "product_id": roll.get("product_id"),
        "warehouse_id": roll.get("warehouse_id"),
        "owner_entity_id": roll.get("owner_entity_id"),
        "movement_type": "sample_issue", "quantity": -qty,
        "unit": roll.get("unit", "meter"), "lot": roll.get("lot", ""),
        "lot_id": roll.get("lot_id", ""), "roll_id": roll["id"],
        "source_document": cur.get("number") or sample_id,
        "reference_id": sample_id, "actor": actor,
        "note": payload.get("note") or "", "timestamp": at,
    }
    await db.inventory_movements.insert_one(dict(mov))
    await roll_service.rebuild_balance(roll.get("product_id"), roll.get("warehouse_id"),
                                       roll.get("owner_entity_id"))
    # FASE F — bahan keluar gudang untuk sample WAJIB berjurnal, kalau tidak nilai
    # persediaan turun di subledger sementara GL 1-1300 tetap (drift INV-GL-DRIFT).
    #   Dr 6-7000 Beban Sample & Pengembangan (R&D) / Cr 1-1300 Persediaan
    je_id, je_number = "", ""
    if cost > EPS:
        from services import gl_service
        try:
            je = await gl_service.post_sample_material_issue(
                movement_id=mov["id"], entity_id=roll.get("owner_entity_id") or "",
                amount=cost, label=f"{cur.get('number') or sample_id} · {roll.get('roll_no', '')}",
                note=payload.get("note") or "", date=at, created_by=actor or "system")
            if je:
                je_id, je_number = je.get("id", ""), je.get("number", "")
        except Exception as exc:  # noqa: BLE001
            # Jurnal gagal = masalah nyata (bukan kosmetik) → mutasi dibatalkan agar
            # tidak meninggalkan stok berkurang tanpa beban tercatat.
            await db.inventory_movements.delete_one({"id": mov["id"]})
            await db.inventory_rolls.update_one({"id": roll["id"]}, {"$set": {
                "length_remaining": have, "status": roll.get("status"), "updated_at": at}})
            await roll_service.rebuild_balance(roll.get("product_id"),
                                               roll.get("warehouse_id"),
                                               roll.get("owner_entity_id"))
            raise RndError("Pengambilan bahan dibatalkan: jurnal beban sample gagal "
                           f"dibuat ({exc}). Stok tidak diubah.") from exc
    # Nama produk dibaca dari master bila roll tidak menyimpannya — supaya baris
    # "bahan yang diambil" di layar menyebut NAMA BARANG, bukan id teknis.
    prod_name = (roll.get("product_name") or "").strip()
    if not prod_name and roll.get("product_id"):
        _p = await db.products.find_one({"id": roll["product_id"]},
                                        {"_id": 0, "name": 1, "sku": 1})
        prod_name = ((_p or {}).get("name") or (_p or {}).get("sku") or "").strip()
    entry = {
        "id": new_id("mi"), "roll_id": roll["id"], "roll_no": roll.get("roll_no", ""),
        "product_id": roll.get("product_id"), "product_name": prod_name,
        "warehouse_id": roll.get("warehouse_id"), "qty": qty,
        "unit": roll.get("unit", "meter"), "unit_cost": unit_cost, "cost": cost,
        "movement_id": mov["id"], "note": payload.get("note") or "",
        "journal_id": je_id, "journal_number": je_number,
        "issued_by": actor, "issued_at": at,
    }
    await db[COLL].update_one({"id": sample_id}, {
        "$push": {"material_issues": entry, "timeline": timeline_entry(
            "material_issued",
            f"Ambil {qty:g} {entry['unit']} dari roll {entry['roll_no']} "
            f"(stok gudang berkurang)", actor, payload.get("note") or "")},
        "$set": {"updated_at": at}})
    await _recalc(sample_id)
    return {"sample": await get_sample(sample_id), "movement": safe_doc(mov),
            "issue": safe_doc(entry)}


# ─── Laporan ──────────────────────────────────────────────────────
async def stats(query: Dict[str, Any]) -> Dict[str, Any]:
    rows = await db[COLL].find(dict(query or {}),
                               {"_id": 0, "status": 1, "sample_types": 1,
                                "sample_type": 1, "cost_total": 1, "rounds": 1,
                                "so_id": 1, "finished_at": 1, "delivered_at": 1}
                               ).to_list(5000)
    out: Dict[str, Any] = {s: 0 for s in SAMPLE_STATUSES}
    out.update({"total": len(rows), "cost_total": 0.0, "overdue_rounds": 0,
                "by_type": {}, "open_rounds": 0,
                # FASE S — angka yang dipakai kartu ringkasan layar. Dihitung di
                # SERVER karena daftar bisa dipaginasi: lencana yang dihitung dari
                # isi halaman diam-diam menyusut mengikuti halaman (pelajaran P2).
                "linked_so": 0, "finished": 0, "delivered": 0, "awaiting_delivery": 0})
    for r in rows:
        out[r.get("status", "draft")] = out.get(r.get("status", "draft"), 0) + 1
        out["cost_total"] = round(out["cost_total"] + float(r.get("cost_total") or 0), 2)
        for t in (types_of(r) or ["(tanpa jenis)"]):
            out["by_type"][t] = out["by_type"].get(t, 0) + 1
        if (r.get("so_id") or "").strip():
            out["linked_so"] += 1
        if r.get("finished_at"):
            out["finished"] += 1
            if not r.get("delivered_at"):
                out["awaiting_delivery"] += 1
        if r.get("delivered_at"):
            out["delivered"] += 1
        for rd in (r.get("rounds") or []):
            if rd.get("status") == "open":
                out["open_rounds"] += 1
                if _is_overdue(rd.get("due_date", "")):
                    out["overdue_rounds"] += 1
            elif rd.get("overdue"):
                out["overdue_rounds"] += 1
    return out


async def performer_report(query: Dict[str, Any]) -> List[Dict[str, Any]]:
    """PS-18 (dasar) — kinerja per pelaksana: jumlah ACC, rata-rata hari, skor rata-rata."""
    from datetime import datetime
    rows = await db[COLL].find(dict(query or {}), {"_id": 0, "rounds": 1}).to_list(5000)
    agg: Dict[str, Dict[str, Any]] = {}
    for s in rows:
        for rd in (s.get("rounds") or []):
            who = (rd.get("performed_by") or "").strip()
            if not who:
                continue
            a = agg.setdefault(who, {"performer": who, "rounds": 0, "acc": 0, "revisi": 0,
                                     "tolak": 0, "overdue": 0, "score_sum": 0.0,
                                     "score_n": 0, "days_sum": 0.0, "days_n": 0})
            a["rounds"] += 1
            res = rd.get("result") or ""
            if res in ("acc", "revisi", "tolak"):
                a[res] += 1
            if rd.get("overdue"):
                a["overdue"] += 1
            if rd.get("score") is not None:
                a["score_sum"] += float(rd["score"])
                a["score_n"] += 1
            try:
                t0 = datetime.fromisoformat(str(rd.get("sent_at")).replace("Z", "+00:00"))
                t1 = datetime.fromisoformat(str(rd.get("received_at")).replace("Z", "+00:00"))
                a["days_sum"] += max((t1 - t0).total_seconds() / 86400.0, 0.0)
                a["days_n"] += 1
            except Exception:  # noqa: BLE001 — round belum disetor
                pass
    out = []
    for a in agg.values():
        out.append({
            "performer": a["performer"], "rounds": a["rounds"], "acc": a["acc"],
            "revisi": a["revisi"], "tolak": a["tolak"], "overdue": a["overdue"],
            "avg_score": round(a["score_sum"] / a["score_n"], 1) if a["score_n"] else None,
            "avg_days": round(a["days_sum"] / a["days_n"], 1) if a["days_n"] else None,
        })
    out.sort(key=lambda r: (-r["acc"], r["performer"]))
    return out
