#!/usr/bin/env python3
"""migrate_n_notif_audience — FASE N: bereskan utang DRIFT **D5**.

## Apa yang dibetulkan
Terukur pada data demo bersih (2026-08-24): **11 dari 35** notifikasi ber-
`recipient_role="all"` → `low_stock` **9** · `order_approval` **1** ·
`internal_request_decided` **1**. Sesudah FASE N tidak ada lagi produsen yang menulis
alamat "all" untuk ketiga peristiwa itu, tetapi dokumen LAMA tetap tinggal di kotak
semua orang. Skrip ini memindahkan dokumen lama itu ke alamat yang benar, memakai
**penyelesai yang sama** dengan kode produksi (`services/notification_audience.py`) —
bukan salinan logikanya, supaya keduanya tidak bisa berbeda.

## Kenapa DIPINDAHKAN, bukan dihapus
Notifikasi adalah **jejak**: "sistem pernah memberi tahu" adalah fakta yang tidak boleh
hilang hanya karena alamatnya salah. Yang diperbaiki alamatnya; isi, waktu, dan status
baca dipertahankan. Untuk peristiwa yang alamatnya JAMAK (mis. 9 pesan stok menipis ke
3 orang berwenang), satu dokumen lama disalin menjadi satu dokumen per penerima dengan
`ref` ber-akhiran `#<user_id>` — bentuk yang sama dengan yang ditulis
`create_addressed()` hari ini, sehingga invarian dedupe (`INV-PS21-01`) tetap berlaku.

## Aman dijalankan berulang
Idempotent: dokumen yang sudah ber-`recipient_user` (atau sudah punya penanda
`audience_migrated`) dilewati. Dijalankan tanpa argumen = **ukur saja** (dry-run);
tambahkan `--apply` untuk benar-benar menulis.

    python scripts/migrate_n_notif_audience.py           # ukur
    python scripts/migrate_n_notif_audience.py --apply   # tulis
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

# Peristiwa "all" yang PUNYA pemilik jelas, beserta wewenang yang menentukan alamatnya.
# Ditulis di satu tempat supaya gate `INV-NOTIF-02` dan skrip ini memakai daftar yang
# sama (lihat scripts/guardrails/verify_notification_audience.py).
RULES = {
    "low_stock":                 {"permission": ("purchase_order", "create")},
    "order_approval":            {"permission": ("order", "approve")},
    "reservation_expiring":      {"permission": ("order", "confirm")},
    "order_split":               {"permission": ("wms", "dispatch")},
    # Keputusan atas permintaan internal hanya milik PEMOHON. Tidak ada izin yang
    # bisa menurunkannya — alamatnya diambil dari dokumen sumbernya.
    "internal_request_decided":  {"requester_from": "internal_requests"},
}


async def main(apply: bool) -> int:
    from db import db
    from core_utils import new_id, now_iso  # noqa: F401  (now_iso dipakai bila menulis)
    from services import notification_audience as aud

    total_all = await db.notifications.count_documents({"recipient_role": "all"})
    print(f"notifikasi ber-recipient_role='all' : {total_all}")
    if not total_all:
        print("  tidak ada yang perlu dipindahkan (D5 sudah lunas).")
        return 0

    dibuat = dihapus = dilewati = 0
    for notif in await db.notifications.find({"recipient_role": "all"}, {"_id": 0}).to_list(2000):
        ntype = str(notif.get("type") or "")
        rule = RULES.get(ntype)
        if not rule:
            dilewati += 1
            print(f"  - {ntype or '(tanpa tipe)'} {notif.get('id')} DILEWATI "
                  f"(tidak ada aturan alamat — biarkan sampai fasenya memutuskan)")
            continue

        penerima = []
        if rule.get("permission"):
            penerima = await aud.resolve_recipients(
                permission=rule["permission"], entity_id=notif.get("entity_id"))
        elif rule.get("requester_from"):
            ref = str(notif.get("ref") or "")
            req_id = ref.split(":")[0] if ref else ""
            src = await db[rule["requester_from"]].find_one({"id": req_id}, {"_id": 0})
            uid = str((src or {}).get("requested_by_id") or "")
            if uid:
                penerima = await aud.resolve_recipients(
                    also_users=(uid,), entity_id=notif.get("entity_id"))

        if not penerima:
            dilewati += 1
            print(f"  - {ntype} {notif.get('id')} DILEWATI (nol penerima berwenang "
                  f"di entitas {notif.get('entity_id') or '(sistem)'})")
            continue

        print(f"  - {ntype} {notif.get('id')} -> {len(penerima)} penerima: "
              f"{', '.join(p.get('email', p['id']) for p in penerima)}")
        if not apply:
            continue

        for p in penerima:
            uid = str(p["id"])
            base_ref = str(notif.get("ref") or "")
            salinan = dict(notif)
            salinan["id"] = new_id("ntf")
            salinan["recipient_role"] = ""
            salinan["recipient_user"] = uid
            salinan["ref"] = f"{base_ref}#{uid}" if base_ref else ""
            day = str(notif.get("created_at") or now_iso())[:10]
            salinan["dedupe_key"] = (f"{ntype}:{salinan['ref']}:{day}"
                                     if salinan["ref"] else "")
            salinan["audience_migrated"] = "FASE-N/D5"
            await db.notifications.insert_one(salinan)
            dibuat += 1
        await db.notifications.delete_one({"id": notif.get("id")})
        dihapus += 1

    print(f"\nRINGKASAN: {dihapus} dokumen 'all' digantikan oleh {dibuat} dokumen "
          f"ber-alamat · {dilewati} dilewati")
    if not apply:
        print("(ukur saja — tambahkan --apply untuk menulis)")
    else:
        sisa = await db.notifications.count_documents({"recipient_role": "all"})
        print(f"sisa recipient_role='all' : {sisa}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--apply" in sys.argv)))
