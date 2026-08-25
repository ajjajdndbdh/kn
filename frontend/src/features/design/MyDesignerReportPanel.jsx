/**
 * MyDesignerReportPanel — FASE D · **Rapor Saya** untuk peran `designer`.
 *
 * KENAPA PANEL TERSENDIRI, bukan `DesignerReportPanel` dengan sebuah `prop`:
 * keduanya menjawab pertanyaan yang berbeda dan berbeda pula wewenangnya.
 *  · `DesignerReportPanel`  → menilai ORANG (tabel lintas desainer) — atasan.
 *  · panel ini              → "bagaimana pekerjaan SAYA" — siapa pun atas dirinya.
 * Menggabungkannya berarti satu komponen memegang dua izin sekaligus, dan cabang
 * `if (isDesigner)` di dalam tabel adalah tempat kebocoran nama rekan akan lahir.
 *
 * Server (`GET /api/design/reports/mine`) sengaja TIDAK mengirim baris rekan —
 * pembanding tim hanya berupa rata-rata (pola privasi PS-18). Jadi panel ini tidak
 * bisa membocorkan apa pun walau kelak dipakai peran lain.
 */
import { useCallback, useEffect, useState } from "react";
import { BarChart3, CalendarClock, RefreshCw, Star, Trophy } from "lucide-react";
import ErrorNotice from "../../components/ErrorNotice";
import { EmptyState } from "../finance/financeShared";
import { apiText, myDesignerReport } from "./designRequestsApi";

function Kpi({ label, value, hint, testId }) {
  return (
    <div className="rounded-lg border border-[#EFF0F2] bg-white px-3 py-2">
      <p className="text-[10px] font-bold uppercase tracking-wide text-[#9A9BA3]">{label}</p>
      <p data-testid={testId} className="text-[15px] font-bold tabular-nums text-[#1C1C1E]">{value}</p>
      {hint ? <p className="mt-0.5 text-[10px] text-[#8E8E93]">{hint}</p> : null}
    </div>
  );
}

const nOrDash = (v) => (v === null || v === undefined ? "—" : v);

