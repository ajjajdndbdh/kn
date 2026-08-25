"""Notification service — pembuatan notifikasi + generator dari event REAL.

Tidak ada data mock: notifikasi dihitung dari kondisi nyata di
`inventory_balances` (stok menipis) dan `sales_orders` (reservasi mendekati
kedaluwarsa 3 hari). Dedupe berbasis `ref` agar tidak menumpuk duplikat.
"""
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone, timedelta
from db import db
from core_utils import new_id, now_iso, safe_doc, rupiah
from services.inventory_service import product_summary

LOW_STOCK_THRESHOLD = 100.0  # meter — ambang batas default stok menipis


async def _has_unread(notif_type: str, ref: str) -> bool:
    return bool(await db.notifications.find_one(
        {"type": notif_type, "ref": ref, "read": False}, {"_id": 1}
    ))


async def create_addressed(
    *, permission: Optional[tuple] = None, division: str = "",
    roles: tuple = (), also_users: tuple = (), **kw: Any,
) -> List[Dict[str, Any]]:
    """FASE N — kirim notifikasi ke ORANG yang berwenang, satu per orang.

    Kenapa fan-out per orang dan bukan satu dokumen ber-"query izin": penyaring
    pembaca memakai **OR** (`recipient_role ∈ {peran, "all"}` OR `recipient_user`),
    jadi satu-satunya alamat yang benar-benar sempit adalah `recipient_user` SENDIRI.
    Menulis `recipient_role` bersama `recipient_user` justru MENYIARKAN ke seluruh
    peran itu — cacat yang terukur di `ar_due_soon` & `internal_request_decided`
    sebelum FASE N. Lihat `services/notification_audience.py` untuk alasan lengkap.

    `ref` diberi akhiran `#<user_id>` supaya **dedupe berjalan per orang**: kalau job
    yang sama jalan dua kali, tiap orang tetap punya satu pesan (bukan "orang pertama
    dapat, sisanya hilang karena ref-nya sudah terpakai").

    Return: daftar notifikasi yang BENAR-BENAR dibuat (yang ter-dedupe tidak masuk).
    Daftar KOSONG berarti tidak ada penerima berwenang — pemanggil yang memutuskan
    apakah itu wajar. Sengaja TIDAK ada jalan mundur ke `recipient_role="all"`.
    """
    from services import notification_audience as aud

    people = await aud.resolve_recipients(
        permission=permission, division=division, roles=roles,
        entity_id=kw.get("entity_id"), also_users=also_users)
    base_ref = str(kw.pop("ref", "") or "")
    out: List[Dict[str, Any]] = []
    for person in people:
        uid = str(person.get("id") or "")
        if not uid:
            continue
        note = await create_notification(
            **{**kw, "recipient_role": "", "recipient_user": uid,
               "ref": f"{base_ref}#{uid}" if base_ref else ""})
        if note:
            out.append(note)
    return out


async def create_notification(
    *, notif_type: str, title: str, body: str, severity: str = "info",
    link: str = "", entity_id: Optional[str] = None, recipient_role: str = "all",
    recipient_user: Optional[str] = None, ref: str = "", dedupe: bool = True,
    dedupe_scope: str = "unread",
    action_type: str = "", action_id: str = "", action_role: str = "",
) -> Optional[Dict[str, Any]]:
    """Buat 1 notifikasi. Return None bila di-dedupe.

    `dedupe_scope`:
    - `"unread"` (default, perilaku lama) → dilewati bila masih ada notifikasi
      SAMA yang BELUM dibaca.
    - `"day"` (R6.5, dipakai job scheduler) → dilewati bila notifikasi sama sudah
      pernah dibuat HARI INI (dibaca atau belum) → job boleh dijalankan berkali-kali
      dalam sehari tanpa menduplikasi.
    - `"ever"` (A2 · 2026-08-25) → dilewati bila notifikasi sama PERNAH dibuat, dibaca
      atau belum. Dipakai job yang hanya **MELAHIRKAN** pemberitahuan sekali untuk
      dokumen yang belum pernah punya penerima; PENAGIHAN BERULANG-nya milik satu
      mesin lain (`services/approval_reminder.py`). Tanpa `"ever"`, `"unread"` akan
      menagih lagi begitu pesannya dibaca — dan dua mesin kembali menagih dokumen
      yang sama tiap hari (kotak yang isinya berulang berhenti dibaca orang).

    `action_type`/`action_id`/`action_role` → aksi inline (mis. approve PO langsung
    dari kartu notifikasi). `action_role` = role minimum yang boleh aksi.
    """
    day = now_iso()[:10]
    dedupe_key = f"{notif_type}:{ref}:{day}" if ref else ""
    if dedupe and ref:
        if dedupe_scope == "day":
            if await db.notifications.find_one({"dedupe_key": dedupe_key}, {"_id": 1}):
                return None
        elif dedupe_scope == "ever":
            if await db.notifications.find_one({"type": notif_type, "ref": ref},
                                               {"_id": 1}):
                return None
        elif await _has_unread(notif_type, ref):
            return None
    doc = {
        "id": new_id("ntf"), "entity_id": entity_id,
        "recipient_role": recipient_role, "recipient_user": recipient_user,
        "type": notif_type, "title": title, "body": body, "link": link,
        "severity": severity, "ref": ref, "dedupe_key": dedupe_key,
        "read": False, "created_at": now_iso(),
        "action_type": action_type, "action_id": action_id, "action_role": action_role,
    }
    await db.notifications.insert_one(doc)
    clean = safe_doc(doc)
    # R6.5 — kanal WhatsApp (best-effort; TIDAK pernah menggagalkan pembuatan notifikasi).
    try:
        from services import wa_alert_service
        await wa_alert_service.push_notification(clean)
    except Exception:  # noqa: BLE001
        pass
    return clean


