/**
 * RndSamplesView (FASE F · PS-12/PS-18, diperluas FASE S) — **Permintaan Sample**
 * (labdip · handfeel · proofing — boleh lebih dari satu per permintaan).
 *
 * Tiga perubahan FASE S yang terlihat langsung di layar ini:
 *   1. **chip penyaring jenis datang dari MASTER** (`/api/rnd/sample-types`), bukan
 *      daftar tetap di kode — jenis yang ditambah pemilik langsung muncul, dan
 *      `bulk_sample` yang dinonaktifkan hilang tanpa perlu ubah kode;
 *   2. kolom **Jenis** menampilkan SEMUA jenis permintaan itu (bisa dua lencana);
 *   3. kartu ringkasan menyebut **tertaut pesanan · jadi · menunggu kirim** —
 *      angkanya dari agregat SERVER, bukan dari isi halaman (pelajaran P2: lencana
 *      yang dihitung dari halaman diam-diam menyusut mengikuti halaman).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Beaker, Plus, RefreshCw, Search } from "lucide-react";
import ErrorNotice from "../../components/ErrorNotice";
import LineFilter from "../../components/LineFilter";   // FASE L
import EntityBadge from "../../components/EntityBadge";
import { formatCurrency } from "../../utils/formatters";
import SampleFormModal from "./SampleFormModal";
import SampleDetailPanel from "./SampleDetailPanel";
import { listSamples, sampleTypes } from "./rndApi";
import { errMsg, SAMPLE_STATUS_META } from "./rndMeta";
import { sampleTypesOf, typeLabel } from "./sampleTypeMeta";
import DetailModal from "../../components/DetailModal";

export default function RndSamplesView({ currentUser, selectedEntity, focus, onFocusConsumed }) {
  const [rows, setRows] = useState([]);
  const [stats, setStats] = useState({});
  const [types, setTypes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [lineFilter, setLineFilter] = useState("");   // FASE L
  const [showForm, setShowForm] = useState(false);
  const [openId, setOpenId] = useState("");
  // Deep-link (event `kn-open-rnd`): prefill form dari Pustaka Warna / kartu desain,
  // atau buka permintaan tertentu dari nomornya (tautan "asal harga" di kontrak).
  const [prefill, setPrefill] = useState(null);
  const [pendingNumber, setPendingNumber] = useState("");

  const role = currentUser?.role;
  const canCreate = ["admin", "manager", "sales"].includes(role);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { limit: 300 };
      if (selectedEntity && selectedEntity !== "all") params.entity_id = selectedEntity;
      if (type) params.sample_type = type;
      if (lineFilter) params.line = lineFilter;          // FASE L
      const res = await listSamples(params);
      setRows(res?.items || []);
      setStats(res?.stats || {});
      setError("");
    } catch (e) {
      setError(errMsg(e, "Gagal memuat permintaan sample."));
    } finally { setLoading(false); }
  }, [selectedEntity, type, lineFilter]);
  useEffect(() => { load(); }, [load]);

  // Chip jenis DARI MASTER — satu sumber dengan form permintaan & validator server.
  useEffect(() => {
    const p = {};
    if (selectedEntity && selectedEntity !== "all") p.entity_id = selectedEntity;
    if (lineFilter) p.line = lineFilter;
    sampleTypes(p).then((r) => setTypes(Array.isArray(r) ? r : []))
      .catch(() => { /* master opsional — penyaring "Semua" tetap berfungsi */ });
  }, [selectedEntity, lineFilter]);

  // ── Deep-link masuk ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!focus?.nonce) return;
    if (focus.sampleId) setOpenId(focus.sampleId);
    else if (focus.sampleNumber) setPendingNumber(focus.sampleNumber);
    if (focus.colorId || focus.designId) {
      setPrefill({
        color_id: focus.colorId || "",
        design_id: focus.designId || "",
        // FASE S — jenis TIDAK ditebak di sini. Dulu baris ini menulis
        // `["proofing"]` untuk deep-link desain: kata "proofing" yang ditanam di
        // layar, padahal jenis mana yang menuntut desain adalah keputusan MASTER
        // (`requires_design`). Yang dikirim sekarang hanya PERTANYAANNYA; form
        // permintaan sample yang menjawabnya dari master.
        need_design: Boolean(focus.designId),
        source_label: focus.colorLabel || focus.designLabel || "",
      });
      setShowForm(true);
    }
    onFocusConsumed?.();
    // Hanya `nonce` yang jadi pemicu — deep-link ke objek sama 2x tetap bekerja.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus?.nonce]);

  // Nomor permintaan → id (dipakai tautan "asal harga" pada layar kontrak).
  useEffect(() => {
    if (!pendingNumber || rows.length === 0) return;
    const hit = rows.find((r) => r.number === pendingNumber);
    if (hit) { setOpenId(hit.id); setPendingNumber(""); }
  }, [pendingNumber, rows]);

  const filtered = useMemo(() => {
    const term = q.trim().toLowerCase();
    if (!term) return rows;
    return rows.filter((r) => [r.number, r.title, r.spec_number, r.color_target?.name,
      r.design_code, r.so_number, ...(r.participants || []).map((p) => p.supplier_name)]
      .some((v) => (v || "").toLowerCase().includes(term)));
  }, [rows, q]);

  const typeFilters = useMemo(
    () => [{ value: "", label: "Semua" }, ...types.map((t) => ({ value: t.value, label: t.label }))],
    [types]);

  return (
    <div data-testid="rnd-samples-view">
      <ErrorNotice message={error} onRetry={load} onDismiss={() => setError("")}
        testId="rnd-samples-error" />

      <div className="section-card mb-3">
        <div className="section-head">
          <div className="flex items-center gap-2">
            <Beaker size={16} className="text-[#0058CC]" />
            <h2 data-testid="rnd-samples-title">Permintaan Sample (Labdip / Handfeel / Proofing)</h2>
          </div>
          <div className="flex items-center gap-2">
            <button className="secondary-button" onClick={load} data-testid="rnd-samples-refresh">
              <RefreshCw size={13} /> Muat ulang
            </button>
            {canCreate && (
              <button className="primary-button" data-testid="rnd-sample-create-button"
                onClick={() => setShowForm(true)}>
                <Plus size={13} /> Permintaan Baru
              </button>
            )}
          </div>
        </div>
        <div className="section-body space-y-2.5">
          {pendingNumber && (
            <div className="rounded-lg bg-[#FFF6E5] px-3 py-2 text-[11.5px] text-[#8C4A00]"
              data-testid="rnd-samples-pending-number">
              Mencari permintaan <b>{pendingNumber}</b>… Bila tidak ditemukan, permintaan itu
              mungkin milik entitas (PT) lain — ganti entitas di pemilih kanan atas.
            </div>
          )}
          <div className="grid grid-cols-2 gap-2 md:grid-cols-6" data-testid="rnd-samples-stats">
            <Kpi label="Total permintaan" value={String(stats.total ?? 0)} />
            <Kpi label="Dikerjakan" value={String(stats.in_progress ?? 0)} tone="#B26A00" />
            <Kpi label="Round terlambat" value={String(stats.overdue_rounds ?? 0)} tone="#C0392B" />
            {/* FASE S — tiga angka baru, semuanya dari agregat SERVER. */}
            <Kpi label="Tertaut pesanan" value={String(stats.linked_so ?? 0)} tone="#0058CC"
              testId="rnd-samples-kpi-so" />
            <Kpi label="Sudah jadi" value={String(stats.finished ?? 0)} tone="#1B7F4B"
              testId="rnd-samples-kpi-finished" />
            <Kpi label="Menunggu dikirim" value={String(stats.awaiting_delivery ?? 0)}
              tone="#8C4A00" testId="rnd-samples-kpi-awaiting" />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative max-w-sm flex-1">
              <Search size={14}
                className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[#9A9BA3]" />
              <input data-testid="rnd-samples-search" value={q}
                onChange={(e) => setQ(e.target.value)} className="field !pl-8"
                placeholder="Cari nomor / judul / supplier / warna / pesanan…" />
            </div>
            <LineFilter value={lineFilter} onChange={setLineFilter} storageKey="rnd-samples"
                        allowed={currentUser?.allowed_line_codes} testId="rnd-samples-line-filter" />
            <div className="flex flex-wrap gap-1.5" data-testid="rnd-samples-filters">
              {typeFilters.map((f) => (
                <button key={f.value} data-testid={`rnd-samples-filter-${f.value || "all"}`}
                  onClick={() => setType(f.value)}
                  className={`rounded-full border px-3 py-1 text-[11px] font-medium ${type === f.value
                    ? "border-[#0058CC] bg-[#0058CC] text-white"
                    : "border-[#E5E5EA] bg-white text-[#3C3C43] hover:border-[#0058CC]"}`}>
                  {f.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="section-card">
        <div className="grid grid-cols-[125px_1.5fr_150px_1.2fr_120px_130px] px-3 py-1.5 bg-[#FAFBFC] text-[10px] font-bold uppercase text-[#6B6B73] border-b border-[#EFF0F2]">
          <span>No. Permintaan</span><span>Judul / spesifikasi</span><span>Jenis</span>
          <span>Supplier &amp; round</span><span>Jadi / dikirim</span>
          <span className="text-right">Status</span>
        </div>
        {loading ? (
          <div className="py-10 text-center text-[12px] text-[#6B6B73]">Memuat permintaan…</div>
        ) : filtered.length === 0 ? (
          <div className="py-12 text-center text-[12px] text-[#6B6B73]"
            data-testid="rnd-samples-empty">
            <Beaker className="mx-auto mb-2 text-gray-300" size={28} />
            <p>Belum ada permintaan sample. Kirim labdip/handfeel/proofing ke beberapa
              supplier sekaligus agar hasilnya bisa dibandingkan sebelum harga dikunci.</p>
          </div>
        ) : (
          <div className="divide-y divide-[#EFF0F2] max-h-[620px] overflow-y-auto">
            {filtered.map((s) => {
              const meta = SAMPLE_STATUS_META[s.status] || SAMPLE_STATUS_META.draft;
              const overdue = (s.rounds || []).some((r) => r.overdue);
              const codes = sampleTypesOf(s);
              return (
                <div key={s.id} data-testid={`rnd-sample-row-${s.id}`}
                  className="grid grid-cols-[125px_1.5fr_150px_1.2fr_120px_130px] items-center px-3 py-2.5 hover:bg-[#FAFBFC]">
                  <button className="text-left text-[11.5px] font-bold text-[#0058CC]"
                    data-testid={`rnd-sample-open-${s.id}`} onClick={() => setOpenId(s.id)}>
                    {s.number}
                  </button>
                  <div className="min-w-0">
                    <p className="truncate text-[12px] font-semibold">{s.title}</p>
                    <p className="truncate text-[10.5px] text-[#6B6B73] flex items-center gap-1">
                      <EntityBadge entityId={s.entity_id} />
                      {s.spec_number || "tanpa spesifikasi"}
                      {s.so_number ? ` · ${s.so_number}` : ""}
                      {s.design_code ? ` · ${s.design_code}` : ""}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-1" data-testid={`rnd-sample-types-${s.id}`}>
                    {codes.length === 0 && <span className="text-[11px] text-[#8E8E93]">—</span>}
                    {codes.map((c) => (
                      <span key={c} className="rounded-full border border-[#E5E5EA] px-1.5 py-0.5 text-[10px]">
                        {typeLabel(c, types)}
                      </span>
                    ))}
                  </div>
                  <div className="min-w-0">
                    <p className="truncate text-[11.5px]">
                      {(s.participants || []).map((p) => p.supplier_name).join(", ") || "—"}
                    </p>
                    <p className="text-[10px] text-[#6B6B73]">
                      {(s.rounds || []).length} round · {formatCurrency(s.cost_total || 0)}
                      {overdue && <span className="ml-1 font-bold text-[#C0392B]">· terlambat</span>}
                    </p>
                  </div>
                  <div className="text-[10.5px]" data-testid={`rnd-sample-exec-${s.id}`}>
                    <p className={s.finished_at ? "font-semibold text-[#1B7F4B]" : "text-[#8E8E93]"}>
                      {s.finished_at ? `jadi ${String(s.finished_at).slice(0, 10)}` : "belum jadi"}
                    </p>
                    <p className={s.delivered_at ? "font-semibold text-[#1B7F4B]" : "text-[#8E8E93]"}>
                      {s.delivered_at
                        ? `kirim ${String(s.delivered_at).slice(0, 10)}` : "belum dikirim"}
                    </p>
                  </div>
                  <div className="flex items-center justify-end">
                    <span className={`status-pill ${meta.cls}`}
                      data-testid={`rnd-sample-status-${s.id}`}>{meta.label}</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {showForm && (
        <SampleFormModal selectedEntity={selectedEntity} prefill={prefill}
          onClose={() => { setShowForm(false); setPrefill(null); }}
          onSaved={(created) => {
            setShowForm(false); setPrefill(null); load(); setOpenId(created?.id || "");
          }} />
      )}
      {openId && (
        <DetailModal onClose={() => setOpenId("")}
          label="Rincian sample" testId="sample-detail-modal">
          <SampleDetailPanel sampleId={openId} currentUser={currentUser} types={types}
            onClose={() => setOpenId("")} onChanged={load} />
        </DetailModal>
      )}
    </div>
  );
}

function Kpi({ label, value, tone = "#1C1C1E", testId }) {
  return (
    <div className="rounded-lg border border-[#EFF0F2] bg-[#FAFBFC] p-2" data-testid={testId}>
      <p className="text-[9.5px] font-bold uppercase text-[#8E8E93]">{label}</p>
      <p className="text-[13px] font-bold tabular-nums leading-tight" style={{ color: tone }}>{value}</p>
    </div>
  );
}
