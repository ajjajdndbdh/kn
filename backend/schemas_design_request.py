"""FASE D — skema **PERMINTAAN DESAIN** (`<ENT>/DSR-#####`).

Batas tegas antar tiga dokumen desain (jangan dilanggar — kalau tidak, lahir
dokumen ke-4 yang tumpang tindih):
  * `design_requests` = **pekerjaan siapa & kapan** (penugasan, tenggat, keputusan)
  * `design_gallery`  = **artwork-nya** (berkas, versi, kode, ACC, nilai bintang)
  * `md_specs`        = **angka tekniknya** (gramasi, lebar, konstruksi)
"""
from typing import List, Optional

from pydantic import BaseModel, Field


class ColorTarget(BaseModel):
    """Warna yang diminta (dari Pustaka Warna / Pantone)."""
    color_id: str = ""
    code: str = ""
    name: str = ""
    hex: str = ""


class DesignRequestCreate(BaseModel):
    source: str = "internal"          # so | customer | internal
    so_id: str = ""
    customer_id: str = ""
    line_code: str = ""
    target_type: str = "motif"        # motif | pattern | artwork
    brief: str = ""
    due_date: str = ""
    assigned_to: str = ""
    color_targets: List[ColorTarget] = Field(default_factory=list)
    #: Langsung diajukan (tanpa mampir status draf) — dipakai tombol "Ajukan" di layar.
    submit_now: bool = False


class DesignRequestUpdate(BaseModel):
    brief: Optional[str] = None
    due_date: Optional[str] = None
    target_type: Optional[str] = None
    line_code: Optional[str] = None
    color_targets: Optional[List[ColorTarget]] = None


class DesignRequestAssign(BaseModel):
    assigned_to: str
    due_date: str = ""


class DesignRequestDeliver(BaseModel):
    gallery_id: str
    note: str = ""


class DesignRequestDecision(BaseModel):
    """Keputusan atasan. `reason` WAJIB untuk menolak/minta revisi & batal."""
    reason: str = ""
    note: str = ""
