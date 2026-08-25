/**
 * ReturnJourneyPanel — FASE I.F · **SEBAB keluhan + PERJALANAN retur** (lembar pemilik).
 *
 * Lembar kerja pemilik menandai empat saat: **SJ Kirim Toko** → **Kirim ke pelanggan**
 * → **Barang sampai** → **Inspeksi selesai**. Sebelum ini, ketiga yang pertama hanya
 * hidup di kertas dan yang keempat tidak pernah punya tanggal yang bisa dipercaya —
 * jadi pertanyaan "sudah sampai belum?" dijawab lewat telepon, bukan lewat sistem.
 *
 * DUA HAL YANG SENGAJA DIBEDAKAN DI SINI
 * ======================================
 * 1. **Tiga tonggak pertama ditandai MANUSIA** (tombol di bawah). Server menolak
 *    tanggal masa depan dan menolak "Barang sampai" sebelum ada pengiriman — jadi
 *    garis waktunya bisa dibaca sebagai cerita, bukan kumpulan tanggal acak.
 * 2. **"Inspeksi selesai" TIDAK bisa ditandai di sini.** Tanggalnya DITURUNKAN dari
 *    dokumen SPK Inspeksi yang ditutup (`inspections`). Kalau layar ini menyediakan
 *    tombolnya, akan ada dua tanggal "inspeksi selesai" yang bisa berbeda — dan tidak
 *    ada cara memilih mana yang benar.
 *
 * `Sebab keluhan` datang dari MASTER (`complaint_reasons`, berlapis per badan usaha),
 * bukan teks bebas: tiga pertanyaan pemilik (supplier mana yang paling sering
 * bermasalah · keluhan mana yang berujung klaim · apakah inspeksi menyetujui keluhan
 * pelanggan) hanya bisa dijawab kalau sebabnya punya kode yang stabil.
 */
import { useEffect, useState } from "react";
import axios, { API } from "../../services/apiClient";
import {
  CheckCircle2, ClipboardCheck, Circle, MessageSquareWarning, PackageCheck, Truck,
} from "lucide-react";
import ErrorNotice from "../../components/ErrorNotice";
import KNSelect from "../../components/KNSelect";
import { notifySuccess } from "../../utils/feedback";
import { apiErrorText } from "../../utils/apiError";

