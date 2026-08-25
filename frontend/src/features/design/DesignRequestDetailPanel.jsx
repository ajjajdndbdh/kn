/**
 * DesignRequestDetailPanel — FASE D · isi pop-up rincian **Permintaan Desain**.
 *
 * Semua aksi hidup di sini supaya papan (kanban) tetap sederhana: menugaskan,
 * mulai mengerjakan, menyerahkan artwork, ACC, minta revisi (alasan WAJIB), dan
 * membatalkan. Tombol yang bukan wewenang peran ini **tidak dirender** — bukan
 * dirender lalu ditolak server (pelajaran "layar mati").
 */
import { useEffect, useState } from "react";
import {
  CalendarClock, CheckCircle2, ClipboardList, Image, RotateCcw, Ban, Play, User,
} from "lucide-react";
import ErrorNotice from "../../components/ErrorNotice";
import KNSelect from "../../components/KNSelect";
import { ColorChip } from "../../components/PantoneFinder";
import { askReason } from "../../services/confirmService";
import { notifySuccess } from "../../utils/feedback";
import {
  apiText, approveDesignRequest, assignDesignRequest, cancelDesignRequest,
  deliverDesignRequest, DSR_STATUS_CLASS, DSR_STATUS_LABEL, galleryOptions,
  rejectDesignRequest, startDesignRequest, submitDesignRequest,
} from "./designRequestsApi";

function Row({ label, children, testId }) {
  return (
    <div className="flex items-start justify-between gap-3 py-1">
      <span className="text-[11px] text-[#6B6B73]">{label}</span>
      <span data-testid={testId} className="text-[11.5px] font-semibold text-[#1C1C1E] text-right">{children}</span>
    </div>
  );
}

