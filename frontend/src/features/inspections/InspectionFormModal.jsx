/**
 * InspectionFormModal — FASE I · **Buat SPK Inspeksi** (pop-up).
 *
 * Jalur NORMAL penerimaan PO tidak lewat sini: dokumennya LAHIR OTOMATIS saat barang
 * masuk antrean QC (user story I.1). Pop-up ini untuk tiga hal yang memang harus
 * diterbitkan manusia — inspeksi **retur pelanggan**, **retur ke supplier**, **hasil
 * makloon**, **barang pengganti** — plus jaring pengaman untuk tugas QC lama yang
 * belum punya SPK.
 *
 * Karena itu pemilih dokumen sumber berubah mengikuti jenisnya: memaksa satu pemilih
 * untuk semua jenis akan menawarkan dokumen yang salah dan ditolak server.
 */
import { useEffect, useMemo, useState } from "react";
import { ClipboardCheck } from "lucide-react";
import FormModal from "../../components/FormModal";
import KNSelect from "../../components/KNSelect";
import { apiText, createInspection, INS_KIND_LABEL, INS_STATUS_LABEL, refDocOptions } from "./inspectionsApi";

/** Status SPK yang masih BERJALAN — cermin `inspection_service.OPEN_STATUSES`. */
const SPK_BERJALAN = ["draft", "assigned", "in_progress"];