async def resolve_action(action_type: str, action_id: str, *, outcome: str = "",
                         actor: str = "") -> int:
    """Tutup notifikasi AKSI yang permintaannya sudah diputus.

    MASALAH YANG DISELESAIKAN: notifikasi "menunggu persetujuan" tetap menyala di
    lonceng walaupun dokumennya sudah disetujui/ditolak. Penerima mengklik tombol
    aksi yang PASTI gagal — bentuk lain dari tombol palsu, dan membuat pengguna
    tidak lagi percaya pada lonceng.

    Notifikasi TIDAK dihapus (jejak audit tetap utuh): ditandai `read` + diberi
    `resolved_at`/`resolution` sehingga aksi inline hilang tetapi riwayat tetap
    bisa dibaca. Aman dipanggil berkali-kali (idempotent) dan tidak pernah
    menggagalkan alur pemanggilnya.
    """
    if not action_type or not action_id:
        return 0
    try:
        res = await db.notifications.update_many(
            {"action_type": action_type, "action_id": action_id,
             "resolved_at": {"$exists": False}},
            {"$set": {"read": True, "read_at": now_iso(), "resolved_at": now_iso(),
                      "resolution": (outcome or "selesai")[:120], "resolved_by": actor}},
        )
        return int(res.modified_count or 0)
    except Exception:  # noqa: BLE001
        return 0


