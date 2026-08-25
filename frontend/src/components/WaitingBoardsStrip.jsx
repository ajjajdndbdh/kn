/**
 * WaitingBoardsStrip — papan "menunggu keputusan" yang bisa ditempel di layar KERJA,
 * bukan hanya di beranda.
 *
 * KENAPA ADA (2026-06): keputusan yang menahan BARANG (tugas transfer, stock opname,
 * barang ditahan QC) hanya terlihat kalau petugas kebetulan membuka tab yang tepat di
 * layar Operasi. Barang bisa berhenti berhari-hari tanpa satu layar pun menyebutnya —
 * kelas cacat "salah tetapi tenang" yang sama seperti B5.
 *
 * Semua angka & umur tunggu datang dari backend (`approval_backlog_service` lewat
 * `/api/home/*`), jadi papan ini tidak boleh punya pendapat sendiri (INV-HOME-01).
 * Keadaan gagal-baca memakai perilaku yang sama dengan beranda: papan utama TETAP
 * digambar dengan pesan "tidak bisa dibaca" + tombol Coba lagi (regresi B5).
 */
import { useCallback, useEffect, useState } from "react";
import axios, { API } from "../services/apiClient";
import WaitingQueueBoard from "./WaitingQueueBoard";
import { boardLook, selectWaitingBoards } from "../config/waitingBoards";

export default function WaitingBoardsStrip({
  endpoint, entityId = "all", primaryKey, testIdPrefix, onNavigate,
}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = entityId && entityId !== "all" ? { entity_id: entityId } : {};
      const res = await axios.get(`${API}${endpoint}`, { params });
      setData(res.data || null);
      setFailed(false);
    } catch (e) {
      setFailed(true);
    } finally { setLoading(false); }
  }, [endpoint, entityId]);
  useEffect(() => { load(); }, [load]);

  const unreadable = !loading && (failed || !data);
  const boards = selectWaitingBoards(data, unreadable, primaryKey);
  const showEntity = !entityId || entityId === "all";

  return (
    <div className="mb-3 grid gap-2" data-testid={`${testIdPrefix}-boards`}>
      {boards.map((b) => {
        const look = boardLook(b.key);
        return (
          <WaitingQueueBoard key={b.key} board={b} loading={loading && !data}
            unreadable={unreadable} onRetry={load}
            onNavigate={(view) => onNavigate && onNavigate(view, b.key)}
            showEntity={showEntity} icon={look.icon} accent={look.accent}
            gotoLabel={look.goto} emptyText={look.empty} title={look.title}
            testIdBase={`${testIdPrefix}-board-${b.key}`}
            rowTestIdBase={`${testIdPrefix}-board-${b.key}-row`} />
        );
      })}
    </div>
  );
}