export default function InspectionFormModal({ open, onClose, onCreated, meta, orphanTasks = [] }) {
  const [kind, setKind] = useState("return_customer");
  const [refId, setRefId] = useState("");
  const [taskId, setTaskId] = useState("");
  const [assignee, setAssignee] = useState("");
  const [remark, setRemark] = useState("");
  const [refs, setRefs] = useState([]);
  const [loadingRefs, setLoadingRefs] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const perluTugas = kind === "po_receipt";

  useEffect(() => {
    if (!open || perluTugas) { setRefs([]); return; }
    let hidup = true;
    setLoadingRefs(true);
    refDocOptions(kind)
      .then((rows) => { if (hidup) setRefs(rows); })
      .catch(() => { if (hidup) setRefs([]); })
      .finally(() => { if (hidup) setLoadingRefs(false); });
    return () => { hidup = false; };
  }, [open, kind, perluTugas]);

  useEffect(() => { setRefId(""); setTaskId(""); }, [kind]);

  /**
   * Dokumen terpilih + SPK yang mungkin SUDAH memeriksanya.
   *
   * Server MENOLAK menerbitkan SPK kedua selama SPK lamanya masih berjalan (satu
   * barang, satu pemeriksa). Tanpa peringatan di sini, penolakan itu baru muncul
   * SESUDAH tombol "Terbitkan SPK" ditekan — dan pengguna tidak punya cara menduga
   * dokumen mana yang aman dipilih.
   */
  const terpilih = useMemo(
    () => refs.find((x) => String(x.value) === String(refId)) || null, [refs, refId]);
  const spkBerjalan = !!terpilih?.spk_number && SPK_BERJALAN.includes(terpilih?.spk_status);
  const spkSelesai = !!terpilih?.spk_number && !spkBerjalan;

  const kindOptions = ((meta?.kinds || []).length
    ? meta.kinds
    : Object.entries(INS_KIND_LABEL).map(([value, label]) => ({ value, label })));
  const taskOptions = orphanTasks.map((t) => ({
    value: t.id,
    label: `${t.po_number || "(tanpa PO)"} · ${t.product_name || "—"}`,
  }));
  const assigneeOptions = [{ value: "", label: "— Belum ditugaskan —" }]
    .concat(meta?.officers || []);

  async function simpan() {
    setBusy(true); setErr("");
    try {
      const doc = await createInspection({
        kind,
        ref_doc_id: perluTugas ? "" : refId,
        task_id: perluTugas ? taskId : "",
        assigned_to: assignee,
        remark,
      });
      onCreated?.(doc);
      setRefId(""); setTaskId(""); setAssignee(""); setRemark("");
    } catch (e) {
      setErr(apiText(e, "Gagal membuat SPK inspeksi."));
    } finally { setBusy(false); }
  }

  return (
    <FormModal
      open={open} onClose={onClose}
      title="SPK Inspeksi Baru"
      subtitle="Pilih apa yang diperiksa, lalu tugaskan petugas Bagian Inspect"
      icon={ClipboardCheck} size="md" testId="ins-create-modal"
      onSubmit={simpan} submitLabel="Terbitkan SPK" busy={busy} error={err}
      submitDisabled={perluTugas ? !taskId : (!refId || spkBerjalan)}
      submitTestId="ins-create-submit"
    >
      {/* `min-w-0` di kedua tingkat: anak grid bawaannya `min-width:auto`, jadi satu
          label pilihan yang panjang bisa MELEBARKAN seluruh pop-up (terukur). */}
      <div className="grid min-w-0 gap-3">
        <label className="block min-w-0">
          <span className="field-label">Jenis inspeksi</span>
          <KNSelect data-testid="ins-kind-select" value={kind} onValueChange={setKind}
            options={kindOptions} className="field" placeholder="Pilih jenis" />
        </label>

        {perluTugas ? (
          <label className="block">
            <span className="field-label">Tugas penerimaan yang belum punya SPK</span>
            <KNSelect data-testid="ins-task-select" value={taskId} onValueChange={setTaskId}
              options={taskOptions} className="field"
              placeholder={taskOptions.length
                ? "Pilih tugas penerimaan"
                : "Tidak ada — semua tugas QC sudah punya SPK"} />
            <span className="mt-1 block text-[10.5px] text-[#6B6B73]">
              SPK penerimaan PO normalnya lahir otomatis saat barang masuk antrean QC.
              Daftar ini hanya berisi tugas yang terlewat (mis. penerimaan sebelum aturan
              itu berlaku).
            </span>
          </label>
        ) : (
          <label className="block min-w-0">
            <span className="field-label">Dokumen yang diperiksa</span>
            <KNSelect data-testid="ins-ref-select" value={refId} onValueChange={setRefId}
              options={refs} className="field" searchable
              placeholder={loadingRefs ? "Memuat dokumen…"
                : (refs.length ? "Pilih dokumen sumber" : "Belum ada dokumen untuk jenis ini")} />
            {spkBerjalan && (
              <span data-testid="ins-ref-spk-open"
                className="mt-1 block rounded-md border border-[#E4B200] bg-[#FFF8E1] px-2 py-1.5
                           text-[10.5px] leading-snug text-[#6B5200]">
                Dokumen ini sedang diperiksa SPK <b>{terpilih.spk_number}</b>
                {terpilih.spk_status ? ` — ${INS_STATUS_LABEL[terpilih.spk_status] || terpilih.spk_status}` : ""}.
                Lanjutkan SPK itu; satu barang cukup satu pemeriksa.
              </span>
            )}
            {spkSelesai && (
              <span data-testid="ins-ref-spk-done"
                className="mt-1 block rounded-md border border-[#D8D8DE] bg-[#F7F7F9] px-2 py-1.5
                           text-[10.5px] leading-snug text-[#57575F]">
                Sudah pernah diperiksa SPK <b>{terpilih.spk_number}</b> (sudah diputuskan).
                Menerbitkan SPK baru berarti <b>pemeriksaan ulang</b> atas barang yang sama.
              </span>
            )}
            {!loadingRefs && !refs.length && (
              <span className="mt-1 block text-[10.5px] text-[#6B6B73]">
                Daftar ini hanya memuat dokumen badan usaha yang sedang aktif. Untuk hasil
                makloon, order yang belum menyerahkan hasil tidak ditawarkan — belum ada
                gulungan yang bisa diperiksa.
              </span>
            )}
          </label>
        )}

        <label className="block">
          <span className="field-label">Petugas inspect</span>
          <KNSelect data-testid="ins-assignee-select" value={assignee}
            onValueChange={setAssignee} options={assigneeOptions} className="field"
            placeholder="Belum ditugaskan" />
        </label>

        <label className="block">
          <span className="field-label">Catatan untuk petugas</span>
          <textarea data-testid="ins-remark-input" className="field" rows={2}
            placeholder="mis. Periksa keluhan warna terhadap sample yang di-ACC."
            value={remark} onChange={(e) => setRemark(e.target.value)} />
        </label>
      </div>
    </FormModal>
  );
}
