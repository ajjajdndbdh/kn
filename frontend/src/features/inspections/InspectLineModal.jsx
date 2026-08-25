/**
 * InspectLineModal — FASE I · **isi hasil pemeriksaan SATU baris** (pop-up).
 *
 * Yang diketik petugas hanya KENYATAAN: cacat yang dilihat (4-point), gramasi & lebar
 * hasil ukur, lalu hasil banding terhadap sample yang di-ACC (warna & handfeel).
 * Poin cacat dan grade **tidak diisi di sini** — keduanya dihitung server
 * (`qc_inspection_service` → `grade_service`). Kalau layar boleh mengirimnya, lahir
 * sumber kebenaran kedua yang tidak pernah cocok dengan roll-nya (§3.4 rencana).
 *
 * Angka poin yang tampil di bawah hanya **pratinjau aritmetika yang sama** (nilai ×
 * jumlah) supaya petugas tahu akibat isiannya sebelum menyimpan; yang disimpan tetap
 * hitungan server, dan panel rincian menampilkan hasil dari server itu.
 */
import { useEffect, useMemo, useState } from "react";
import { Ruler } from "lucide-react";
import FormModal from "../../components/FormModal";
import KNSelect from "../../components/KNSelect";
import QtyDual from "../../components/QtyDual";
import { apiText, inspectLine, INS_COLOR_LABEL, INS_HANDFEEL_LABEL } from "./inspectionsApi";

// Nilai poin 4-point yang sah (D-01): 1 · 2 · 3 · 4 — makin panjang cacatnya, makin besar.
const POINT_ROWS = [
  { value: 1, label: "1 poin", hint: "cacat sampai 3 inci" },
  { value: 2, label: "2 poin", hint: "3–6 inci" },
  { value: 3, label: "3 poin", hint: "6–9 inci" },
  { value: 4, label: "4 poin", hint: "lebih dari 9 inci / lubang" },
];

const KOSONG = { 1: "", 2: "", 3: "", 4: "" };

