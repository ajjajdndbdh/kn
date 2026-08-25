/**
 * RoundActionModal (FASE F · PS-18, diperluas FASE S) — dua peran:
 *  - mode "submit": setor hasil round (catatan + hasil ukur + biaya). Lampiran WAJIB
 *    sudah diunggah lebih dulu — server menolak bila belum ada.
 *  - mode "assess": nilai hasil (acc | revisi | tolak) + skor (wajib saat ACC).
 *
 * FASE S — kolom hasil ukur **DINAMIS dari master jenis** (`measurement_fields`).
 * Sebelumnya form ini punya 5 kolom TETAP (ΔE, GSM, susut, tahan cuci, tahan gosok),
 * sehingga: round handfeel tidak punya tempat untuk `handfeel_score`, round proofing
 * tidak punya tempat untuk `repeat_cm`/register, dan `delta_e` tetap diminta pada
 * jenis yang tidak mengukur warna. Kolomnya kini persis yang diminta server — satu
 * daftar, dua pemakai (validator & form), jadi mustahil ada kolom yang ditolak tanpa
 * pernah ditampilkan (atau sebaliknya).
 */
import { useMemo, useState } from "react";
import { Save, X } from "lucide-react";
import KNSelect from "../../components/KNSelect";
import { overlayDismiss } from "@/utils/overlayDismiss";
import { measurementFieldsOf, measurementMeta, typeLabel } from "./sampleTypeMeta";

const RESULT_OPTS = [
  { value: "acc", label: "ACC — diterima (wajib skor)" },
  { value: "revisi", label: "Revisi — minta perbaikan (round berikutnya)" },
  { value: "tolak", label: "Tolak — supplier tidak dilanjutkan" },
];

