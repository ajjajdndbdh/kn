/**
 * InspectionsView — FASE I · **INSPEKSI & QC SEBAGAI DOKUMEN** (`<ENT>/INS-#####`).
 *
 * Lembar kerja pemilik ("Inspect PO", "Inspect Retur", "Inspect retur & replacement")
 * akhirnya punya dokumennya: siapa memeriksa, kapan, atas dasar sample yang mana, dan
 * keputusannya. Tiga peran memakai layar yang sama:
 *  - **Kepala gudang / manajer**: menugaskan petugas (SPK penerimaan PO sudah LAHIR
 *    OTOMATIS saat barang masuk antrean QC — tidak dibuat dari nol), lalu memutuskan.
 *  - **Petugas Bagian Inspect**: mengisi cacat per roll + hasil warna & handfeel
 *    dibanding sample yang di-ACC; grade muncul sendiri dari poin.
 *  - **Manajer**: melepas tahanan barang yang warnanya beda (keputusan pemilik #5).
 *
 * Kartu ringkasan SELALU dari agregat server (`stats`) — pelajaran FASE P5: lencana
 * yang dihitung dari isi halaman diam-diam menyusut begitu daftarnya berhalaman.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { ClipboardCheck, Lock, Plus, RefreshCw, ShieldAlert } from "lucide-react";
import axios, { API } from "../../services/apiClient";
import DetailModal from "../../components/DetailModal";
import ErrorNotice from "../../components/ErrorNotice";
import LineFilter from "../../components/LineFilter";
import PaginationBar from "../../components/PaginationBar";
import QtyDual from "../../components/QtyDual";
import { usePagedList } from "../../hooks/usePagedList";
import { qtyDualCsvColumns } from "../../utils/qtyDualCsv";
import { EmptyState } from "../finance/financeShared";
import InspectionDetailPanel from "./InspectionDetailPanel";
import InspectionFormModal from "./InspectionFormModal";
import {
  apiText, getInspection, INS_BOARD_ORDER, INS_KIND_LABEL, INS_KIND_SHORT,
  INS_STATUS_CLASS, INS_STATUS_LABEL, inspectionsMeta, qcTasksWithoutDoc,
} from "./inspectionsApi";

// Kolom CSV: dua satuan memakai `qtyDualCsvColumns` (FASE U / INV-QTY-01) supaya
// kolom Roll di berkas unduhan TIDAK pernah dihitung ulang di layar — angka yang
// dihitung dua kali adalah angka yang akan menyimpang.
const CSV_COLUMNS = [
  { key: "number", header: "Nomor" },
  { header: "Jenis", get: (r) => INS_KIND_LABEL[r.kind] || r.kind || "" },
  { key: "ref_doc_number", header: "Dokumen sumber" },
  { header: "Supplier / Pelanggan", get: (r) => r.supplier_name || r.customer_name || "" },
  { key: "assigned_name", header: "Petugas inspect" },
  { key: "spk_date", header: "Tanggal SPK" },
  { header: "Status", get: (r) => INS_STATUS_LABEL[r.status] || r.status || "" },
  { key: "baseline_sample_number", header: "Acuan sample" },
].concat(
  qtyDualCsvColumns({ itemsOf: (r) => r.lines || [], rollHeader: "Roll",
                      measureHeader: "Jumlah" }),
).concat([
  { header: "Poin cacat", type: "number", get: (r) => (r.summary || {}).points_total },
  { header: "Baris ditahan", type: "int", get: (r) => (r.summary || {}).hold },
  { key: "decision_label", header: "Keputusan" },
]);

export default function InspectionsView({ currentUser, selectedEntity = "all" }) {
  const [meta, setMeta] = useState({
    kinds: [], statuses: [], decisions: [], color_results: [], handfeel_results: [],
    officers: [], policy: {}, role: "", can_release_hold: false,
  });
  const [kindFilter, setKindFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [holdOnly, setHoldOnly] = useState(false);
  const [line, setLine] = useState("");
  const [search, setSearch] = useState("");
  const [detail, setDetail] = useState(null);
  const [showCreate, setShowCreate] = useState(false);
  const [orphanTasks, setOrphanTasks] = useState([]);
  const [error, setError] = useState("");

  const role = meta.role || currentUser?.role || "";
  const canCreate = ["admin", "manager"].includes(role);

  const params = useMemo(() => {
    const p = {};
    if (kindFilter) p.kind = kindFilter;
    if (statusFilter) p.status = statusFilter;
    if (holdOnly) p.hold_only = true;
    if (line) p.line = line;
    if (selectedEntity && selectedEntity !== "all") p.entity_id = selectedEntity;
    return p;
  }, [kindFilter, statusFilter, holdOnly, line, selectedEntity]);

  const paged = usePagedList("/inspections", { pageSize: 25, params, search });
  const [stats, setStats] = useState({});

  useEffect(() => {
    inspectionsMeta(selectedEntity)
      .then(setMeta)
      .catch((e) => setError(apiText(e, "Gagal memuat pilihan layar inspeksi.")));
  }, [selectedEntity]);

  const loadStats = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/inspections`, {
        params: { ...params, ...(search ? { q: search } : {}), page: 1, page_size: 1 } });
      setStats(r.data?.stats || {});
    } catch (e) { /* bilah galat daftar sudah bicara — jangan dobel */ }
  }, [params, search]);

  useEffect(() => { loadStats(); }, [loadStats]);

  const loadOrphans = useCallback(() => {
    qcTasksWithoutDoc().then(setOrphanTasks).catch(() => setOrphanTasks([]));
  }, []);
  useEffect(() => { loadOrphans(); }, [loadOrphans]);

  const openDetail = useCallback(async (id) => {
    try { setDetail(await getInspection(id)); }
    catch (e) { setError(apiText(e, "Gagal memuat rincian inspeksi.")); }
  }, []);

  const refreshAll = useCallback(() => {
    paged.refresh(); loadStats(); loadOrphans();
  }, [paged, loadStats, loadOrphans]);

  const kindChips = [{ key: "", label: "Semua jenis" }].concat(
    (meta.kinds || []).map((k) => ({ key: k.value, label: INS_KIND_SHORT[k.value] || k.label })));
  const statusChips = [{ key: "", label: "Semua status" }].concat(
    INS_BOARD_ORDER.map((s) => ({ key: s, label: INS_STATUS_LABEL[s] })));

  const policy = meta.policy || {};

  return (
    <div data-testid="inspections-view" className="grid gap-3">
      {error && (
        <ErrorNotice message={error} onRetry={refreshAll} onDismiss={() => setError("")}
          testId="ins-error" />
      )}
      {paged.error && !error && (
        <ErrorNotice message={paged.error} onRetry={paged.refresh} testId="ins-list-error" />
      )}

      {/* Kepala + aksi */}
      <div className="section-card">
        <div className="section-head">
          <div className="flex items-center gap-2 min-w-0">
            <ClipboardCheck size={15} className="text-[#1F6FEB]" />
            <div className="min-w-0">
              <span className="kicker">Gudang &amp; Operasi</span>
              <h2 data-testid="panel-title" className="text-[13px] font-bold">SPK Inspeksi &amp; QC</h2>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <LineFilter value={line} onChange={setLine} storageKey="inspections"
              allowed={currentUser?.allowed_line_codes} className="!py-1.5"
              testId="ins-line-filter" />
            <input data-testid="ins-search" className="field !py-1.5 !text-[11.5px] w-56"
              placeholder="Cari nomor / dokumen sumber / petugas…"
              value={search} onChange={(e) => setSearch(e.target.value)} />
            <button data-testid="ins-refresh" className="secondary-button !py-1.5"
              onClick={refreshAll}>
              <RefreshCw size={12} /> Muat ulang
            </button>
            {canCreate && (
              <button data-testid="ins-create-button" className="primary-button"
                onClick={() => setShowCreate(true)}>
                <Plus size={13} /> Buat SPK Inspeksi
              </button>
            )}
          </div>
        </div>

        {/* Kartu ringkasan — dari agregat SERVER (bukan dari isi halaman) */}
        <div className="grid gap-2 sm:grid-cols-5">
          {[
            ["Total SPK", stats.total ?? 0, "ins-kpi-total"],
            ["Belum ditugaskan", stats.draft ?? 0, "ins-kpi-draft"],
            ["Sedang diperiksa", stats.in_progress ?? 0, "ins-kpi-progress"],
            ["Barang DITAHAN", stats.hold ?? 0, "ins-kpi-hold"],
            ["Ditolak", stats.rejected ?? 0, "ins-kpi-rejected"],
          ].map(([label, value, tid]) => (
            <div key={tid} className="rounded-lg border border-[#EFF0F2] bg-white px-3 py-2">
              <p className="text-[10px] font-bold uppercase tracking-wide text-[#9A9BA3]">{label}</p>
              <p data-testid={tid} className="text-[15px] font-bold tabular-nums text-[#1C1C1E]">{value}</p>
            </div>
          ))}
        </div>

        {/* Kebijakan yang BERLAKU — supaya petugas tahu akibat sebelum mengisi */}
        <p data-testid="ins-policy-note" className="mt-2 text-[11px] text-[#6B6B73]">
          Kebijakan berlaku: warna beda dari sample &rarr;{" "}
          <strong>{policy.color_mismatch_label || "—"}</strong> · handfeel beda &rarr;{" "}
          <strong>{policy.handfeel_mismatch_label || "—"}</strong>. Tahanan hanya bisa
          dilepas manajer, dengan alasan tertulis.
        </p>
      </div>

      {/* Jaring pengaman: tugas QC tanpa SPK (biasanya kosong) */}
      {orphanTasks.length > 0 && (
        <div data-testid="ins-orphan-tasks" className="section-card border-l-2 border-l-[#FF9500]">
          <div className="flex items-start gap-2">
            <ShieldAlert size={15} className="mt-0.5 shrink-0 text-[#B45309]" />
            <div>
              <p className="text-[12px] font-bold text-[#1C1C1E]">
                {orphanTasks.length} tugas QC belum punya SPK Inspeksi
              </p>
              <p className="mt-0.5 text-[11px] text-[#6B6B73]">
                SPK penerimaan PO seharusnya lahir otomatis saat barang masuk antrean QC.
                Barang di bawah ini masuk sebelum aturan itu berlaku — terbitkan SPK-nya
                lewat tombol <strong>Buat SPK Inspeksi</strong> (jenis “Penerimaan PO”).
              </p>
              <ul className="mt-1 grid gap-0.5">
                {orphanTasks.slice(0, 5).map((t) => (
                  <li key={t.id} data-testid={`ins-orphan-${t.id}`} className="text-[11px] text-[#3C3C43]">
                    {t.po_number || "(tanpa PO)"} · {t.product_name || "—"} ·{" "}
                    <QtyDual rolls={t.qty_rolls} measure={t.quantity} unit={t.unit}
                      testId={`ins-orphan-qty-${t.id}`} compact />
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* Penyaring */}
      <div className="flex flex-wrap items-center gap-1.5">
        {kindChips.map((c) => (
          <button key={c.key || "all-kind"} data-testid={`ins-chip-kind-${c.key || "all"}`}
            className={`status-pill ${kindFilter === c.key ? "pill-info" : "pill-muted"}`}
            onClick={() => setKindFilter(c.key)}>{c.label}</button>
        ))}
        <span className="mx-1 h-4 w-px bg-[#E5E5EA]" />
        {statusChips.map((c) => (
          <button key={c.key || "all-status"} data-testid={`ins-chip-status-${c.key || "all"}`}
            className={`status-pill ${statusFilter === c.key ? "pill-info" : "pill-muted"}`}
            onClick={() => setStatusFilter(c.key)}>{c.label}</button>
        ))}
        <button data-testid="ins-chip-hold"
          className={`status-pill ${holdOnly ? "pill-danger" : "pill-muted"}`}
          onClick={() => setHoldOnly((v) => !v)}>
          <Lock size={9} className="mr-1 inline" /> Hanya yang DITAHAN
        </button>
      </div>

      {paged.loading ? (
        <div data-testid="ins-loading" className="section-card grid gap-2">
          {[0, 1, 2, 3].map((i) => <div key={i} className="h-9 animate-pulse rounded-md bg-[#F2F2F5]" />)}
        </div>
      ) : (paged.items || []).length === 0 ? (
        <div className="section-card">
          <EmptyState icon={ClipboardCheck} title="Belum ada SPK inspeksi"
            hint={holdOnly
              ? "Tidak ada barang yang sedang ditahan. Hapus penyaring “Hanya yang DITAHAN” untuk melihat seluruh SPK."
              : "SPK penerimaan PO lahir otomatis saat barang masuk antrean QC. Untuk retur, hasil makloon, atau barang pengganti, terbitkan SPK-nya lewat tombol Buat SPK Inspeksi."}
            testId="ins-empty" />
        </div>
      ) : (
        <div className="section-card">
          <div className="overflow-x-auto">
            <table className="w-full text-[11.5px]">
              <thead>
                <tr className="bg-[#FAFBFC] text-[10px] font-bold uppercase text-[#6B6B73]">
                  <th className="px-2 py-1.5 text-left">Nomor</th>
                  <th className="px-2 py-1.5 text-left">Jenis</th>
                  <th className="px-2 py-1.5 text-left">Dokumen sumber</th>
                  <th className="px-2 py-1.5 text-left">Petugas</th>
                  <th className="px-2 py-1.5 text-right">Barang</th>
                  <th className="px-2 py-1.5 text-right">Poin</th>
                  <th className="px-2 py-1.5 text-left">Status</th>
                  <th className="px-2 py-1.5 text-right">Aksi</th>
                </tr>
              </thead>
              <tbody>
                {(paged.items || []).map((r) => {
                  const s = r.summary || {};
                  return (
                    <tr key={r.id} data-testid={`ins-row-${r.id}`}
                      className="border-b border-[#F2F2F5] last:border-0">
                      <td className="px-2 py-1.5 font-semibold text-[#1C1C1E]">
                        {r.number}
                        {s.hold ? (
                          <span data-testid={`ins-hold-badge-${r.id}`}
                            className="ml-1 status-pill pill-danger">
                            <Lock size={9} className="mr-0.5 inline" />{s.hold} ditahan
                          </span>
                        ) : null}
                      </td>
                      <td className="px-2 py-1.5 text-[#3C3C43]">{INS_KIND_SHORT[r.kind] || r.kind}</td>
                      <td className="px-2 py-1.5 text-[#3C3C43]">
                        {r.ref_doc_number || "—"}
                        <span className="block text-[10px] text-[#8E8E93]">
                          {r.supplier_name || r.customer_name || ""}
                        </span>
                      </td>
                      <td className="px-2 py-1.5">{r.assigned_name || "Belum ditugaskan"}</td>
                      <td className="px-2 py-1.5 text-right">
                        <QtyDual rolls={s.rolls} measure={s.measure} unit={s.unit}
                          testId={`ins-qty-${r.id}`} compact />
                      </td>
                      <td className="px-2 py-1.5 text-right tabular-nums">
                        {s.points_total ? s.points_total : "—"}
                      </td>
                      <td className="px-2 py-1.5">
                        <span className={`status-pill ${INS_STATUS_CLASS[r.status] || "pill-muted"}`}>
                          {INS_STATUS_LABEL[r.status] || r.status}
                        </span>
                        {r.decision_label ? (
                          <span className="block text-[10px] text-[#6B6B73]">{r.decision_label}</span>
                        ) : null}
                      </td>
                      <td className="px-2 py-1.5 text-right">
                        <button data-testid={`ins-detail-${r.id}`} className="link-button"
                          onClick={() => openDetail(r.id)}>Buka SPK</button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="mt-2">
            <PaginationBar
              page={paged.page} pageSize={paged.pageSize} total={paged.total}
              hasMore={paged.hasMore} loading={paged.loading}
              onPrev={paged.prev} onNext={paged.next} onPageSize={paged.setPageSize}
              testId="ins-pager" label="SPK inspeksi"
              exportConfig={{ columns: CSV_COLUMNS, rows: paged.items,
                fetchAll: paged.fetchAll, filename: "inspeksi-qc" }}
            />
          </div>
        </div>
      )}

      <InspectionFormModal
        open={showCreate} onClose={() => setShowCreate(false)} meta={meta}
        orphanTasks={orphanTasks}
        onCreated={() => { setShowCreate(false); refreshAll(); }}
      />

      {detail && (
        <DetailModal onClose={() => setDetail(null)} label="Rincian SPK inspeksi"
          size="xl" testId="ins-detail-modal">
          <InspectionDetailPanel
            doc={detail} meta={meta} currentUser={currentUser}
            onChanged={(fresh) => { if (fresh) setDetail(fresh); refreshAll(); }}
            onClose={() => { setDetail(null); refreshAll(); }}
          />
        </DetailModal>
      )}
    </div>
  );
}