export default function InspectLineModal({ open, onClose, doc, line, meta, onSaved }) {
  const [counts, setCounts] = useState(KOSONG);
  const [form, setForm] = useState({
    gsm_actual: "", width_actual: "", color_result: "", handfeel_result: "",
    handfeel_score: "", delta_e: "", remark: "",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  // Isi ulang setiap kali baris berganti — tanpa ini hasil roll sebelumnya
  // “menempel” di form roll berikutnya (kelas bug yang paling mudah lolos uji).
  useEffect(() => {
    if (!open || !line) return;
    setCounts(KOSONG);
    setForm({
      gsm_actual: line.gsm_actual ?? "",
      width_actual: line.width_actual ?? "",
      color_result: line.color_result || "",
      handfeel_result: line.handfeel_result || "",
      handfeel_score: line.handfeel_score ?? "",
      delta_e: line.delta_e ?? "",
      remark: line.remark || "",
    });
    setErr("");
  }, [open, line]);

  const set = (patch) => setForm((f) => ({ ...f, ...patch }));

  const previewPoints = useMemo(
    () => POINT_ROWS.reduce((sum, r) => sum + (Number(counts[r.value]) || 0) * r.value, 0),
    [counts]);

  const colorOptions = (meta?.color_results || []).length
    ? meta.color_results
    : Object.entries(INS_COLOR_LABEL).map(([value, label]) => ({ value, label }));
  const handfeelOptions = (meta?.handfeel_results || []).length
    ? meta.handfeel_results
    : Object.entries(INS_HANDFEEL_LABEL).map(([value, label]) => ({ value, label }));

  const policy = meta?.policy || {};
  const akanDitahan =
    (form.color_result && form.color_result !== "sesuai"
      && policy.color_mismatch_action === "tahan")
    || (form.handfeel_result && form.handfeel_result !== "sesuai"
      && policy.handfeel_mismatch_action === "tahan");

  async function simpan() {
    if (!line) return;
    setBusy(true); setErr("");
    try {
      const defects = POINT_ROWS
        .filter((r) => Number(counts[r.value]) > 0)
        .map((r) => ({ point_value: r.value, count: Number(counts[r.value]) }));
      const fresh = await inspectLine(doc.id, line.id, {
        defects,
        gsm_actual: form.gsm_actual === "" ? null : Number(form.gsm_actual),
        width_actual: form.width_actual === "" ? null : Number(form.width_actual),
        color_result: form.color_result,
        handfeel_result: form.handfeel_result,
        handfeel_score: form.handfeel_score === "" ? null : Number(form.handfeel_score),
        delta_e: form.delta_e === "" ? null : Number(form.delta_e),
        remark: form.remark,
      });
      onSaved?.(fresh);
    } catch (e) {
      setErr(apiText(e, "Gagal menyimpan hasil pemeriksaan."));
    } finally { setBusy(false); }
  }

  if (!line) return null;

  return (
    <FormModal
      open={open} onClose={onClose}
      title={`Hasil periksa · ${line.roll_no || line.sku || "barang retur"}`}
      subtitle={doc?.baseline_sample_number
        ? `Dibandingkan dengan sample yang di-ACC: ${doc.baseline_sample_number}${doc.baseline_color ? ` · ${doc.baseline_color}` : ""}`
        : "Belum ada sample ACC untuk barang ini — hasil warna & handfeel dicatat sebagai pengamatan"}
      icon={Ruler} size="lg" testId="ins-line-modal"
      onSubmit={simpan} submitLabel="Simpan hasil" busy={busy} error={err}
      submitTestId="ins-line-submit"
    >
      <div className="grid gap-3">
        <div className="rounded-lg border border-[#EFF0F2] bg-[#FAFBFC] px-3 py-2">
          <p className="text-[11px] text-[#6B6B73]">
            {line.article || "—"}{line.lot ? ` · lot ${line.lot}` : ""}
            {line.dye_lot ? ` · dye lot ${line.dye_lot}` : ""}
          </p>
          <p className="mt-0.5 text-[11.5px] font-semibold text-[#1C1C1E]">
            <QtyDual rolls={line.qty_rolls} measure={line.quantity} unit={line.unit}
              testId="ins-line-modal-qty" />
            {line.gsm_standard ? <span className="ml-2 text-[11px] font-normal text-[#6B6B73]">
              standar {line.gsm_standard} g/m²
              {line.width_standard ? ` · ${line.width_standard} cm` : ""}
            </span> : null}
          </p>
        </div>

        {/* Cacat 4-point — hanya untuk baris yang menunjuk ROLL fisik */}
        {line.roll_id ? (
          <div>
            <span className="field-label">Cacat 4-point (jumlah per nilai poin)</span>
            <div className="grid gap-2 sm:grid-cols-4">
              {POINT_ROWS.map((r) => (
                <label key={r.value} className="block">
                  <span className="block text-[10.5px] text-[#6B6B73]">
                    {r.label} <span className="text-[#9A9BA3]">({r.hint})</span>
                  </span>
                  <input data-testid={`ins-defect-${r.value}`} type="number" min="0"
                    className="field" value={counts[r.value]}
                    onChange={(e) => setCounts((c) => ({ ...c, [r.value]: e.target.value }))} />
                </label>
              ))}
            </div>
            <p data-testid="ins-points-preview" className="mt-1 text-[11px] text-[#6B6B73]">
              Perkiraan poin: <strong className="tabular-nums">{previewPoints}</strong>{" "}
              — grade akhir dihitung server dari ambang yang berlaku, bukan di layar ini.
            </p>
          </div>
        ) : (
          <p data-testid="ins-line-no-roll" className="text-[11px] text-[#6B6B73]">
            Baris retur tidak menunjuk roll gudang, jadi tidak ada perhitungan poin cacat
            di sini. Hasil per barang retur tetap tercatat di dokumen returnya.
          </p>
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="field-label">Hasil banding WARNA</span>
            <KNSelect data-testid="ins-color-select" value={form.color_result}
              onValueChange={(v) => set({ color_result: v })} options={colorOptions}
              className="field" placeholder="Pilih hasil warna" />
          </label>
          <label className="block">
            <span className="field-label">Hasil banding HANDFEEL</span>
            <KNSelect data-testid="ins-handfeel-select" value={form.handfeel_result}
              onValueChange={(v) => set({ handfeel_result: v })} options={handfeelOptions}
              className="field" placeholder="Pilih hasil handfeel" />
          </label>
          <label className="block">
            <span className="field-label">Selisih warna ΔE (opsional)</span>
            <input data-testid="ins-delta-e" type="number" step="0.1" min="0" className="field"
              value={form.delta_e} onChange={(e) => set({ delta_e: e.target.value })}
              placeholder="mis. 1.8" />
          </label>
          <label className="block">
            <span className="field-label">Skor handfeel (1–5)</span>
            <input data-testid="ins-handfeel-score" type="number" min="1" max="5" className="field"
              value={form.handfeel_score}
              onChange={(e) => set({ handfeel_score: e.target.value })} />
          </label>
          {line.roll_id ? (
            <>
              <label className="block">
                <span className="field-label">Gramasi aktual (g/m²)</span>
                <input data-testid="ins-gsm-actual" type="number" step="0.1" className="field"
                  value={form.gsm_actual} onChange={(e) => set({ gsm_actual: e.target.value })} />
              </label>
              <label className="block">
                <span className="field-label">Lebar aktual (cm)</span>
                <input data-testid="ins-width-actual" type="number" step="0.1" className="field"
                  value={form.width_actual}
                  onChange={(e) => set({ width_actual: e.target.value })} />
              </label>
            </>
          ) : null}
          <label className="block sm:col-span-2">
            <span className="field-label">Catatan pemeriksaan</span>
            <textarea data-testid="ins-line-remark" className="field" rows={2}
              placeholder="mis. Shade lebih tua dari sample pada 2 meter awal."
              value={form.remark} onChange={(e) => set({ remark: e.target.value })} />
          </label>
        </div>

        {akanDitahan && (
          <p data-testid="ins-will-hold-warning"
            className="rounded-md border border-[#FFD9A0] bg-[#FFF7E6] px-3 py-2 text-[11px] text-[#B45309]">
            Dengan kebijakan yang berlaku, hasil ini akan <strong>MENAHAN</strong> barang:
            roll tidak boleh ditempatkan ke rak sampai manajer melepasnya ber-alasan.
          </p>
        )}
      </div>
    </FormModal>
  );
}
