/**
 * PoStageModal — FASE P · pop-up **menandai satu tahap** PO di papan per lini.
 *
 * TIGA KEPUTUSAN YANG SENGAJA
 * ===========================
 * 1. **Pop-up, bukan klik-langsung-ubah.** Menandai "celup selesai" adalah
 *    pernyataan yang tercatat namanya di dokumen (user story P-2: *"tercatat siapa
 *    & kapan"*). Satu klik tanpa konfirmasi membuat salah-klik menjadi jejak
 *    palsu yang harus dibatalkan orang lain.
 * 2. **Memakai `FormModal` bersama** — bukan modal sendiri. Dengan begitu Esc,
 *    backdrop, fokus awal, dan tempat galat mengikuti standar yang dijaga
 *    `INV-UI-01`/`INV-UI-03`/`INV-UI-10`. Modal yang memasang pendengar Esc
 *    sendiri pernah membuat isian pengguna hilang (pelajaran FASE U).
 * 3. **Galat tampil DI DALAM pop-up.** Aturan INV-UI-03 C: menaruh galat di bilah
 *    halaman (di belakang lapisan modal) membuat tombol tampak "tidak melakukan
 *    apa-apa" — kelas bug yang sudah pernah dilaporkan pemilik.
 */
import { useEffect, useState } from "react";
import { ListChecks } from "lucide-react";

import FormModal from "../../components/FormModal";
import KNSelect from "../../components/KNSelect";
import { STAGE_STATUS_LABEL, apiText, longDateTime, setStage } from "./poBoardApi";

export default function PoStageModal({ open, row, stage, onClose, onSaved }) {
  const [status, setStatus] = useState("done");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    // Nilai awal = langkah BERIKUTNYA yang wajar, bukan status sekarang: orang
    // membuka pop-up ini untuk MENGUBAH sesuatu.
    setStatus(stage?.status === "in_progress" ? "done"
      : stage?.status === "done" ? "in_progress" : "in_progress");
    setNote("");
    setError("");
  }, [open, stage?.code, stage?.status]);

  if (!open || !row || !stage) return null;

  const options = Object.entries(STAGE_STATUS_LABEL).map(([value, label]) => ({ value, label }));

  async function submit() {
    setBusy(true);
    setError("");
    try {
      const updated = await setStage(row.po_id, { stage_code: stage.code, status, note });
      onSaved?.(updated);
      onClose?.();
    } catch (e) {
      setError(apiText(e, "Gagal menyimpan tahap."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <FormModal
      open={open}
      onClose={onClose}
      title={`Tahap ${stage.label}`}
      subtitle={`${row.po_number} · ${row.items_label || "—"}`}
      icon={ListChecks}
      size="sm"
      testId="po-stage-modal"
      onSubmit={submit}
      submitLabel="Simpan Tahap"
      submitTestId="po-stage-submit"
      cancelTestId="po-stage-cancel"
      busy={busy}
      error={error}
    >
      <div className="grid gap-3">
        <div className="rounded-lg border border-[#E5E5EA] bg-[#FAFBFC] px-3 py-2">
          <p className="text-[10px] font-bold uppercase tracking-wide text-[#8E8E93]">
            Status sekarang
          </p>
          <p data-testid="po-stage-current" className="text-[12px] font-semibold">
            {STAGE_STATUS_LABEL[stage.status] || stage.status}
            {stage.by ? (
              <span className="ml-1 font-normal text-[#6B6B73]">
                — {stage.by}{stage.at ? ` · ${longDateTime(stage.at)}` : ""}
              </span>
            ) : null}
          </p>
          {stage.note ? (
            <p className="mt-0.5 text-[11px] text-[#6B6B73]">“{stage.note}”</p>
          ) : null}
        </div>

        <label className="grid gap-1">
          <span className="text-[10px] font-bold uppercase tracking-wide text-[#8E8E93]">
            Status baru
          </span>
          <KNSelect
            value={status}
            onValueChange={setStatus}
            options={options}
            className="field"
            placeholder="Pilih status"
            data-testid="po-stage-status"
          />
        </label>

        <label className="grid gap-1">
          <span className="text-[10px] font-bold uppercase tracking-wide text-[#8E8E93]">
            Keterangan (opsional)
          </span>
          <input
            data-testid="po-stage-note"
            className="field"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="mis. celup ulang karena warna terlalu tua"
          />
          <span className="text-[10.5px] text-[#8E8E93]">
            Keterangan ikut tercatat di riwayat PO bersama nama & waktu Anda.
          </span>
        </label>
      </div>
    </FormModal>
  );
}
