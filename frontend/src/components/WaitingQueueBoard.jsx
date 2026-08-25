/**
 * WaitingQueueBoard — papan "yang menunggu keputusan" beserta UMUR TUNGGU-nya.
 *
 * Lahir sebagai Papan PO Custom di Control Tower pemilik (2026-08-24), lalu dipakai
 * ULANG (2026-06) untuk antrean lain yang sama mahalnya bila menunggu: kontrabon
 * bersengketa & retur antar-PT — dan sekarang juga muncul di Dasbor Manajer, orang
 * yang tanda tangannya justru ditunggu.
 *
 * Semua angka datang dari SATU sumber (`approval_backlog_service.queue_detail`):
 * `count` (yang menunggu), `shown`/`hidden`/`truncated` (kejujuran saat daftar
 * dipotong), dan `days_waiting` per baris. Layar tidak menghitung ulang apa pun,
 * jadi mustahil berselisih dengan antrean di layar yang sama (INV-HOME-01).
 */
import { RefreshCw } from "lucide-react";
import EntityBadge from "./EntityBadge";
import { roleLabel } from "../config/roles";

const fmt = new Intl.NumberFormat("id-ID");
const fmtCur = (v) => `Rp ${fmt.format(Math.round(v || 0))}`;

/** Umur tunggu diberi warna: "12 hari" dan "hari ini" bukan pekerjaan yang sama mendesaknya. */
function AgeBadge({ days, testId }) {
  const cls = days >= 7
    ? "bg-[#FFE5E5] text-[#C62828]"
    : days >= 3 ? "bg-[#FFF1DB] text-[#B26A00]" : "bg-[#EFF3FB] text-[#33538B]";
  return (
    <span data-testid={testId}
      className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-bold tabular-nums ${cls}`}>
      {days === 0 ? "hari ini" : `${days} hari`}
    </span>
  );
}

export default function WaitingQueueBoard({
  board = {}, loading = false, unreadable = false, onRetry, onNavigate,
  showEntity = false, icon: Icon, accent = "#6C3FD1", title,
  testIdBase, rowTestIdBase, gotoLabel = "Buka layarnya →", emptyText, gotoTestId,
}) {
  const rows = board.rows || [];
  const go = () => { if (board.view && onNavigate) onNavigate(board.view); };
  const judul = title || (board.label || "Menunggu keputusan");

  return (
    <div className="rounded-xl border p-4"
      style={{ borderColor: `${accent}33`, background: `${accent}0A` }}
      data-testid={testIdBase}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          {Icon ? <Icon size={15} style={{ color: accent }} /> : null}
          <h3 className="truncate text-[14px] font-bold">
            {judul} {unreadable ? "(—)" : `(${board.count ?? 0})`}
          </h3>
        </div>
        <button type="button"
          className="shrink-0 text-[12px] font-semibold disabled:cursor-not-allowed disabled:opacity-40"
          style={{ color: accent }}
          onClick={go} disabled={!board.view}
          title={board.view ? "" : "Layar tujuan belum dikirim server"}
          data-testid={gotoTestId || `${testIdBase}-goto`}>{gotoLabel}</button>
      </div>

      {loading ? (
        <div className="h-16 animate-pulse rounded-lg bg-white/70" />
      ) : unreadable ? (
        /* Kegagalan pemuatan TIDAK boleh tampil sebagai kabar baik (B5). */
        <div className="flex flex-col items-center justify-center gap-2 py-4 text-center"
          data-testid={`${testIdBase}-unreadable`}>
          <p className="text-[13px] font-semibold text-[#C62828]">
            {judul} tidak bisa dibaca
          </p>
          <p className="text-[11.5px] text-[#6B6B73]">
            Data gagal dimuat — ini BUKAN berarti tidak ada yang menunggu keputusan.
          </p>
          {onRetry && (
            <button type="button" onClick={onRetry} className="secondary-button"
              data-testid={`${testIdBase}-retry`}>
              <RefreshCw size={13} /> Coba lagi
            </button>
          )}
        </div>
      ) : rows.length === 0 ? (
        <div className="flex h-16 items-center justify-center text-[13px] text-[#8E8E93]"
          data-testid={`${testIdBase}-empty`}>
          {emptyText || "Tidak ada dokumen yang menunggu keputusan"}
        </div>
      ) : (
        <div className="grid gap-1.5" data-testid={`${testIdBase}-list`}>
          {rows.map((r) => (
            <button key={r.id || r.number} type="button"
              data-testid={`${rowTestIdBase}-${r.id}`}
              onClick={go}
              className="flex items-center gap-3 rounded-lg border border-[#EDEFF3] bg-white px-3 py-2 text-left transition hover:border-[#C9D6E8]">
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-1.5 truncate text-[12px] font-semibold text-[#1C1C1E]">
                  {r.number} · {r.title}
                  {showEntity && r.entity_id ? <EntityBadge entityId={r.entity_id} /> : null}
                </p>
                <p className="truncate text-[10.5px] text-[#8E8E93]">
                  {/* Label peran dari registry (`Manajer`), bukan kode mentah (C1). */}
                  {r.note || judul}{r.role ? ` · perlu ${roleLabel(r.role)}` : ""}
                </p>
              </div>
              {r.amount > 0 && (
                <span className="shrink-0 text-[12px] font-bold tabular-nums"
                  style={{ color: accent }}>{fmtCur(r.amount)}</span>
              )}
              <AgeBadge days={r.days_waiting} testId={`${rowTestIdBase}-age-${r.id}`} />
            </button>
          ))}
          {/* Angka di judul tidak boleh lebih besar dari daftar di layar yang sama
              TANPA satu pun tanda (B2). Penanda datang dari backend. */}
          {board.truncated && (
            <button type="button" data-testid={`${testIdBase}-truncated`}
              onClick={go} disabled={!board.view}
              className="rounded-lg border border-dashed bg-white/60 px-3 py-2 text-[11.5px] font-semibold disabled:opacity-40"
              style={{ borderColor: `${accent}55`, color: accent }}>
              Menampilkan {board.shown ?? rows.length} dari {board.count} —
              {" "}{board.hidden ?? (board.count - rows.length)} lainnya belum tampil ·
              {" "}{gotoLabel}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
