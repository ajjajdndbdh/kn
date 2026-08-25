#!/usr/bin/env python3
"""POC — SESI 2026-06: **true-up persediaan · papan antrean mahal · satu bentuk riwayat**

KENAPA POC INI ADA
==================
Tiga pekerjaan sesi ini semuanya berjenis "salah tetapi TENANG" — tidak ada galat,
tidak ada layar merah, hanya angka yang perlahan berbohong. Kelas seperti itu hanya
bisa dijaga oleh POC yang MEMBUAT keadaannya, mengukurnya, lalu membersihkannya.

YANG DIBUKTIKAN
---------------
G1 **INV-GL-DRIFT — true-up persediaan tidak boleh terkunci kalender.** Kunci
   idempotensi lama `"{entitas}:{tanggal}"` membuat panggilan KEDUA di hari yang sama
   selalu dilewati. Jadi begitu stok bergerak SETELAH true-up hari itu (POC, fixture,
   koreksi gudang), GL tertinggal dari subledger sampai HARI BERGANTI — dan
   `verify_data_integrity` GL-3 memperingatkan drift (dulu `ent_kanda` Δ900.000) yang
   tidak bisa dipulihkan hari itu juga. POC: true-up → tambah stok Rp 900.000 → true-up
   lagi WAJIB memposting dan selisihnya WAJIB kembali 0.
G2 **Papan antrean mahal ADA JUGA di Dasbor Manajer.** Sebelum ini hanya beranda
   pemilik memilikinya, padahal yang tanda tangannya ditunggu justru manajer: pemilik
   melihat pekerjaan yang orangnya sendiri tidak pernah lihat. Angka kedua beranda
   wajib IDENTIK (satu sumber `approval_backlog_service`).
G3 **Lencana umur tunggu dipakai ULANG untuk antrean lain yang mahal bila menunggu:**
   kontrabon bersengketa & retur antar-PT. Dokumen uji berumur 5 & 12 hari wajib
   dilaporkan dengan umur, nomor, dan NILAI RUPIAH-nya (field `DETAIL_META` yang nyata,
   bukan ditebak) di kedua beranda.
G4 **`status_history[]` hanya punya SATU bentuk.** Dulu `special_orders` menulis
   `{"timestamp","user"}` sementara `inventory_lots` menulis `{"at","actor"}`: pembaca
   lintas koleksi mendapat `None` tanpa galat lalu jatuh ke `created_at` (kelas cacat
   B1 lewat pintu belakang). POC: penyusun SSOT berbentuk kanonik, jalur tulis lot
   memakainya, nol dokumen berbentuk lama, dan `waiting_since` membaca kunci kanonik.
G5 **NOL RESIDU** (INV-GATE-01) — diukur, plus bukti-merah pengukurnya sendiri.

Usage:  python backend/test_core_sesi_2026_06_poc.py
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
TOUCHED = ["inventory_rolls", "journal_entries", "contra_bons", "interco_returns",
           "audit_logs", "sessions", "login_attempts", "inventory_lots",
           "notifications"]
TANDA = "POC_SESI_2026_06"
ENTITAS = "ent_ksc"
NILAI_UJI = 900_000.0          # sama besarnya dengan drift `ent_kanda` yang dilaporkan

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


def doc_counts(db, colls=None):
    return {c: db[c].count_documents({}) for c in (colls or TOUCHED)}


def residu(base, db):
    now = doc_counts(db)
    return {c: (base[c], now[c]) for c in base if base[c] != now[c]}


def papan_of(payload, key):
    for b in (payload.get("waiting_boards") or []):
        if b.get("key") == key:
            return b
    return {}


async def main() -> int:  # noqa: PLR0915
    print(f"{B}{'=' * 78}\n  POC SESI 2026-06 (true-up · papan · riwayat)  ·  {BASE}\n"
          f"{'=' * 78}{X}")
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=4000)[
        os.environ["DB_NAME"]]
    db.command("ping")

    from services import gl_service, status_history as sh
    from services.special_order_service import waiting_since

    base = doc_counts(db)
    snap = DbSnapshot(db, ["audit_logs", "sessions", "login_attempts"])
    snap.take()
    try:
        adm = login("admin@kainnusantara.id", entity="all")
        mgr = login("manager@kainnusantara.id", entity="all")

        # ── G1 — true-up persediaan tidak terkunci kalender ───────────────────
        print(f"\n{B}▶ G1 — INV-GL-DRIFT: true-up boleh berjalan lagi di HARI YANG SAMA{X}")
        await gl_service.post_inventory_opening_balance("poc")   # samakan keadaan awal
        awal = await gl_service.inventory_reconciliation()
        beda_awal = {r["entity_id"]: r["difference"] for r in awal["rows"]}
        ok(all(abs(v) <= 1.0 for v in beda_awal.values()),
           "keadaan awal: subledger == GL 1-1300 di semua buku", f"{beda_awal}")

        db.inventory_rolls.insert_one({
            "id": "roll_poc_sesi_2026_06", "roll_number": "ROLL-POC-2026-06",
            "owner_entity_id": ENTITAS, "entity_id": ENTITAS, "status": "available",
            "length_remaining": 10.0, "length_initial": 10.0, "unit": "yard",
            "unit_cost": NILAI_UJI / 10.0, "created_at": hari_lalu(0), "_poc": TANDA})
        sesudah_stok = await gl_service.inventory_reconciliation()
        drift = next(r["difference"] for r in sesudah_stok["rows"]
                     if r["entity_id"] == ENTITAS)
        ok(abs(drift - NILAI_UJI) <= 1.0,
           "stok masuk SETELAH true-up hari ini menciptakan drift yang nyata",
           f"Δ{drift:,.0f}")

        hasil = await gl_service.post_inventory_opening_balance("poc")
        ok(hasil["count"] >= 1,
           "true-up kedua di HARI YANG SAMA benar-benar memposting "
           "(dulu dilewati `_already_posted` → drift menginap sampai besok)",
           f"posted={hasil['posted']}")
        akhir = await gl_service.inventory_reconciliation()
        sisa = next(r["difference"] for r in akhir["rows"]
                    if r["entity_id"] == ENTITAS)
        ok(abs(sisa) <= 1.0, "sesudah true-up kedua: drift kembali 0 di hari yang sama",
           f"Δ{sisa:,.0f}")

        je_poc = list(db.journal_entries.find(
            {"source_type": "inventory_opening", "entity_id": ENTITAS,
             "created_at": {"$gte": hari_lalu(0)[:10]}}, {"_id": 0, "id": 1,
                                                          "source_id": 1}))
        ok(any("#" in (j.get("source_id") or "") for j in je_poc),
           "kunci idempotensi memakai urutan (`#n`), bukan hanya tanggal",
           f"{[j.get('source_id') for j in je_poc][-2:]}")

        # ── G1b — DRIFT tidak lagi menunggu ditemukan orang ───────────────────
        #  Lanjutan INV-GL-DRIFT: sampai sesi ini selisih hanya terlihat bila ada yang
        #  menjalankan `scripts/verify_data_integrity.py` (alat pengembang). POC ini
        #  MEMBUAT drift, lalu menuntut: (a) pemantau menemukannya & memberi tahu yang
        #  BERWENANG, (b) alasan true-up sampai ke JURNALNYA, (c) sesudah beres
        #  pemantau DIAM (pagar dua arah — pemantau yang selalu berteriak sama tidak
        #  bergunanya dengan yang tak pernah berteriak).
        print(f"\n{B}▶ G1b — drift diberitahukan sendiri + alasan true-up sampai ke jurnal{X}")
        from services import inventory_drift_watch as invdrift
        db.inventory_rolls.insert_one({
            "id": "roll_poc_drift_2026_06", "roll_no": "ROLL-POC-DRIFT",
            "owner_entity_id": ENTITAS, "entity_id": ENTITAS, "status": "available",
            "length_remaining": 10.0, "length_initial": 10.0, "unit": "yard",
            "unit_cost": NILAI_UJI / 10.0, "created_at": hari_lalu(0), "_poc": TANDA})
        pantau = await invdrift.scan()
        kena = [r for r in pantau["rows"] if r["entity_id"] == ENTITAS]
        ok(bool(kena) and kena[0]["notified"] >= 1,
           "pemantau MENEMUKAN drift dan memberi tahu pemegang izin accounting.manage",
           f"{kena[:1]}")
        notif = db.notifications.find_one({"ref": {"$regex": f"^inventory_drift:{ENTITAS}"}})
        ok(bool(notif) and "900.000" in (notif or {}).get("title", ""),
           "pesannya menyebut NILAI selisihnya (bukan 'ada selisih')",
           (notif or {}).get("title", ""))
        ok(bool(notif) and "1-1300" in (notif or {}).get("body", "")
           and "True-up terakhir" in (notif or {}).get("body", ""),
           "pesannya menyebut saldo GL & true-up terakhir (menjelaskan, bukan menuduh)")
        ok((notif or {}).get("recipient_role", "all") != "all",
           "alamatnya BUKAN siaran `all` (FASE N: alamat = izin, bukan nama peran)",
           f"recipient_role={(notif or {}).get('recipient_role')!r}")
        ulang = await invdrift.scan()
        ok(ulang["created"] == 0,
           "dijalankan ulang di hari yang sama: nol pesan baru (dedupe harian)",
           f"created={ulang['created']}")

        DASAR = "POC sesi 2026-06 · stock opname roll uji"
        hasil2 = await gl_service.post_inventory_opening_balance("poc", reason=DASAR)
        je_dasar = db.journal_entries.find_one(
            {"source_type": "inventory_opening", "entity_id": ENTITAS},
            sort=[("created_at", -1)]) or {}
        ok(je_dasar.get("reason") == DASAR,
           "ALASAN true-up tersimpan di jurnalnya (dulu berhenti di `audit_logs`)",
           f"reason={je_dasar.get('reason')!r}")
        ok(DASAR in (je_dasar.get("description") or ""),
           "dasar penyesuaian ikut terbaca di deskripsi jurnal (yang dibaca saat tutup buku)",
           f"posted={hasil2['count']}")
        db.notifications.delete_many({"ref": {"$regex": "^inventory_drift:"}})
        sesudah_beres = await invdrift.scan()
        ok(all(r["entity_id"] != ENTITAS for r in sesudah_beres["rows"]),
           "sesudah true-up: pemantau DIAM untuk buku itu (bukti-merah dua arah)",
           f"{[r['entity_id'] for r in sesudah_beres['rows']]}")
        db.notifications.delete_many({"ref": {"$regex": "^inventory_drift:"}})

        # bersihkan G1: roll uji + jurnal true-up yang lahir karenanya
        db.inventory_rolls.delete_many({"_poc": TANDA})
        db.journal_entries.delete_many(
            {"source_type": "inventory_opening",
             "source_id": {"$regex": r"#\d+$"}, "entity_id": ENTITAS})
        pulih = await gl_service.inventory_reconciliation()
        beda_pulih = next(r["difference"] for r in pulih["rows"]
                          if r["entity_id"] == ENTITAS)
        ok(abs(beda_pulih) <= 1.0,
           "sesudah dibersihkan: buku kembali seperti sebelum POC (nol residu nilai)",
           f"Δ{beda_pulih:,.0f}")

        # ── G2 — papan antrean mahal ada di KEDUA beranda ─────────────────────
        print(f"\n{B}▶ G2 — papan antrean mahal ada di beranda pemilik DAN manajer{X}")
        pa = adm.get("/api/home/admin").json()
        pm = mgr.get("/api/home/manager").json()
        ok(isinstance(pm.get("special_orders_waiting"), dict),
           "Dasbor Manajer memuat Papan PO Custom (dulu hanya beranda pemilik)")
        ok([b["key"] for b in (pa.get("waiting_boards") or [])]
           == [b["key"] for b in (pm.get("waiting_boards") or [])],
           "daftar & urutan papan identik di kedua beranda (satu SSOT `HOME_BOARD_KEYS`)",
           f"{[b['key'] for b in (pm.get('waiting_boards') or [])]}")
        ok(papan_of(pa, "special_order").get("count")
           == papan_of(pm, "special_order").get("count"),
           "jumlah PO custom menunggu SAMA di pemilik & manajer",
           f"{papan_of(pa, 'special_order').get('count')}")

        # ── G3 — lencana umur tunggu dipakai ulang ────────────────────────────
        print(f"\n{B}▶ G3 — antrean lain yang mahal bila menunggu ikut ber-umur-tunggu{X}")
        db.contra_bons.insert_one({
            "id": "cb_poc_sesi_2026_06", "number": "CB-POC-0001", "status": "disputed",
            "entity_id": ENTITAS, "supplier_name": "PT Pemasok Uji POC",
            "dispute_reason_code": "qty_tidak_cocok",
            "totals": {"bills_total": 12_000_000.0, "net_payable": 11_500_000.0},
            "disputed_at": hari_lalu(5), "created_at": hari_lalu(20), "_poc": TANDA})
        db.interco_returns.insert_one({
            "id": "icr_poc_sesi_2026_06", "number": "ICR-POC-0001", "status": "draft",
            "entity_id": ENTITAS, "role": "returner", "counterparty_name": "CV Kanda Suka",
            "reason": "Warna tidak sesuai sample (dokumen uji POC)",
            "grand_total": 4_750_000.0, "created_at": hari_lalu(12), "_poc": TANDA})

        for nama, cl, path in (("pemilik", adm, "/api/home/admin"),
                               ("manajer", mgr, "/api/home/manager")):
            p = cl.get(path).json()
            cb = papan_of(p, "contra_bon_dispute")
            ic = papan_of(p, "interco_return")
            ok(cb.get("count") == 1 and ic.get("count") == 1,
               f"{nama}: kedua papan baru menghitung dokumen uji",
               f"kontrabon={cb.get('count')} retur={ic.get('count')}")
            b_cb = (cb.get("rows") or [{}])[0]
            b_ic = (ic.get("rows") or [{}])[0]
            ok(b_cb.get("days_waiting") == 5,
               f"{nama}: umur tunggu kontrabon dihitung dari `disputed_at` (5 hari)",
               f"{b_cb.get('days_waiting')} hari · since={b_cb.get('since')}")
            ok(b_ic.get("days_waiting") == 12,
               f"{nama}: umur tunggu retur antar-PT 12 hari",
               f"{b_ic.get('days_waiting')} hari")
            ok(b_cb.get("amount") == 11_500_000.0 and b_ic.get("amount") == 4_750_000.0,
               f"{nama}: nilai rupiah dibaca dari field NYATA (`DETAIL_META`), bukan 0",
               f"{b_cb.get('amount')} · {b_ic.get('amount')}")
            ok(b_cb.get("number") == "CB-POC-0001" and b_ic.get("number") == "ICR-POC-0001",
               f"{nama}: nomor dokumen bisa dicari orang", "")

        komponen = (ROOT / "frontend/src/components/WaitingQueueBoard.jsx").read_text(
            encoding="utf-8")
        ok("roleLabel(r.role)" in komponen and "EntityBadge entityId={r.entity_id}"
           in komponen,
           "komponen papan memakai `roleLabel()` + `<EntityBadge/>` (C1/C2 tetap "
           "berlaku untuk SEMUA papan, bukan hanya PO custom)")
        ok("board.truncated" in komponen and "-unreadable" in komponen,
           "B2 & B5 ikut terbawa ke semua papan (penanda terpotong + 'tidak bisa dibaca')")
        mh = (ROOT / "frontend/src/features/home/ManagerHome.jsx").read_text(
            encoding="utf-8")
        ah = (ROOT / "frontend/src/features/home/AdminHome.jsx").read_text(
            encoding="utf-8")
        pemilih = (ROOT / "frontend/src/config/waitingBoards.js").read_text(
            encoding="utf-8")
        ok("WaitingQueueBoard" in mh,
           "ManagerHome.jsx memakai komponen papan yang SAMA (nol salinan kedua)")
        # REGRESI B5 (temuan agen uji 2026-06) — dua beranda dulu menyaring papan
        # sendiri-sendiri, dan penyaring itu mengembalikan daftar KOSONG saat pemuatan
        # gagal → papan hilang total, jadi keadaan "tidak bisa dibaca" tak pernah
        # tampil dan layar kembali terasa kabar baik. Pemilihnya kini SATU fungsi.
        ok("selectWaitingBoards(data, boardsUnreadable)" in mh
           and "selectWaitingBoards(data, boardsUnreadable)" in ah,
           "kedua beranda memakai SATU pemilih papan (B5 tak bisa hilang di satu layar)")
        ok('return utama.length ? utama : [{ key: "special_order" }]' in pemilih,
           "saat data tak terbaca pemilih tetap mengembalikan KERANGKA papan "
           "(supaya 'tidak bisa dibaca' + Coba lagi terlihat)")
        ok("manager-home-approvals-unreadable" in mh
           and "manager-home-late-unreadable" in mh,
           "Dasbor Manajer tidak lagi berbunyi 'Meja Anda bersih' saat gagal dimuat")
        ok('"Tidak bisa dibaca — coba muat ulang"' in ah,
           "KPI 'Persetujuan Menunggu' tidak lagi berbunyi 'Tidak ada yang menunggu' "
           "saat datanya gagal dibaca")

        # ── G4 — satu bentuk `status_history` ─────────────────────────────────
        print(f"\n{B}▶ G4 — `status_history[]` hanya punya SATU bentuk (INV-HIST-01){X}")
        e = sh.entry("pending_approval", user="poc@kn.id", note="uji")
        ok(sh.TIME_KEY in e and sh.ACTOR_KEY in e and "at" not in e,
           "penyusun SSOT menghasilkan bentuk kanonik", f"{sorted(e)}")
        ok(sh.time_of(e) == e["timestamp"] and sh.time_of({"at": "x"}) == "",
           "pembaca kanonik membaca satu kunci (bentuk lama TIDAK diam-diam diterima)")
        lama = db.inventory_lots.count_documents({"status_history.at": {"$exists": True}})
        ok(lama == 0, "nol lot masih memakai bentuk lama `at` (migrasi sudah jalan)",
           f"{lama} lot")
        lama_so = db.special_orders.count_documents({"status_history.at": {"$exists": True}})
        ok(lama_so == 0, "nol PO custom memakai bentuk lama", f"{lama_so} dokumen")
        contoh = db.inventory_lots.find_one({"status_history.0": {"$exists": True}},
                                            {"_id": 0, "status_history": 1})
        h0 = ((contoh or {}).get("status_history") or [{}])[0]
        ok("timestamp" in h0 and "user" in h0,
           "riwayat lot nyata sudah berbentuk kanonik", f"{sorted(h0)}")
        ws = waiting_since({"status_history": [
            {"status": "draft", "timestamp": hari_lalu(20), "user": "poc"},
            {"status": "pending_approval", "timestamp": hari_lalu(2), "user": "poc"}],
            "created_at": hari_lalu(20)})
        ok(ws.startswith(hari_lalu(2)[:10]),
           "`waiting_since` membaca kunci kanonik (umur 2 hari, bukan 20)", f"{ws[:10]}")
    finally:
        db.inventory_rolls.delete_many({"_poc": TANDA})
        db.contra_bons.delete_many({"_poc": TANDA})
        db.interco_returns.delete_many({"_poc": TANDA})
        db.journal_entries.delete_many(
            {"source_type": "inventory_opening", "source_id": {"$regex": r"#\d+$"}})
        snap.restore()

    # ── G5 — nol residu (DIUKUR) ─────────────────────────────────────────────
    print(f"\n{B}▶ G5 — nol residu setelah POC (DIUKUR, bukan diklaim){X}")
    sisa_dok = residu(base, db)
    ok(not sisa_dok, "seluruh koleksi tersentuh kembali ke jumlah awal (INV-GATE-01)",
       f"{sisa_dok}" if sisa_dok else f"{len(base)} koleksi identik")
    sentinel = {"id": "poc_sesi_2026_06_sentinel", "actor": "poc", "action": "sentinel",
                "entity_type": "gate", "entity_id": "INV-GATE-01"}
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
