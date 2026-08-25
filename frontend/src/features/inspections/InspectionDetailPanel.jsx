/**
 * InspectionDetailPanel — FASE I · isi pop-up rincian **SPK Inspeksi & QC**.
 *
 * Semua aksi hidup di sini supaya daftar tetap sederhana: menugaskan petugas,
 * memulai pemeriksaan, mengisi hasil per baris, MELEPAS TAHANAN (manajer),
 * menutup dengan keputusan, dan membuka kembali — dua yang terakhir wajib ber-alasan.
 *
 * Tombol yang bukan wewenang peran ini **tidak dirender** — bukan dirender lalu
 * ditolak server (pelajaran “layar mati” dari `audit_sales_roles_ux`).
 *
 * Angka yang ditampilkan di sini adalah RINGKASAN dari dokumen; poin cacat & grade
 * dihitung mesin 4-point di server (§3.4 rencana MD-ERP) dan tidak pernah dihitung
 * ulang di layar — dua angka untuk satu fakta adalah kelas cacat yang paling sering
 * menipu di repo ini.
 */
import { useState } from "react";
import {
  CalendarClock, CheckCircle2, FlaskConical, Lock, LockOpen, Play, RotateCcw, User,
} from "lucide-react";
import ErrorNotice from "../../components/ErrorNotice";
import KNSelect from "../../components/KNSelect";
import QtyDual from "../../components/QtyDual";
import { askReason } from "../../services/confirmService";
import { notifySuccess } from "../../utils/feedback";
import DocumentActionsBar from "../documents/DocumentActionsBar";
import InspectLineModal from "./InspectLineModal";
import {
  apiText, assignInspection, finishInspection, INS_COLOR_LABEL, INS_DECISION_LABEL,
  INS_HANDFEEL_LABEL, INS_KIND_LABEL, INS_STATUS_CLASS, INS_STATUS_LABEL,
  releaseHold, reopenInspection, resultPill, startInspection,
} from "./inspectionsApi";

function Row({ label, children, testId }) {
  return (
    <div className="flex items-start justify-between gap-3 py-1">
      <span className="text-[11px] text-[#6B6B73]">{label}</span>
      <span data-testid={testId} className="text-[11.5px] font-semibold text-[#1C1C1E] text-right">
        {children}
      </span>
    </div>
  );
}

