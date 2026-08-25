"""services/inventory_drift_watch.py — PEMANTAU DRIFT PERSEDIAAN (INV-GL-DRIFT).

MASALAH NYATA YANG DISELESAIKAN
==============================
Sesi 2026-06 sudah membuat true-up persediaan bisa dijalankan ulang di hari yang sama
(`gl_service.post_inventory_opening_balance`). Tetapi selisih antara **subledger roll**
dan **GL 1-1300** tetap hanya ditemukan bila SESEORANG menjalankan
`scripts/verify_data_integrity.py` — sebuah alat pengembang. Di lapangan artinya: buku
bisa berselisih berhari-hari tanpa satu orang pun diberi tahu, karena kelas cacat ini
tidak pernah memunculkan galat atau layar merah. Ia hanya membuat neraca perlahan
berbohong, dan baru terasa saat tutup buku ketika penyebabnya sudah tidak bisa
dilacak lagi.

CARA KERJANYA (menumpang infrastruktur yang SUDAH ADA)
-----------------------------------------------------
* Angkanya dibaca dari **satu sumber** `gl_service.inventory_reconciliation()` — sumber
  yang sama dengan tab "Rekonsiliasi Persediaan" dan pagar `verify_data_integrity` GL-3,
  jadi notifikasi mustahil menyebut selisih yang beda dari layar.
* Ambangnya milik pemilik, bukan kode: `inventory.drift_alert_rupiah` (Pusat Pengaturan).
  Selisih pembulatan rupiah tidak boleh membangunkan orang; selisih senilai satu roll
  wajib.
* Alamatnya **berbasis izin** (`accounting.manage` — yang memang bisa memposting
  true-up), lewat `create_addressed`. Menulis nama peran di sini akan mengulang cacat
  FASE N (lihat `services/notification_audience.py`).
* `dedupe_scope="day"` → job boleh dijalankan berkali-kali sehari tanpa menggandakan.

Pesannya SENGAJA menyebut kapan true-up terakhir dilakukan dan atas dasar apa: "GL vs
fisik berselisih" tanpa riwayat hanya memindahkan kebingungan ke orang berikutnya.
"""
from typing import Any, Dict, List, Optional

from db import db
from services import gl_service
from services.config_resolver import value_of
from services.notification_service import create_addressed

#: Ambang bawaan bila setelannya belum pernah diisi (rupiah, nilai absolut).
DEFAULT_THRESHOLD = 1000.0
#: Selisih ≥ KRITIS × ambang bukan lagi "perlu dirapikan" — ada yang salah jalan.
KRITIS = 10


def rupiah(v: float) -> str:
    return "Rp " + f"{abs(float(v or 0)):,.0f}".replace(",", ".")


async def threshold(entity_id: Optional[str] = None) -> float:
    try:
        raw = await value_of("inventory.drift_alert_rupiah",
                             {"entity_id": entity_id} if entity_id else None)
        return max(0.0, float(raw))
    except Exception:  # noqa: BLE001 — setelan belum ada → bawaan aman
        return DEFAULT_THRESHOLD


async def last_true_up(entity_id: str) -> Dict[str, Any]:
    """Jurnal true-up terakhir buku ini (untuk menjelaskan, bukan menuduh)."""
    return await db.journal_entries.find_one(
        {"source_type": "inventory_opening", "entity_id": entity_id,
         "status": {"$ne": "void"}},
        {"_id": 0, "number": 1, "date": 1, "created_by": 1, "reason": 1,
         "total_debit": 1},
        sort=[("created_at", -1)]) or {}


def _body(row: Dict[str, Any], amb: float, terakhir: Dict[str, Any]) -> str:
    arah = ("nilai fisik roll LEBIH BESAR dari saldo GL"
            if row["difference"] > 0 else "saldo GL LEBIH BESAR dari nilai fisik roll")
    baris = [
        f"Nilai fisik (roll × HPP): {rupiah(row['subledger_value'])}",
        f"Saldo GL 1-1300: {rupiah(row['gl_balance'])}",
        f"Selisih: {rupiah(row['difference'])} — {arah}.",
        f"Ambang peringatan: {rupiah(amb)}.",
    ]
    if terakhir:
        baris.append(
            f"True-up terakhir: {terakhir.get('number', '—')} "
            f"({(terakhir.get('date') or '')[:10]}, oleh "
            f"{terakhir.get('created_by') or '—'})"
            + (f" · dasar: {terakhir['reason']}" if terakhir.get("reason") else
               " · TANPA dasar tercatat"))
    else:
        baris.append("Buku ini belum pernah di-true-up.")
    baris.append("Buka Buku Besar → tab Rekonsiliasi Persediaan untuk menelusuri "
                 "penyebabnya SEBELUM memposting true-up: true-up menyamakan angka, "
                 "ia tidak menjelaskan penyebabnya.")
    return "\n".join(baris)


async def scan() -> Dict[str, Any]:
    """Ukur drift tiap buku, beri tahu yang berwenang bila di luar ambang."""
    recon = await gl_service.inventory_reconciliation()
    drifting: List[Dict[str, Any]] = []
    created = 0
    for row in recon.get("rows", []):
        amb = await threshold(row["entity_id"])
        diff = float(row.get("difference") or 0)
        if abs(diff) <= amb:
            continue
        terakhir = await last_true_up(row["entity_id"])
        notes = await create_addressed(
            permission=("accounting", "manage"),
            notif_type="inventory_drift",
            ref=f"inventory_drift:{row['entity_id']}",
            title=(f"Persediaan berselisih {rupiah(diff)} — "
                   f"{row.get('entity_name') or row['entity_id']}"),
            body=_body(row, amb, terakhir),
            severity="critical" if abs(diff) >= amb * KRITIS else "warning",
            link="general-ledger", entity_id=row["entity_id"], dedupe_scope="day",
        )
        created += len(notes)
        drifting.append({"entity_id": row["entity_id"],
                         "entity_name": row.get("entity_name"),
                         "difference": round(diff, 2), "threshold": amb,
                         "notified": len(notes),
                         "last_true_up": terakhir.get("number", "")})
    return {"scanned": len(recon.get("rows", [])), "drifting": len(drifting),
            "created": created, "rows": drifting}


async def job_inventory_drift_watch() -> Dict[str, Any]:
    """JOB harian: cari buku yang GL persediaannya berselisih dari subledger."""
    res = await scan()
    detail = (f"{res['drifting']} buku berselisih di luar ambang"
              if res["drifting"] else "semua buku sinkron dengan subledger")
    return {"scanned": res["scanned"], "created": res["created"], "detail": detail,
            "rows": res["rows"]}
