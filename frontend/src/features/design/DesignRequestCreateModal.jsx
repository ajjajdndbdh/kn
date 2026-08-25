/**
 * DesignRequestCreateModal — FASE D · **Buat Permintaan Desain** (pop-up).
 *
 * Pop-up (bukan form inline) mengikuti standar `FormModal` FASE P4/P5: daftar &
 * papan di belakang tetap terlihat, galat tampil DI DALAM pop-up, Esc menutup
 * hanya lapisan teratas (INV-UI-10).
 */
import { useState } from "react";
import { Palette } from "lucide-react";
import FormModal from "../../components/FormModal";
import KNSelect from "../../components/KNSelect";
import PantoneFinder, { ColorChip } from "../../components/PantoneFinder";
import { apiText, createDesignRequest } from "./designRequestsApi";

export default function DesignRequestCreateModal({ open, onClose, onCreated, meta, orders = [] }) {
  const [form, setForm] = useState({
    source: "internal", so_id: "", target_type: "motif", brief: "",
    due_date: "", assigned_to: "", line_code: "",
  });
  const [colors, setColors] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const set = (patch) => setForm((f) => ({ ...f, ...patch }));

  const designerOptions = [{ value: "", label: "— Belum ditugaskan —" }].concat(
    (meta?.designers || []).map((d) => ({
      value: d.id,
      label: d.has_account ? d.name : `${d.name} (belum punya akun)`,
    })));
  const targetOptions = (meta?.target_types || []).map((t) => ({ value: t.id, label: t.label }));
  const sourceOptions = (meta?.sources || []).map((s) => ({ value: s.id, label: s.label }));
  const orderOptions = [{ value: "", label: "— Pilih pesanan —" }].concat(
    orders.map((o) => ({ value: o.id, label: `${o.number || o.order_number || o.id} · ${o.customer_name || ""}` })));

  async function simpan() {
    setBusy(true); setErr("");
    try {
      const doc = await createDesignRequest({
        ...form,
        color_targets: colors,
        submit_now: true,
      });
      onCreated?.(doc);
      setForm({ source: "internal", so_id: "", target_type: "motif", brief: "",
                due_date: "", assigned_to: "", line_code: "" });
      setColors([]);
    } catch (e) {
      setErr(apiText(e, "Gagal membuat permintaan desain."));
    } finally { setBusy(false); }
  }

  return (
    <FormModal
      open={open} onClose={onClose}
      title="Permintaan Desain Baru"
      subtitle="Tulis brief-nya, tentukan tenggat, lalu tugaskan ke desainer"
      icon={Palette} size="lg" testId="dsr-create-modal"
      onSubmit={simpan} submitLabel="Ajukan Permintaan" busy={busy} error={err}
      submitDisabled={(form.brief || "").trim().length < 5}
      submitTestId="dsr-create-submit"
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="field-label">Sumber permintaan</span>
          <KNSelect data-testid="dsr-source-select" value={form.source}
            onValueChange={(v) => set({ source: v, so_id: v === "so" ? form.so_id : "" })}
            options={sourceOptions} className="field" placeholder="Pilih sumber" />
        </label>
        <label className="block">
          <span className="field-label">Jenis yang diminta</span>
          <KNSelect data-testid="dsr-target-select" value={form.target_type}
            onValueChange={(v) => set({ target_type: v })}
            options={targetOptions} className="field" placeholder="Pilih jenis" />
        </label>
        {form.source === "so" && (
          <label className="block sm:col-span-2">
            <span className="field-label">Pesanan pelanggan</span>
            <KNSelect data-testid="dsr-so-select" value={form.so_id}
              onValueChange={(v) => set({ so_id: v })} options={orderOptions}
              className="field" placeholder="Pilih pesanan" searchable />
          </label>
        )}
        <label className="block sm:col-span-2">
          <span className="field-label">Brief (apa yang harus dibuat)</span>
          <textarea data-testid="dsr-brief-input" className="field" rows={3}
            placeholder="mis. Motif batik pesisir untuk katalog lebaran — 3 alternatif warna."
            value={form.brief} onChange={(e) => set({ brief: e.target.value })} />
        </label>
        <label className="block">
          <span className="field-label">Tenggat</span>
          <input data-testid="dsr-due-input" type="date" className="field"
            value={form.due_date} onChange={(e) => set({ due_date: e.target.value })} />
        </label>
        <label className="block">
          <span className="field-label">Ditugaskan ke</span>
          <KNSelect data-testid="dsr-assignee-select" value={form.assigned_to}
            onValueChange={(v) => set({ assigned_to: v })} options={designerOptions}
            className="field" placeholder="Belum ditugaskan" />
        </label>
        <div className="sm:col-span-2">
          <span className="field-label">Warna target (opsional)</span>
          <PantoneFinder triggerTestId="dsr-color-picker"
            label="Tambah warna dari Pustaka Warna…"
            onSelect={(c) => setColors((prev) => (
              prev.some((p) => p.code === c.code)
                ? prev
                : prev.concat([{ color_id: c.id || "", code: c.code || "", name: c.name || "", hex: c.hex || "" }])))} />
          {colors.length > 0 && (
            <div data-testid="dsr-color-chips" className="mt-1.5 flex flex-wrap gap-1.5">
              {colors.map((c) => (
                <span key={c.code} className="inline-flex items-center gap-1 rounded-full border border-[#EFF0F2] px-2 py-0.5 text-[10.5px]">
                  <ColorChip hex={c.hex} size={12} />
                  {c.code} · {c.name}
                  <button type="button" className="text-[#9A9BA3]"
                    data-testid={`dsr-color-remove-${c.code}`}
                    onClick={() => setColors((prev) => prev.filter((p) => p.code !== c.code))}>×</button>
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </FormModal>
  );
}
