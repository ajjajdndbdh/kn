#!/usr/bin/env python3
"""INV-SAMPLE-01 — MASTER JENIS SAMPLING vs DOKUMEN SAMPLE (FASE S).

KELAS BUG YANG DICEGAH
======================
FASE S memindahkan dua kelakuan dari KODE ke DATA (master `sample_types`):

    requires_design      dulu `if stype == "proofing"` di rnd_sample_service
    measurement_fields   dulu 5 field TETAP di `schemas_rnd.RoundMeasurements`

dan mengubah satu fakta tunggal menjadi DAFTAR (`md_samples.sample_types[]`), dengan
tiap iterasi milik satu jenis (`rounds[].type_code`). Kebebasan itu membuka tujuh cara
gagal yang semuanya SENYAP — tidak ada galat, tidak ada layar merah, hanya papan &
rapor yang perlahan berbohong:

  A. **Jenis yang masih dipakai dokumen dihapus/dinonaktifkan.** Permintaan lama
     menunjuk kode yang tak ada lagi → layar menampilkan lencana tanpa nama, dan
     penyaring jenis kehilangan barisnya. Karena itu penjaga ini tidak cukup
     membandingkan daftar: ia **MENGHITUNG dokumen pemakainya** sebelum menuduh
     (pelajaran INV-DOMAIN-06: penjaga yang menuduh palsu akan diabaikan).
  B. **DUA SUMBER jenis.** `sample_type` (tunggal) masih menempel di samping
     `sample_types[]`. Selama dua-duanya hidup, tiap pembaca baru punya dua tempat
     untuk bertanya dan keduanya akan menyimpang dalam beberapa sesi. Termasuk di
     sini: dokumen yang TIDAK punya jenis sama sekali (tak muncul di penyaring
     mana pun → pekerjaan tak terlihat, kelas cacat yang sama dengan FASE L).
  C. **Round tanpa jenis / berjenis asing.** `rounds[].type_code` kosong atau bukan
     bagian `sample_types[]` dokumen → round itu masuk rangkaian yang salah, dan
     skor labdip (warna) dibandingkan dengan skor handfeel (rasa) seolah setara.
  D. **`measurement_fields` menyebut field yang tidak ada kamusnya**
     (`domain_registry.SAMPLE_MEASUREMENTS`). Akibatnya form setor hasil meminta
     kolom yang tak punya label/satuan/batas, dan validator tak punya aturan —
     petugas mengisi angka yang tak pernah bisa dinilai siapa pun.
  E. **Hasil ukur round menyimpang dari jenisnya.** Round menyimpan kunci yang
     TIDAK diminta jenis itu (angka yang tak pernah ditampilkan) atau kehilangan
     kunci yang diminta (perbandingan supplier jadi selera).
  F. **Jenis ber-`requires_design` dipakai tanpa kode desain.** Ini aturan
     bisnis yang dulu dijaga `if` di kode; setelah menjadi data, satu-satunya yang
     bisa menjaganya adalah penjaga.
  G. **Urutan & wewenang pelaksanaan.** `delivered_at` tanpa `finished_at`
     (dikirim sebelum jadi), `delivered_at` tanpa `delivered_to` (laporan
     pengiriman yang tak bisa menjawab "ke mana"), `delivered_to` di luar
     `sample_deliver_target`, dan — statik — endpoint `finish`/`deliver` yang
     berubah menjadi pintu keputusan tanpa didaftarkan sebagai antrean.
     Aturan G inilah yang MENJAGA keputusan pemilik "kirim sample tidak butuh
     persetujuan": begitu izinnya diganti ke `decide`, gate menuntut antreannya.

YANG DIPERIKSA
--------------
STATIK  (tanpa basis data)
  S1. benih `SAMPLE_TYPES` lolos aturan D (kamus hasil ukur) & punya kode unik
  S2. (G) `POST /rnd/samples/{id}/finish` & `/deliver` ADA, memakai izin
      **pelaksana** (`rnd.submit`), dan alasan "bukan antrean" tertulis di
      `approval_backlog_service.py`
RUNTIME (Mongo langsung — opini kedua, tidak lewat API yang sedang diuji)
  R1. (A) jenis yang dipakai `md_samples.sample_types[]` masih ada & aktif
  R2. (B) satu sumber jenis: nol sisa `sample_type`, nol dokumen tanpa jenis
  R3. (C) `rounds[].type_code` ada & ∈ `sample_types[]` dokumennya
  R4. (D) `measurement_fields` master ⊆ kamus `sample_measurement`
  R5. (E) kunci `rounds[].measurements` == `measurement_fields` jenis round itu
  R6. (F) dokumen ber-jenis `requires_design` punya `design_id`
  R7. (G) urutan penanda pelaksanaan & tujuan pengiriman sah
  R8. nomor dokumen `md_samples` mengikuti pola `<ENT>/SMP-#####` dan UNIK
      (anti-regresi D7: seeder yang menomori sendiri dengan f-string pernah
       menghasilkan 5 pasang NOMOR DOKUMEN KEMBAR)

Resilient: tanpa MONGO_URL / basis data mati → bagian runtime SKIP (exit 0),
bagian statik tetap jalan. Exit 1 hanya bila invarian terbukti dilanggar.

Usage:
    python scripts/guardrails/verify_sample_types.py
    python scripts/guardrails/verify_sample_types.py --self-test   # bukti-merah, tanpa DB
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[2]
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env")
except Exception:  # noqa: BLE001
    pass

sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import B, G, R, X, Y, Guard  # noqa: E402

import domain_registry as dr  # noqa: E402

NUMBER_RE = re.compile(r"^[A-Z]+/SMP-\d{5}$")
# Endpoint pelaksanaan yang keputusan pemiliknya "BUKAN antrean persetujuan".
EXEC_DOORS = ("/rnd/samples/{sample_id}/finish", "/rnd/samples/{sample_id}/deliver")
EXEC_PERMISSION = 'require_permission(request, "rnd", "submit")'


# ═══════════════════════════════════════════════════════════════════════════
# FUNGSI MURNI — bisa diuji tanpa Mongo (dipakai --self-test)
# ═══════════════════════════════════════════════════════════════════════════

def _code(row: Dict[str, Any]) -> str:
    return str(row.get("code") or row.get("value") or "").strip().lower()


def _is_active(row: Dict[str, Any]) -> bool:
    if row.get("active") is False:
        return False
    return str(row.get("status") or "active") != "inactive"


def _fields(row: Dict[str, Any]) -> List[str]:
    return [str(f).strip().lower() for f in (row.get("measurement_fields") or [])
            if str(f or "").strip()]


def types_of(doc: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for v in (doc.get("sample_types") or []):
        code = str(v or "").strip().lower()
        if code and code not in out:
            out.append(code)
    return out


def check_still_used(master_rows: List[Dict[str, Any]],
                     usage: Dict[str, int]) -> List[str]:
    """A — jenis yang MASIH dipakai dokumen tidak boleh hilang/nonaktif.

    Menuduh berdasarkan daftar saja akan memerah setiap kali pemilik merapikan
    jenis yang memang tak terpakai (mis. `bulk_sample`, yang justru DISENGAJA
    dinonaktifkan) — penjaga yang menuduh palsu akan diabaikan, lalu berhenti
    menjaga apa pun.
    """
    out: List[str] = []
    known = {_code(r) for r in master_rows}
    active = {_code(r) for r in master_rows if _is_active(r)}
    for code, n in sorted(usage.items()):
        if not code or n <= 0:
            continue
        if code not in known:
            out.append(f"(A) jenis '{code}' dipakai {n} permintaan sample tetapi TIDAK "
                       "ADA di master `sample_types` — layar menampilkan lencana tanpa "
                       "nama dan penyaring jenis kehilangan barisnya. Kembalikan "
                       "barisnya (Pengaturan → Master → Jenis Sampling) atau ubah "
                       "dokumennya lebih dulu.")
        elif code not in active:
            out.append(f"(A) jenis '{code}' DINONAKTIFKAN padahal masih dipakai {n} "
                       "permintaan sample. Nonaktifkan hanya setelah tidak ada dokumen "
                       "pemakai yang masih berjalan.")
    return out


def check_single_source(docs: List[Dict[str, Any]]) -> List[str]:
    """B — satu sumber jenis: nol `sample_type` lama, nol dokumen tanpa jenis."""
    out: List[str] = []
    legacy = [d.get("number") or d.get("id") for d in docs if "sample_type" in d]
    if legacy:
        out.append(f"(B) {len(legacy)} dokumen masih punya field lama `sample_type` "
                   f"di samping `sample_types[]` ({', '.join(map(str, legacy[:5]))}) — "
                   "DUA SUMBER untuk satu fakta. Jalankan "
                   "`python scripts/migrate_sample_types.py`.")
    kosong = [d.get("number") or d.get("id") for d in docs if not types_of(d)]
    if kosong:
        out.append(f"(B) {len(kosong)} dokumen TIDAK punya jenis sampling sama sekali "
                   f"({', '.join(map(str, kosong[:5]))}) — dokumen begini tidak muncul "
                   "di penyaring jenis mana pun, jadi pekerjaannya tak terlihat. Isi "
                   "jenisnya dari layar (jangan ditebak skrip).")
    return out


def check_round_types(docs: List[Dict[str, Any]]) -> List[str]:
    """C — tiap round punya `type_code` dan jenisnya bagian dokumen itu."""
    out: List[str] = []
    for d in docs:
        kinds = set(types_of(d))
        for r in (d.get("rounds") or []):
            code = str(r.get("type_code") or "").strip().lower()
            if not code:
                out.append(f"(C) {d.get('number') or d.get('id')} round "
                           f"{r.get('round_no')} tidak punya `type_code` — round tanpa "
                           "jenis akan tampak di dua rangkaian sekaligus (atau tak "
                           "tampak di mana pun) begitu permintaan menempuh >1 jenis.")
            elif kinds and code not in kinds:
                out.append(f"(C) {d.get('number') or d.get('id')} round "
                           f"{r.get('round_no')} berjenis '{code}' yang BUKAN bagian "
                           f"permintaan itu (diminta: {', '.join(sorted(kinds))}) — "
                           "riwayatnya masuk rangkaian yang salah.")
    return out


def check_measurement_dict(master_rows: List[Dict[str, Any]],
                           known_fields: Set[str]) -> List[str]:
    """D — `measurement_fields` harus punya kamusnya (label · satuan · batas)."""
    out: List[str] = []
    for r in master_rows:
        if not _is_active(r):
            continue
        for f in _fields(r):
            if f not in known_fields:
                out.append(f"(D) jenis '{_code(r)}' meminta hasil ukur '{f}' yang tidak "
                           "ada di `domain_registry.SAMPLE_MEASUREMENTS`. Form setor "
                           "hasil akan menampilkan kolom tanpa label/satuan dan "
                           "validator tak punya batas wajarnya. Pilihan: "
                           f"{', '.join(sorted(known_fields))}.")
    return out


def check_round_measurements(docs: List[Dict[str, Any]],
                            want_by_type: Dict[str, List[str]]) -> List[str]:
    """E — kunci hasil ukur round == `measurement_fields` jenis round itu.

    DUA pembebasan yang DISENGAJA, supaya penjaga ini tidak menuduh palsu:
      * round yang masih TERBUKA memang belum punya angka — menuduhnya akan memerah
        untuk pekerjaan yang sedang berjalan;
      * round **historis/impor** yang JUJUR menyatakan tidak mengumpulkan bukti
        (`proof_required: False` **dan** `measurements` kosong). Pola kejujuran ini
        sudah dipakai repo di INV-RND-02: data riwayat demo tidak dipalsukan dengan
        lampiran kosong, jadi ia juga tidak boleh dipaksa mengarang hasil ukur.
        Perhatikan: pembebasan ini HANYA untuk yang kosong seluruhnya. Round yang
        mengisi SEBAGIAN tetap diperiksa — separuh angka lebih menyesatkan daripada
        tidak ada angka, karena layar menampilkannya seolah lengkap.
    """
    out: List[str] = []
    for d in docs:
        for r in (d.get("rounds") or []):
            if str(r.get("status") or "") not in ("submitted", "assessed"):
                continue
            code = str(r.get("type_code") or "").strip().lower()
            want = set(want_by_type.get(code, []))
            if not want:
                continue
            have = {str(k).strip().lower()
                    for k, v in (r.get("measurements") or {}).items() if v is not None}
            if not have and r.get("proof_required") is False:
                continue
            extra = sorted(have - want)
            missing = sorted(want - have)
            label = f"{d.get('number') or d.get('id')} round {r.get('round_no')} ({code})"
            if extra:
                out.append(f"(E) {label} menyimpan hasil ukur {', '.join(extra)} yang "
                           "TIDAK diminta jenisnya — angka yang tak pernah ditampilkan "
                           "di layar mana pun.")
            if missing:
                out.append(f"(E) {label} kehilangan hasil ukur wajib "
                           f"{', '.join(missing)} — perbandingan supplier jadi selera, "
                           "bukan angka.")
    return out


def check_requires_design(docs: List[Dict[str, Any]],
                          need_design: Set[str],
                          known_designs: Set[str]) -> List[str]:
    """F — jenis ber-`requires_design` wajib merujuk desain yang NYATA."""
    out: List[str] = []
    for d in docs:
        hit = need_design & set(types_of(d))
        if not hit:
            continue
        design_id = str(d.get("design_id") or "").strip()
        if not design_id:
            out.append(f"(F) {d.get('number') or d.get('id')} memuat jenis "
                       f"{', '.join(sorted(hit))} yang WAJIB berkode desain, tetapi "
                       "`design_id` kosong.")
        elif known_designs and design_id not in known_designs:
            out.append(f"(F) {d.get('number') or d.get('id')} menunjuk desain "
                       f"'{design_id}' yang tidak ada di master desain — lencana desain "
                       "di layar akan kosong tanpa ada yang tahu kenapa.")
    return out


def check_execution_marks(docs: List[Dict[str, Any]],
                          targets: Set[str]) -> List[str]:
    """G (data) — urutan penanda pelaksanaan & tujuan pengiriman."""
    out: List[str] = []
    for d in docs:
        num = d.get("number") or d.get("id")
        delivered = str(d.get("delivered_at") or "").strip()
        finished = str(d.get("finished_at") or "").strip()
        to = str(d.get("delivered_to") or "").strip().lower()
        if delivered and not finished:
            out.append(f"(G) {num} tercatat DIKIRIM tetapi tidak pernah ditandai JADI — "
                       "urutannya mustahil, dan laporan memakai urutan itu sebagai bukti.")
        if delivered and not to:
            out.append(f"(G) {num} tercatat DIKIRIM tanpa TUJUAN — laporan pengiriman "
                       "sample tidak bisa menjawab 'ke mana', yang justru pertanyaannya.")
        if to and to not in targets:
            out.append(f"(G) {num} bertujuan '{to}' yang bukan pilihan sah "
                       f"({', '.join(sorted(targets))}).")
        if to and not delivered:
            out.append(f"(G) {num} punya tujuan '{to}' tetapi tanpa tanggal kirim — "
                       "tujuan tanpa peristiwa berarti dokumen mengaku terkirim.")
    return out


def check_exec_doors(router_src: str, backlog_src: str) -> List[str]:
    """G (statik) — pelaksanaan tetap PELAKSANAAN, bukan pintu keputusan diam-diam.

    Keputusan pemilik FASE S: `finish` & `deliver` tidak butuh persetujuan siapa pun.
    Keputusan itu hanya bertahan bila ada yang menjaganya: kalau suatu hari izinnya
    diganti ke `rnd.decide` (atau path-nya diberi kata keputusan) tanpa mendaftarkan
    antreannya, dokumen yang menunggu tidak akan pernah muncul di KPI beranda.
    Alasannya WAJIB tertulis di `approval_backlog_service.py` — di sanalah orang
    berikutnya mencari daftar antrean.
    """
    out: List[str] = []
    for door in EXEC_DOORS:
        if f'"{door}"' not in router_src:
            out.append(f"(G) endpoint pelaksanaan `{door}` tidak ada lagi di "
                       "`routers/rnd.py` — user story S.F-4 (Sample Jadi & Kirim) "
                       "kehilangan pintunya.")
    if EXEC_DOORS[0] in router_src or EXEC_DOORS[1] in router_src:
        blok = router_src.split(EXEC_DOORS[0].split("/finish")[0])[-1]
        if EXEC_PERMISSION not in blok:
            out.append("(G) endpoint `finish`/`deliver` tidak lagi memakai izin "
                       f"pelaksana ({EXEC_PERMISSION}). Bila pengirimannya memang jadi "
                       "KEPUTUSAN, daftarkan antreannya di "
                       "`approval_backlog_service.QUEUES` — kalau tidak, dokumen yang "
                       "menunggu tak akan pernah terhitung.")
    if "SENGAJA BUKAN ANTREAN" not in backlog_src:
        out.append("(G) alasan 'finish & deliver SENGAJA BUKAN ANTREAN' tidak tertulis "
                   "di `services/approval_backlog_service.py`. Pembebasan tanpa alasan "
                   "tertulis = penjaga yang dijinakkan (kelas INV-APPR-01).")
    return out


def check_numbers(numbers: List[str]) -> List[str]:
    """R8 — pola & keunikan nomor dokumen sample (anti-regresi D7)."""
    out: List[str] = []
    salah = [n for n in numbers if not NUMBER_RE.match(str(n or ""))]
    if salah:
        out.append(f"(D7) {len(salah)} nomor `md_samples` menyimpang dari pola "
                   f"`<ENT>/SMP-#####` ({', '.join(map(str, salah[:5]))}) → seeder/kode "
                   "menomori sendiri alih-alih `core_utils.next_doc_number()`.")
    dup = sorted({n for n in numbers if numbers.count(n) > 1 and n})
    if dup:
        out.append(f"(D7) NOMOR DOKUMEN KEMBAR di `md_samples`: {', '.join(dup[:5])} "
                   "→ papan & laporan menampilkan dua baris bernomor sama, dan gate "
                   "keunikan nomor apa pun akan memerah dengan benar.")
    return out


# ═══════════════════════════════════════════════════════════════════════════
# STATIK — benihnya sendiri & pintu pelaksanaan
# ═══════════════════════════════════════════════════════════════════════════

def run_static(guard: Guard) -> None:
    seed = [dict(v) for v in dr.enum_items("sample_type")]
    known = {m["value"] for m in dr.enum_items("sample_measurement")}
    guard.bump(3)
    for v in check_measurement_dict(seed, known):
        guard.add(f"[benih] {v}")
    codes = [_code(r) for r in seed]
    dup = sorted({c for c in codes if codes.count(c) > 1})
    if dup:
        guard.add(f"[benih] kode jenis KEMBAR di `SAMPLE_TYPES`: {', '.join(dup)} — "
                  "master akan menolak salah satunya dan nilainya jadi tak tentu.")
    router = (ROOT / "backend" / "routers" / "rnd.py").read_text(encoding="utf-8")
    backlog = (ROOT / "backend" / "services"
               / "approval_backlog_service.py").read_text(encoding="utf-8")
    for v in check_exec_doors(router, backlog):
        guard.add(v)
    print(f"  · benih SAMPLE_TYPES: {len(seed)} jenis diperiksa ({', '.join(codes)}) · "
          f"kamus hasil ukur {len(known)} field")


# ═══════════════════════════════════════════════════════════════════════════
# RUNTIME — master hidup + dokumen pemakainya
# ═══════════════════════════════════════════════════════════════════════════

async def run_runtime(guard: Guard) -> None:
    from db import db

    rows = await db.sample_types.find({}, {"_id": 0}).to_list(500)
    if not rows:
        # Fallback benih adalah perilaku yang DISENGAJA (instalasi baru tidak mati),
        # tetapi ia harus DISEBUT — bukan dianggap hijau diam-diam.
        print(f"{Y}  · koleksi `sample_types` masih KOSONG — sistem memakai nilai benih "
              f"`domain_registry.SAMPLE_TYPES`. Jalankan "
              f"`python scripts/migrate_sample_types.py` agar jenisnya bisa diubah "
              f"pemilik.{X}")
        rows = [dict(v) for v in dr.enum_items("sample_type")]

    docs = await db.md_samples.find({}, {"_id": 0}).to_list(5000)
    usage: Dict[str, int] = {}
    for d in docs:
        for code in types_of(d):
            usage[code] = usage.get(code, 0) + 1
        legacy = str(d.get("sample_type") or "").strip().lower()
        if legacy and legacy not in types_of(d):
            usage[legacy] = usage.get(legacy, 0) + 1

    want_by_type = {_code(r): _fields(r) for r in rows}
    need_design = {_code(r) for r in rows if r.get("requires_design")}
    designs = {d["id"] for d in await db.design_gallery.find(
        {}, {"_id": 0, "id": 1}).to_list(5000)}
    targets = set(dr.values_of("sample_deliver_target"))
    known_fields = {m["value"] for m in dr.enum_items("sample_measurement")}

    guard.bump(8)
    for v in check_still_used(rows, usage):
        guard.add(v)
    for v in check_single_source(docs):
        guard.add(v)
    for v in check_round_types(docs):
        guard.add(v)
    for v in check_measurement_dict(rows, known_fields):
        guard.add(v)
    for v in check_round_measurements(docs, want_by_type):
        guard.add(v)
    for v in check_requires_design(docs, need_design, designs):
        guard.add(v)
    for v in check_execution_marks(docs, targets):
        guard.add(v)
    for v in check_numbers([str(d.get("number") or "") for d in docs]):
        guard.add(v)
    n_rounds = sum(len(d.get("rounds") or []) for d in docs)
    n_multi = sum(1 for d in docs if len(types_of(d)) > 1)
    print(f"  · master hidup: {len(rows)} jenis · dokumen {len(docs)} "
          f"({n_multi} ber-banyak-jenis) · {n_rounds} round · "
          f"jenis terpakai {len(usage)}")


# ═══════════════════════════════════════════════════════════════════════════
# SELF-TEST — bukti-merah DUA ARAH (bersih & pelanggaran)
# ═══════════════════════════════════════════════════════════════════════════

def self_test() -> int:
    cases: List[Tuple[str, bool]] = []

    def case(label: str, cond: bool) -> None:
        cases.append((label, bool(cond)))

    labdip = {"code": "labdip", "active": True, "requires_design": False,
              "measurement_fields": ["delta_e", "colorfastness_wash"]}
    handfeel = {"code": "handfeel", "active": True, "requires_design": False,
                "measurement_fields": ["gsm_actual", "handfeel_score"]}
    proofing = {"code": "proofing", "active": True, "requires_design": True,
                "measurement_fields": ["delta_e", "repeat_cm"]}
    bulk = {"code": "bulk_sample", "active": False, "requires_design": False,
            "measurement_fields": []}
    master = [labdip, handfeel, proofing, bulk]
    known = {"delta_e", "colorfastness_wash", "gsm_actual", "handfeel_score",
             "repeat_cm", "register_mm"}
    want = {"labdip": ["delta_e", "colorfastness_wash"],
            "handfeel": ["gsm_actual", "handfeel_score"],
            "proofing": ["delta_e", "repeat_cm"]}

    def doc(**kw):
        base = {"number": "KSC/SMP-00001", "sample_types": ["labdip"], "rounds": [],
                "design_id": "", "finished_at": "", "delivered_at": "",
                "delivered_to": ""}
        base.update(kw)
        return base

    def rnd(type_code="labdip", status="assessed", meas=None, no=1):
        return {"round_no": no, "type_code": type_code, "status": status,
                "measurements": meas if meas is not None
                else {"delta_e": 1.0, "colorfastness_wash": 4}}

    # ── A — jenis yang masih dipakai dokumen ────────────────────────────────
    case("A bersih (semua jenis yang dipakai ada & aktif)",
         check_still_used(master, {"labdip": 5, "handfeel": 3}) == [])
    case("A memerah bila jenis yang dipakai DIHAPUS dari master",
         len(check_still_used([labdip], {"handfeel": 2})) == 1)
    case("A memerah bila jenis yang dipakai DINONAKTIFKAN",
         len(check_still_used([{**handfeel, "active": False}, labdip],
                              {"handfeel": 3})) == 1)
    case("A TIDAK menuduh `bulk_sample` nonaktif yang tak terpakai (anti tuduh palsu)",
         check_still_used(master, {"labdip": 1}) == [])

    # ── B — satu sumber jenis ───────────────────────────────────────────────
    case("B bersih (hanya `sample_types[]`)",
         check_single_source([doc(), doc(sample_types=["labdip", "handfeel"])]) == [])
    case("B memerah bila field lama `sample_type` masih menempel",
         len(check_single_source([{**doc(), "sample_type": "labdip"}])) == 1)
    case("B memerah bila dokumen TIDAK punya jenis sama sekali",
         len(check_single_source([doc(sample_types=[])])) == 1)

    # ── C — round & jenisnya ────────────────────────────────────────────────
    case("C bersih (dua jenis, dua rangkaian)",
         check_round_types([doc(sample_types=["labdip", "handfeel"],
                                rounds=[rnd("labdip"), rnd("handfeel")])]) == [])
    case("C memerah bila round tanpa `type_code`",
         len(check_round_types([doc(rounds=[{**rnd(), "type_code": ""}])])) == 1)
    case("C memerah bila round berjenis yang tidak diminta dokumen",
         len(check_round_types([doc(sample_types=["labdip"],
                                    rounds=[rnd("handfeel")])])) == 1)

    # ── D — kamus hasil ukur ────────────────────────────────────────────────
    case("D bersih", check_measurement_dict(master, known) == [])
    case("D memerah untuk field hasil ukur tanpa kamus",
         len(check_measurement_dict(
             [{**labdip, "measurement_fields": ["kilap"]}], known)) == 1)
    case("D TIDAK menuduh jenis nonaktif (tak dipakai form mana pun)",
         check_measurement_dict([{**bulk, "active": False,
                                  "measurement_fields": ["kilap"]}], known) == [])

    # ── E — hasil ukur round vs jenisnya ────────────────────────────────────
    case("E bersih", check_round_measurements([doc(rounds=[rnd()])], want) == [])
    case("E memerah bila round menyimpan hasil ukur yang tak diminta",
         len(check_round_measurements(
             [doc(rounds=[rnd(meas={"delta_e": 1, "colorfastness_wash": 4,
                                    "gsm_actual": 150})])], want)) == 1)
    case("E memerah bila hasil ukur wajib HILANG",
         len(check_round_measurements(
             [doc(rounds=[rnd(meas={"delta_e": 1})])], want)) == 1)
    case("E TIDAK menuduh round yang masih TERBUKA (belum ada angkanya)",
         check_round_measurements(
             [doc(rounds=[rnd(status="open", meas={})])], want) == [])
    case("E TIDAK menuduh round HISTORIS yang jujur tanpa bukti "
         "(proof_required=False & kosong)",
         check_round_measurements(
             [doc(rounds=[{**rnd(meas={}), "proof_required": False}])], want) == [])
    case("E TETAP memerah bila round tanpa bukti mengisi SEBAGIAN "
         "(separuh angka lebih menyesatkan)",
         len(check_round_measurements(
             [doc(rounds=[{**rnd(meas={"delta_e": 1}), "proof_required": False}])],
             want)) == 1)

    # ── F — requires_design ─────────────────────────────────────────────────
    case("F bersih (proofing berkode desain nyata)",
         check_requires_design([doc(sample_types=["proofing"], design_id="dsg_1")],
                               {"proofing"}, {"dsg_1"}) == [])
    case("F memerah bila jenis wajib-desain tanpa `design_id`",
         len(check_requires_design([doc(sample_types=["proofing"])],
                                   {"proofing"}, {"dsg_1"})) == 1)
    case("F memerah bila `design_id` menunjuk desain yang tidak ada",
         len(check_requires_design([doc(sample_types=["proofing"], design_id="hantu")],
                                   {"proofing"}, {"dsg_1"})) == 1)
    case("F TIDAK menuduh labdip tanpa desain (memang tidak wajib)",
         check_requires_design([doc()], {"proofing"}, {"dsg_1"}) == [])

    # ── G (data) — urutan & tujuan pelaksanaan ──────────────────────────────
    targets = {"customer", "sales", "supplier", "internal"}
    case("G bersih (jadi → dikirim ke pelanggan)",
         check_execution_marks([doc(finished_at="2026-08-20",
                                    delivered_at="2026-08-21",
                                    delivered_to="customer")], targets) == [])
    case("G bersih untuk sample yang baru JADI (belum dikirim)",
         check_execution_marks([doc(finished_at="2026-08-20")], targets) == [])
    case("G memerah bila DIKIRIM tanpa pernah JADI",
         len(check_execution_marks([doc(delivered_at="2026-08-21",
                                        delivered_to="sales")], targets)) == 1)
    case("G memerah bila DIKIRIM tanpa tujuan",
         len(check_execution_marks([doc(finished_at="2026-08-20",
                                        delivered_at="2026-08-21")], targets)) == 1)
    case("G memerah untuk tujuan di luar daftar sah",
         len(check_execution_marks([doc(finished_at="2026-08-20",
                                        delivered_at="2026-08-21",
                                        delivered_to="tetangga")], targets)) == 1)
    case("G memerah bila ada tujuan tanpa tanggal kirim",
         len(check_execution_marks([doc(finished_at="2026-08-20",
                                        delivered_to="customer")], targets)) == 1)

    # ── G (statik) — pintu pelaksanaan tetap pelaksanaan ────────────────────
    router_ok = ('@router.post("/rnd/samples/{sample_id}/finish")\n'
                 '    actor = await require_permission(request, "rnd", "submit")\n'
                 '@router.post("/rnd/samples/{sample_id}/deliver")\n'
                 '    actor = await require_permission(request, "rnd", "submit")\n')
    backlog_ok = "# SENGAJA BUKAN ANTREAN: finish & deliver …"
    case("G statik bersih", check_exec_doors(router_ok, backlog_ok) == [])
    case("G statik memerah bila endpoint pelaksanaan hilang",
         len(check_exec_doors('@router.post("/rnd/samples/{sample_id}/finish")\n'
                              '    require_permission(request, "rnd", "submit")',
                              backlog_ok)) == 1)
    case("G statik memerah bila izinnya naik jadi pintu keputusan",
         len(check_exec_doors(router_ok.replace('"rnd", "submit"', '"rnd", "decide"'),
                              backlog_ok)) == 1)
    case("G statik memerah bila alasan 'bukan antrean' tak tertulis",
         len(check_exec_doors(router_ok, "QUEUES = []")) == 1)

    # ── D7 — nomor dokumen ──────────────────────────────────────────────────
    case("D7 bersih (pola & unik)",
         check_numbers(["KSC/SMP-00001", "KSC/SMP-00002", "KANDA/SMP-00001"]) == [])
    case("D7 memerah untuk nomor di luar pola (bukti-merah seeder f-string)",
         len(check_numbers(["KSC/SMP-H1DE", "KSC/SMP-00001"])) == 1)
    case("D7 memerah untuk NOMOR KEMBAR",
         len(check_numbers(["KSC/SMP-00001", "KSC/SMP-00001"])) == 1)
    case("D7 memerah DUA KALI bila pola salah DAN kembar",
         len(check_numbers(["KSC/SMP-H1DE", "KSC/SMP-H1DE"])) == 2)

    print(f"{B}== SELF-TEST INV-SAMPLE-01 (bukti-merah dua arah) =={X}")
    fails = 0
    for label, cond in cases:
        print(f"  {G}[OK]{X} {label}" if cond else f"  {R}[GAGAL]{X} {label}")
        fails += 0 if cond else 1
    if fails:
        print(f"{R}SELF-TEST GAGAL: {fails}/{len(cases)} — penjaga tidak bisa dipercaya.{X}")
        return 1
    print(f"{G}SELF-TEST LULUS: {len(cases)}/{len(cases)} kasus (bersih & pelanggaran).{X}")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    guard = Guard("INV-SAMPLE-01",
                  "Master jenis sampling vs dokumen sample (jenis terpakai · satu "
                  "sumber · round ber-jenis · hasil ukur dari master · wajib desain · "
                  "urutan jadi→kirim · nomor unik)")
    run_static(guard)
    if os.environ.get("MONGO_URL"):
        try:
            asyncio.run(run_runtime(guard))
        except Exception as exc:  # noqa: BLE001 — DB mati ≠ pelanggaran invarian
            print(f"{Y}[SKIP]{X} bagian runtime dilewati: {type(exc).__name__}: {exc}")
    else:
        print(f"{Y}[SKIP]{X} MONGO_URL tidak tersedia — hanya pemeriksaan statik.")
    return guard.finish()


if __name__ == "__main__":
    raise SystemExit(main())
