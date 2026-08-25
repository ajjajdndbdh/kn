"""SSOT bentuk satu entri `status_history[]` — dipakai SEMUA koleksi.

MASALAH YANG DITUTUP (2026-06, utang dari audit 2026-08-25 butir "struktur data
keputusan persetujuan"): field bernama SAMA (`status_history`) ternyata punya DUA
bentuk berbeda di repo ini —

    special_orders / sales_orders : {"status", "timestamp", "user", "note"}
    inventory_lots               : {"status", "at",        "actor", "reason"}

Nama yang sama dengan bentuk berbeda adalah jebakan yang tenang: pembaca lintas
koleksi (mis. `special_order_service.waiting_since`, atau timeline generik apa pun
yang lahir kelak) membaca `entry["timestamp"]`, mendapat `None` untuk koleksi yang
memakai `at`, lalu diam-diam jatuh ke cadangan `created_at` — persis kelas cacat B1
("field ditebak") yang sudah dibayar mahal sekali.

Karena itu bentuknya sekarang DITETAPKAN di satu tempat, dipakai seluruh jalur tulis,
dan dijaga pagar statik `scripts/guardrails/verify_status_history.py` (INV-HIST-01)
supaya bentuk ke-tiga tidak bisa lahir tanpa ada yang memerah.
"""
from typing import Any, Dict

from core_utils import now_iso

#: Kunci waktu KANONIK satu entri riwayat. Pembaca cukup membaca kunci ini.
TIME_KEY = "timestamp"
#: Kunci pelaku KANONIK (email atau nama — apa pun yang dipegang pemanggil).
ACTOR_KEY = "user"


def entry(status: str, *, user: str = "", note: str = "", at: str = "",
          **extra: Any) -> Dict[str, Any]:
    """Satu entri riwayat status berbentuk kanonik.

    `at` hanya untuk pemanggil yang punya waktu kejadian sendiri (mis. keputusan yang
    waktunya sudah tercatat di dokumen lain) — nilainya tetap disimpan di `timestamp`.
    """
    row: Dict[str, Any] = {"status": str(status or ""),
                           TIME_KEY: at or now_iso(),
                           ACTOR_KEY: str(user or "")}
    if note:
        row["note"] = str(note)
    row.update({k: v for k, v in extra.items() if v not in (None, "")})
    return row


def time_of(row: Dict[str, Any]) -> str:
    """Kapan entri ini terjadi — satu kunci, tanpa menebak."""
    if not isinstance(row, dict):
        return ""
    return str(row.get(TIME_KEY) or "")
