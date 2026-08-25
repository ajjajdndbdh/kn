/**
 * PoBoardView — FASE P · **PAPAN PO PER LINI** (kertas kerja MD dalam bentuk layar).
 *
 * Permintaan pemilik: satu baris per PO dengan kolom *Nama Sales · No PO · Nama Item ·
 * Qty · Warna · Tanggal Order · Estimasi Ready · tahap berjalan · Tanggal Masuk ·
 * Qty Terima · Keterangan* — dan **tab per lini**, karena woven/knit/printing
 * dikerjakan orang yang berbeda dengan urutan tahap yang berbeda.
 *
 * EMPAT HAL YANG DISENGAJA DI LAYAR INI
 * ====================================
 * 1. **Tab lini datang dari MASTER** (`lines` pada respons papan), bukan empat blok
 *    statis. Pemilik menambah lini keempat di Pengaturan → Master → Lini Produk dan
 *    tabnya muncul di sini tanpa satu baris kode berubah.
 * 2. **Chip tahap `inspect` MATI dan menjelaskan dirinya** (`locked` +
 *    `locked_reason`). Layar yang menawarkan tombol yang server pasti tolak 409
 *    adalah jebakan; chip mati tanpa penjelasan akan dilaporkan sebagai kerusakan.
 * 3. **Kartu ringkasan dari agregat server** (`summary`), bukan dihitung dari isi
 *    halaman — pelajaran FASE P5: lencana yang dihitung dari halaman aktif diam-diam
 *    menyusut begitu daftarnya berhalaman.
 * 4. **Dua satuan lewat `<QtyDual/>`** (INV-QTY-01): dokumen lama tanpa jumlah roll
 *    tampil "—", bukan "0 roll" yang menyatakan hal yang salah. Kolom CSV memakai
 *    helper bersama `qtyDualRootCsvColumns` supaya berkas dari layar mana pun bisa
 *    ditumpuk di satu lembar.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { ClipboardList, RefreshCw, Search } from "lucide-react";

import ErrorNotice from "../../components/ErrorNotice";
import PaginationBar from "../../components/PaginationBar";
import QtyDual from "../../components/QtyDual";
import { qtyDualRootCsvColumns } from "../../utils/qtyDualCsv";
import PoStageModal from "./PoStageModal";
import {
  PO_STATUS_TABS, STAGE_STATUS_CLASS, STAGE_STATUS_LABEL,
  apiText, fetchBoard, longDateTime, shortDate,
} from "./poBoardApi";

const COLS = "150px 120px 1.3fr 130px 110px 100px 110px 1.5fr 110px 130px 1fr";

const CSV_COLUMNS = [
  { key: "sales_name", header: "Nama Sales" },
  { key: "po_number", header: "No PO" },
  { key: "items_label", header: "Nama Item" },
  ...qtyDualRootCsvColumns({ rollHeader: "Roll Dipesan", measureHeader: "Jumlah Dipesan" }),
  { key: "colors", header: "Warna" },
  { header: "Tanggal Order", type: "date", get: (r) => r.order_date },
  { header: "Estimasi Ready", type: "date", get: (r) => r.eta_ready },
  { header: "Tahap Berjalan", get: (r) => r.current_stage?.label || "" },
  {
    header: "Tahap Selesai",
    get: (r) => (r.stages || []).filter((s) => s.status === "done")
      .map((s) => s.label).join(" · "),
  },
  { header: "Tanggal Masuk", type: "date", get: (r) => r.first_receipt_at },
  ...qtyDualRootCsvColumns({
    rollField: "received_rolls", rollHeader: "Roll Diterima",
    measureHeader: "Jumlah Diterima", measureField: "received_measure",
    unitField: "received_unit",
  }),
  { key: "pr_number", header: "No PR" },
  { header: "No Pesanan", get: (r) => (r.so_numbers || []).join(" · ") },
  { key: "supplier_name", header: "Supplier" },
  { key: "status", header: "Status PO" },
  { key: "notes", header: "Keterangan" },
];

// `currentUser` TIDAK dipakai di layar ini dengan sengaja: pagar lini & isinya
// ditentukan SERVER (`line_restricted` pada respons papan). Menyaring lagi di layar
// berarti dua opini tentang satu hak akses — dan yang salah akan menyembunyikan
// pekerjaan orang tanpa jejak.
export default function PoBoardView({ selectedEntity = "all" }) {
  const [line, setLine] = useState("");
  const [status, setStatus] = useState("open");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [data, setData] = useState({ items: [], total: 0, summary: {}, lines: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [picked, setPicked] = useState(null);      // {row, stage} → pop-up tahap

  const params = useMemo(() => {
    const p = { page, page_size: pageSize };
    if (line) p.line = line;
    if (status) p.status = status;
    if (search.trim()) p.q = search.trim();
    if (selectedEntity && selectedEntity !== "all") p.entity_id = selectedEntity;
    return p;
  }, [line, status, search, page, pageSize, selectedEntity]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await fetchBoard(params);
      setData({
        items: d.items || [], total: d.total || 0,
        summary: d.summary || {}, lines: d.lines || [],
        has_more: Boolean(d.has_more),
      });
      setError("");
    } catch (e) {
      setError(apiText(e, "Gagal memuat papan PO."));
      setData({ items: [], total: 0, summary: {}, lines: [] });
    } finally {
      setLoading(false);
    }
  }, [params]);

  useEffect(() => { load(); }, [load]);
  // Ganti penyaring → kembali ke halaman 1 (kalau tidak, halaman 3 dari hasil lama
  // menghasilkan daftar kosong yang tampak seperti "tidak ada data").
  useEffect(() => { setPage(1); }, [line, status, search, pageSize, selectedEntity]);

  /** Ambil SELURUH baris hasil filter untuk unduhan CSV (bukan hanya halaman ini). */
  const fetchAll = useCallback(async ({ onProgress } = {}) => {
    const out = [];
    let p = 1;
    for (;;) {
      const d = await fetchBoard({ ...params, page: p, page_size: 200 });
      out.push(...(d.items || []));
      onProgress?.({ done: out.length, total: d.total || out.length });
      if (!d.has_more) break;
      p += 1;
      if (p > 50) break;                        // pagar aman (10.000 baris)
    }
    return out;
  }, [params]);

  const rows = data.items;
  const sum = data.summary || {};

  function onSaved(updated) {
    setData((d) => ({
      ...d,
      items: (d.items || []).map((r) => (r.po_id === updated.po_id ? updated : r)),
    }));
    // Ringkasan ikut berubah begitu satu tahap ditandai → ambil ulang agregatnya.
    load();
  }

  return (
    <div data-testid="po-board-view" className="grid gap-3">
      {error && (
        <ErrorNotice message={error} onRetry={load} onDismiss={() => setError("")}
                     testId="po-board-error" />
      )}

      {/* Kepala + penyaring */}
      <section className="section-card">
        <div className="section-head">
          <div className="flex items-center gap-2 min-w-0">
            <ClipboardList size={15} className="text-[#0058CC]" />
            <div className="min-w-0">
              <span className="kicker">Pembelian</span>
              <h2 data-testid="panel-title" className="text-[13px] font-bold">
                Papan PO per Lini
              </h2>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-[#8E8E93]" />
              <input
                data-testid="po-board-search"
                className="field pl-7 w-[190px]"
                placeholder="Cari PO / sales / item…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <button data-testid="po-board-refresh" className="btn-secondary btn-xs"
                    onClick={load} disabled={loading}>
              <RefreshCw size={12} className={loading ? "animate-spin" : ""} /> Muat ulang
            </button>
          </div>
        </div>

        {/* Kartu ringkasan — dari agregat server (seluruh hasil filter) */}
        <div className="grid gap-2 px-3 pb-3 sm:grid-cols-3 lg:grid-cols-5">
          <Metric testId="po-board-metric-total" label="PO di papan" value={sum.total ?? 0} />
          <Metric testId="po-board-metric-belum" label="Belum mulai" value={sum.belum_mulai ?? 0} />
          <Metric testId="po-board-metric-berjalan" label="Berjalan" value={sum.berjalan ?? 0} />
          <Metric testId="po-board-metric-selesai" label="Tahap selesai" value={sum.selesai ?? 0} />
          <Metric testId="po-board-metric-terlambat" label="Lewat estimasi"
                  value={sum.terlambat ?? 0} tone="#FFF1F0" />
        </div>

        {/* Tab lini — DARI MASTER (bukan blok statis). SENGAJA tidak ada bilah
            `<LineFilter/>` di layar ini: dua kontrol untuk satu penyaring adalah
            cara termurah membuat keduanya berselisih (satu ingat pilihan lama di
            localStorage, satu tidak) — kontrak "satu fakta, satu kontrol". */}
        <div className="flex flex-wrap items-center gap-1.5 px-3 pb-2">
          <button data-testid="po-board-tab-all"
                  className={`tab-button ${line === "" ? "active" : ""}`}
                  onClick={() => setLine("")}>
            Semua lini
          </button>
          {(data.lines || []).map((l) => (
            <button key={l.code} data-testid={`po-board-tab-${l.code}`}
                    className={`tab-button ${line === l.code ? "active" : ""}`}
                    onClick={() => setLine(l.code)}
                    title={(l.stage_sequence || []).join(" → ")}>
              {l.name}
            </button>
          ))}
          {(data.line_restricted || []).length ? (
            <span data-testid="po-board-line-restricted"
                  className="ml-1 rounded bg-[#FFF4E5] px-1.5 py-0.5 text-[9.5px] font-bold text-[#B45309]"
                  title="Akses akun Anda dibatasi pada lini ini oleh admin (Badan Usaha & Akses → Akun).">
              akses lini terbatas
            </span>
          ) : null}
        </div>

        {/* Tab status PO */}
        <div className="flex flex-wrap gap-1.5 px-3 pb-3">
          {PO_STATUS_TABS.map((t) => (
            <button key={t.key || "all"} data-testid={`po-board-status-${t.key || "all"}`}
                    className={`tab-button ${status === t.key ? "active" : ""}`}
                    onClick={() => setStatus(t.key)}>
              {t.label}
            </button>
          ))}
        </div>
      </section>

      {/* Papan */}
      <section className="section-card">
        <div className="overflow-x-auto">
          <div className="min-w-[1500px]">
            <div className="grid px-3 py-1.5 bg-[#FAFBFC] text-[10px] font-bold uppercase
                            text-[#6B6B73] border-b border-[#EFF0F2]"
                 style={{ gridTemplateColumns: COLS }}>
              <span>Nama Sales</span><span>No PO</span><span>Nama Item</span>
              <span>Qty</span><span>Warna</span><span>Tgl Pesan</span>
              <span>Est. Siap</span><span>Tahap</span><span>Tgl Masuk</span>
              <span>Qty Terima</span><span>Keterangan</span>
            </div>

            {loading ? (
              <div data-testid="po-board-loading"
                   className="py-10 text-center text-[12px] text-[#6B6B73]">Memuat…</div>
            ) : rows.length === 0 ? (
              <div data-testid="po-board-empty"
                   className="py-12 text-center text-[12px] text-[#6B6B73]">
                Belum ada PO pada penyaring ini. Coba tab <b>Semua</b> atau lini lain.
              </div>
            ) : (
              <div className="divide-y divide-[#EFF0F2]">
                {rows.map((r) => (
                  <div key={r.po_id} data-testid={`po-board-row-${r.po_id}`}
                       className="grid items-center px-3 py-2.5 hover:bg-[#FAFBFC]"
                       style={{ gridTemplateColumns: COLS }}>
                    {/* Nama Sales — DIRUNUT dari pesanan (P-0). Kosong = memang tak ada. */}
                    <div className="min-w-0">
                      {r.sales_name ? (
                        <p data-testid={`po-board-sales-${r.po_id}`}
                           className="text-[12px] font-semibold truncate">{r.sales_name}</p>
                      ) : (
                        <p data-testid={`po-board-sales-${r.po_id}`}
                           className="text-[12px] text-[#8E8E93]"
                           title="PO pembelian rutin — tidak lahir dari pesanan pelanggan, jadi tidak ada sales-nya.">
                          —
                        </p>
                      )}
                      {r.so_numbers?.length ? (
                        <p className="text-[10px] text-[#9A9BA3] truncate">
                          {r.so_numbers.join(" · ")}
                        </p>
                      ) : null}
                    </div>

                    <div className="min-w-0">
                      <p className="text-[11.5px] font-bold text-[#0058CC] truncate">{r.po_number}</p>
                      {r.pr_number ? (
                        <p className="text-[10px] text-[#9A9BA3] truncate">dari {r.pr_number}</p>
                      ) : null}
                    </div>

                    <div className="min-w-0">
                      <p className="text-[12px] font-semibold truncate">{r.items_label || "—"}</p>
                      <p className="text-[10px] text-[#9A9BA3] truncate">{r.supplier_name}</p>
                    </div>

                    <QtyDual rolls={r.qty_rolls} measure={r.quantity} unit={r.unit}
                             className="text-[11.5px]" testId={`po-board-qty-${r.po_id}`} />

                    <span className="text-[11.5px] truncate" title={r.colors || ""}>
                      {r.colors || "—"}
                    </span>
                    <span className="text-[11px] text-[#6B6B73]">{shortDate(r.order_date)}</span>
                    <span className={`text-[11px] ${r.late ? "font-bold text-[#B42318]" : "text-[#6B6B73]"}`}
                          title={r.late ? "Sudah lewat estimasi ready dan belum selesai" : ""}>
                      {shortDate(r.eta_ready)}
                    </span>

                    {/* Tahap — urutan dari master lini dokumen ini */}
                    <div className="flex flex-wrap gap-1">
                      {(r.stages || []).length === 0 ? (
                        <span className="text-[11px] text-[#8E8E93]"
                              title="Produk pada PO ini belum bergolong lini, jadi urutan tahapnya belum diketahui.">
                          belum ada lini
                        </span>
                      ) : r.stages.map((st) => (
                        <button
                          key={st.code}
                          type="button"
                          data-testid={`po-board-stage-${r.po_id}-${st.code}`}
                          disabled={st.locked}
                          onClick={() => setPicked({ row: r, stage: st })}
                          title={st.locked
                            ? st.locked_reason
                            : `${STAGE_STATUS_LABEL[st.status] || st.status}${st.by ? ` — ${st.by}` : ""}${st.at ? ` · ${longDateTime(st.at)}` : ""}${st.note ? `\n“${st.note}”` : ""}`}
                          className={`rounded-md border px-1.5 py-0.5 text-[10.5px] font-semibold
                                      ${STAGE_STATUS_CLASS[st.status] || STAGE_STATUS_CLASS.pending}
                                      ${st.locked ? "cursor-not-allowed opacity-70" : "hover:border-[#1C1C1E]/40"}`}
                        >
                          {st.label}
                          {st.locked ? " 🔒" : ""}
                        </button>
                      ))}
                    </div>

                    <span className="text-[11px] text-[#6B6B73]"
                          title={r.last_receipt_at ? `Terakhir: ${longDateTime(r.last_receipt_at)}` : ""}>
                      {shortDate(r.first_receipt_at)}
                    </span>

                    <QtyDual rolls={r.received_rolls} measure={r.received_measure}
                             unit={r.received_unit} className="text-[11.5px]"
                             testId={`po-board-received-${r.po_id}`} />

                    <span className="text-[11px] text-[#6B6B73] truncate" title={r.notes || ""}>
                      {r.notes || "—"}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="px-3 py-2">
          <PaginationBar
            testId="po-board-pager" label="PO"
            page={page} pageSize={pageSize} total={data.total}
            hasMore={Boolean(data.has_more)} loading={loading}
            onPrev={() => setPage((p) => Math.max(1, p - 1))}
            onNext={() => setPage((p) => p + 1)}
            onPageSize={setPageSize}
            exportConfig={{ columns: CSV_COLUMNS, rows, fetchAll, filename: "papan-po" }}
          />
        </div>
      </section>

      <PoStageModal
        open={Boolean(picked)}
        row={picked?.row}
        stage={picked?.stage}
        onClose={() => setPicked(null)}
        onSaved={onSaved}
      />
    </div>
  );
}

function Metric({ label, value, testId, tone = "#F2F6FF" }) {
  return (
    <div data-testid={testId} className="metric-card">
      <div className="metric-icon" style={{ background: tone }}>
        <ClipboardList size={16} className="text-[#1C1C1E]" />
      </div>
      <div className="min-w-0">
        <p className="text-[10px] font-bold uppercase tracking-wide text-[#8E8E93]">{label}</p>
        <p className="text-[17px] font-bold tabular-nums">{value}</p>
      </div>
    </div>
  );
}
