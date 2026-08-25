"""FASE F — Schemas **R&D & Design** (`md_specs`, `md_samples`).

Di-re-export lewat `schemas.py`. Rujukan: `docs/KN_31_PLAN_FASE_F_RND_DESIGN.md`
(PS-12 alur R&D · PS-13 warna berstandar · PS-14 design/pattern · PS-18 iterasi round
· PS-19 stok sample). Angka desimal memakai tipe `QtyDecimal`/`MoneyDecimal` supaya
input "10,5" maupun "10.5" diterima seragam (PS-15 / R5).
"""
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from core_utils import MoneyDecimal, OptQtyDecimal, QtyDecimal


class SpecTarget(BaseModel):
    """Target teknis kain yang diminta R&D (dipakai membentuk produk saat ACC)."""
    stage: str = "finished"
    fabric_type: str = ""          # WAJIB (INV-DOMAIN-02) — woven | knit
    gramasi: OptQtyDecimal = None  # GSM — wajib untuk stage >= grey (D-22)
    lebar: OptQtyDecimal = None    # cm
    yarn_count: str = ""
    yarn_count_system: str = ""
    epi: OptQtyDecimal = None
    ppi: OptQtyDecimal = None
    warp_count: str = ""
    weft_count: str = ""
    reed_width: OptQtyDecimal = None
    grade: str = ""


class ColorTarget(BaseModel):
    """Warna target — WAJIB dari pustaka warna (PS-13: tidak boleh teks bebas)."""
    color_id: str = ""
    code: str = ""
    name: str = ""
    hex: str = ""


class SpecInput(BaseModel):
    title: str = ""
    category: str = ""
    base_unit: str = ""
    sku_hint: str = ""                  # kode SKU usulan (dipakai saat ACC)
    sample_type_hint: str = "labdip"    # labdip | proofing | bulk_sample
    target: SpecTarget = Field(default_factory=SpecTarget)
    color_target: ColorTarget = Field(default_factory=ColorTarget)
    design_id: str = ""
    design_version: int = 0
    customer_id: str = ""
    so_id: str = ""
    target_price: MoneyDecimal = 0
    notes: str = ""
    line_code: str = ""                 # FASE L — lini kerja MD (woven/knit/printing/…)