export default function RoundActionModal({ mode, round, types, measurements,
  onClose, onConfirm, busy }) {
  const isSubmit = mode === "submit";
  const typeCode = String(round?.type_code || "").toLowerCase();
  const fields = useMemo(() => measurementFieldsOf(typeCode, types), [typeCode, types]);

  const [note, setNote] = useState("");
  const [cost, setCost] = useState("");
  const [result, setResult] = useState("acc");
  const [score, setScore] = useState("");
  const [m, setM] = useState({});
  const setMeas = (k, v) => setM((p) => ({ ...p, [k]: v }));
  const nAttach = (round?.attachments || []).length;
  const missing = fields.filter((f) => String(m[f] ?? "").trim() === "");

  const confirm = () => {
    if (isSubmit) {
      onConfirm({
        note, cost: cost || 0,
        // Hanya kolom yang DIMINTA jenis ini dikirim. Mengirim kolom lain akan
        // ditolak server dengan menyebut kolom yang benar — dan lebih baik
        // ditolak daripada tersimpan sebagai angka yang tak pernah ditampilkan.
        measurements: Object.fromEntries(
          fields.map((k) => [k, String(m[k] ?? "").trim() === "" ? null : m[k]])),
      });
    } else {
      onConfirm({ result, score: score === "" ? null : score, note });
    }
  };

  return (
    <div data-testid="round-action-modal"
      className="fixed inset-0 z-[176] flex items-center justify-center bg-black/50 p-4"
      {...overlayDismiss(onClose)}>
      <div className="flex max-h-[92vh] w-full max-w-[580px] flex-col overflow-hidden rounded-xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-[#EFF0F2] px-4 py-3">
          <h2 className="text-[15px] font-bold">
            {isSubmit ? `Setor hasil rnd ${round?.round_no}` : `Nilai hasil rnd ${round?.round_no}`}
            <span className="ml-2 text-[11.5px] font-normal text-[#6B6B73]"
              data-testid="round-modal-context">
              {typeLabel(typeCode, types)} · {round?.supplier_name}
            </span>
          </h2>
          <button className="icon-button" onClick={onClose} data-testid="round-modal-close">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 space-y-2.5 overflow-y-auto p-4">
          {isSubmit && (
            <div className={`rounded-lg px-3 py-2 text-[11.5px] ${nAttach
              ? "bg-[#EAF7EF] text-[#1A7A3A]" : "bg-[#FFF6E5] text-[#8C4A00]"}`}
              data-testid="round-attach-hint">
              {nAttach
                ? `${nAttach} bukti sudah terunggah — hasil boleh disetor.`
                : "Belum ada bukti terunggah. Unggah minimal 1 berkas (foto hasil / artwork / "
                  + "hasil ukur) di baris round sebelum menyetor — server akan menolaknya."}
            </div>
          )}

          {isSubmit ? (
            <>
              <Field label="Catatan / penjelasan hasil (WAJIB)">
                <textarea className="field" rows={3} data-testid="round-note-input" value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="mis. Warna sedikit lebih tua dari target, handfeel bagus" />
              </Field>

              <div className="rounded-lg bg-[#F2F7FF] px-3 py-2 text-[11px] text-[#004099]"
                data-testid="round-meas-hint">
                Kolom hasil ukur di bawah datang dari <b>master Jenis Sampling</b> untuk
                jenis <b>{typeLabel(typeCode, types)}</b>. Untuk menambah/mengurangi
                kolomnya: Pengaturan → Master → Jenis Sampling — tanpa programmer.
              </div>

              {fields.length === 0 ? (
                <p className="text-[11.5px] text-[#6B6B73]" data-testid="round-meas-none">
                  Jenis ini tidak meminta hasil ukur — cukup catatan & bukti.
                </p>
              ) : (
                <div className="grid gap-2.5 md:grid-cols-3" data-testid="round-meas-fields">
                  {fields.map((key) => {
                    const meta = measurementMeta(key, measurements);
                    return (
                      <Field key={key}
                        label={`${meta.label}${meta.unit ? ` (${meta.unit})` : ""} *`}>
                        <input className="field" data-testid={`round-meas-${key}`}
                          value={m[key] ?? ""} title={meta.hint || ""}
                          onChange={(e) => setMeas(key, e.target.value)}
                          placeholder={meta.min != null ? `${meta.min}–${meta.max}` : ""} />
                      </Field>
                    );
                  })}
                  <Field label="Biaya sample (Rp)">
                    <input className="field" data-testid="round-cost-input" value={cost}
                      onChange={(e) => setCost(e.target.value)} placeholder="150000" />
                  </Field>
                </div>
              )}
              {missing.length > 0 && (
                <p className="text-[11px] text-[#8C4A00]" data-testid="round-meas-missing">
                  Masih kosong: <b>{missing.map((k) => measurementMeta(k, measurements).label)
                    .join(", ")}</b>. Server menolak hasil yang belum lengkap — angka inilah
                  yang dipakai membandingkan supplier.
                </p>
              )}
            </>
          ) : (
            <>
              <Field label="Hasil penilaian *">
                <KNSelect data-testid="round-result-select" className="field" value={result}
                  options={RESULT_OPTS} onValueChange={setResult} />
              </Field>
              <Field label={`Skor 0–100${result === "acc" ? " (WAJIB saat ACC)" : ""}`}>
                <input className="field" data-testid="round-score-input" value={score}
                  onChange={(e) => setScore(e.target.value)} placeholder="92" />
              </Field>
              <p className="text-[10.5px] text-[#6B6B73]">
                Skor jenis <b>{typeLabel(typeCode, types)}</b> hanya dibandingkan dengan
                skor jenis yang sama — 90 pada labdip berarti warnanya tepat, 90 pada
                handfeel berarti rasanya tepat.
              </p>
              <Field label="Catatan penilai">
                <textarea className="field" rows={2} data-testid="round-assess-note" value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="mis. Warna presisi, siap dilanjutkan ke kontrak" />
              </Field>
            </>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-[#EFF0F2] px-4 py-3">
          <button className="secondary-button" onClick={onClose}>Batal</button>
          <button className="primary-button" onClick={confirm} disabled={busy}
            data-testid="round-modal-confirm">
            <Save size={13} /> {busy ? "Menyimpan…" : isSubmit ? "Setor hasil" : "Simpan penilaian"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[10.5px] font-semibold text-[#6B6B73]">{label}</span>
      {children}
    </label>
  );
}
