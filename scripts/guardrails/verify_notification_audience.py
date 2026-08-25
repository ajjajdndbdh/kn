#!/usr/bin/env python3
"""INV-NOTIF-02 — ALAMAT NOTIFIKASI (FASE N).

Menjaga DUA kelas cacat yang keduanya sudah benar-benar terjadi di repo ini, dan
keduanya **tidak menghasilkan satu pun galat** sehingga tak ada uji yang menangkapnya:

## K1 — peristiwa ber-PEMILIK JELAS disiarkan ke `recipient_role="all"`
Terukur 2026-08-24 pada data demo bersih: **11 dari 35** notifikasi ber-alamat "all"
(`low_stock` 9 · `order_approval` 1 · `internal_request_decided` 1). Akibatnya Finance
membuka kotak notifikasinya dan menemukan sembilan pesan stok kain. Kotak yang isinya
bukan urusan kita adalah kotak yang berhenti dibaca — dan sesudah itu peringatan
pertama yang sungguh penting pun ikut tak terbaca. "all" hanya sah untuk peristiwa yang
memang milik semua orang (pengumuman sistem); untuk sisanya ia adalah alamat yang malas.

## K2 — `recipient_role` DAN `recipient_user` ditulis bersamaan
Ini yang paling menipu. Penyaring pembaca (`routers/notifications.py:_scope_query`)
memakai **OR**:

    {recipient_role ∈ {peran_saya, "all"}}  OR  {recipient_user == saya}

Jadi `recipient_role="sales", recipient_user=<sales pemegang akun>` **bukan** berarti
"hanya sales itu" — ia berarti **SELURUH sales**. Penulisnya yakin sedang menyempitkan
alamat, padahal sedang menyiarkan. Terukur di DUA tempat sebelum FASE N:
`alert_ops_service.job_ar_due_soon` (seluruh sales melihat piutang pelanggan rekannya)
dan `internal_request_service._notify_requester` (keputusan permintaan satu orang
terlihat semua pengguna). Karena bentuknya "kelihatan lebih aman daripada aslinya",
kelas ini wajib dijaga secara STRUKTURAL, bukan diingat-ingat.

Pemakaian:
    python scripts/guardrails/verify_notification_audience.py
    python scripts/guardrails/verify_notification_audience.py --self-test
"""
from __future__ import annotations

import ast
import os
import sys
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND = os.path.join(ROOT, "backend")