export default function InspectionDetailPanel({ doc, meta, currentUser, onChanged, onClose }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [assignee, setAssignee] = useState(doc.assigned_to || "");
  const [bagian, setBagian] = useState(doc.bagian || "Bagian Inspect");
  const [decision, setDecision] = useState("");
  const [lineOpen, setLineOpen] = useState(null);

  const role = meta?.role || currentUser?.role || "";
  const canAssign = ["admin", "manager"].includes(role);
  const canDecide = ["admin", "manager"].includes(role);
  const canInspect = ["admin", "manager", "warehouse"].includes(role);
  const canReleaseHold = Boolean(meta?.can_release_hold);
  // Ambang panjang alasan datang dari SERVER (`policy.min_reason_length`), bukan
  // ditebak layar: server menolak alasan pendek dengan 400, jadi pop-up harus
  // memakai angka yang SAMA — kalau tidak, tombolnya bisa ditekan untuk aturan
  // yang sudah pasti ditolak. Cadangan 15 hanya untuk meta yang belum termuat.
  const minAlasan = Number(meta?.policy?.min_reason_length) || 15;

  const summary = doc.summary || {};
  const lines = doc.lines || [];
  const open = ["draft", "assigned", "in_progress"].includes(doc.status);
  const decisionOptions = (meta?.decisions || []).length
    ? meta.decisions
    : Object.entries(INS_DECISION_LABEL).map(([value, label]) => ({ value, label }));

  async function run(fn, pesan) {
    setBusy(true); setErr("");
    try {
      const fresh = await fn();
      notifySuccess("Berhasil", pesan);
      onChanged?.(fresh);
      return fresh;
    } catch (e) {
      setErr(apiText(e, "Aksi gagal."));
      return null;
    } finally { setBusy(false); }
  }

  async function tutupDenganKeputusan() {
    if (!decision) return;
    // “Tolak” WAJIB ber-alasan dan alasannya tersimpan DI DOKUMEN (bukan hanya di
    // jejak audit yang tak pernah dibaca orang yang sedang bertanya).
    if (decision === "tolak") {
      const alasan = await askReason({
        title: "Tolak hasil inspeksi",
        message: `Sebutkan alasan penolakan ${doc.number}. Alasan ini dibaca supplier/mitra dan menjadi dasar klaim.`,
        confirmLabel: "Tolak & tutup SPK",
        reasonMinLength: minAlasan,
      });
      if (!alasan) return;
      await run(() => finishInspection(doc.id, decision, alasan), "SPK ditutup: ditolak.");
      return;
    }
    await run(() => finishInspection(doc.id, decision, ""),
      `SPK ditutup: ${INS_DECISION_LABEL[decision] || decision}.`);
  }

  async function bukaKembali() {
    const alasan = await askReason({
      title: "Buka kembali SPK inspeksi",
      message: `Mengapa keputusan pada ${doc.number} dianulir? Alasan wajib — keputusan yang dibatalkan tanpa alasan menghapus jejak tanggung jawab.`,
      confirmLabel: "Buka kembali",
      reasonMinLength: minAlasan,
    });
    if (!alasan) return;
    await run(() => reopenInspection(doc.id, alasan), "SPK dibuka kembali.");
  }

  async function lepasTahanan(line) {
    const alasan = await askReason({
      title: "Lepas tahanan barang",
      message: `Barang ${line.roll_no || line.sku || "ini"} ditahan karena ${line.hold_reason || "selisih terhadap sample"}. Sebutkan dasar keputusan Anda — inilah satu-satunya catatan mengapa barang yang menyimpang tetap masuk gudang.`,
      confirmLabel: "Lepas tahanan",
      reasonMinLength: minAlasan,
    });
    if (!alasan) return;
    await run(() => releaseHold(doc.id, line.id, alasan), "Tahanan dilepas.");
  }

  return (
    <div data-testid="ins-detail-panel" className="grid gap-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p data-testid="ins-detail-number" className="text-[13.5px] font-bold text-[#1C1C1E]">
            {doc.number}
          </p>
          <p className="text-[11px] text-[#6B6B73]">
            {INS_KIND_LABEL[doc.kind] || doc.kind}
            {doc.ref_doc_number ? ` · sumber ${doc.ref_doc_number}` : ""}
            {doc.supplier_name ? ` · ${doc.supplier_name}` : ""}
            {doc.customer_name ? ` · ${doc.customer_name}` : ""}
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <span data-testid="ins-detail-status"
            className={`status-pill ${INS_STATUS_CLASS[doc.status] || "pill-muted"}`}>
            {INS_STATUS_LABEL[doc.status] || doc.status}
          </span>
          {summary.hold ? (
            <span data-testid="ins-detail-hold-badge" className="status-pill pill-danger">
              <Lock size={9} className="mr-0.5 inline" />{summary.hold} barang ditahan
            </span>
          ) : null}
        </div>
      </div>

      {err && <ErrorNotice message={err} onDismiss={() => setErr("")} testId="ins-detail-error" />}

      {/* Acuan penilaian — tanpa menyebut NAMA sample-nya, kolom “warna sesuai?”
          hanya berisi pendapat yang tidak bisa diperiksa ulang siapa pun. */}
      <div className="section-card">
        <div className="flex items-start gap-2">
          <FlaskConical size={14} className="mt-0.5 shrink-0 text-[#6B219A]" />
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wide text-[#9A9BA3]">
              Acuan penilaian
            </p>
            <p data-testid="ins-detail-baseline" className="mt-0.5 text-[11.5px] text-[#3C3C43]">
              {doc.baseline_sample_number
                ? `Sample ${doc.baseline_sample_number}${doc.baseline_color ? ` · ${doc.baseline_color}` : ""}`
                : "Belum ada sample yang di-ACC untuk barang ini — hasil warna & handfeel dicatat sebagai pengamatan, bukan pembandingan."}
            </p>
          </div>
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <div className="section-card">
          <Row label="Tanggal SPK" testId="ins-detail-spk-date">{doc.spk_date || "—"}</Row>
          <Row label="Petugas inspect" testId="ins-detail-officer">
            {doc.assigned_name || "Belum ditugaskan"}
          </Row>
          <Row label="Bagian" testId="ins-detail-bagian">{doc.bagian || "—"}</Row>
          <Row label="Mulai diperiksa" testId="ins-detail-started">
            {(doc.started_at || "").slice(0, 16).replace("T", " ") || "—"}
          </Row>
          <Row label="Selesai" testId="ins-detail-finished">
            {(doc.finished_at || "").slice(0, 16).replace("T", " ") || "—"}
          </Row>
        </div>
        <div className="section-card">
          <Row label="Barang diperiksa" testId="ins-detail-qty">
            <QtyDual rolls={summary.rolls} measure={summary.measure} unit={summary.unit}
              testId="ins-detail-qty-dual" />
          </Row>
          <Row label="Baris sudah diperiksa" testId="ins-detail-inspected">
            {summary.inspected || 0} dari {summary.lines || 0}
          </Row>
          <Row label="Total poin cacat" testId="ins-detail-points">
            {summary.points_total ? summary.points_total : "—"}
          </Row>
          <Row label="Selisih warna / handfeel" testId="ins-detail-mismatch">
            {summary.color_mismatch || 0} / {summary.handfeel_mismatch || 0}
          </Row>
          <Row label="Keputusan" testId="ins-detail-decision">
            {doc.decision_label || "Belum diputuskan"}
          </Row>
        </div>
      </div>

      {doc.reject_reason ? (
        <div className="section-card border-l-2 border-l-[#FF3B30]">
          <p className="text-[11px] font-bold uppercase tracking-wide text-[#9A9BA3]">
            Alasan penolakan
          </p>
          <p data-testid="ins-detail-reject-reason" className="mt-0.5 text-[11.5px] text-[#3C3C43]">
            {doc.reject_reason}
          </p>
        </div>
      ) : null}

      {/* ── BARIS PEMERIKSAAN ── */}
      <div className="section-card">
        <p className="mb-1 text-[11px] font-bold uppercase tracking-wide text-[#9A9BA3]">
          Barang yang diperiksa
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-[11.5px]">
            <thead>
              <tr className="bg-[#FAFBFC] text-[10px] font-bold uppercase text-[#6B6B73]">
                <th className="px-2 py-1.5 text-left">Roll / Artikel</th>
                <th className="px-2 py-1.5 text-right">Jumlah</th>
                <th className="px-2 py-1.5 text-right">Poin</th>
                <th className="px-2 py-1.5 text-left">Grade</th>
                <th className="px-2 py-1.5 text-left">Warna</th>
                <th className="px-2 py-1.5 text-left">Handfeel</th>
                <th className="px-2 py-1.5 text-right">Aksi</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((ln) => (
                <tr key={ln.id} data-testid={`ins-line-${ln.id}`}
                  className="border-b border-[#F2F2F5] last:border-0">
                  <td className="px-2 py-1.5">
                    <span className="font-semibold text-[#1C1C1E]">{ln.roll_no || ln.sku || "—"}</span>
                    <span className="block text-[10px] text-[#8E8E93]">{ln.article || ""}</span>
                    {ln.hold ? (
                      <span data-testid={`ins-line-hold-${ln.id}`} className="status-pill pill-danger mt-0.5">
                        <Lock size={9} className="mr-0.5 inline" /> DITAHAN
                      </span>
                    ) : null}
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    <QtyDual rolls={ln.qty_rolls} measure={ln.quantity} unit={ln.unit}
                      testId={`ins-line-qty-${ln.id}`} compact />
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums">
                    {ln.points_snapshot === null || ln.points_snapshot === undefined
                      ? "—" : ln.points_snapshot}
                  </td>
                  <td className="px-2 py-1.5">
                    {ln.grade_after
                      ? <span data-testid={`ins-line-grade-${ln.id}`}>
                          {ln.grade_before || "—"} &rarr; <strong>{ln.grade_after}</strong>
                        </span>
                      : (ln.grade_before || "—")}
                  </td>
                  <td className="px-2 py-1.5">
                    <span className={`status-pill ${resultPill(ln.color_result)}`}>
                      {INS_COLOR_LABEL[ln.color_result] || "Belum diperiksa"}
                    </span>
                  </td>
                  <td className="px-2 py-1.5">
                    <span className={`status-pill ${resultPill(ln.handfeel_result)}`}>
                      {INS_HANDFEEL_LABEL[ln.handfeel_result] || "Belum diperiksa"}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    <div className="flex flex-wrap justify-end gap-1">
                      {canInspect && open && (
                        <button data-testid={`ins-line-inspect-${ln.id}`} className="link-button"
                          onClick={() => setLineOpen(ln)}>
                          {ln.inspected_at ? "Ubah hasil" : "Isi hasil"}
                        </button>
                      )}
                      {ln.hold && canReleaseHold && (
                        <button data-testid={`ins-line-release-${ln.id}`} className="link-button"
                          disabled={busy} onClick={() => lepasTahanan(ln)}>
                          <LockOpen size={11} className="mr-0.5 inline" /> Lepas tahanan
                        </button>
                      )}
                      {ln.hold && !canReleaseHold && (
                        <span data-testid={`ins-line-hold-note-${ln.id}`} className="text-[10px] text-[#B45309]">
                          menunggu keputusan manajer
                        </span>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {lines.length === 0 && (
                <tr><td colSpan={7} className="px-2 py-3 text-center text-[11px] text-[#8E8E93]">
                  SPK ini belum punya baris barang — biasanya karena roll penerimaannya
                  belum dibuat. Muat ulang setelah penerimaan selesai.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
        {lines.some((l) => l.hold) && (
          <p data-testid="ins-hold-explainer" className="mt-1.5 text-[11px] text-[#B45309]">
            Barang yang DITAHAN tidak bisa ditempatkan ke rak (putaway) sebelum manajer
            melepasnya ber-alasan — supaya barang menyimpang tidak terjual diam-diam.
          </p>
        )}
      </div>

      {/* ── AKSI ── */}
      <div className="section-card grid gap-2">
        <p className="text-[11px] font-bold uppercase tracking-wide text-[#9A9BA3]">Tindakan</p>

        {canAssign && open && (
          <div className="grid gap-2 sm:grid-cols-[1fr_160px_auto] sm:items-end">
            <label className="block">
              <span className="field-label">Tugaskan ke petugas inspect</span>
              <KNSelect data-testid="ins-assign-select" value={assignee}
                onValueChange={setAssignee} options={meta?.officers || []}
                className="field" placeholder="Pilih petugas" />
            </label>
            <label className="block">
              <span className="field-label">Bagian</span>
              <input data-testid="ins-assign-bagian" className="field" value={bagian}
                onChange={(e) => setBagian(e.target.value)} placeholder="Bagian Inspect" />
            </label>
            <button data-testid="ins-assign-button" className="primary-button"
              disabled={busy || !assignee}
              onClick={() => run(() => assignInspection(doc.id, assignee, bagian),
                                 "SPK ditugaskan.")}>
              <User size={13} /> Tugaskan
            </button>
          </div>
        )}

        <div className="flex flex-wrap items-end gap-2">
          {canInspect && ["draft", "assigned"].includes(doc.status) && (
            <button data-testid="ins-start-button" className="secondary-button" disabled={busy}
              onClick={() => run(() => startInspection(doc.id), "Pemeriksaan dimulai.")}>
              <Play size={13} /> Mulai periksa
            </button>
          )}

          {canDecide && ["assigned", "in_progress"].includes(doc.status) && (
            <>
              <label className="block w-60">
                <span className="field-label">Keputusan akhir</span>
                <KNSelect data-testid="ins-decision-select" value={decision}
                  onValueChange={setDecision} options={decisionOptions}
                  className="field" placeholder="Pilih keputusan" />
              </label>
              <button data-testid="ins-finish-button" className="primary-button"
                disabled={busy || !decision} onClick={tutupDenganKeputusan}>
                <CheckCircle2 size={13} /> Tutup SPK
              </button>
            </>
          )}

          {canDecide && doc.status === "done" && (
            <button data-testid="ins-reopen-button" className="secondary-button" disabled={busy}
              onClick={bukaKembali}>
              <RotateCcw size={13} /> Buka kembali
            </button>
          )}

          <button data-testid="ins-detail-close" className="secondary-button" onClick={onClose}>
            Tutup
          </button>
        </div>

        {/* Cetak / tanda tangan lewat PLATFORM DOKUMEN (G-4) — bukan mesin PDF sendiri */}
        <div className="border-t border-[#EFF0F2] pt-2">
          <DocumentActionsBar docType="inspection_spk" sourceId={doc.id}
            entityId={doc.entity_id} number={doc.number} currentUser={currentUser} />
        </div>
      </div>

      {/* ── RIWAYAT ── */}
      <div className="section-card">
        <p className="text-[11px] font-bold uppercase tracking-wide text-[#9A9BA3]">Riwayat</p>
        <div data-testid="ins-detail-history" className="mt-1 grid gap-1">
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

      <InspectLineModal
        open={Boolean(lineOpen)} onClose={() => setLineOpen(null)}
        doc={doc} line={lineOpen} meta={meta}
        onSaved={(fresh) => { setLineOpen(null); onChanged?.(fresh); }}
      />
    </div>
  );
}