export default function MyDesignerReportPanel({ selectedEntity = "all", line = "" }) {
  const [period, setPeriod] = useState("");
  const [data, setData] = useState({ me: null, totals: {}, team: {} });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (period) params.period = period;
      if (line) params.line = line;
      if (selectedEntity && selectedEntity !== "all") params.entity_id = selectedEntity;
      setData(await myDesignerReport(params));
      setError("");
    } catch (e) {
      setError(apiText(e, "Gagal memuat rapor Anda."));
    } finally { setLoading(false); }
  }, [period, line, selectedEntity]);

  useEffect(() => { load(); }, [load]);

  const me = data.me || null;
  const t = data.totals || {};
  const team = data.team || {};

  return (
    <div data-testid="my-designer-report-panel" className="grid gap-3">
      {error && (
        <ErrorNotice message={error} onRetry={load} onDismiss={() => setError("")}
          testId="dsr-myreport-error" />
      )}

      <div className="section-card">
        <div className="section-head">
          <div className="flex items-center gap-2">
            <BarChart3 size={14} className="text-[#6B219A]" />
            <div className="min-w-0">
              <span className="kicker">Desain</span>
              <h2 className="text-[13px] font-bold">Rapor Saya</h2>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <input data-testid="dsr-myreport-period" type="month"
              className="field !py-1.5 !text-[11.5px]"
              value={period} onChange={(e) => setPeriod(e.target.value)} />
            <button data-testid="dsr-myreport-refresh" className="secondary-button !py-1.5"
              onClick={load}>
              <RefreshCw size={12} /> Muat ulang
            </button>
          </div>
        </div>

        <div className="grid gap-2 sm:grid-cols-5">
          <Kpi label="Ditugaskan" value={t.requests ?? 0} testId="dsr-myreport-total" />
          <Kpi label="Diserahkan" value={t.delivered ?? 0} testId="dsr-myreport-delivered" />
          <Kpi label="Disetujui (ACC)" value={t.approved ?? 0} testId="dsr-myreport-approved" />
          <Kpi label="Putaran revisi" value={t.revision ?? 0} testId="dsr-myreport-revision" />
          <Kpi label="Lewat tenggat" value={t.overdue ?? 0} testId="dsr-myreport-overdue" />
        </div>
      </div>

      <div className="section-card">
        {loading ? (
          <div data-testid="dsr-myreport-loading" className="grid gap-2">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-8 animate-pulse rounded-md bg-[#F2F2F5]" />
            ))}
          </div>
        ) : !me ? (
          <EmptyState icon={BarChart3} title="Belum ada permintaan desain untuk Anda"
            hint="Begitu atasan menugaskan sebuah permintaan, angkanya muncul di sini."
            testId="dsr-myreport-empty" />
        ) : (
          <div className="grid gap-3">
            <div className="grid gap-2 sm:grid-cols-4">
              <Kpi label="Rata-rata hari kerja" value={nOrDash(me.avg_days)}
                hint="dari ditugaskan sampai diserahkan" testId="dsr-myreport-avg-days" />
              <div className="rounded-lg border border-[#EFF0F2] bg-white px-3 py-2">
                <p className="text-[10px] font-bold uppercase tracking-wide text-[#9A9BA3]">
                  Rata-rata bintang
                </p>
                <p data-testid="dsr-myreport-avg-stars"
                  className="inline-flex items-center gap-1 text-[15px] font-bold tabular-nums text-[#1C1C1E]">
                  {me.avg_stars === null || me.avg_stars === undefined ? "—" : (
                    <>
                      <Star size={12} className="text-[#F0A100]" /> {me.avg_stars}
                    </>
                  )}
                </p>
                <p className="mt-0.5 text-[10px] text-[#8E8E93]">nilai artwork di Galeri Desain</p>
              </div>
              <Kpi label="% ACC" value={`${me.acc_rate_pct ?? 0}%`}
                hint="disetujui / ditugaskan" testId="dsr-myreport-acc-rate" />
              <div className="rounded-lg border border-[#EFF0F2] bg-white px-3 py-2">
                <p className="text-[10px] font-bold uppercase tracking-wide text-[#9A9BA3]">
                  Posisi saya
                </p>
                <p data-testid="dsr-myreport-rank"
                  className="inline-flex items-center gap-1 text-[15px] font-bold tabular-nums text-[#1C1C1E]">
                  <Trophy size={12} className="text-[#6B219A]" />
                  {data.rank ? `${data.rank} dari ${data.total_designers}` : "—"}
                </p>
                <p className="mt-0.5 text-[10px] text-[#8E8E93]">berdasarkan jumlah pekerjaan</p>
              </div>
            </div>

            <div className="rounded-lg bg-[#FAFBFC] px-3 py-2">
              <p className="flex items-center gap-1.5 text-[11px] font-bold text-[#3C3C43]">
                <CalendarClock size={12} className="text-[#8E8E93]" />
                Pembanding tim (rata-rata, tanpa nama rekan)
              </p>
              <p data-testid="dsr-myreport-team" className="mt-1 text-[11.5px] text-[#6B6B73]">
                {team.designers
                  ? `${team.designers} desainer aktif · rata-rata ditugaskan `
                    + `${nOrDash(team.avg_assigned)} · diserahkan ${nOrDash(team.avg_delivered)} `
                    + `· ACC ${nOrDash(team.avg_approved)}`
                  : "Belum ada pembanding untuk periode ini."}
              </p>
              <p className="mt-1 text-[10.5px] text-[#9A9BA3]">
                Rapor lintas desainer (per orang) adalah wewenang atasan — di sini Anda
                hanya melihat angka Anda sendiri.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