async def notify_po_awaiting_approval(po: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Depth #3 — notifikasi ke role approver saat PO masuk waiting_approval.

    Ditujukan ke `required_approval_role` (mis. manager). Dedupe via ref po_appr:<id>.
    Menyertakan alasan deviasi harga bila ada + aksi approve inline.
    """
    role = po.get("required_approval_role") or "manager"
    dev = po.get("price_deviation") or {}
    extra = ""
    if dev.get("flagged"):
        extra = f" Harga di atas price-list (+{dev.get('max_deviation_pct')}%)."
    return await create_notification(
        notif_type="po_approval", ref=f"po_appr:{po.get('id', '')}",
        title=f"PO menunggu persetujuan: {po.get('po_number', '')}",
        body=(f"{po.get('supplier_name', '')} · {rupiah(float(po.get('total_amount', 0)))}.{extra} "
              f"Perlu persetujuan {role}."),
        severity="warning" if dev.get("flagged") else "info",
        link="purchase-approval", entity_id=po.get("entity_id"), recipient_role=role,
        action_type="po_approve", action_id=po.get("id", ""), action_role=role,
    )


async def generate_system_notifications() -> int:
    """Pindai kondisi nyata sistem & buat notifikasi. Return jumlah yang dibuat.

    FASE N — alamat tiap peristiwa diturunkan dari WEWENANG, bukan disiarkan ke
    `recipient_role="all"`. Terukur sebelum fase ini: 9 dari 11 notifikasi ber-alamat
    "all" berasal dari fungsi ini (semuanya `low_stock`), sehingga Finance & Sales
    membuka kotaknya dan menemukan sembilan pesan stok kain. Lihat
    `services/notification_audience.py` untuk alasan lengkap.
    """
    from services.config_resolver import value_of

    created = 0

    # 1) Stok menipis — ambang batas per produk (`reorder_point`, konfigurasi NYATA
    #    di master produk); fallback ke ambang default bila produk belum diatur.
    #    ALAMAT (FASE N): pemegang `purchase_order.create` — karena pertanyaannya
    #    "siapa yang bisa BERTINDAK atas pesan ini?" — plus divisi tambahan bila
    #    pemilik mengisinya (`notif.low_stock_division`, bawaan kosong).
    division = str(await value_of("notif.low_stock_division", {"entity_id": ""}) or "").strip()
    products = await db.products.find({"status": "active"}, {"_id": 0}).to_list(300)
    for product in products:
        summary = await product_summary(product["id"])
        threshold = float(product.get("reorder_point") or 0) or LOW_STOCK_THRESHOLD
        if summary["available_qty"] < threshold:
            notes = await create_addressed(
                permission=("purchase_order", "create"), division=division,
                notif_type="low_stock", ref=f"low_stock:{product['id']}",
                title=f"Stok menipis: {product['name']}",
                body=(f"Available {summary['available_qty']:.0f} "
                      f"{product.get('base_unit', 'meter')} (< ambang {threshold:.0f}). "
                      f"Pertimbangkan buat PO ulang."),
                severity="warning", link="reorder", entity_id=product.get("entity_id"),
                dedupe_scope="day",
            )
            created += len(notes)

    # 2) Reservasi mendekati kedaluwarsa (<= 24 jam) dari sales_orders
    #    ALAMAT: yang boleh MENGONFIRMASI pesanan (`order.confirm`) + sales pemegang
    #    akunnya. Dulu "all" — padahal gudang & finance tak bisa berbuat apa pun.
    soon = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    orders = await db.sales_orders.find(
        {"status": {"$in": ["reserved", "waiting_approval", "approved"]},
         "reservation_expires_at": {"$lte": soon}}, {"_id": 0}
    ).to_list(200)
    for order in orders:
        notes = await create_addressed(
            permission=("order", "confirm"),
            also_users=(order.get("assigned_sales_id") or "",),
            notif_type="reservation_expiring", ref=f"resv:{order['id']}",
            title=f"Reservasi akan kedaluwarsa: {order.get('number', '')}",
            body=(f"Order {order.get('number', '')} ({order.get('customer_name', '')}) "
                  f"reservasinya mendekati batas 3 hari. Segera approve/konfirmasi."),
            severity="warning", link="orders", entity_id=order.get("entity_id"),
        )
        created += len(notes)

    # 3) Order menunggu persetujuan (actionable, dari sales_orders)
    #    ALAMAT: pemegang `order.approve` — orang yang tombolnya memang ada.
    pending = await db.sales_orders.find({"status": "waiting_approval"}, {"_id": 0}).to_list(200)
    for order in pending:
        notes = await create_addressed(
            permission=("order", "approve"),
            notif_type="order_approval", ref=f"appr:{order['id']}",
            title=f"Order menunggu persetujuan: {order.get('number', '')}",
            body=(f"{order.get('customer_name', '')} · {rupiah(float(order.get('total_amount', 0)))}. "
                  f"Memerlukan persetujuan manajer."),
            severity="info", link="orders", entity_id=order.get("entity_id"),
        )
        created += len(notes)

    # 4) Order split antar gudang (informasi fulfillment)
    #    ALAMAT: yang mengerjakan barangnya — pemegang `wms.dispatch`.
    splits = await db.sales_orders.find(
        {"is_split_warehouse": True, "status": {"$nin": ["cancelled", "expired", "done"]}}, {"_id": 0}
    ).to_list(200)
    for order in splits:
        notes = await create_addressed(
            permission=("wms", "dispatch"),
            notif_type="order_split", ref=f"split:{order['id']}",
            title=f"Order split antar gudang: {order.get('number', '')}",
            body=(f"Order {order.get('number', '')} dipenuhi dari beberapa gudang. "
                  f"Koordinasikan pengiriman gabungan."),
            severity="info", link="operations", entity_id=order.get("entity_id"),
        )
        created += len(notes)

    # 5) PO menunggu persetujuan (Depth #3 — approver notification, deduped)
    pending_po = await db.purchase_orders.find(
        {"status": "waiting_approval"}, {"_id": 0}).to_list(200)
    for po in pending_po:
        note = await notify_po_awaiting_approval(po)
        if note:
            created += 1

    # 6) FASE N — TAHAP PO MACET. Papan PO per Lini (FASE P) sudah menampilkan progres
    #    tahap, tetapi tidak ada yang MEMBERI TAHU ketika satu tahap berhenti bergerak;
    #    selama ini kemacetan hanya terlihat oleh orang yang kebetulan membuka papannya.
    #    Ambang hari datang dari config (`notif.po_stage_stuck_days`), bukan angka di kode.
    created += await _notify_stuck_po_stages()

    # 7) FASE N — PO CUSTOM MENUNGGU KEPUTUSAN (`special_orders`).
    #    Endpoint pembuatannya sudah memberi tahu (routers/special_orders.py), tetapi
    #    itu hanya berlaku untuk dokumen yang lahir SESUDAH FASE N. Dokumen yang sudah
    #    menunggu sebelum itu — termasuk seluruh data demo (terukur: 3 dokumen, 0
    #    notifikasi) — tidak akan pernah punya penerima, dan justru dokumen inilah yang
    #    paling mahal bila terlambat (kain dipesan khusus, tak bisa dijual ke orang lain).
    #    Job ini menutupnya dari sisi KEADAAN (bukan kejadian): apa pun asal dokumennya,
    #    selama statusnya masih menunggu keputusan, pemegang wewenangnya diberi tahu.
    created += await _notify_pending_special_orders()

    return created


#: Jenis notifikasi "PO custom menunggu keputusan". Hanya SATU fungsi di seluruh
#: backend yang boleh menyusunnya (dijaga INV-NOTIF-02 aturan K3).
SPECIAL_ORDER_WAITING_TYPE = "special_order_approval"


def _rupiah_aman(value: Any) -> str:
    """`rupiah()` yang tidak bisa menjatuhkan job/endpoint pemanggilnya.

    B4 (2026-08-25): `total_amount` bisa berupa TEKS di dokumen lama/hasil impor
    (mis. `"43.500.000"`). `float()` mentah melempar `ValueError` → job notifikasi
    berhenti di tengah jalan dan sisa dokumennya tak pernah diberitahukan.
    """
    try:
        return rupiah(float(value))
    except (TypeError, ValueError):
        return rupiah(0.0)


async def notify_special_order_waiting(
    so: Dict[str, Any], *, actor_name: str = "",
    dedupe_scope: str = "ever",
) -> List[Dict[str, Any]]:
    """SATU-SATUNYA penyusun pesan "PO custom menunggu keputusan".

    A1 DIBAYAR (2026-08-25): judul/isi/tautan/keparahan dulu diketik di DUA tempat —
    `routers/special_orders.py` (saat dokumen LAHIR) dan `_notify_pending_special_orders`
    (job, saat KEADAAN masih menunggu) — dan keduanya sudah tidak identik (versi
    endpoint menyebut "Diajukan oleh …", versi job tidak). Kelas cacat "dua layar
    bicara beda" yang persis sama dengan `approval_requests` dulu. Sekarang pesannya
    lahir di sini saja; pemanggil hanya memberi dokumen + siapa yang mengajukan.

    Alamatnya BUKAN "manager" yang diketik: peran yang memang diminta rantai
    persetujuan dokumen (`required_approval_role`, bisa Direksi untuk nilai besar) +
    pemegang `order.approve`, supaya tak pernah ada dokumen menunggu tanpa penerima.

    A2 — `dedupe_scope` bawaannya `"ever"`: fungsi ini hanya **MELAHIRKAN** pesan
    SEKALI untuk satu dokumen (dibaca atau belum, ia tidak menagih lagi). PENAGIHAN
    BERULANG harian adalah milik `services/approval_reminder.py` — SATU pemilik
    pengingat. Sebelum ini job memakai `dedupe_scope="day"`, sehingga satu PO custum
    yang menggantung menghasilkan DUA pesan tiap hari dari dua mesin berbeda
    (`special_order_approval` + `approval_backlog`) yang menyebut dokumen yang sama.
    """
    need_role = str(so.get("required_approval_role") or "")
    diajukan = f" Diajukan oleh {actor_name}." if actor_name else ""
    return await create_addressed(
        permission=("order", "approve"),
        roles=((need_role,) if need_role else ()),
        notif_type=SPECIAL_ORDER_WAITING_TYPE,
        ref=f"so_custom_appr:{so.get('id', '')}",
        title=f"PO custom menunggu persetujuan: {so.get('number', '')}",
        body=(f"{so.get('customer_name', '')} · "
              f"{_rupiah_aman(so.get('total_amount'))}.{diajukan} Perlu persetujuan "
              f"{need_role or 'manajer'}."),
        severity="warning", link="special-orders",
        entity_id=so.get("entity_id"), dedupe_scope=dedupe_scope,
    )


async def _notify_pending_special_orders() -> int:
    """Lahirkan pemberitahuan untuk PO custom menunggu yang BELUM punya penerima.

    Dokumen yang sudah menunggu sebelum FASE N — termasuk seluruh data demo — tidak
    akan pernah punya penerima kalau hanya endpoint pembuatannya yang memberi tahu.
    Job ini menutupnya dari sisi KEADAAN. Pesannya disusun `notify_special_order_waiting`
    (satu penyusun) dengan `dedupe_scope="ever"`: sekali lahir, tidak menagih lagi —
    penagihan berulang tetap milik `approval_reminder` (A2 di HANDOFF audit).
    """
    created = 0
    rows = await db.special_orders.find(
        {"status": "pending_approval"},
        {"_id": 0, "id": 1, "number": 1, "entity_id": 1, "customer_name": 1,
         "total_amount": 1, "required_approval_role": 1},
    ).to_list(200)
    for so in rows:
        created += len(await notify_special_order_waiting(so))
    return created


async def _notify_stuck_po_stages() -> int:
    """Beri tahu pemegang wewenang PO bila satu tahap proses berhenti bergerak.

    Ambang: `notif.po_stage_stuck_days` (bawaan 7 hari).

    BENTUK DATA — DIUKUR, bukan ditebak (2026-08-24). Versi pertama fungsi ini membaca
    `started_at` / `done_at` / `label`, dan **ketiganya tidak ada**. Baris
    `stage_progress` yang nyata berisi `stage_code` · `status` · `at` · `note` · `by`
    (3 PO memakainya di data demo). Kalau salah baca, fungsinya tidak error — ia hanya
    **diam selamanya**, kelas cacat termahal di repo ini (bandingkan SPK hasil makloon
    yang lahir nol baris karena `mko_number` dicari sebagai `number`). Nama tahap yang
    dibaca manusia diambil dari MASTER `process_stages`, bukan kode teknisnya.
    """
    from services.config_resolver import value_of

    created = 0
    try:
        limit_days = int(float(await value_of("notif.po_stage_stuck_days", {"entity_id": ""}) or 7))
    except (TypeError, ValueError):
        limit_days = 7
    limit_days = max(1, limit_days)
    batas = (datetime.now(timezone.utc) - timedelta(days=limit_days)).isoformat()

    stages = await db.process_stages.find({}, {"_id": 0, "code": 1, "name": 1}).to_list(200)
    label_of = {str(s.get("code")): str(s.get("name") or s.get("code")) for s in stages}

    rows = await db.purchase_orders.find(
        {"stage_progress": {"$exists": True, "$ne": []}},
        {"_id": 0, "id": 1, "po_number": 1, "entity_id": 1, "supplier_name": 1,
         "stage_progress": 1},
    ).to_list(500)
    for po in rows:
        for st in (po.get("stage_progress") or []):
            if str(st.get("status") or "") != "in_progress":
                continue
            sejak = str(st.get("at") or "")
            if not sejak or sejak > batas:
                continue
            code = str(st.get("stage_code") or "")
            stage_label = label_of.get(code, code or "tahap")
            notes = await create_addressed(
                permission=("purchase_order", "create"),
                notif_type="po_stage_stuck",
                ref=f"po_stuck:{po['id']}:{code}",
                title=f"Tahap PO macet: {po.get('po_number', '')} · {stage_label}",
                body=(f"Tahap '{stage_label}' pada {po.get('po_number', '')} "
                      f"({po.get('supplier_name', '')}) berjalan sejak {sejak[:10]} dan "
                      f"belum selesai — lebih dari {limit_days} hari. "
                      f"Periksa Papan PO per Lini."),
                severity="warning", link="purchase-orders", entity_id=po.get("entity_id"),
                dedupe_scope="day",
            )
            created += len(notes)
    return created
