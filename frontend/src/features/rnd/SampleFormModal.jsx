/**
 * SampleFormModal (FASE F, diperluas FASE S) — buat permintaan sample.
 *
 * FASE S mengubah tiga hal yang dulu memaksa pekerjaan nyata dipecah jadi dua
 * dokumen:
 *   1. **JENIS boleh lebih dari satu** (labdip + handfeel + proofing) — dipilih
 *      sebagai chip, bukan dropdown tunggal;
 *   2. usulan jenis datang dari **master lini** (`sample_types_default`), jadi
 *      pemilik bisa mengubahnya tanpa programmer;
 *   3. permintaan bisa **ditautkan ke PESANAN** (user story S.F-2) sehingga dari
 *      layar pesanan sample-nya bisa ditemukan lewat Jejak Dokumen.
 *
 * "Wajib kode desain" TIDAK lagi ditebak layar (`if jenis == proofing`): ia dibaca
 * dari baris master (`requires_design`). Layar hanya MENAMPILKAN keputusan server —
 * kalau ia memutuskan sendiri, akan lahir aturan kedua yang menyimpang.
 */
import { useEffect, useMemo, useState } from "react";
import { Beaker, Save, X } from "lucide-react";
import KNSelect from "../../components/KNSelect";
import { overlayDismiss } from "@/utils/overlayDismiss";
import axios, { API } from "@/services/apiClient";
import { createSample, listColors, listDesigns, listSpecs, sampleTypes } from "./rndApi";
import { errMsg } from "./rndMeta";
import { typeLabel, typeMeta } from "./sampleTypeMeta";

// Daftar pesanan hidup DI SINI (bukan di `rndApi.js`): modul bersama itu diimpor
// juga oleh layar Desain & Pattern milik peran `designer` yang TIDAK punya izin
// pesanan — menumpangkannya di sana membuat audit peran melaporkan panel mati pada
// layar yang sebenarnya tidak pernah memanggilnya (pelajaran FASE D).
const listOrders = (params) =>
  axios.get(`${API}/sales-orders`, { params }).then((r) => r.data);

