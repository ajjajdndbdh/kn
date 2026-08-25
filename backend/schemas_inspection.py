"""FASE I — skema masukan **INSPEKSI & QC SEBAGAI DOKUMEN** (`<ENT>/INS-#####`).

Skema di sini sengaja TIPIS: ia hanya menerima apa yang diketik petugas. Angka
turunan (poin cacat, grade, ringkasan dokumen) TIDAK boleh masuk dari luar — itu
dihitung `qc_inspection_service` dan diringkas `inspection_service`, karena begitu
satu angka turunan bisa dikirim klien, lahir sumber kebenaran kedua yang tidak
pernah cocok dengan roll-nya (kelas cacat §3.4 rencana MD-ERP).
"""
from typing import List, Optional

from pydantic import BaseModel, Field

from schemas_purchasing import RollDefectInput


class InspectionCreate(BaseModel):
    """Buat SPK inspeksi manual (jalur otomatisnya: penerimaan PO → `qc_pending`)."""
    kind: str = Field(..., description="po_receipt | makloon_output | return_customer | "
                                      "return_supplier | replacement")
    ref_doc_type: str = ""
    ref_doc_id: str = ""
    task_id: str = ""
    line_code: str = ""
    spk_date: str = ""
    assigned_to: str = ""
    bagian: str = ""
    baseline_sample_id: str = ""
    remark: str = ""


class InspectionAssign(BaseModel):
    assigned_to: str = ""
    bagian: str = ""
    spk_date: str = ""


class InspectionLineInspect(BaseModel):
    """Hasil pemeriksaan SATU baris (satu roll, atau satu barang retur).

    `defects` dipakai mesin 4-point yang SUDAH ADA; `color_result`/`handfeel_result`
    adalah yang baru di FASE I — pembanding terhadap sample yang di-ACC.
    """
    defects: List[RollDefectInput] = []
    gsm_actual: Optional[float] = None
    width_actual: Optional[float] = None
    color_result: str = ""          # sesuai | beda_shade | tolak
    handfeel_result: str = ""       # sesuai | beda | tolak
    handfeel_score: Optional[float] = None    # 1..5
    delta_e: Optional[float] = None
    decision: str = ""              # terima | terima_sebagian | turun_grade | tolak
    remark: str = ""
    supplier_lot: str = ""
    dye_lot: str = ""
    shade_ref: str = ""


class InspectionFinish(BaseModel):
    decision: str = Field(..., description="terima | terima_sebagian | turun_grade | tolak")
    remark: str = ""


class InspectionReason(BaseModel):
    """Alasan WAJIB (buka kembali dokumen · lepas tahanan roll)."""
    reason: str = ""


class ReturnMilestoneInput(BaseModel):
    """FASE I.F — tonggak waktu retur dari lembar pemilik (satu titik per panggilan)."""
    milestone: str = Field(..., description="shipped_to_store | shipped_to_customer | "
                                           "goods_arrived")
    at: str = ""                    # kosong = hari ini
    note: str = ""


class ReturnComplaintInput(BaseModel):
    """FASE I.F — kode keluhan pelanggan (master `complaint-reasons`) + catatannya."""
    complaint_code: str = ""
    complaint_note: str = ""