export default function DesignRequestDetailPanel({ doc, meta, onChanged, onClose }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [assignee, setAssignee] = useState(doc.assigned_to || "");
  const [due, setDue] = useState(doc.due_date || "");
  const [gallery, setGallery] = useState([]);
  const [galleryId, setGalleryId] = useState("");

  const role = meta?.role || "";
  const canDecide = ["admin", "manager"].includes(role);
  const canAssign = canDecide;
  const canWork = ["admin", "manager", "designer"].includes(role);

  useEffect(() => {
    if (!canWork) return;
    galleryOptions().then(setGallery).catch(() => setGallery([]));
  }, [canWork]);

  async function run(fn, pesan) {
    setBusy(true); setErr("");
    try {
      const fresh = await fn();
      notifySuccess("Berhasil", pesan);
      onChanged?.(fresh);
    } catch (e) {
      setErr(apiText(e, "Aksi gagal."));
    } finally { setBusy(false); }
  }

  async function mintaRevisi() {
    const alasan = await askReason({
      title: "Minta revisi",
      message: `Apa yang harus diubah pada ${doc.number}? Alasan ini dibaca desainer.`,
      confirmLabel: "Kirim permintaan revisi",
    });
    if (!alasan) return;
    await run(() => rejectDesignRequest(doc.id, alasan), "Permintaan revisi terkirim.");
  }

  async function batalkan() {
    const alasan = await askReason({
      title: "Batalkan permintaan desain",
      message: `Sebutkan alasan pembatalan ${doc.number}.`,
      confirmLabel: "Batalkan permintaan",
    });
    if (!alasan) return;
    await run(() => cancelDesignRequest(doc.id, alasan), "Permintaan dibatalkan.");
  }

  return (
    <div data-testid="dsr-detail-panel" className="grid gap-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p data-testid="dsr-detail-number" className="text-[13.5px] font-bold text-[#1C1C1E]">{doc.number}</p>
          <p className="text-[11px] text-[#6B6B73]">
            {doc.target_label} · {doc.source_label}
            {doc.so_number ? ` · pesanan ${doc.so_number}` : ""}
            {doc.customer_name ? ` · ${doc.customer_name}` : ""}
          </p>
        </div>
        <span data-testid="dsr-detail-status"
          className={`status-pill ${DSR_STATUS_CLASS[doc.status] || "pill-muted"}`}>
          {DSR_STATUS_LABEL[doc.status] || doc.status}
        </span>
      </div>

      {err && <ErrorNotice message={err} onDismiss={() => setErr("")} testId="dsr-detail-error" />}

      <div className="section-card">
        <p className="text-[11px] font-bold uppercase tracking-wide text-[#9A9BA3]">Brief</p>
        <p data-testid="dsr-detail-brief" className="mt-1 whitespace-pre-wrap text-[12px] text-[#3C3C43]">{doc.brief}</p>
        {(doc.color_targets || []).length > 0 && (
          <div data-testid="dsr-detail-colors" className="mt-2 flex flex-wrap gap-1.5">
            {(doc.color_targets || []).map((c) => (
              <span key={c.code} className="inline-flex items-center gap-1 rounded-full border border-[#EFF0F2] px-2 py-0.5 text-[10.5px]">
                <ColorChip hex={c.hex} size={12} /> {c.code} · {c.name}
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="section-card">
        <Row label="Diminta oleh" testId="dsr-detail-requester">{doc.requested_by || "—"}</Row>
        <Row label="Desainer" testId="dsr-detail-assignee">{doc.assigned_name || "Belum ditugaskan"}</Row>
        <Row label="Tenggat" testId="dsr-detail-due">
          {doc.due_date || "—"}{doc.is_overdue ? " · lewat tenggat" : ""}
        </Row>
        <Row label="Versi diserahkan" testId="dsr-detail-versions">{doc.versions || 0}</Row>
        <Row label="Putaran revisi" testId="dsr-detail-revisions">{doc.revision_count || 0}</Row>
        {doc.reject_reason && (
          <Row label="Alasan revisi terakhir" testId="dsr-detail-reject-reason">{doc.reject_reason}</Row>
        )}
        {doc.cancelled_reason && (
          <Row label="Alasan pembatalan" testId="dsr-detail-cancel-reason">{doc.cancelled_reason}</Row>
        )}
      </div>

      {/* ── AKSI ── */}
      <div className="section-card grid gap-2">
        <p className="text-[11px] font-bold uppercase tracking-wide text-[#9A9BA3]">Tindakan</p>

        {canAssign && !["approved", "cancelled"].includes(doc.status) && (
          <div className="grid gap-2 sm:grid-cols-[1fr_140px_auto] sm:items-end">
            <label className="block">
              <span className="field-label">Tugaskan ke desainer</span>
              <KNSelect data-testid="dsr-assign-select" value={assignee}
                onValueChange={setAssignee}
                options={(meta?.designers || []).map((d) => ({
                  value: d.id,
                  label: d.has_account ? d.name : `${d.name} (belum punya akun)`,
                }))}
                className="field" placeholder="Pilih desainer" />
            </label>
            <label className="block">
              <span className="field-label">Tenggat</span>
              <input data-testid="dsr-assign-due" type="date" className="field"
                value={due} onChange={(e) => setDue(e.target.value)} />
            </label>
            <button data-testid="dsr-assign-button" className="primary-button"
              disabled={busy || !assignee}
              onClick={() => run(() => assignDesignRequest(doc.id, assignee, due),
                                 "Permintaan ditugaskan.")}>
              <User size={13} /> Tugaskan
            </button>
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          {doc.status === "draft" && (
            <button data-testid="dsr-submit-button" className="secondary-button" disabled={busy}
              onClick={() => run(() => submitDesignRequest(doc.id), "Permintaan diajukan.")}>
              <ClipboardList size={13} /> Ajukan
            </button>
          )}
          {canWork && ["assigned", "revision"].includes(doc.status) && (
            <button data-testid="dsr-start-button" className="secondary-button" disabled={busy}
              onClick={() => run(() => startDesignRequest(doc.id), "Ditandai sedang dikerjakan.")}>
              <Play size={13} /> Mulai kerjakan
            </button>
          )}
          {canDecide && doc.status === "delivered" && (
            <>
              <button data-testid="dsr-approve-button" className="primary-button" disabled={busy}
                onClick={() => run(() => approveDesignRequest(doc.id, ""), "Desain disetujui.")}>
                <CheckCircle2 size={13} /> Setujui (ACC)
              </button>
              <button data-testid="dsr-reject-button" className="secondary-button" disabled={busy}
                onClick={mintaRevisi}>
                <RotateCcw size={13} /> Minta revisi
              </button>
            </>
          )}
          {canDecide && !["approved", "cancelled"].includes(doc.status) && (
            <button data-testid="dsr-cancel-button" className="secondary-button" disabled={busy}
              onClick={batalkan}>
              <Ban size={13} /> Batalkan
            </button>
          )}
          <button data-testid="dsr-detail-close" className="secondary-button" onClick={onClose}>Tutup</button>
        </div>

        {canWork && ["assigned", "in_progress", "revision", "delivered"].includes(doc.status) && (
          <div className="grid gap-2 sm:grid-cols-[1fr_auto] sm:items-end border-t border-[#EFF0F2] pt-2">
            <label className="block">
              <span className="field-label">Serahkan artwork dari Galeri Desain</span>
              <KNSelect data-testid="dsr-gallery-select" value={galleryId}
                onValueChange={setGalleryId} options={gallery} className="field"
                placeholder={gallery.length ? "Pilih artwork…" : "Belum ada entri galeri"}
                searchable />
            </label>
            <button data-testid="dsr-deliver-button" className="primary-button"
              disabled={busy || !galleryId}
              onClick={() => run(() => deliverDesignRequest(doc.id, galleryId),
                                 "Hasil diserahkan — menunggu keputusan atasan.")}>
              <Image size={13} /> Serahkan hasil
            </button>
          </div>
        )}
      </div>

      {/* ── RIWAYAT ── */}
      <div className="section-card">
        <p className="text-[11px] font-bold uppercase tracking-wide text-[#9A9BA3]">Riwayat</p>
        <div data-testid="dsr-detail-history" className="mt-1 grid gap-1">
          {(doc.history || []).slice().reverse().map((h, i) => (
            <div key={`${h.at}-${i}`} className="flex items-start gap-2 text-[11px]">
              <CalendarClock size={12} className="mt-0.5 shrink-0 text-[#9A9BA3]" />
              <span className="text-[#3C3C43]">
                <strong>{h.label}</strong> · {h.actor} · {(h.at || "").slice(0, 16).replace("T", " ")}
                {h.note ? <span className="text-[#6B6B73]"> — {h.note}</span> : null}
              </span>
            </div>
          ))}
          {(doc.history || []).length === 0 && (
            <p className="text-[11px] text-[#8E8E93]">Belum ada riwayat.</p>
          )}
        </div>
      </div>
    </div>
  );
}