function fmtStamp(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso).slice(0, 10);
    return d.toLocaleString("id-ID", {
      day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch { return String(iso).slice(0, 10); }
}

const STEPS = [
  { key: "shipped_to_store", field: "shipped_to_store_at", label: "SJ Kirim Toko",
    icon: Truck, hint: "Surat jalan pengembalian ke toko diterbitkan" },
  { key: "shipped_to_customer", field: "shipped_to_customer_at", label: "Kirim ke pelanggan",
    icon: Truck, hint: "Barang pengganti dikirim ke pelanggan" },
  { key: "goods_arrived", field: "goods_arrived_at", label: "Barang sampai",
    icon: PackageCheck, hint: "Barang diterima kembali & siap diperiksa" },
];

export default function ReturnJourneyPanel({ ret, canEdit = false, onChanged }) {
  const [reasons, setReasons] = useState([]);
  const [code, setCode] = useState(ret?.complaint_code || "");
  const [note, setNote] = useState(ret?.complaint_note || "");
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    setCode(ret?.complaint_code || "");
    setNote(ret?.complaint_note || "");
  }, [ret?.id, ret?.complaint_code, ret?.complaint_note]);

  useEffect(() => {
    if (!canEdit) return;
    let hidup = true;
    axios.get(`${API}/sales-returns/meta/complaint-reasons`)
      .then((r) => { if (hidup) setReasons(r.data?.items || []); })
      .catch(() => { if (hidup) setReasons([]); });
    return () => { hidup = false; };
  }, [canEdit]);

  if (!ret) return null;

  async function simpanKeluhan() {
    setBusy("complaint"); setErr("");
    try {
      const r = await axios.post(`${API}/sales-returns/${ret.id}/complaint`,
        { complaint_code: code, complaint_note: note });
      notifySuccess("Berhasil", "Sebab keluhan tersimpan.");
      onChanged?.(r.data);
    } catch (e) {
      setErr(apiErrorText(e, "Gagal menyimpan sebab keluhan."));
    } finally { setBusy(""); }
  }

  async function tandai(step) {
    setBusy(step); setErr("");
    try {
      const r = await axios.post(`${API}/sales-returns/${ret.id}/milestone`,
        { milestone: step });
      notifySuccess("Berhasil", "Perjalanan retur diperbarui.");
      onChanged?.(r.data);
    } catch (e) {
      setErr(apiErrorText(e, "Gagal menandai perjalanan retur."));
    } finally { setBusy(""); }
  }

  const selectedMeta = reasons.find((r) => r.value === code);

  return (
    <div className="section-card" data-testid="return-journey-panel">
      <div className="section-header">
        <MessageSquareWarning size={14} /> Sebab Keluhan &amp; Perjalanan Retur
      </div>

      <div className="p-3 grid gap-3">
        {err && <ErrorNotice message={err} onDismiss={() => setErr("")} testId="return-journey-error" />}

        {/* ── SEBAB KELUHAN ── */}
        <div>
          <p className="text-[11px] font-bold uppercase tracking-wide text-[#9A9BA3]">
            Sebab keluhan pelanggan
          </p>
          {canEdit ? (
            <div className="mt-1 grid gap-2 sm:grid-cols-[220px_1fr_auto] sm:items-end">
              <label className="block">
                <span className="field-label">Alasan (dari Master Data)</span>
                <KNSelect data-testid="return-complaint-select" value={code}
                  onValueChange={setCode}
                  options={reasons.map((r) => ({ value: r.value, label: r.label }))}
                  className="field" placeholder="Pilih sebab keluhan" />
              </label>
              <label className="block">
                <span className="field-label">Catatan pelanggan</span>
                <input data-testid="return-complaint-note" className="field" value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="mis. warna lebih tua dari sample yang di-ACC" />
              </label>
              <button data-testid="return-complaint-save" className="primary-button"
                disabled={busy === "complaint" || !code} onClick={simpanKeluhan}>
                Simpan sebab
              </button>
            </div>
          ) : (
            <p data-testid="return-complaint-readonly" className="mt-0.5 text-[11.5px] text-[#3C3C43]">
              {ret.complaint_label || ret.complaint_code || "—"}
              {ret.complaint_note ? ` — ${ret.complaint_note}` : ""}
            </p>
          )}
          {(selectedMeta || ret.complaint_needs_inspection || ret.complaint_claimable) && (
            <p data-testid="return-complaint-meta" className="mt-1 text-[11px] text-[#6B6B73]">
              {(selectedMeta?.needs_inspection ?? ret.complaint_needs_inspection)
                ? "Keluhan ini wajib dibuktikan lewat inspeksi fisik sebelum kredit/ganti diberikan. "
                : "Keluhan administratif — tidak perlu perhitungan poin cacat. "}
              {(selectedMeta?.claimable ?? ret.complaint_claimable)
                ? "Wajar diteruskan sebagai klaim ke supplier." : ""}
            </p>
          )}
        </div>

        {/* ── GARIS WAKTU PERJALANAN ── */}
        <div className="border-t border-[#EFF0F2] pt-2">
          <p className="text-[11px] font-bold uppercase tracking-wide text-[#9A9BA3]">
            Perjalanan barang
          </p>
          <div className="mt-1.5 grid gap-1.5">
            {STEPS.map((s) => {
              const at = ret[s.field];
              const Icon = at ? CheckCircle2 : Circle;
              return (
                <div key={s.key} data-testid={`return-milestone-${s.key}`}
                  className="flex items-center justify-between gap-3">
                  <span className="flex items-center gap-2 text-[11.5px]">
                    <Icon size={14} className={at ? "text-[#15803D]" : "text-[#C7C7CC]"} />
                    <span className={at ? "font-semibold text-[#1C1C1E]" : "text-[#6B6B73]"}>
                      {s.label}
                    </span>
                    <span className="text-[10.5px] text-[#8E8E93]">
                      {at ? fmtStamp(at) : s.hint}
                    </span>
                  </span>
                  {canEdit && (
                    <button data-testid={`return-milestone-mark-${s.key}`}
                      className="secondary-button !py-1 !text-[11px]"
                      disabled={busy === s.key} onClick={() => tandai(s.key)}>
                      {at ? "Perbarui tanggal" : "Tandai sekarang"}
                    </button>
                  )}
                </div>
              );
            })}

            {/* Tonggak ke-4: DITURUNKAN dari dokumen inspeksi — sengaja tanpa tombol. */}
            <div data-testid="return-milestone-inspect" className="flex items-center justify-between gap-3">
              <span className="flex items-center gap-2 text-[11.5px]">
                <ClipboardCheck size={14}
                  className={ret.inspect_done_at ? "text-[#15803D]" : "text-[#C7C7CC]"} />
                <span className={ret.inspect_done_at ? "font-semibold text-[#1C1C1E]" : "text-[#6B6B73]"}>
                  Inspeksi selesai
                </span>
                <span className="text-[10.5px] text-[#8E8E93]">
                  {ret.inspect_done_at
                    ? `${fmtStamp(ret.inspect_done_at)}${ret.inspection_number ? ` · ${ret.inspection_number}` : ""}`
                    : (ret.inspection_number
                      ? `SPK ${ret.inspection_number} belum ditutup`
                      : "belum ada SPK Inspeksi untuk retur ini")}
                </span>
              </span>
              <span className="text-[10.5px] text-[#8E8E93]">
                dari dokumen SPK Inspeksi
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