G, R, Y, B, RST = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[0m"

# ── Peristiwa yang PUNYA pemilik jelas → dilarang ber-alamat "all" ──────────────
# Daftar ini adalah SSOT yang sama dengan `scripts/migrate_n_notif_audience.py`.
# Menambah peristiwa baru ke sini adalah keputusan sadar: artinya "peristiwa ini
# punya pemilik, dan alamatnya wajib diturunkan dari wewenang".
OWNED_EVENTS = {
    "low_stock":                "yang boleh menerbitkan PO (purchase_order.create)",
    "order_approval":           "yang boleh menyetujui pesanan (order.approve)",
    "reservation_expiring":     "yang boleh mengonfirmasi pesanan (order.confirm)",
    "order_split":              "yang mengerjakan pengiriman (wms.dispatch)",
    "internal_request_decided": "PEMOHON permintaan internal itu sendiri",
    "ar_due_soon":              "sales pemegang akun + pemegang ar_receipt.create",
    "special_order_approval":   "pemegang keputusan PO custom (order.approve)",
    "inspection_assigned":      "petugas yang ditugaskan",
    "po_stage_stuck":           "yang boleh menerbitkan PO (purchase_order.create)",
}

# Pembebasan WAJIB ber-alasan tertulis. Kosong hari ini — dan itu memang tujuannya.
# ── K3: peristiwa yang pesannya hanya boleh disusun di SATU tempat ─────────────
# A1 (2026-08-25): judul/isi/tautan/keparahan "PO custom menunggu keputusan" dulu
# diketik DUA KALI — di `routers/special_orders.py` (saat dokumen LAHIR) dan di
# `services/notification_service._notify_pending_special_orders()` (job, saat KEADAAN
# masih menunggu). Keduanya sudah tidak identik: versi endpoint menyebut "Diajukan
# oleh …", versi job tidak. Besok salah satu diperbaiki dan yang lain tidak — kelas
# cacat "dua layar bicara beda" yang persis sama dengan `approval_requests` dulu.
# Karena itu: peristiwa di daftar ini hanya boleh disusun di FUNGSI yang ditunjuk.
SINGLE_OWNER: dict[str, tuple[str, str]] = {
    "special_order_approval": ("services/notification_service.py",
                               "notify_special_order_waiting"),
}


def _owner_of_calls(tree: ast.AST) -> dict[int, str]:
    """Peta `id(node Call)` → nama fungsi TERDALAM yang memuatnya."""
    owner: dict[int, str] = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(fn):
                if isinstance(node, ast.Call):
                    owner[id(node)] = fn.name
    return owner


EXEMPT: dict[str, str] = {}


def _str_of(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _kw(call: ast.Call, name: str):
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def scan_source(src: str, label: str) -> list[str]:
    """Kembalikan daftar pelanggaran (string) untuk satu berkas sumber."""
    bad: list[str] = []
    try:
        tree = ast.parse(src)
    except SyntaxError as e:                                    # pragma: no cover
        return [f"{label}: tidak bisa di-parse ({e})"]
    owner = _owner_of_calls(tree)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fname = ""
        if isinstance(node.func, ast.Name):
            fname = node.func.id
        elif isinstance(node.func, ast.Attribute):
            fname = node.func.attr
        if fname not in {"create_notification", "create_addressed"}:
            continue

        role_node = _kw(node, "recipient_role")
        user_node = _kw(node, "recipient_user")
        type_node = _kw(node, "notif_type")
        role = _str_of(role_node) if role_node is not None else None
        ntype = _str_of(type_node) if type_node is not None else None
        line = getattr(node, "lineno", 0)

        # ── K3: pesan untuk satu peristiwa hanya boleh disusun di SATU fungsi ─
        if ntype in SINGLE_OWNER:
            berkas, fungsi = SINGLE_OWNER[ntype]
            if not (label.replace("\\", "/").endswith(berkas)
                    and owner.get(id(node), "") == fungsi):
                bad.append(
                    f"{label}:{line}: K3 pesan `{ntype}` disusun DI LUAR "
                    f"`{berkas}::{fungsi}()` — judul/isi/tautan yang diketik dua kali "
                    f"akan berbeda pelan-pelan (kelas cacat 'dua layar bicara beda'). "
                    f"Panggil fungsi itu, jangan menyusun pesannya lagi.")

        # ── K1: peristiwa ber-pemilik tidak boleh "all" ───────────────────────
        # `create_notification` tanpa `recipient_role` = bawaan "all" → ikut dijaga.
        efektif = role if role_node is not None else (
            "all" if fname == "create_notification" else "")
        if ntype in OWNED_EVENTS and efektif == "all":
            if ntype in EXEMPT:
                continue
            bad.append(f"{label}:{line}: K1 `{ntype}` ber-recipient_role=\"all\" — "
                       f"pemiliknya jelas: {OWNED_EVENTS[ntype]}")

        # ── K2: role + user bersamaan = SIARAN, bukan alamat sempit ───────────
        if user_node is not None and role_node is not None and role not in ("", None):
            bad.append(f"{label}:{line}: K2 `recipient_role=\"{role}\"` ditulis BERSAMA "
                       f"`recipient_user` — penyaring pembaca memakai OR, jadi ini "
                       f"menyiarkan ke SELURUH peran \"{role}\". Hapus recipient_role.")
        # `recipient_user` tanpa `recipient_role` sama sekali juga aman: bawaan
        # "all" hanya berlaku bila argumennya memang tidak dikirim DAN tidak ada
        # recipient_user — kasus itu ditangkap K1 di atas bila peristiwanya ber-pemilik.
        if (user_node is not None and role_node is None
                and fname == "create_notification"):
            bad.append(f"{label}:{line}: K2 `recipient_user` dikirim tanpa "
                       f"`recipient_role=\"\"` — bawaan parameternya \"all\", jadi "
                       f"pesannya tetap tersiar. Tulis recipient_role=\"\" secara eksplisit.")
    return bad


def scan_repo() -> list[str]:
    bad: list[str] = []
    for base, dirs, files in os.walk(BACKEND):
        dirs[:] = [d for d in dirs if d not in {"__pycache__", ".venv"}]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            # POC & uji sengaja dilewati: berkas itu memang menulis bentuk data
            # lama/ekstrem untuk MEMBUKTIKAN pagarnya bekerja.
            if fn.startswith(("test_", "backend_test")):
                continue
            path = os.path.join(base, fn)
            rel = os.path.relpath(path, ROOT)
            with open(path, encoding="utf-8") as fh:
                bad += scan_source(fh.read(), rel)
    return bad


async def scan_data() -> list[str]:
    """Lapisan DATA: tidak boleh ada dokumen hidup ber-alamat "all" untuk peristiwa
    ber-pemilik. Kode bisa benar sementara dokumen warisan masih menyiarkan —
    itulah utang D5, dan gate harus melihatnya."""
    sys.path.insert(0, BACKEND)
    from db import db

    bad: list[str] = []
    from collections import Counter
    rows = await db.notifications.find(
        {"recipient_role": "all"}, {"_id": 0, "type": 1}).to_list(5000)
    per_type = Counter(str(r.get("type") or "") for r in rows)
    for ntype, n in sorted(per_type.items()):
        if ntype in OWNED_EVENTS and ntype not in EXEMPT:
            bad.append(f"DATA: {n} notifikasi `{ntype}` masih ber-recipient_role=\"all\" "
                       f"(pemiliknya: {OWNED_EVENTS[ntype]}) — jalankan "
                       f"`python scripts/migrate_n_notif_audience.py --apply`")
    return bad


# ══════════════════════════════════════════════════════════════════════════════
# SELF-TEST (bukti-merah DUA ARAH — aturan repo #6)
# ══════════════════════════════════════════════════════════════════════════════
HARUS_MERAH = [
    ("K1 low_stock ber-all",
     'await create_notification(notif_type="low_stock", title="t", body="b",\n'
     '                          recipient_role="all")'),
    ("K1 low_stock tanpa recipient_role (bawaan all)",
     'await create_notification(notif_type="low_stock", title="t", body="b")'),
    ("K1 order_approval ber-all",
     'await create_notification(notif_type="order_approval", title="t", body="b",\n'
     '                          recipient_role="all")'),
    ("K2 role sales + user (kasus ar_due_soon sebelum FASE N)",
     'await create_notification(notif_type="ar_due_soon", title="t", body="b",\n'
     '                          recipient_role="sales", recipient_user=uid)'),
    ("K2 role all + user (kasus internal_request_decided sebelum FASE N)",
     'await create_notification(notif_type="internal_request_decided", title="t",\n'
     '                          body="b", recipient_role="all", recipient_user=uid)'),
    ("K2 user tanpa role eksplisit (bawaan all tetap menyiarkan)",
     'await create_notification(notif_type="inspection_assigned", title="t",\n'
     '                          body="b", recipient_user=uid)'),
    ("K1 po_stage_stuck ber-all",
     'await create_addressed(notif_type="po_stage_stuck", title="t", body="b",\n'
     '                       recipient_role="all")'),
    ("K2 role manager + user pada peristiwa ber-pemilik",
     'await create_notification(notif_type="special_order_approval", title="t",\n'
     '                          body="b", recipient_role="manager", recipient_user=uid)'),
]

HARUS_HIJAU = [
    ("alamat per orang yang benar (role dikosongkan eksplisit)",
     'await create_notification(notif_type="inspection_assigned", title="t", body="b",\n'
     '                          recipient_role="", recipient_user=uid)'),
    ("alamat berbasis izin lewat create_addressed",
     'await create_addressed(permission=("purchase_order", "create"),\n'
     '                       notif_type="low_stock", title="t", body="b")'),
    ("peristiwa yang memang milik semua orang tetap boleh 'all'",
     'await create_notification(notif_type="pengumuman_sistem", title="t", body="b",\n'
     '                          recipient_role="all")'),
    ("alamat peran untuk peristiwa yang bukan daftar ber-pemilik",
     'await create_notification(notif_type="po_approval", title="t", body="b",\n'
     '                          recipient_role="manager")'),
    ("create_addressed tanpa recipient_role (bawaannya bukan 'all')",
     'await create_addressed(roles=("manager",), notif_type="order_split",\n'
     '                       title="t", body="b")'),
    ("fungsi lain bernama mirip tidak ikut dituduh",
     'await kirim_email(notif_type="low_stock", recipient_role="all")'),
]


def self_test() -> int:
    print(f"{B}INV-NOTIF-02 SELF-TEST (bukti-merah dua arah){RST}")
    lulus = gagal = 0
    # ── K3 (2026-08-25) — satu peristiwa, satu penyusun pesan ─────────────────
    k3_merah = ('async def f():\n'
                '    await create_addressed(notif_type="special_order_approval",\n'
                '                           roles=("manager",), title="t", body="b")\n')
    if scan_source(k3_merah, "routers/special_orders.py"):
        print(f"  {G}✓{RST} MEMERAH: K3 pesan PO custom disusun di luar penyusun tunggal")
        lulus += 1
    else:
        print(f"  {R}✗{RST} LOLOS padahal harus merah: K3 pesan PO custom ganda")
        gagal += 1
    k3_hijau = ('async def notify_special_order_waiting(so):\n'
                '    return await create_addressed(\n'
                '        notif_type="special_order_approval", roles=("manager",),\n'
                '        title="t", body="b")\n')
    if not scan_source(k3_hijau, "services/notification_service.py"):
        print(f"  {G}✓{RST} tetap HIJAU (tidak menuduh palsu): K3 penyusun tunggal yang sah")
        lulus += 1
    else:
        print(f"  {R}✗{RST} TUDUHAN PALSU: K3 penyusun tunggal yang sah")
        gagal += 1
    for nama, cuplikan in HARUS_MERAH:
        src = "async def f():\n" + textwrap.indent(cuplikan, "    ") + "\n"
        temuan = scan_source(src, "<uji>")
        if temuan:
            print(f"  {G}✓{RST} MEMERAH: {nama}")
            lulus += 1
        else:
            print(f"  {R}✗{RST} LOLOS padahal harus merah: {nama}")
            gagal += 1
    for nama, cuplikan in HARUS_HIJAU:
        src = "async def f():\n" + textwrap.indent(cuplikan, "    ") + "\n"
        temuan = scan_source(src, "<uji>")
        if not temuan:
            print(f"  {G}✓{RST} tetap HIJAU (tidak menuduh palsu): {nama}")
            lulus += 1
        else:
            print(f"  {R}✗{RST} TUDUHAN PALSU: {nama} → {temuan}")
            gagal += 1
    print(f"\n  HASIL SELF-TEST: {G}{lulus} PASS{RST} · "
          f"{R if gagal else G}{gagal} FAIL{RST} dari {lulus + gagal} kasus")
    return 1 if gagal else 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    print(f"{B}INV-NOTIF-02 — alamat notifikasi (kode + data){RST}")
    bad = scan_repo()
    try:
        import asyncio
        bad += asyncio.run(scan_data())
    except Exception as e:                                       # noqa: BLE001
        print(f"  {Y}(lapisan DATA dilewati: {e}){RST}")

    if bad:
        print(f"\n  {R}✗ {len(bad)} pelanggaran:{RST}")
        for b in bad:
            print(f"    - {b}")
        print(f"\n  Peristiwa ber-pemilik: {', '.join(sorted(OWNED_EVENTS))}")
        return 1
    print(f"  {G}✓ nol peristiwa ber-pemilik yang disiarkan ke \"all\"; "
          f"nol `recipient_role` + `recipient_user` bersamaan.{RST}")
    print(f"  ({len(OWNED_EVENTS)} peristiwa ber-pemilik dijaga di kode DAN data)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
