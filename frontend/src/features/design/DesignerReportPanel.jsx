/**
 * DesignerReportPanel — FASE D · **Rapor Desainer** (angka dari dokumen, bukan diketik).
 *
 * Isinya menjawab pertanyaan pemilik: berapa yang diminta, selesai, revisi,
 * rata-rata hari kerja, dan rata-rata bintang — per desainer. Semua dihitung server
 * (`GET /api/design/reports/by-designer`) supaya angka rapor tidak mungkin berbeda
 * dengan isi papan.
 */
import { useCallback, useEffect, useState } from "react";
import { BarChart3, RefreshCw, Star } from "lucide-react";
import ErrorNotice from "../../components/ErrorNotice";
import { EmptyState } from "../finance/financeShared";
import { apiText, designerReport } from "./designRequestsApi";

function Kpi({ label, value, testId }) {
  return (
    <div className="rounded-lg border border-[#EFF0F2] bg-white px-3 py-2">
      <p className="text-[10px] font-bold uppercase tracking-wide text-[#9A9BA3]">{label}</p>
      <p data-testid={testId} className="text-[15px] font-bold tabular-nums text-[#1C1C1E]">{value}</p>
    </div>
  );
}

export default function DesignerReportPanel({ selectedEntity = "all", line = "" }) {
  const [period, setPeriod] = useState("");
  const [data, setData] = useState({ items: [], totals: {} });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (period) params.period = period;
      if (line) params.line = line;
      if (selectedEntity && selectedEntity !== "all") params.entity_id = selectedEntity;
      setData(await designerReport(params));
      setError("");
    } catch (e) {
      setError(apiText(e, "Gagal memuat rapor desainer."));
    } finally { setLoading(false); }
  }, [period, line, selectedEntity]);

  useEffect(() => { load(); }, [load]);

  const t = data.totals || {};
  return (
    <div data-testid="designer-report-panel" className="grid gap-3">
      {error && <ErrorNotice message={error} onRetry={load} onDismiss={() => setError("")} testId="dsr-report-error" />}

      <div className="section-card">
        <div className="section-head">
          <div className="flex items-center gap-2">
            <BarChart3 size={14} className="text-[#6B219A]" />
            <h2 className="text-[13px] font-bold">Rapor Desainer</h2>
          </div>
          <div className="flex items-center gap-2">
            <input data-testid="dsr-report-period" type="month" className="field !py-1.5 !text-[11.5px]"
              value={period} onChange={(e) => setPeriod(e.target.value)} />
            <button data-testid="dsr-report-refresh" className="secondary-button !py-1.5" onClick={load}>
              <RefreshCw size={12} /> Muat ulang
            </button>
          </div>
        </div>
        <div className="grid gap-2 sm:grid-cols-5">
          <Kpi label="Permintaan" value={t.requests ?? 0} testId="dsr-report-total" />
          <Kpi label="Diserahkan" value={t.delivered ?? 0} testId="dsr-report-delivered" />
          <Kpi label="Disetujui" value={t.approved ?? 0} testId="dsr-report-approved" />
          <Kpi label="Putaran revisi" value={t.revision ?? 0} testId="dsr-report-revision" />
          <Kpi label="Lewat tenggat" value={t.overdue ?? 0} testId="dsr-report-overdue" />
        </div>
      </div>

      <div className="section-card">
        {loading ? (
          <div data-testid="dsr-report-loading" className="grid gap-2">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-8 animate-pulse rounded-md bg-[#F2F2F5]" />
            ))}
          </div>
        ) : (data.items || []).length === 0 ? (
          <EmptyState icon={BarChart3} title="Belum ada angka untuk periode ini"
            hint="Rapor terisi begitu ada permintaan desain yang ditugaskan & diserahkan."
            testId="dsr-report-empty" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[11.5px]">
              <thead>
                <tr className="bg-[#FAFBFC] text-[10px] font-bold uppercase text-[#6B6B73]">
                  <th className="px-2 py-1.5 text-left">Desainer</th>
                  <th className="px-2 py-1.5 text-right">Ditugaskan</th>
                  <th className="px-2 py-1.5 text-right">Dikerjakan</th>
                  <th className="px-2 py-1.5 text-right">Diserahkan</th>
                  <th className="px-2 py-1.5 text-right">ACC</th>
                  <th className="px-2 py-1.5 text-right">Revisi</th>
                  <th className="px-2 py-1.5 text-right">Lewat tenggat</th>
                  <th className="px-2 py-1.5 text-right">Rata-rata hari</th>
                  <th className="px-2 py-1.5 text-right">Bintang</th>
                  <th className="px-2 py-1.5 text-right">% ACC</th>
                </tr>
              </thead>
              <tbody>
                {(data.items || []).map((r) => (
                  <tr key={r.designer_id || r.designer} data-testid={`dsr-report-row-${r.designer_id || "none"}`}
                    className="border-b border-[#F2F2F5] last:border-0">
                    <td className="px-2 py-1.5 font-semibold text-[#1C1C1E]">{r.designer}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{r.assigned}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{r.in_progress}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{r.delivered}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{r.approved}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{r.revision}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{r.overdue}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">
                      {r.avg_days === null || r.avg_days === undefined ? "—" : r.avg_days}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums">
                      {r.avg_stars === null || r.avg_stars === undefined ? "—" : (
                        <span className="inline-flex items-center gap-1">
                          <Star size={11} className="text-[#F0A100]" /> {r.avg_stars}
                        </span>
                      )}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{r.acc_rate_pct}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
