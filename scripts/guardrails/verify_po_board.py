#!/usr/bin/env python3
"""INV-STAGE-01 — **PAPAN PO PER LINI: tahap dari MASTER, `inspect` tak bisa diklik**.

KELAS BUG YANG DICEGAH (semuanya SENYAP — tidak ada layar merah)
===============================================================
  A. **Urutan tahap yang menunjuk kode yang tidak ada.** Ditemukan saat FASE P
     dibangun (2026-08-21): `product_lines.stage_sequence` menyimpan `yarn`,
     sementara master `process_stages` menyebut langkah itu `benang`
     ("Benang (bahan masuk)"). `yarn` adalah kosakata **tahap BAHAN** (keadaan
     kain), bukan **tahap PROSES** (langkah kerja) — satu kata dipakai untuk dua
     arti. Akibatnya papan menampilkan chip **"Yarn"** hasil menebak dari kodenya,
     dan master tahap yang diubah pemilik **tidak berpengaruh apa pun** pada tahap
     pertama. Tidak ada galat, tidak ada yang tahu.
  B. **Papan mengaku "sudah diinspeksi" tanpa dokumen inspeksi.** Kalau tahap
     `inspect` bisa ditandai tangan, catatan mutu menjadi opini — dan barang cacat
     lolos ke pelanggan atas dasar catatan yang salah. Karena itu tahap turunan
     **ditolak** di layanan, dan gate ini memeriksa bahwa (1) penolakannya masih
     ada di kode, dan (2) tidak ada satu pun dokumen yang membawa tandanya (mis.
     disuntik skrip/seed).
  C. **Pintu ke-5 lahirnya PO lahir tanpa field papan.** PO dibuat dari empat
     tempat; yang kelima akan melahirkan dokumen tanpa `stage_progress` sehingga
     papan tidak bisa membedakan "belum ditandai" dari "dokumen lahir sebelum
     papan ada".
  D. **Tanda tahap tanpa siapa & kapan.** User story P-2 pemilik: *"saya klik
     'celup selesai'; tercatat siapa & kapan"*. Entri tanpa `by`/`at` membuat
     papan tak bisa dipertanggungjawabkan — dan itu justru gunanya papan.
  E. **Tanda tahap di luar urutan lini dokumen.** Sisa dari lini yang berubah:
     chip yang tak pernah tampil, tetapi tetap dihitung sebagai "sudah selesai".

YANG DIPERIKSA
--------------
STATIK  (tanpa basis data)
  S1. Keempat penulis `purchase_orders` men-spread `PO_BOARD_EMPTY`.
  S2. `po_board_service` masih MENOLAK tahap turunan (`DERIVED_STAGES` dipakai di
      `set_stage`, bukan cuma didefinisikan) & `inspect` masih terdaftar turunan.
  S3. Layar papan (`features/purchasing/PoBoardView.jsx`) ada dan **menonaktifkan**
      kontrol untuk tahap ber-`locked` — layar yang menawarkan tombol yang server
      PASTI tolak adalah jebakan, bukan fitur.
RUNTIME (Mongo langsung — opini kedua, tidak lewat API yang sedang diuji)
  R1. (A) semua kode di `product_lines.stage_sequence` ada di `process_stages`.
  R2. (E) semua `stage_progress[].stage_code` ada di urutan lini PO-nya.
  R3. (B) nol tanda tahap untuk tahap TURUNAN.
  R4. (C) semua dokumen `purchase_orders` punya field `stage_progress`.
  R5. (D) tiap tanda tahap membawa `by` + `at` + status yang dikenal.

Resilient: tanpa MONGO_URL / basis data mati → bagian runtime SKIP (exit 0).

Usage:
    python scripts/guardrails/verify_po_board.py
    python scripts/guardrails/verify_po_board.py -v
    python scripts/guardrails/verify_po_board.py --self-test
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env")
except Exception:  # noqa: BLE001
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import B, C, G, R, X, Y, Guard  # noqa: E402

BE = ROOT / "backend"
FE = ROOT / "frontend" / "src"

SERVICE_REL = "services/po_board_service.py"
BOARD_VIEW_REL = "features/purchasing/PoBoardView.jsx"

#: Berkas yang MENYISIPKAN dokumen `purchase_orders` (empat pintu lahirnya PO).
PO_WRITERS = (
    "services/pr_sourcing_service.py",
    "services/rfq_service.py",
    "services/blanket_po_service.py",
    "routers/purchase_orders.py",
)

INSERT_RE = re.compile(r"db\.purchase_orders\.insert_(?:one|many)\s*\(")
STATUSES = ("pending", "in_progress", "done")


# ═══════════════════════════════════════════════════════════════════════════
# STATIK
# ═══════════════════════════════════════════════════════════════════════════
def check_board_field(sources: Dict[str, str]) -> List[str]:
    """S1 — penulis PO wajib men-spread `PO_BOARD_EMPTY`."""
    out: List[str] = []
    writers = sorted(rel for rel, text in sources.items() if INSERT_RE.search(text))
    for rel in writers:
        if "PO_BOARD_EMPTY" not in sources[rel]:
            out.append(
                f"{rel} menyisipkan dokumen `purchase_orders` TANPA "
                "`po_board_service.PO_BOARD_EMPTY` → PO baru lahir tanpa field papan "
                "`stage_progress`, dan papan tidak bisa membedakan 'belum ditandai' "
                "dari 'dokumen lahir sebelum papan ada'.")
    for rel in PO_WRITERS:
        if rel not in writers:
            out.append(
                f"{rel} tidak lagi terdeteksi sebagai penulis PO — pola pencarian gate "
                "ini kedaluwarsa. Perbaiki gate (jangan diabaikan): gate yang kehilangan "
                "jejak pintunya berhenti menjaga apa pun.")
    return out


def check_derived_rule(service_text: str) -> List[str]:
    """S2 — penolakan tahap turunan masih hidup di kode."""
    out: List[str] = []
    if not service_text:
        return ["services/po_board_service.py tidak ditemukan — papan PO kehilangan "
                "satu-satunya tempat aturannya ditulis."]
    m = re.search(r"DERIVED_STAGES\s*=\s*\(([^)]*)\)", service_text)
    codes = re.findall(r'"([a-z_]+)"', m.group(1)) if m else []
    if "inspect" not in codes:
        out.append("`DERIVED_STAGES` tidak lagi memuat `inspect` → tahap inspeksi bisa "
                   "ditandai manual, dan papan bisa mengaku sudah diinspeksi tanpa satu "
                   "dokumen inspeksi pun.")
    body = service_text.split("async def set_stage", 1)
    if len(body) < 2:
        out.append("fungsi `set_stage()` hilang dari `po_board_service` — tidak ada lagi "
                   "satu pintu tulis untuk progres tahap.")
    elif "DERIVED_STAGES" not in body[1]:
        out.append("`set_stage()` tidak lagi memeriksa `DERIVED_STAGES` → tahap turunan "
                   "hanya 'dianggap' turunan di layar, sementara server menerimanya.")
    return out


def check_board_view(view_text: str) -> List[str]:
    """S3 — layar menonaktifkan kontrol tahap terkunci."""
    if not view_text:
        return [f"{BOARD_VIEW_REL} tidak ditemukan — papan PO tidak punya layar, jadi "
                "fase ini hanya bisa dibuktikan lewat API (pemilik tidak bisa memakainya)."]
    out: List[str] = []
    if not re.search(r"disabled=\{[^}]*lock", view_text, re.I):
        out.append(f"{BOARD_VIEW_REL} tidak menonaktifkan kontrol tahap ber-`locked` "
                   "(`disabled={… locked …}`) → layar menawarkan tombol yang server PASTI "
                   "tolak 409. Tombol yang tidak melakukan apa pun adalah jebakan.")
    if "locked_reason" not in view_text:
        out.append(f"{BOARD_VIEW_REL} tidak menampilkan `locked_reason` → pengguna melihat "
                   "chip mati tanpa penjelasan, lalu melaporkannya sebagai kerusakan.")
    return out


# ═══════════════════════════════════════════════════════════════════════════
# RUNTIME — fungsi MURNI supaya `--self-test` bisa membuktikannya merah
# ═══════════════════════════════════════════════════════════════════════════
def check_sequences(lines: Sequence[Dict[str, Any]],
                    stage_codes: set) -> List[str]:
    """R1 — kode tahap pada urutan lini wajib ada di master tahap."""
    out: List[str] = []
    for ln in lines:
        for code in (ln.get("stage_sequence") or []):
            c = str(code or "").strip().lower()
            if c and c not in stage_codes:
                out.append(
                    f"lini `{ln.get('code')}` memuat tahap `{c}` yang TIDAK ADA di master "
                    "`process_stages` → papan menampilkan label hasil menebak dari kodenya, "
                    "dan perubahan master tidak berpengaruh pada tahap itu. Perbaiki "
                    "urutan lini (Pengaturan → Master → Lini Produk) atau tambahkan "
                    "tahapnya (Master → Tahapan Proses).")
    return out


def check_progress(pos: Sequence[Dict[str, Any]], lines_by_code: Dict[str, List[str]],
                   derived: Sequence[str]) -> List[str]:
    """R2–R5 — tanda tahap: field ada · di dalam urutan · bukan turunan · ber-jejak."""
    out: List[str] = []
    for po in pos:
        num = po.get("po_number") or po.get("id")
        if "stage_progress" not in po:
            out.append(f"{num}: dokumen tidak punya field `stage_progress` → lahir dari "
                       "pintu yang belum memakai `PO_BOARD_EMPTY` (atau belum dimigrasi: "
                       "`python scripts/migrate_po_stage_progress.py`).")
            continue
        seq: List[str] = []
        for code in (po.get("line_codes") or []):
            seq.extend(lines_by_code.get(str(code or "").strip().lower(), []))
        for row in (po.get("stage_progress") or []):
            code = str((row or {}).get("stage_code") or "").strip().lower()
            if code in derived:
                out.append(f"{num}: menyimpan tanda tahap TURUNAN `{code}` — tahap ini "
                           "hanya boleh mengikuti bukti inspeksi, bukan ditandai orang "
                           "atau disuntik skrip.")
            elif seq and code not in seq:
                out.append(f"{num}: tanda tahap `{code}` di luar urutan lini dokumen ini "
                           f"({'→'.join(seq)}) → chip-nya tak pernah tampil tetapi tetap "
                           "terhitung 'sudah selesai'.")
            status = str((row or {}).get("status") or "")
            if status not in STATUSES:
                out.append(f"{num}: tanda tahap `{code}` ber-status `{status}` yang tidak "
                           f"dikenal (sah: {', '.join(STATUSES)}).")
            if not str((row or {}).get("by") or "").strip():
                out.append(f"{num}: tanda tahap `{code}` tanpa `by` — papan tidak bisa "
                           "menjawab SIAPA yang menandainya (user story P-2).")
            if not str((row or {}).get("at") or "").strip():
                out.append(f"{num}: tanda tahap `{code}` tanpa `at` — papan tidak bisa "
                           "menjawab KAPAN tahap itu selesai.")
    return out


async def run_runtime(guard: Guard, verbose: bool = False) -> None:
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=4000)
    dbx = client[os.environ.get("DB_NAME", "test_database")]
    await dbx.command("ping")

    lines = await dbx.product_lines.find(
        {}, {"_id": 0, "code": 1, "stage_sequence": 1}).to_list(500)
    stage_codes = {str(s.get("code") or "").strip().lower()
                   for s in await dbx.process_stages.find({}, {"_id": 0, "code": 1}).to_list(500)}
    if not stage_codes:
        print(f"{Y}[SKIP]{X} master `process_stages` masih kosong — jalankan "
              "`python scripts/migrate_process_stages.py` lebih dulu.")
        return
    pos = await dbx.purchase_orders.find(
        {}, {"_id": 0, "id": 1, "po_number": 1, "line_codes": 1, "stage_progress": 1}
    ).to_list(5000)

    lines_by_code = {str(ln.get("code") or "").strip().lower():
                     [str(s or "").strip().lower() for s in (ln.get("stage_sequence") or [])]
                     for ln in lines}
    guard.bump(len(lines) + len(pos))
    for v in check_sequences(lines, stage_codes):
        guard.add(v)
    for v in check_progress(pos, lines_by_code, ("inspect",)):
        guard.add(v)
    ber_progres = sum(1 for p in pos if (p.get("stage_progress") or []))
    print(f"{C}[DB]{X} {len(lines)} lini · {len(stage_codes)} tahap master · {len(pos)} PO "
          f"({ber_progres} sudah ada tahap ditandai).")
    if verbose:
        for ln in lines:
            print(f"      {ln.get('code'):10s} {'→'.join(ln.get('stage_sequence') or [])}")


# ═══════════════════════════════════════════════════════════════════════════
# SELF-TEST (bukti-merah dua arah — tanpa DB)
# ═══════════════════════════════════════════════════════════════════════════
def self_test() -> int:  # noqa: C901 — daftar kasus memang panjang & linear
    cases: List[Tuple[str, bool]] = []

    def case(label: str, cond: bool) -> None:
        cases.append((label, bool(cond)))

    OK_SRC = {rel: ('await db.purchase_orders.insert_one({**PO_BOARD_EMPTY})\n')
              for rel in PO_WRITERS}
    case("S1 keempat pintu memakai `PO_BOARD_EMPTY` → bersih",
         check_board_field(OK_SRC) == [])
    bad = dict(OK_SRC)
    bad["services/rfq_service.py"] = "await db.purchase_orders.insert_one({'id': 1})\n"
    case("S1 satu pintu lupa field papan → MERAH",
         len([v for v in check_board_field(bad) if "TANPA" in v]) == 1)
    case("S1 pintu yang HILANG dari kode → MERAH (gate kedaluwarsa berisik)",
         any("kedaluwarsa" in v for v in check_board_field(
             {k: v for k, v in list(OK_SRC.items())[:3]})))

    svc_ok = ('DERIVED_STAGES = ("inspect",)\n'
              'async def set_stage(po_id):\n'
              '    if code in DERIVED_STAGES:\n        raise BoardError("x")\n')
    case("S2 aturan turunan lengkap → bersih", check_derived_rule(svc_ok) == [])
    case("S2 `inspect` dicabut dari daftar turunan → MERAH",
         len(check_derived_rule(svc_ok.replace('"inspect",', ''))) >= 1)
    case("S2 `set_stage` berhenti memeriksa daftar turunan → MERAH",
         any("tidak lagi memeriksa" in v for v in check_derived_rule(
             'DERIVED_STAGES = ("inspect",)\nasync def set_stage(po_id):\n    pass\n')))
    case("S2 berkas layanan hilang → MERAH", len(check_derived_rule("")) == 1)

    view_ok = ('<button disabled={st.locked || busy} title={st.locked_reason}>x</button>')
    case("S3 layar menonaktifkan chip terkunci + menjelaskan → bersih",
         check_board_view(view_ok) == [])
    case("S3 chip terkunci tetap bisa diklik → MERAH",
         any("menonaktifkan" in v for v in check_board_view(
             '<button onClick={go} title={st.locked_reason}>x</button>')))
    case("S3 tanpa `locked_reason` → MERAH",
         any("locked_reason" in v for v in check_board_view(
             '<button disabled={st.locked}>x</button>')))
    case("S3 layar belum ada → MERAH", len(check_board_view("")) == 1)

    master = {"benang", "tenun", "celup", "inspect"}
    case("R1 urutan lini memakai kode master → bersih",
         check_sequences([{"code": "woven",
                           "stage_sequence": ["benang", "tenun", "celup", "inspect"]}],
                         master) == [])
    case("R1 kode `yarn` (kosakata tahap BAHAN) → MERAH — inilah drift 2026-08-21",
         len(check_sequences([{"code": "woven",
                               "stage_sequence": ["yarn", "tenun"]}], master)) == 1)

    lines_by_code = {"woven": ["benang", "tenun", "celup", "inspect"]}
    ok_po = {"id": "po1", "po_number": "PO-1", "line_codes": ["woven"],
             "stage_progress": [{"stage_code": "tenun", "status": "done",
                                 "by": "Dewi", "at": "2026-08-21T00:00:00Z"}]}
    case("R PO bertanda tahap yang sah → bersih",
         check_progress([ok_po], lines_by_code, ("inspect",)) == [])
    case("R4 dokumen tanpa field papan → MERAH",
         len(check_progress([{"id": "po2", "po_number": "PO-2", "line_codes": ["woven"]}],
                            lines_by_code, ("inspect",))) == 1)
    case("R PO dengan field papan KOSONG tidak dituduh apa pun",
         check_progress([{"id": "po3", "po_number": "PO-3", "line_codes": ["woven"],
                          "stage_progress": []}], lines_by_code, ("inspect",)) == [])
    case("R3 tanda tahap TURUNAN (`inspect`) → MERAH",
         any("TURUNAN" in v for v in check_progress(
             [{**ok_po, "stage_progress": [{"stage_code": "inspect", "status": "done",
                                            "by": "X", "at": "t"}]}],
             lines_by_code, ("inspect",))))
    case("R2 tanda tahap di luar urutan lini → MERAH",
         any("di luar urutan" in v for v in check_progress(
             [{**ok_po, "stage_progress": [{"stage_code": "printing", "status": "done",
                                            "by": "X", "at": "t"}]}],
             lines_by_code, ("inspect",))))
    case("R5 tanda tahap tanpa `by` → MERAH",
         any("tanpa `by`" in v for v in check_progress(
             [{**ok_po, "stage_progress": [{"stage_code": "tenun", "status": "done",
                                            "by": "", "at": "t"}]}],
             lines_by_code, ("inspect",))))
    case("R5 tanda tahap tanpa `at` → MERAH",
         any("tanpa `at`" in v for v in check_progress(
             [{**ok_po, "stage_progress": [{"stage_code": "tenun", "status": "done",
                                            "by": "X", "at": ""}]}],
             lines_by_code, ("inspect",))))
    case("R5 status asing → MERAH",
         any("tidak" in v and "dikenal" in v for v in check_progress(
             [{**ok_po, "stage_progress": [{"stage_code": "tenun", "status": "beres",
                                            "by": "X", "at": "t"}]}],
             lines_by_code, ("inspect",))))
    case("R PO tanpa lini (dokumen lama) tidak dituduh soal urutan",
         check_progress([{"id": "po4", "po_number": "PO-4", "line_codes": [],
                          "stage_progress": [{"stage_code": "apa_saja", "status": "done",
                                              "by": "X", "at": "t"}]}],
                        lines_by_code, ("inspect",)) == [])

    print(f"{B}== SELF-TEST INV-STAGE-01 (bukti-merah dua arah) =={X}")
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
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    guard = Guard("INV-STAGE-01",
                  "Papan PO per lini (tahap dari master · `inspect` turunan · "
                  "tanda tahap ber-jejak)")

    sources: Dict[str, str] = {}
    for rel in PO_WRITERS + (SERVICE_REL,):
        path = BE / rel
        if path.exists():
            sources[rel] = path.read_text(encoding="utf-8")
    guard.bump(len(PO_WRITERS) + 3)
    for v in check_board_field({k: v for k, v in sources.items() if k != SERVICE_REL}):
        guard.add(v)
    for v in check_derived_rule(sources.get(SERVICE_REL, "")):
        guard.add(v)
    view_path = FE / BOARD_VIEW_REL
    for v in check_board_view(view_path.read_text(encoding="utf-8")
                              if view_path.exists() else ""):
        guard.add(v)

    if os.environ.get("MONGO_URL"):
        try:
            asyncio.run(run_runtime(guard, verbose))
        except Exception as exc:  # noqa: BLE001 — DB mati ≠ pelanggaran invarian
            print(f"{Y}[SKIP]{X} bagian runtime dilewati: {type(exc).__name__}: {exc}")
    else:
        print(f"{Y}[SKIP]{X} MONGO_URL tidak tersedia — hanya pemeriksaan statik.")
    return guard.finish()


if __name__ == "__main__":
    raise SystemExit(main())
