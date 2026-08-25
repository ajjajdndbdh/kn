#!/usr/bin/env python3
"""POC — **PAPAN PO CUSTOM** di Control Tower pemilik (D2 · sesi 2026-08-25).

KENAPA POC INI ADA
==================
Papan PO Custom lahir sesi 2026-08-24 dan hijau di seluruh gate — lalu audit mandiri
menemukan **enam** cacat yang tidak satu pun tertangkap, karena buktinya hanya
penjaga statik/HTTP terhadap DATA DEMO YANG ADA. Belum ada POC yang **MEMBUAT
dokumen berumur**, mengukur papannya, lalu membersihkannya — padahal itulah pola
"bukti-merah, nol residu" yang dipakai seluruh fase lain di repo ini.

YANG DIBUKTIKAN (tiap butir = satu temuan audit yang sudah TERBUKTI empiris)
---------------------------------------------------------------------------
P1 **B1 — umur tunggu tidak ditebak.** Dokumen dengan `created_at` 20 hari lalu tetapi
   baru MASUK ANTREAN 2 hari lalu wajib dilaporkan **2 hari**, bukan 20. Sebelum
   perbaikan, `AGING_META` menyebut `submitted_at`/`approval_requested_at` yang nol
   jalur tulis → papan selalu memakai `created_at` dan melebih-lebihkan umurnya.
P2 **B3 — yang TERTUA tidak boleh terpotong.** 12 dokumen menunggu, yang PALING TUA
   (60 hari) disisipkan TERAKHIR supaya urutan alami koleksi menaruhnya di belakang:
   ia WAJIB muncul, dan wajib di baris pertama.
P3 **B2 — jujur saat daftarnya dipotong.** `count` > `len(rows)` wajib disertai
   `shown`/`hidden`/`truncated`; angka di judul yang tak cocok dengan daftar di layar
   yang sama adalah kelas cacat yang justru diperangi INV-HOME-01.
P4 **B4 — satu dokumen aneh tidak boleh menjatuhkan beranda.** `total_amount` berupa
   TEKS (`"43.500.000"`, hasil impor lama) dulu membuat `GET /api/home/admin` **500**
   sehingga SELURUH Control Tower kosong. Sekarang: 200, nilainya dilaporkan 0, dan
   `verify_data_integrity` yang menuntut tipenya dibetulkan.
P5 **A1/A2 — satu pesan, satu penagih.** Job notifikasi dijalankan DUA kali → setiap
   orang menerima maksimal SATU `special_order_approval` per dokumen, isinya identik
   dengan penyusun tunggal, dan pengingat antrean TIDAK ikut menagih dokumen yang
   pemberitahuan miliknya sendiri masih belum dibaca (nol pesan kembar per hari).
P6 **C1/C2 — layar punya bahan yang benar.** Baris papan mengirim `role` & `entity_id`,
   dan `AdminHome.jsx` memakai `roleLabel()` + `<EntityBadge/>` (bukan kode peran
   mentah / id teknis `ent_*` yang dilarang INV-UI-02).
P7 **NOL RESIDU** (INV-GATE-01) — diukur, plus bukti-merah pengukurnya sendiri.

Usage:  python backend/test_core_papan_po_custom_poc.py
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env")
except Exception:  # noqa: BLE001
    pass

import httpx  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts" / "guardrails"))
from _common import DbSnapshot  # noqa: E402

BASE = os.environ.get("POC_BASE", "http://localhost:8001")
PWD = "demo12345"
G, R, Y, B, DIM, X = ("\033[92m", "\033[91m", "\033[93m", "\033[1m", "\033[2m", "\033[0m")
TOUCHED = ["special_orders", "notifications", "audit_logs", "sessions",
           "login_attempts"]
TANDA = "POC_PAPAN_PO_CUSTOM"          # penanda dokumen uji (dihapus di `finally`)
ENTITAS = "ent_ksc"

PASS = FAIL = 0


def ok(cond, label, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [{G}PASS{X}] {label}" + (f" {DIM}{extra}{X}" if extra else ""))
    else:
        FAIL += 1
        print(f"  [{R}FAIL{X}] {label}" + (f" {R}{extra}{X}" if extra else ""))
    return cond


def login(email, entity=ENTITAS):
    c = httpx.Client(base_url=BASE, timeout=120.0)
    r = c.post("/api/auth/login", json={"email": email, "password": PWD})
    r.raise_for_status()
    c.headers.update({"Authorization": f"Bearer {r.json()['token']}",
                      "X-Entity-Id": entity})
    return c


def hari_lalu(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


def dok_uji(db, idx: int, *, umur_dibuat: int, umur_tunggu=None,
            total=25_000_000, role="manager", note="Kain custom uji POC"):
    """Sisipkan satu `special_orders` menunggu keputusan. `umur_tunggu=None` → tak ada
    `approval_requested_at` (dokumen warisan sebelum B1 dibayar)."""
    doc = {
        "id": f"sord_poc_{idx}", "number": f"SORD-POC-{idx:04d}",
        "status": "pending_approval", "type": "special_order",
        "customer_id": "cust_poc", "customer_name": f"Pelanggan Uji {idx}",
        "custom_item": {"description": note, "quantity": 100, "unit": "yard",
                        "target_price": 250_000},
        "total_amount": total, "requires_approval": True,
        "required_approval_role": role, "entity_id": ENTITAS,
        "status_history": [{"status": "draft", "timestamp": hari_lalu(umur_dibuat),
                            "user": "poc"}],
        "created_at": hari_lalu(umur_dibuat), "updated_at": hari_lalu(0),
        "created_by": "poc", "_poc": TANDA,
    }
    if umur_tunggu is not None:
        doc["approval_requested_at"] = hari_lalu(umur_tunggu)
        doc["status_history"].append({"status": "pending_approval",
                                      "timestamp": hari_lalu(umur_tunggu),
                                      "user": "poc"})
    db.special_orders.insert_one(doc)
    return doc


def papan(cl, entity=ENTITAS):
    r = cl.get("/api/home/admin", params={"entity_id": entity})
    return r.status_code, (r.json().get("special_orders_waiting") or {}
                           if r.status_code == 200 else {})


def doc_counts(db, colls=None):
    return {c: db[c].count_documents({}) for c in (colls or TOUCHED)}


def residu(base, db):
    now = doc_counts(db)
    return {c: (base[c], now[c]) for c in base if base[c] != now[c]}


async def main() -> int:  # noqa: PLR0915
    print(f"{B}{'=' * 78}\n  POC PAPAN PO CUSTOM (D2)  ·  {BASE}\n{'=' * 78}{X}")
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=4000)[
        os.environ["DB_NAME"]]
    db.command("ping")

    # Snapshot & sidik jari SEBELUM login (login menulis sesi + audit_logs).
    base = doc_counts(db)
    snap = DbSnapshot(db, collections=TOUCHED).take()
    adm = login("admin@kainnusantara.id")

    try:
        # ── P1 — B1: umur tunggu dibaca dari kapan ia MULAI menunggu ──────────
        print(f"\n{B}▶ P1 — B1: umur tunggu bukan tebakan dari `created_at`{X}")
        dok_uji(db, 1, umur_dibuat=20, umur_tunggu=2)
        st, p = papan(adm)
        ok(st == 200, "GET /api/home/admin → 200", f"→ {st}")
        baris = {r["number"]: r for r in (p.get("rows") or [])}
        r1 = baris.get("SORD-POC-0001")
        ok(bool(r1), "dokumen uji muncul di Papan PO Custom")
        ok(bool(r1) and r1["days_waiting"] == 2,
           "dibuat 20 hari lalu · masuk antrean 2 hari lalu → papan lapor 2 hari",
           f"days_waiting={(r1 or {}).get('days_waiting')} (sebelum B1 dibayar: 20)")

        # Dokumen WARISAN (tanpa `approval_requested_at`) tetap jujur lewat backfill.
        dok_uji(db, 2, umur_dibuat=15, umur_tunggu=None)
        from services import special_order_service as sos
        hasil_bf = await sos.ensure_approval_requested_at(None)
        warisan = db.special_orders.find_one({"id": "sord_poc_2"}, {"_id": 0})
        ok(hasil_bf["written"] >= 1, "backfill mengisi dokumen warisan",
           f"{hasil_bf}")
        ok(bool(warisan.get("approval_requested_at")),
           "dokumen warisan kini punya `approval_requested_at` (dari status_history)")

        # ── P2 — B3: yang TERTUA tidak boleh terpotong ────────────────────────
        print(f"\n{B}▶ P2 — B3: dokumen TERTUA wajib ikut walau disisipkan terakhir{X}")
        for i in range(3, 14):
            dok_uji(db, i, umur_dibuat=i, umur_tunggu=i % 5)
        # PALING TUA, disisipkan TERAKHIR → urutan alami koleksi menaruhnya di belakang.
        dok_uji(db, 99, umur_dibuat=61, umur_tunggu=60)
        st, p = papan(adm)
        nomor = [r["number"] for r in (p.get("rows") or [])]
        ok(st == 200, "papan tetap terbaca dengan 14+ dokumen menunggu", f"→ {st}")
        ok("SORD-POC-0099" in nomor,
           "dokumen 60 hari (disisipkan TERAKHIR) IKUT muncul di 10 baris",
           f"rows={nomor[:4]}…")
        ok(nomor[:1] == ["SORD-POC-0099"],
           "yang paling lama menunggu berada di BARIS PERTAMA",
           f"rows[0]={nomor[0] if nomor else '—'}")
        umur = [r["days_waiting"] for r in (p.get("rows") or [])]
        ok(all(a >= b for a, b in zip(umur, umur[1:])),
           "baris terurut dari yang paling lama menunggu", f"{umur}")

        # ── P3 — B2: jujur saat daftarnya dipotong ────────────────────────────
        print(f"\n{B}▶ P3 — B2: angka di judul WAJIB mengaku bila daftarnya dipotong{X}")
        ok(p.get("count", 0) > len(p.get("rows") or []),
           "kasus uji memang terpotong (count > baris)",
           f"count={p.get('count')} rows={len(p.get('rows') or [])}")
        ok(p.get("shown") == len(p.get("rows") or []), "`shown` = jumlah baris terkirim",
           f"shown={p.get('shown')}")
        ok(p.get("truncated") is True, "`truncated` menyala")
        ok(p.get("hidden") == p.get("count", 0) - (p.get("shown") or 0),
           "`hidden` = selisih yang tidak tampil", f"hidden={p.get('hidden')}")

        # ── P4 — B4: satu dokumen bertipe aneh tidak boleh menjatuhkan beranda ─
        print(f"\n{B}▶ P4 — B4: `total_amount` berupa TEKS tidak boleh 500-kan beranda{X}")
        db.special_orders.update_one({"id": "sord_poc_1"},
                                     {"$set": {"total_amount": "43.500.000"}})
        st, p2 = papan(adm)
        ok(st == 200, "GET /api/home/admin tetap 200 (dulu: 500 → Control Tower kosong)",
           f"→ {st}")
        aneh = next((r for r in (p2.get("rows") or [])
                     if r["number"] == "SORD-POC-0001"), None)
        ok(bool(aneh) and aneh["amount"] == 0.0,
           "nilai yang tak bisa dibaca dilaporkan 0 (bukan melempar galat)",
           f"amount={(aneh or {}).get('amount')}")
        db.special_orders.update_one({"id": "sord_poc_1"},
                                     {"$set": {"total_amount": 25_000_000}})

        # ── P5 — A1/A2: satu penyusun pesan, satu pemilik penagihan berulang ──
        print(f"\n{B}▶ P5 — A1/A2: satu pesan, satu penagih (nol pesan kembar harian){X}")
        db.notifications.delete_many({"type": {"$in": ["special_order_approval",
                                                       "approval_backlog"]}})
        from services import notification_service as notif
        from services import approval_reminder as aprem
        lahir1 = await notif._notify_pending_special_orders()   # noqa: SLF001
        lahir2 = await notif._notify_pending_special_orders()   # noqa: SLF001
        ok(lahir1 > 0, "job melahirkan pemberitahuan PO custom", f"{lahir1} notifikasi")
        ok(lahir2 == 0, "job kedua TIDAK menggandakan (satu pesan per dokumen)",
           f"{lahir2}")
        semua = list(db.notifications.find(
            {"type": "special_order_approval"}, {"_id": 0}))
        per_orang_dok = {}
        for n in semua:
            kunci = (n.get("recipient_user"), n.get("ref"))
            per_orang_dok[kunci] = per_orang_dok.get(kunci, 0) + 1
        ok(all(v == 1 for v in per_orang_dok.values()),
           "maksimal SATU pesan per orang per dokumen",
           f"{sorted(set(per_orang_dok.values()))}")
        ok(all("Perlu persetujuan" in n["body"] for n in semua),
           "isi pesan datang dari penyusun TUNGGAL (bentuknya seragam)")
        # A2 — INI bukti-nya: sesudah pesannya DIBACA, job keadaan TIDAK menagih lagi.
        # Dengan `dedupe_scope="unread"` (versi pertama perbaikan) ia akan melahirkan
        # pesan BARU setiap kali yang lama dibaca → dua mesin menagih dokumen yang
        # sama tiap hari, persis cacat yang sedang ditutup.
        db.notifications.update_many({"type": "special_order_approval"},
                                     {"$set": {"read": True}})
        lahir3 = await notif._notify_pending_special_orders()   # noqa: SLF001
        ok(lahir3 == 0,
           "sesudah pesannya DIBACA, job keadaan tetap tidak menagih lagi "
           "(penagihan berulang milik `approval_reminder`)", f"{lahir3}")
        # …dan pengingat harian TETAP jujur: ia menyebut dokumen TERTUA yang nyata.
        h = await aprem.remind_entity(ENTITAS)
        pengingat = list(db.notifications.find({"type": "approval_backlog"}, {"_id": 0}))
        ok(bool(pengingat), "pengingat harian tetap terkirim (satu pemilik penagihan)",
           f"matched={h.get('matched')} · tertua={h.get('oldest_days')} hari")
        ok(h.get("oldest_number") == "SORD-POC-0099",
           "pengingat menyebut dokumen TERTUA yang nyata (tidak disembunyikan)",
           f"oldest={h.get('oldest_number')} {h.get('oldest_days')} hari")
        per_orang_hari = {}
        for n in pengingat:
            kunci = (n.get("recipient_user"), n.get("dedupe_key"))
            per_orang_hari[kunci] = per_orang_hari.get(kunci, 0) + 1
        ok(all(v == 1 for v in per_orang_hari.values()),
           "pengingat harian: maksimal SATU per orang per hari",
           f"{sorted(set(per_orang_hari.values()))}")

        # ── P6 — C1/C2: layar punya bahan yang benar ──────────────────────────
        print(f"\n{B}▶ P6 — C1/C2: peran ber-label & badan usaha disebut{X}")
        st, p3 = papan(adm)
        satu = (p3.get("rows") or [{}])[0]
        ok(bool(satu.get("role")), "baris papan mengirim `role` (bahan label peran)",
           f"role={satu.get('role')!r}")
        ok(bool(satu.get("entity_id")), "baris papan mengirim `entity_id` (bahan badge)",
           f"entity_id={satu.get('entity_id')!r}")
        # 2026-06 — papan PO custom kini digambar komponen bersama
        # (`WaitingQueueBoard.jsx`) supaya kontrabon bersengketa & retur antar-PT
        # memakai lencana umur tunggu yang SAMA, dan Dasbor Manajer memakai papan
        # yang sama. Bukti C1/C2/A3/B5 karena itu dibaca dari KEDUA berkas: yang
        # penting bukan di berkas mana kodenya, melainkan bahwa layar tidak menebak.
        layar = (ROOT / "frontend/src/features/home/AdminHome.jsx").read_text(
            encoding="utf-8") + (
            ROOT / "frontend/src/components/WaitingQueueBoard.jsx").read_text(
            encoding="utf-8")
        ok("roleLabel(r.role)" in layar,
           "AdminHome.jsx memakai `roleLabel()` (bukan kode peran mentah `manager`)")
        ok("EntityBadge entityId={r.entity_id}" in layar,
           "AdminHome.jsx menampilkan `<EntityBadge/>` (INV-UI-02: id `ent_*` dilarang)")
        ok('custom.view || "special-orders"' not in layar,
           "A3: nama layar tujuan TIDAK lagi ditebak di frontend (nol fallback)")
        ok('"admin-home-special-orders"' in layar and "-unreadable" in layar,
           "B5: papan punya keadaan 'tidak bisa dibaca' (kegagalan ≠ kabar baik)")
        # B5.2 (2026-06) — KEBOCORAN yang ditemukan agen uji: cabang "tidak bisa
        # dibaca" pernah ditulis DI DALAM cabang "daftar kosong". Karena `load()`
        # yang gagal tidak mengosongkan `data`, daftarnya TIDAK kosong dan layar
        # menyajikan antrean BASI dengan percaya diri — cabang unreadable tak pernah
        # dievaluasi. Pagar ini menuduh urutan cabangnya, bukan satu kasusnya.
        import re as _re
        bocor = _re.compile(r"\.length\s*===\s*0\s*\?\s*\(?\s*(?:/\*.*?\*/\s*)?"
                            r"\w*[Uu]nreadable\s*\?", _re.S)
        for _f in ("AdminHome.jsx", "ManagerHome.jsx"):
            _src = (ROOT / f"frontend/src/features/home/{_f}").read_text(encoding="utf-8")
            ok(not bocor.search(_src),
               f"B5.2: {_f} menilai 'tidak bisa dibaca' SEBELUM 'daftar kosong'",
               "cabang unreadable bersarang di dalam cek panjang daftar"
               if bocor.search(_src) else "urutan cabang benar")
        _mgr = (ROOT / "frontend/src/features/home/ManagerHome.jsx").read_text(
            encoding="utf-8")
        for _tid in ("manager-home-approvals-unreadable", "manager-home-late-unreadable"):
            ok(_tid in _mgr, f"B5.2: Dasbor Manajer punya `{_tid}`")
    finally:
        db.special_orders.delete_many({"_poc": TANDA})
        db.notifications.delete_many({"ref": {"$regex": "^so_custom_appr:sord_poc_"}})
        snap.restore()

    # ── P7 — nol residu (DIUKUR) ──────────────────────────────────────────────
    print(f"\n{B}▶ P7 — nol residu setelah POC (DIUKUR, bukan diklaim){X}")
    sisa = residu(base, db)
    ok(not sisa, "seluruh koleksi tersentuh kembali ke jumlah awal (INV-GATE-01)",
       f"{sisa}" if sisa else f"{len(base)} koleksi identik")
    sentinel = {"id": "poc_papan_residue_sentinel", "actor": "poc",
                "action": "sentinel", "entity_type": "gate", "entity_id": "INV-GATE-01"}
    db.audit_logs.insert_one(sentinel)
    ok("audit_logs" in residu(base, db),
       "BUKTI-MERAH: pengukur residu MEMERAH saat 1 dokumen sengaja nyangkut")
    db.audit_logs.delete_one({"_id": sentinel["_id"]})
    ok(not residu(base, db), "sentinel ikut dibersihkan (POC ini nol residu)")

    print(f"\n{B}{'=' * 78}{X}")
    print(f"  HASIL: {G}{PASS} PASS{X} · {R}{FAIL} FAIL{X} dari {PASS + FAIL} pemeriksaan")
    print(f"{B}{'=' * 78}{X}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
