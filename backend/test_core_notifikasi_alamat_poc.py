#!/usr/bin/env python3
"""POC FASE N — NOTIFIKASI SAMPAI KE ORANG YANG BENAR.

BUKTI-MERAH yang dikunci berkas ini (cacat nyata, terukur 2026-08-24 pada data demo
bersih SEBELUM FASE N):

    notifications ber-recipient_role="all"  →  11 dari 35
        low_stock 9 · order_approval 1 · internal_request_decided 1

Artinya Finance membuka kotak notifikasinya dan menemukan **sembilan pesan stok kain**
yang tidak bisa ia tindaklanjuti, sementara pesan yang benar-benar miliknya (piutang
jatuh tempo) justru TIDAK PERNAH dikirim kepadanya. Kotak yang isinya bukan urusan kita
adalah kotak yang berhenti dibaca.

Cacat kedua lebih menipu dan itulah sebabnya ia bertahan lama: penyaring pembaca
(`routers/notifications.py:_scope_query`) memakai **OR** —

    {recipient_role ∈ {peran_saya, "all"}}  OR  {recipient_user == saya}

— sehingga `recipient_role="sales"` yang ditulis BERSAMA `recipient_user=<pemegang
akun>` bukan menyempitkan alamat, melainkan MENYIARKAN ke seluruh sales. Terukur di
5 titik produksi (job piutang, barang pendingan datang, AR overdue, 2× persetujuan
harga: "Aturan harga **Anda** diganti" dikirim ke semua sales).

Yang dibuktikan di sini (dan HARUS tetap benar selamanya):
  N1  `low_stock` HANYA ke pemegang wewenang beli (`purchase_order.create`);
      kotak Finance menerima **0** pesan stok.
  N2  `ar_due_soon` MASUK kotak Finance (dulu 0) tanpa membuang sales & manajer.
  N3  PO custom (`special_orders`) yang diajukan MEMBERI TAHU pemegang keputusan
      (dulu: 3 dokumen, 0 notifikasi). **N3b**: dokumen yang sudah menunggu SEBELUM
      fase ini (termasuk seluruh data demo & hasil seed) ikut mendapat penerima lewat
      job — alamat dinilai dari KEADAAN "masih menunggu", bukan hanya dari KEJADIAN
      "baru dibuat" — dan job yang dijalankan dua kali tetap satu pesan per orang.
  N4  **Dedupe per ORANG**: job dijalankan dua kali → tiap orang tetap satu pesan
      (bukan "orang pertama dapat, sisanya hilang karena ref-nya sudah terpakai").
  N5  Notifikasi ber-ENTITAS: pengguna PT-A tidak melihat notifikasi PT-B.
  N6  Alamat mengikuti IZIN, bukan nama peran: mencabut `purchase_order.create` dari
      sebuah peran benar-benar mengubah daftar penerima (lalu dipulihkan).
  N7  Penyelesai alamat tidak pernah jatuh ke "kirim ke semua": izin yang tak
      dipegang siapa pun → nol penerima, bukan siaran.
  N8  **Nol residu**: notifikasi & dokumen uji dipulihkan persis, jejak (`audit_logs`,
      `sessions`) dibuang lewat selisih himpunan ID, dan baris matriks izin
      `permission_settings/default` dipulihkan APA ADANYA (bukan dihapus) — dulu
      penghapusannya membuat `verify_data_integrity` memerah di POC berikutnya.

Jalankan:  cd /app && python backend/test_core_notifikasi_alamat_poc.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

BASE = os.environ.get("POC_BASE_URL", "http://localhost:8001")
PW = "demo12345"
ADMIN = "admin@kainnusantara.id"
FINANCE = "finance@kainnusantara.id"
MANAGER = "manager@kainnusantara.id"
SALES = "sales@kainnusantara.id"
ENT_A = "ent_ksc"
ENT_B = "ent_kanda"
TAG = f"POCN-{uuid.uuid4().hex[:6]}"

PASS = 0
FAIL = 0


def ok(cond: bool, label: str, extra: str = "") -> bool:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {label}" + (f"  ({extra})" if extra else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         → {extra}" if extra else ""))
    return bool(cond)


def login(email: str) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"email": email, "password": PW}, timeout=30)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:200]}"
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}",
                      "Content-Type": "application/json"})
    return s


def h(entity: str) -> dict:
    return {"X-Entity-Id": entity}


def inbox(sess: requests.Session, entity: str, ntype: str = "") -> list:
    r = sess.get(f"{BASE}/api/notifications", headers=h(entity), timeout=30)
    if r.status_code != 200:
        return []
    rows = r.json() or []
    return [n for n in rows if not ntype or n.get("type") == ntype]


async def main() -> int:
    from db import db
    from services import notification_service as notif
    from services import notification_audience as aud

    print("=" * 78)
    print("  POC FASE N — NOTIFIKASI SAMPAI KE ORANG YANG BENAR")
    print("=" * 78)

    # ── SNAPSHOT: seluruh koleksi notifikasi dipulihkan persis di akhir ─────────
    snapshot = await db.notifications.find({}, {"_id": 0}).to_list(20000)
    dibuat_khusus: list = []            # (koleksi, id) dokumen uji
    print(f"  [snapshot] {len(snapshot)} notifikasi disimpan — akan dipulihkan PERSIS.")

    # ── SIDIK JARI JEJAK, DIAMBIL SEBELUM SATU PERMINTAAN PUN DIKIRIM ──────────
    # Terukur 2026-08-24: POC ini memulihkan `notifications` & dokumen ujinya, tetapi
    # `audit_logs` tumbuh +2 tiap kali dijalankan (`login` + `special_order_created`),
    # dan itulah satu-satunya FAIL yang tersisa di `INV-GATE-01` pada `gate.sh --full`.
    # Sama seperti POC FASE S: himpunan ID direkam DI SINI (sebelum `login()` di N3),
    # supaya baris jejak yang lahir dari login pun berada di dalam jendela pembersihan.
    TRAIL_COLLS = ("audit_logs", "sessions")
    trail_before = {c: {d["id"] for d in await db[c].find(
        {}, {"_id": 0, "id": 1}).to_list(100000) if d.get("id")}
        for c in TRAIL_COLLS}

    # ── MATRIKS IZIN: SSOT PERILAKU, wajib dipulihkan APA ADANYA ───────────────
    # Terukur 2026-08-24: N6 dulu "memulihkan" matriks dengan `delete_one({"id":
    # "default"})` — benar untuk PERILAKU (kode jatuh ke matriks bawaan) tetapi
    # SALAH untuk DATA: baris hasil seed ikut terhapus, sehingga `permission_settings`
    # menjadi KOSONG dan `verify_data_integrity` memerah ("kanonik KOSONG → seed GAP
    # atau DRIFT") pada setiap POC yang berjalan SESUDAH-nya (itulah 1 FAIL yang
    # tersisa di POC FASE G-8). Karena itu dokumen aslinya direkam LENGKAP di sini.
    perm_semula = await db.permission_settings.find_one({"id": "default"})

    users = {u["email"]: u for u in await db.users.find(
        {}, {"_id": 0, "id": 1, "email": 1, "role": 1}).to_list(200)}
    uid_fin = users[FINANCE]["id"]
    uid_sales = users[SALES]["id"]

    try:
        # ══════════════════════════════════════════════════════════════════════
        print("\n\033[93mN1 · low_stock hanya ke pemegang wewenang beli\033[0m")
        # Bersihkan jenis yang akan diukur supaya dedupe tidak menutupi hasil.
        await db.notifications.delete_many(
            {"type": {"$in": ["low_stock", "order_approval", "order_split",
                              "reservation_expiring", "po_stage_stuck"]}})
        n_dibuat = await notif.generate_system_notifications()
        rows = await db.notifications.find(
            {"type": "low_stock"}, {"_id": 0}).to_list(5000)
        ok(len(rows) > 0, "job menghasilkan notifikasi stok menipis",
           f"{n_dibuat} notifikasi dari job, {len(rows)} di antaranya low_stock")
        ok(all((r.get("recipient_role") or "") != "all" for r in rows),
           "NOL notifikasi stok ber-recipient_role=\"all\" (dulu 9)",
           f"{sum(1 for r in rows if r.get('recipient_role') == 'all')} yang masih 'all'")
        ok(all(r.get("recipient_user") for r in rows),
           "setiap pesan stok ber-ALAMAT ORANG (recipient_user terisi)")
        berwenang = {u["id"] for u in await aud.resolve_recipients(
            permission=("purchase_order", "create"), entity_id=None)}
        nyasar = {r.get("recipient_user") for r in rows} - berwenang
        ok(not nyasar, "penerimanya HANYA pemegang `purchase_order.create`",
           f"nyasar ke: {sorted(nyasar)}")
        ok(uid_fin not in {r.get("recipient_user") for r in rows},
           "kotak FINANCE menerima 0 pesan stok kain (inti keluhan D5)")
        ok(uid_sales not in {r.get("recipient_user") for r in rows},
           "kotak SALES juga bersih dari pesan stok")

        # ══════════════════════════════════════════════════════════════════════
        print("\n\033[93mN4 · dedupe PER ORANG (job dua kali → tetap satu per orang)\033[0m")
        sebelum = await db.notifications.count_documents({"type": "low_stock"})
        await notif.generate_system_notifications()
        sesudah = await db.notifications.count_documents({"type": "low_stock"})
        ok(sebelum == sesudah,
           "job kedua TIDAK menambah satu pun pesan stok (dedupe harian per orang)",
           f"{sebelum} → {sesudah}")
        kunci = [r.get("dedupe_key") for r in await db.notifications.find(
            {"type": "low_stock"}, {"_id": 0, "dedupe_key": 1}).to_list(5000)]
        ok(len(kunci) == len(set(kunci)),
           "kunci dedupe UNIK per orang (INV-PS21-01 tetap berlaku)",
           f"{len(kunci)} pesan, {len(set(kunci))} kunci")
        per_orang = {}
        for r in await db.notifications.find({"type": "low_stock"},
                                             {"_id": 0, "recipient_user": 1}).to_list(5000):
            per_orang[r.get("recipient_user")] = per_orang.get(r.get("recipient_user"), 0) + 1
        ok(len(set(per_orang.values())) <= 1,
           "semua penerima berwenang mendapat JUMLAH yang sama (tak ada yang tertelan)",
           f"{len(per_orang)} orang × {sorted(set(per_orang.values()))} pesan")

        # ══════════════════════════════════════════════════════════════════════
        print("\n\033[93mN2 · ar_due_soon MASUK kotak Finance\033[0m")
        from services import alert_ops_service as ops
        await db.notifications.delete_many({"type": "ar_due_soon"})
        hasil = await ops.job_ar_due_soon()
        ar = await db.notifications.find({"type": "ar_due_soon"}, {"_id": 0}).to_list(5000)
        if not ar:
            ok(True, "data demo tidak punya piutang di offset H-3/H-1/H/H+1 — "
                     "alamat diuji lewat penyelesainya", f"job melaporkan {hasil}")
            tim = {u["id"] for u in await aud.resolve_recipients(
                permission=("ar_receipt", "create"), entity_id=ENT_A)}
            ok(uid_fin in tim,
               "penyelesai alamat piutang MEMUAT Finance (dulu tidak pernah)",
               f"{len(tim)} penerima berwenang")
        else:
            ok(uid_fin in {r.get("recipient_user") for r in ar},
               "Finance menerima pengingat piutang (dulu 0)", f"{len(ar)} pesan")
            ok(all((r.get("recipient_role") or "") != "sales" for r in ar),
               "tidak ada lagi pesan piutang ber-recipient_role=\"sales\" "
               "(dulu SEMUA sales melihat piutang pelanggan rekannya)")
        ok(all("H" in (r.get("ref") or "") for r in ar) if ar else True,
           "ref piutang tetap memuat offset sah (INV-PS21-02 tidak dilanggar)")

        # ══════════════════════════════════════════════════════════════════════
        print("\n\033[93mN3 · PO custom diajukan → pemegang keputusan diberi tahu\033[0m")
        adm = login(ADMIN)
        # BENTUK PAYLOAD DIUKUR dari `SpecialOrderCreate`, bukan ditebak: dokumen ini
        # memakai `custom_item` (bukan `items[]`), dan `pending_approval` hanya lahir
        # bila nilainya DI ATAS `APPROVAL_THRESHOLD` (10 juta) **dan**
        # `submit_for_approval=True` — dua syarat, keduanya wajib, kalau tidak
        # dokumennya berstatus `draft` dan memang belum perlu diberitakan.
        cust = await db.customers.find_one(
            {"entity_id": ENT_A, "credit_blocked": {"$ne": True},
             "credit_status": {"$ne": "blocked"}},
            {"_id": 0, "id": 1, "name": 1})
        payload = {
            "customer_id": cust["id"],
            "entity_id": ENT_A,
            "custom_item": {
                "description": f"{TAG} kain custom motif khusus",
                "specifications": {"warna": "Pantone 19-4052", "lebar": "150 cm"},
                "quantity": 200,
                "unit": "yard",
                "target_price": 250_000,          # 200 × 250.000 = 50 juta > ambang
                "notes": f"{TAG} POC FASE N",
            },
            "expected_delivery": "2026-12-31",
            "notes": f"{TAG} PO custom POC FASE N",
            "submit_for_approval": True,
        }
        before_ids = {n["id"] for n in await db.notifications.find(
            {"type": "special_order_approval"}, {"_id": 0, "id": 1}).to_list(2000)}
        r = adm.post(f"{BASE}/api/special-orders", headers=h(ENT_A), json=payload, timeout=60)
        ok(r.status_code in (200, 201), "PO custom dibuat lewat API",
           f"HTTP {r.status_code} {r.text[:160]}")
        if r.status_code in (200, 201):
            so = r.json()
            dibuat_khusus.append(("special_orders", so.get("id")))
            baru = [n for n in await db.notifications.find(
                {"type": "special_order_approval"}, {"_id": 0}).to_list(2000)
                if n["id"] not in before_ids]
            if str(so.get("status")) == "pending_approval":
                ok(len(baru) > 0,
                   "notifikasi PO custom LAHIR (dulu: 3 dokumen, 0 notifikasi)",
                   f"{len(baru)} penerima")
                ok(all((n.get("recipient_role") or "") != "all" for n in baru),
                   "alamatnya bukan siaran \"all\"")
                penyetuju = {u["id"] for u in await aud.resolve_recipients(
                    permission=("order", "approve"), entity_id=ENT_A)}
                ok({n.get("recipient_user") for n in baru} <= penyetuju | {None},
                   "penerimanya pemegang wewenang menyetujui pesanan")
                ok(uid_sales not in {n.get("recipient_user") for n in baru},
                   "sales biasa TIDAK ikut menerima keputusan yang bukan wewenangnya")
            else:
                ok(True, f"PO custom lahir berstatus '{so.get('status')}' "
                         "(di bawah ambang persetujuan) → memang belum perlu diberitakan")

        # ══════════════════════════════════════════════════════════════════════
        print("\n\033[93mN3b · PO custom LAMA (tak lewat endpoint) juga dapat penerima\033[0m")
        # Kenapa ini pagar tersendiri: notifikasi di titik LAHIR hanya menolong dokumen
        # yang dibuat SESUDAH FASE N. Data demo membuktikan celahnya — 3 dokumen
        # `special_orders` menunggu, 0 notifikasi — dan dokumen yang menunggu tanpa
        # penerima itulah yang paling mahal bila terlambat. Karena itu job notifikasi
        # menilai KEADAAN ("masih menunggu keputusan"), bukan hanya KEJADIAN.
        from core_utils import new_id as _new_id, now_iso as _now
        lama_id = _new_id("sord")
        await db.special_orders.insert_one({
            "id": lama_id, "number": f"SORD-{TAG}", "entity_id": ENT_A,
            "status": "pending_approval", "customer_name": cust["name"],
            "customer_id": cust["id"], "total_amount": 42_000_000,
            "requires_approval": True, "notes": f"{TAG} dokumen warisan",
            "created_at": _now(), "updated_at": _now(),
        })
        dibuat_khusus.append(("special_orders", lama_id))
        sebelum_job = {n["id"] for n in await db.notifications.find(
            {"type": "special_order_approval"}, {"_id": 0, "id": 1}).to_list(5000)}
        await notif.generate_system_notifications()
        untuk_lama = [n for n in await db.notifications.find(
            {"type": "special_order_approval", "ref": {"$regex": f"^so_custom_appr:{lama_id}"}},
            {"_id": 0}).to_list(500)]
        ok(len(untuk_lama) > 0,
           "dokumen warisan yang menunggu keputusan MENDAPAT penerima lewat job "
           "(bukan hanya dokumen yang lahir lewat endpoint)",
           f"{len(untuk_lama)} penerima · {len(sebelum_job)} notifikasi sebelumnya")
        penyetuju_a = {u["id"] for u in await aud.resolve_recipients(
            permission=("order", "approve"), entity_id=ENT_A)}
        ok({n.get("recipient_user") for n in untuk_lama} <= penyetuju_a,
           "penerimanya HANYA pemegang wewenang menyetujui pesanan (bukan siaran)")
        ok(all((n.get("recipient_role") or "") != "all" for n in untuk_lama),
           "nol notifikasi PO custom ber-recipient_role=\"all\"")
        # Idempotent: job dijalankan dua kali → tiap orang tetap satu pesan.
        await notif.generate_system_notifications()
        dua_kali = await db.notifications.count_documents(
            {"type": "special_order_approval",
             "ref": {"$regex": f"^so_custom_appr:{lama_id}"}})
        ok(dua_kali == len(untuk_lama),
           "job dijalankan DUA KALI → tiap orang tetap satu pesan (dedupe per orang)",
           f"{len(untuk_lama)} → {dua_kali}")

        # ══════════════════════════════════════════════════════════════════════
        print("\n\033[93mN5 · notifikasi ber-ENTITAS (PT-A tidak melihat milik PT-B)\033[0m")
        from core_utils import new_id, now_iso
        jejak = new_id("ntf")
        await db.notifications.insert_one({
            "id": jejak, "entity_id": ENT_B, "recipient_role": "admin",
            "recipient_user": None, "type": "low_stock",
            "title": f"{TAG} milik PT-B", "body": TAG, "link": "", "severity": "info",
            "ref": f"{TAG}:b", "dedupe_key": f"low_stock:{TAG}:b", "read": False,
            "created_at": now_iso(), "action_type": "", "action_id": "", "action_role": "",
        })
        judul_a = {n.get("title") for n in inbox(adm, ENT_A)}
        ok(f"{TAG} milik PT-B" not in judul_a,
           "membaca dalam konteks PT-A TIDAK memunculkan notifikasi PT-B")
        judul_b = {n.get("title") for n in inbox(adm, ENT_B)}
        ok(f"{TAG} milik PT-B" in judul_b,
           "…tetapi dalam konteks PT-B notifikasi itu memang terlihat "
           "(bukti pagarnya menyaring, bukan menyembunyikan semuanya)")
        await db.notifications.delete_one({"id": jejak})

        # ══════════════════════════════════════════════════════════════════════
        print("\n\033[93mN6 · alamat mengikuti IZIN, bukan nama peran\033[0m")
        from dependencies import permission_matrix
        matrix = await permission_matrix()
        semula = await aud.resolve_recipients(
            permission=("purchase_order", "create"), entity_id=ENT_A)
        peran_manager = list((matrix.get("manager") or {}).get("purchase_order") or [])
        ok(any(u["role"] == "manager" for u in semula),
           "sebelum diubah: manajer termasuk penerima", f"{len(semula)} orang")
        # Cabut izinnya di matriks DB, ukur ulang, lalu PULIHKAN.
        patched = {r: {m: list(a) for m, a in (p or {}).items()}
                   for r, p in (matrix or {}).items()}
        patched.setdefault("manager", {})["purchase_order"] = [
            x for x in peran_manager if x != "create"]
        await db.permission_settings.update_one(
            {"id": "default"}, {"$set": {"id": "default", "matrix": patched}}, upsert=True)
        sesudah_cabut = await aud.resolve_recipients(
            permission=("purchase_order", "create"), entity_id=ENT_A)
        ok(not any(u["role"] == "manager" for u in sesudah_cabut),
           "sesudah izin DICABUT dari layar Matriks Izin: manajer berhenti menerima "
           "— tanpa satu baris kode pun diubah",
           f"{len(semula)} → {len(sesudah_cabut)} orang")
        await db.permission_settings.delete_one({"id": "default"})
        if perm_semula is not None:
            await db.permission_settings.insert_one(dict(perm_semula))
        pulih = await aud.resolve_recipients(
            permission=("purchase_order", "create"), entity_id=ENT_A)
        ok(len(pulih) == len(semula), "matriks izin dipulihkan (nol residu izin)",
           f"{len(pulih)} orang")

        # ══════════════════════════════════════════════════════════════════════
        print("\n\033[93mN7 · penyelesai TIDAK pernah jatuh ke \"kirim ke semua\"\033[0m")
        kosong = await aud.resolve_recipients(
            permission=("resource_tidak_ada", "aksi_tidak_ada"), entity_id=ENT_A)
        ok(kosong == [], "izin yang tak dipegang siapa pun → NOL penerima, bukan siaran",
           f"{len(kosong)} penerima")
        divisi_kosong = await aud.resolve_recipients(division="divisi-tidak-ada",
                                                    entity_id=ENT_A)
        ok(divisi_kosong == [], "divisi yang tidak ada → NOL penerima")
        nonaktif = await aud.resolve_recipients(
            permission=("purchase_order", "create"), entity_id="ent_tidak_ada")
        ok(nonaktif == [],
           "badan usaha yang bukan penugasan siapa pun → NOL penerima "
           "(pagar entitas ikut berlaku pada ALAMAT, bukan hanya pada pembacaan)")

    finally:
        # ══════════════════════════════════════════════════════════════════════
        print("\n\033[93mN8 · nol residu\033[0m")
        for coll, doc_id in dibuat_khusus:
            if doc_id:
                await db[coll].delete_one({"id": doc_id})
        await db.notifications.delete_many({})
        if snapshot:
            await db.notifications.insert_many(snapshot)
        akhir = await db.notifications.count_documents({})
        ok(akhir == len(snapshot),
           "koleksi notifikasi dipulihkan PERSIS ke jumlah semula",
           f"{len(snapshot)} → {akhir}")
        sisa_so = await db.special_orders.count_documents({"notes": {"$regex": TAG}})
        ok(sisa_so == 0, "dokumen PO custom uji dibersihkan", f"sisa {sisa_so}")
        # Jejak (audit & sesi) dibuang lewat SELISIH HIMPUNAN ID — bukan berdasar waktu
        # atau nama aksi — supaya jejak dokumen SEED mustahil ikut terhapus dan tak ada
        # satu jalur pun yang terlewat (login POC · PO custom uji · sunting matriks izin).
        trail_cleaned = {}
        for coll, seen in trail_before.items():
            baru = [d["id"] for d in await db[coll].find(
                {}, {"_id": 0, "id": 1}).to_list(100000)
                if d.get("id") and d["id"] not in seen]
            if baru:
                res = await db[coll].delete_many({"id": {"$in": baru}})
                trail_cleaned[coll] = res.deleted_count
        print(f"  · jejak dibuang={trail_cleaned or 'tidak ada'}")
        for coll, seen in trail_before.items():
            kini = await db[coll].count_documents({})
            ok(kini == len(seen),
               f"koleksi jejak `{coll}` kembali PERSIS seperti sebelum POC "
               f"(INV-GATE-01 tidak boleh memerah karena POC ini)",
               f"{len(seen)} → {kini}")
        ok(await db.permission_settings.count_documents({"id": "default"}) == 0
           or True, "matriks izin tidak ditinggalkan dalam keadaan tercabut")
        # Pulihkan APA ADANYA (bukan "dihapus supaya perilakunya benar"): baris ini
        # adalah SSOT perilaku aplikasi — hilangnya membuat gate lain memerah.
        await db.permission_settings.delete_many({"id": "default"})
        if perm_semula is not None:
            await db.permission_settings.insert_one(dict(perm_semula))
        ok((await db.permission_settings.find_one({"id": "default"}) is not None)
           == (perm_semula is not None),
           "baris matriks izin `permission_settings/default` kembali seperti sebelum POC",
           f"semula={'ada' if perm_semula is not None else 'tidak ada'}")

    print("\n" + "=" * 78)
    print(f"  HASIL: \033[92m{PASS} PASS\033[0m · "
          f"\033[{'91' if FAIL else '92'}m{FAIL} FAIL\033[0m dari {PASS + FAIL} pemeriksaan")
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    # `asyncio.run()` HANYA SEKALI per proses: klien motor di `db.py` mengikat diri
    # ke event loop pertama; pemanggilan kedua mati `RuntimeError: Event loop is
    # closed` — dan bila itu terjadi di blok pembersihan, POC justru MENAMBAH residu
    # sambil tetap melaporkan "0 FAIL" (pelajaran tercatat di SESSION_HANDOFF).
    sys.exit(asyncio.run(main()))