class SpecPatch(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    base_unit: Optional[str] = None
    sku_hint: Optional[str] = None
    sample_type_hint: Optional[str] = None
    target: Optional[SpecTarget] = None
    color_target: Optional[ColorTarget] = None
    design_id: Optional[str] = None
    design_version: Optional[int] = None
    customer_id: Optional[str] = None
    so_id: Optional[str] = None
    target_price: Optional[float] = None
    notes: Optional[str] = None


class ReasonBody(BaseModel):
    reason: str = Field(..., min_length=3)
    note: str = ""


class SpecApproveBody(BaseModel):
    """ACC spesifikasi → produk lahir (lifecycle `disetujui`, BELUM boleh dijual)."""
    sku: str = ""
    name: str = ""
    price: MoneyDecimal = 0
    note: str = ""


class SampleInput(BaseModel):
    spec_id: str = ""
    # FASE S — BOLEH LEBIH DARI SATU jenis (labdip + handfeel + proofing). Kosong =
    # ambil usulan dari master lini (`product_lines.sample_types_default`), bukan
    # bawaan yang diketik di kode.
    sample_types: List[str] = Field(default_factory=list)
    # Kompatibilitas pemanggil lama (skrip & integrasi yang masih mengirim tunggal).
    # SENGAJA tidak diberi bawaan "labdip": bawaan di sini akan mengalahkan usulan
    # master lini dan membuat masternya tampak tidak berpengaruh.
    sample_type: str = ""
    title: str = ""
    brief: str = ""
    color_target: ColorTarget = Field(default_factory=ColorTarget)
    design_id: str = ""
    design_version: int = 0
    customer_id: str = ""
    so_id: str = ""
    target_date: str = ""
    qty_requested: QtyDecimal = 0
    unit: str = ""
    line_code: str = ""                # FASE L — lini kerja MD (warisi spec bila kosong)


class SamplePatch(BaseModel):
    title: Optional[str] = None
    brief: Optional[str] = None
    color_target: Optional[ColorTarget] = None
    design_id: Optional[str] = None
    design_version: Optional[int] = None
    target_date: Optional[str] = None
    qty_requested: Optional[float] = None
    unit: Optional[str] = None
    # FASE S — jenis boleh ditambah selama permintaan masih terbuka; tautan pesanan
    # & pelanggan bisa dipasang belakangan (user story S.F-2).
    sample_types: Optional[List[str]] = None
    so_id: Optional[str] = None
    customer_id: Optional[str] = None


class SampleSendBody(BaseModel):
    """Kirim permintaan ke ≥1 supplier × ≥1 jenis (bisa dibandingkan hasilnya)."""
    supplier_ids: List[str] = Field(default_factory=list)
    # Kosong = semua jenis yang diminta dokumen. Diisi bila pemakai hanya ingin
    # mengirim sebagian (mis. labdip dulu, handfeel menyusul).
    type_codes: List[str] = Field(default_factory=list)
    due_date: str = ""
    note: str = ""


class RoundOpenBody(BaseModel):
    supplier_id: str
    # FASE S — WAJIB diisi bila dokumen menempuh >1 jenis; server menolak bila kosong
    # supaya round tidak pernah masuk ke rangkaian yang salah.
    type_code: str = ""
    due_date: str = ""
    note: str = ""
    reason: str = ""          # wajib bila melewati batas `rnd.max_rounds`


class RoundSubmitBody(BaseModel):
    """Setor hasil round.

    FASE S — `measurements` sengaja **bebas-kunci** (`Dict[str, float|None]`), bukan
    5 field tetap seperti sebelumnya. Kolom yang WAJIB diisi ditentukan master jenis
    (`sample_types.measurement_fields`) dan divalidasi di layanan; skema yang
    mengunci 5 nama justru sumber cacatnya — `handfeel_score` tidak punya tempat
    sementara `delta_e` diminta pada jenis yang tidak mengukur warna.
    """
    note: str = ""
    measurements: Dict[str, Optional[float]] = Field(default_factory=dict)
    cost: MoneyDecimal = 0


class RoundAssessBody(BaseModel):
    result: str            # acc | revisi | tolak
    score: OptQtyDecimal = None
    note: str = ""


class SampleDecideBody(BaseModel):
    supplier_id: str
    reason_code: str
    note: str = ""
    price: MoneyDecimal = 0
    supplier_sku: str = ""
    supplier_uom: str = ""
    moq: QtyDecimal = 0
    lead_time_days: int = 0
    valid_to: str = ""


class IssueMaterialBody(BaseModel):
    roll_id: str
    qty: QtyDecimal
    note: str = ""


# ─── FASE S — pelaksanaan sample (user story S.F-4) ──────────────────────────
class SampleFinishBody(BaseModel):
    """Tandai sample JADI. Tanggal kosong = hari ini (dicatat penuh dengan jam)."""
    date: str = ""
    note: str = ""


class SampleDeliverBody(BaseModel):
    """Catat sample dikirim — `to` WAJIB (pelanggan/sales/supplier/internal).

    `to` tidak diberi bawaan DENGAN SENGAJA: bawaan apa pun akan membuat separuh
    dokumen bertujuan "pelanggan" hanya karena tombolnya ditekan cepat, dan laporan
    pengiriman sample berhenti bisa dipakai.
    """
    to: str = Field(..., min_length=2)
    to_name: str = ""
    date: str = ""
    note: str = ""


class DesignVersionBody(BaseModel):
    note: str = ""
    repeat_cm: OptQtyDecimal = None
    color_count: Optional[int] = None
    screen_count: Optional[int] = None


class DesignMasterPatch(BaseModel):
    """Perluasan master design (PS-14) pada koleksi `design_gallery` yang SUDAH ADA."""
    code: Optional[str] = None
    design_type: Optional[str] = None      # motif | pattern | artwork
    repeat_cm: Optional[float] = None
    color_count: Optional[int] = None
    screen_count: Optional[int] = None
    status: Optional[str] = None           # draft | approved | retired
