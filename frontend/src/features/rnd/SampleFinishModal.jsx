/**
 * SampleFinishModal (FASE S · user story S.F-4) — dua peran, satu permukaan:
 *  - mode "finish"  : tandai **Sample Jadi** (fisiknya sudah ada). Server menolak
 *                     bila belum ada round yang ACC — "jadi" tanpa ACC membuat
 *                     tanggalnya jadi bukti palsu.
 *  - mode "deliver" : catat **Kirim Sample**. TUJUAN WAJIB (pelanggan / sales /
 *                     supplier / arsip internal) dan urutannya ditegakkan server:
 *                     tidak mungkin dikirim sebelum jadi.
 *
 * Kenapa dua peristiwa, bukan satu tombol "selesai": tanggalnya dipakai orang
 * berbeda — "jadi" oleh R&D untuk menutup pekerjaan, "dikirim" oleh sales untuk
 * menjawab pelanggan. Menggabungkannya memaksa salah satu tanggal ditebak.
 */
import { useState } from "react";
import { CheckCircle2, Send, X } from "lucide-react";
import KNSelect from "../../components/KNSelect";
import { overlayDismiss } from "@/utils/overlayDismiss";
import { DELIVER_LABEL } from "./sampleTypeMeta";

export default function SampleFinishModal({ mode = "finish", sample, targets, busy,
  onClose, onConfirm }) {
  const isFinish = mode === "finish";
  const [date, setDate] = useState("");
  const [note, setNote] = useState("");
  const [to, setTo] = useState("");
  const [toName, setToName] = useState("");

  const opts = ((targets && targets.length ? targets
    : Object.entries(DELIVER_LABEL).map(([value, label]) => ({ value, label }))));
  // Placeholder dirender sebagai OPSI oleh `KNSelect`; memilihnya mengosongkan
  // pilihan sehingga tombol simpan mati — itu memang yang diinginkan karena tujuan
  // WAJIB, dan server pun menolaknya.
  const options = [{ value: "", label: "— pilih tujuan pengiriman —" }, ...opts];

  return (
    <div data-testid={isFinish ? "sample-finish-modal" : "sample-deliver-modal"}
      className="fixed inset-0 z-[178] flex items-center justify-center bg-black/50 p-4"
      {...overlayDismiss(onClose)}>
      <div className="flex max-h-[92vh] w-full max-w-[520px] flex-col overflow-hidden rounded-xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-[#EFF0F2] px-4 py-3">
          <h2 className="flex items-center gap-2 text-[15px] font-bold">
            {isFinish ? <CheckCircle2 size={16} className="text-[#1B7F4B]" />
              : <Send size={16} className="text-[#0058CC]" />}
            {isFinish ? "Tandai Sample Jadi" : "Catat Pengiriman Sample"}
            <span className="text-[11.5px] font-normal text-[#6B6B73]">
              {sample?.number}
            </span>
          </h2>
          <button className="icon-button" onClick={onClose}
            data-testid="sample-finish-close"><X size={18} /></button>
        </div>

        <div className="flex-1 space-y-2.5 overflow-y-auto p-4">
          <div className="rounded-lg bg-[#F2F7FF] px-3 py-2 text-[11.5px] text-[#004099]">
            {isFinish
              ? "Menandai sample JADI hanya boleh setelah ada round yang ACC — tanggal "
                + "ini dipakai laporan sebagai bukti bahwa sample-nya sah."
              : "Tujuan pengiriman WAJIB dipilih. Tanpa tujuan, laporan sample tidak bisa "
                + "menjawab pertanyaan yang sebenarnya ditanyakan: “sample untuk siapa "
                + "yang belum kembali?”"}
          </div>

          {!isFinish && (
            <>
              <Field label="Dikirim ke *">
                <KNSelect data-testid="sample-deliver-to" className="field" value={to}
                  options={options} onValueChange={setTo} />
              </Field>
              <Field label="Nama penerima (opsional)">
                <input className="field" data-testid="sample-deliver-name" value={toName}
                  onChange={(e) => setToName(e.target.value)}
                  placeholder="mis. Ibu Komang — Butik Bali Indah" />
              </Field>
            </>
          )}

          <Field label={`Tanggal ${isFinish ? "selesai" : "kirim"} (kosong = hari ini)`}>
            <input className="field" type="date"
              data-testid={isFinish ? "sample-finish-date" : "sample-deliver-date"}
              value={date} onChange={(e) => setDate(e.target.value)} />
          </Field>
          <Field label="Catatan">
            <textarea className="field" rows={2}
              data-testid={isFinish ? "sample-finish-note" : "sample-deliver-note"}
              value={note} onChange={(e) => setNote(e.target.value)}
              placeholder={isFinish
                ? "mis. Swatch pemenang sudah dijilid & diberi label"
                : "mis. Dikirim bersama surat pengantar untuk persetujuan akhir"} />
          </Field>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-[#EFF0F2] px-4 py-3">
          <button className="secondary-button" onClick={onClose}>Batal</button>
          <button className="primary-button" disabled={busy || (!isFinish && !to)}
            data-testid={isFinish ? "sample-finish-confirm" : "sample-deliver-confirm"}
            title={!isFinish && !to ? "Pilih tujuan pengiriman lebih dulu" : ""}
            onClick={() => onConfirm(isFinish
              ? { date, note }
              : { to, to_name: toName, date, note })}>
            {isFinish ? <CheckCircle2 size={13} /> : <Send size={13} />}
            {busy ? "Menyimpan…" : isFinish ? "Tandai Jadi" : "Catat Pengiriman"}
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