export default function SampleFormModal({ selectedEntity, prefill, onClose, onSaved }) {
  const [specs, setSpecs] = useState([]);
  const [colors, setColors] = useState([]);
  const [designs, setDesigns] = useState([]);
  const [orders, setOrders] = useState([]);
  const [types, setTypes] = useState([]);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [f, setF] = useState({
    spec_id: "",
    sample_types: prefill?.sample_types
      || (prefill?.sample_type ? [prefill.sample_type] : []),
    title: "", brief: "",
    color_id: prefill?.color_id || "", design_id: prefill?.design_id || "",
    so_id: prefill?.so_id || "", line_code: prefill?.line_code || "",
    target_date: "", qty_requested: "3", unit: "meter",
  });
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));

  useEffect(() => {
    const params = selectedEntity && selectedEntity !== "all" ? { entity_id: selectedEntity } : {};
    listSpecs({ ...params, limit: 200 }).then((r) => setSpecs(r?.items || [])).catch(() => {});
    listColors().then((c) => setColors(Array.isArray(c) ? c : c?.items || [])).catch(() => {});
    listDesigns().then((d) => setDesigns(Array.isArray(d) ? d : d?.items || [])).catch(() => {});
    listOrders({ ...params, limit: 200 })
      .then((r) => setOrders(Array.isArray(r) ? r : r?.items || [])).catch(() => {});
  }, [selectedEntity]);

  // Pilihan jenis DARI MASTER, disaring per lini bila lininya sudah diketahui —
  // jenis `proofing` hanya berlaku di lini printing (`applies_to_lines`).
  useEffect(() => {
    const p = {};
    if (selectedEntity && selectedEntity !== "all") p.entity_id = selectedEntity;
    if (f.line_code) p.line = f.line_code;
    sampleTypes(p).then((rows) => setTypes(Array.isArray(rows) ? rows : []))
      .catch(() => { /* master opsional — form tetap bisa dipakai dengan jenis lama */ });
  }, [selectedEntity, f.line_code]);

  // Bawaan jenis: dari usulan lini (bila belum ada yang dipilih pengguna).
  useEffect(() => {
    if (f.sample_types.length || types.length === 0) return;
    const spec = specs.find((x) => x.id === f.spec_id);
    const hint = spec?.sample_type_hint;
    if (hint && types.some((t) => t.value === hint)) { set("sample_types", [hint]); return; }
    // Deep-link dari Galeri Desain / Pustaka Warna hanya mengirim PERTANYAANNYA
    // ("permintaan ini berangkat dari sebuah desain?"). Jawabannya dibaca dari
    // master: jenis pertama yang `requires_design` cocok — bukan kata "proofing"
    // yang ditanam di layar (kalau pemilik menambah jenis printing baru, layar
    // lama akan tetap memaksa "proofing" dan itu kebohongan yang tenang).
    if (prefill?.need_design !== undefined) {
      const hit = types.find(
        (t) => Boolean(t.requires_design) === Boolean(prefill.need_design));
      if (hit) set("sample_types", [hit.value]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [types, f.spec_id]);

  const needDesign = useMemo(
    () => f.sample_types.some((c) => typeMeta(c, types).requires_design),
    [f.sample_types, types]);

  const pickSpec = (id) => {
    const s = specs.find((x) => x.id === id);
    setF((p) => ({
      ...p, spec_id: id,
      title: p.title || (s ? `Sampling ${s.title}` : ""),
      sample_types: p.sample_types.length ? p.sample_types
        : (s?.sample_type_hint ? [s.sample_type_hint] : []),
      color_id: s?.color_target?.color_id || p.color_id,
      design_id: s?.design_id || p.design_id,
      so_id: s?.so_id || p.so_id,
      line_code: s?.line_code || p.line_code,
      unit: s?.base_unit || p.unit,
    }));
  };

  const toggleType = (code) => setF((p) => ({
    ...p,
    sample_types: p.sample_types.includes(code)
      ? p.sample_types.filter((x) => x !== code)
      : [...p.sample_types, code],
  }));

  const submit = async () => {
    setErr("");
    if (!f.title.trim()) { setErr("Judul permintaan wajib diisi."); return; }
    if (f.sample_types.length === 0) {
      setErr("Pilih minimal satu JENIS sampling — satu permintaan boleh menempuh "
        + "beberapa jenis sekaligus (mis. labdip + handfeel).");
      return;
    }
    setSaving(true);
    try {
      const created = await createSample({
        spec_id: f.spec_id, sample_types: f.sample_types, title: f.title, brief: f.brief,
        color_target: f.color_id ? { color_id: f.color_id } : {},
        design_id: f.design_id, so_id: f.so_id, line_code: f.line_code,
        target_date: f.target_date,
        qty_requested: f.qty_requested || 0, unit: f.unit,
      });
      onSaved?.(created);
    } catch (e) {
      setErr(errMsg(e, "Gagal membuat permintaan sample."));
      setSaving(false);
    }
  };

  return (
    <div data-testid="sample-form-modal"
      className="fixed inset-0 z-[170] flex items-center justify-center bg-black/50 p-4"
      {...overlayDismiss(onClose)}>
      <div className="flex max-h-[94vh] w-full max-w-[740px] flex-col overflow-hidden rounded-xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-[#EFF0F2] px-4 py-3">
          <h2 className="flex items-center gap-2 text-[15px] font-bold">
            <Beaker size={16} className="text-[#0058CC]" /> Permintaan Sample Baru
          </h2>
          <button className="icon-button" onClick={onClose} data-testid="sample-form-close">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {err && (
            <div className="rounded-lg bg-[#FDEDE7] px-3 py-2 text-[11.5px] text-[#C0392B]"
              data-testid="sample-form-error">{err}</div>
          )}
          {prefill?.source_label && (
            <div className="rounded-lg bg-[#F2F7FF] px-3 py-2 text-[11.5px] text-[#004099]"
              data-testid="sample-form-prefill">
              Diisi otomatis dari <b>{prefill.source_label}</b>
              {prefill.design_id ? " — jenis sampling disetel ke proofing." : "."}
              {" "}Tinggal beri judul lalu simpan.
            </div>
          )}

          <Field label="Spesifikasi acuan (opsional)">
            <KNSelect data-testid="sample-spec" className="field" value={f.spec_id}
              options={[{ value: "", label: "— tanpa spesifikasi —" },
                ...specs.map((s) => ({ value: s.id, label: `${s.number} · ${s.title}` }))]}
              onValueChange={pickSpec} />
          </Field>

          {/* FASE S — JENIS boleh lebih dari satu. Chip, bukan dropdown: pilihan
              ganda pada dropdown tunggal adalah cara paling cepat membuat orang
              yakin hanya boleh satu. */}
          <div>
            <p className="mb-1 text-[10.5px] font-semibold text-[#6B6B73]">
              Jenis sampling * — boleh lebih dari satu, masing-masing punya rangkaian
              round sendiri
            </p>
            <div className="flex flex-wrap gap-1.5" data-testid="sample-type-picker">
              {types.length === 0 && (
                <span className="text-[11.5px] text-[#8C4A00]"
                  data-testid="sample-type-empty">
                  Belum ada jenis sampling aktif. Tambahkan di Pengaturan → Master →
                  Jenis Sampling.
                </span>
              )}
              {types.map((t) => {
                const on = f.sample_types.includes(t.value);
                return (
                  <button key={t.value} type="button"
                    data-testid={`sample-type-${t.value}`}
                    onClick={() => toggleType(t.value)}
                    title={t.notes || ""}
                    className={`rounded-full border px-3 py-1 text-[11px] font-medium ${on
                      ? "border-[#0058CC] bg-[#0058CC] text-white"
                      : "border-[#E5E5EA] bg-white text-[#3C3C43] hover:border-[#0058CC]"}`}>
                    {t.label}
                    {t.requires_design ? " · wajib desain" : ""}
                  </button>
                );
              })}
            </div>
            {f.sample_types.length > 0 && (
              <p className="mt-1 text-[10.5px] text-[#6B6B73]"
                data-testid="sample-type-summary">
                Dipilih: <b>{f.sample_types.map((c) => typeLabel(c, types)).join(" + ")}</b>.
                Hasil ukur yang diminta tiap jenis:{" "}
                {f.sample_types.map((c) => {
                  const fields = typeMeta(c, types).measurement_fields || [];
                  return `${typeLabel(c, types)} → ${fields.join(", ") || "tidak ada"}`;
                }).join(" · ")}
              </p>
            )}
          </div>

          <Field label="Judul permintaan *">
            <input className="field" data-testid="sample-title-input" value={f.title}
              onChange={(e) => set("title", e.target.value)}
              placeholder="mis. Sampling Katun Premium warna khusus" />
          </Field>

          <div className="grid gap-2.5 md:grid-cols-2">
            <Field label="Warna target">
              <KNSelect data-testid="sample-color" className="field" value={f.color_id}
                options={[{ value: "", label: "— belum ditentukan —" },
                  ...colors.map((c) => ({ value: c.id, label: `${c.code} · ${c.name}` }))]}
                onValueChange={(v) => set("color_id", v)} />
            </Field>
            <Field label={`Desain / pattern${needDesign ? " (WAJIB untuk jenis yang dipilih)" : ""}`}>
              <KNSelect data-testid="sample-design" className="field" value={f.design_id}
                options={[{ value: "", label: "— tanpa desain —" },
                  ...designs.map((d) => ({ value: d.id,
                    label: `${d.code || "tanpa kode"} · ${d.title} (v${d.version || 1})` }))]}
                onValueChange={(v) => set("design_id", v)} />
            </Field>
          </div>

          {/* FASE S · user story S.F-2 — tautan PESANAN. Dipilih dari daftar (bukan
              diketik) supaya jejak dokumen SO ↔ sample selalu utuh dua arah. */}
          <Field label="Untuk pesanan (opsional) — muncul di Jejak Dokumen pesanan itu">
            <KNSelect data-testid="sample-so" className="field" value={f.so_id}
              options={[{ value: "", label: "— bukan dari pesanan tertentu —" },
                ...orders.map((o) => ({ value: o.id,
                  label: `${o.order_number || o.number || o.id}`
                    + `${o.customer_name ? ` · ${o.customer_name}` : ""}` }))]}
              onValueChange={(v) => set("so_id", v)} />
          </Field>

          <div className="grid gap-2.5 md:grid-cols-3">
            <Field label="Jumlah diminta">
              <input className="field" data-testid="sample-qty-input" value={f.qty_requested}
                onChange={(e) => set("qty_requested", e.target.value)} placeholder="3" />
            </Field>
            <Field label="Satuan">
              <input className="field" data-testid="sample-unit-input" value={f.unit}
                onChange={(e) => set("unit", e.target.value)} placeholder="meter" />
            </Field>
            <Field label="Target tanggal selesai">
              <input className="field" type="date" data-testid="sample-target-date"
                value={f.target_date} onChange={(e) => set("target_date", e.target.value)} />
            </Field>
          </div>
          <Field label="Brief untuk supplier">
            <textarea className="field" rows={3} data-testid="sample-brief-input" value={f.brief}
              onChange={(e) => set("brief", e.target.value)}
              placeholder="mis. Cocokkan warna target maksimal ΔE 1.5, kirim swatch 3 meter" />
          </Field>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-[#EFF0F2] px-4 py-3">
          <button className="secondary-button" onClick={onClose}>Batal</button>
          <button className="primary-button" onClick={submit}
            disabled={saving || f.sample_types.length === 0}
            title={f.sample_types.length === 0 ? "Pilih minimal satu jenis sampling" : ""}
            data-testid="sample-form-save">
            <Save size={13} /> {saving ? "Menyimpan…" : "Simpan Draft"}
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
