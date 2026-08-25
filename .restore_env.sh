#!/usr/bin/env bash
# Restore runtime environment after clone (deps + seed + FE build).
#
# ─── PELAJARAN 2026-08-20 (FASE D) — BACA SEBELUM MENGUBAH URUTAN ────────────
# Kontainer bisa datang dengan **mongodb MATI** (supervisor: STOPPED). Versi lama
# skrip ini tidak pernah memeriksanya, jadi yang terjadi:
#   [3/5] restart backend  → `bootstrap.run_bootstrap()` jalan, gagal diam-diam
#                            (tak ada DB) → koleksi FONDASI tidak pernah lahir
#   [4/5] seed_realistic   → mati dengan ServerSelectionTimeoutError
# Sesudah mongo dinyalakan tangan lalu seed diulang, semuanya TAMPAK sehat —
# padahal `expense_categories`, COA, dsb. tetap KOSONG karena bootstrap hanya
# jalan saat backend START, dan backend tidak pernah di-restart lagi.
#
# Akibatnya nyata & memakan waktu: `gate.sh --full` memerah di POC FASE E-4
# ("Kategori Biaya: 0 baris global terlihat dari KSC") — gate benar, kodenya tidak
# salah, LINGKUNGANNYA yang separuh jadi. Kelas jebakan ini sudah pernah tercatat
# di SESSION_HANDOFF (K1: "uoms 4 baris, CM/INCH hilang tergantung urutan restart
# vs seed") tetapi belum pernah dijaga skripnya.
#
# Maka sekarang: (1) mongo dipastikan HIDUP lebih dulu, (2) backend di-restart
# SESUDAH itu supaya bootstrap menulis ke DB yang nyata, (3) ada langkah
# VERIFIKASI FONDASI yang GAGAL BERISIK. Gagal berisik di sini jauh lebih murah
# daripada memburu gate merah yang bukan bug.
set -uo pipefail

echo "=== [1/7] pip install (skip emergentintegrations & litellm: sudah di base image) $(date)"
cd /app/backend
grep -vE '^(emergentintegrations|litellm)' requirements.txt > /tmp/req_filtered.txt
pip install --no-input -q -r /tmp/req_filtered.txt 2>&1 | tail -20
echo "PIP_EXIT=$?"

echo "=== [2/7] yarn install $(date)"
cd /app/frontend
yarn install --silent --network-timeout 600000 2>&1 | tail -20
echo "YARN_EXIT=$?"

echo "=== [3/7] pastikan MongoDB HIDUP (prasyarat bootstrap & seed) $(date)"
supervisorctl start mongodb 2>&1 | tail -3
for i in $(seq 1 30); do
  if python -c "
import sys
from pymongo import MongoClient
try:
    MongoClient('mongodb://localhost:27017', serverSelectionTimeoutMS=1500).server_info()
except Exception:
    sys.exit(1)
" 2>/dev/null; then
    echo "mongodb SIAP setelah ${i}x percobaan."
    break
  fi
  sleep 2
  if [ "$i" -eq 30 ]; then
    echo "FATAL: mongodb tidak pernah siap — hentikan restore (bootstrap & seed akan"
    echo "       'berhasil' tanpa menulis apa pun, dan gate akan memerah di tempat"
    echo "       yang salah). Periksa: supervisorctl status mongodb"
    exit 1
  fi
done

echo "=== [4/7] restart backend — bootstrap fondasi menulis ke DB yang HIDUP $(date)"
supervisorctl restart backend 2>&1 | tail -5
sleep 12
curl -s -o /dev/null -w "backend /api/ -> %{http_code}\n" http://localhost:8001/api/

echo "=== [5/7] seed_realistic $(date)"
cd /app
python seed_realistic.py 2>&1 | tail -15
echo "SEED_EXIT=$?"

echo "=== [6/7] VERIFIKASI FONDASI (gagal berisik, bukan gate merah menyesatkan) $(date)"
python - <<'PY'
import sys
from pymongo import MongoClient

# Koleksi yang HANYA lahir dari `bootstrap.run_bootstrap()` (saat backend START),
# bukan dari `seed_realistic.py`. Kalau salah satu kosong, artinya backend pernah
# start tanpa DB → restart backend sekali lagi sudah cukup.
WAJIB = {
    "expense_categories": "kategori pengeluaran petty cash (POC FASE E-4 memeriksanya)",
    "uoms": "master satuan (FASE U: CM·INCH·KG·MTR·PANEL·PCS·RLL·YRD)",
    "gl_accounts": "bagan akun baku (COA) — semua jurnal bergantung padanya",
}
db = MongoClient("mongodb://localhost:27017")["test_database"]
kosong = {c: why for c, why in WAJIB.items() if db[c].count_documents({}) == 0}
for c, why in sorted(WAJIB.items()):
    n = db[c].count_documents({})
    print(f"  {'OK ' if n else 'KOSONG'}  {c:22s} {n:>4} dok   — {why}")
if kosong:
    print("\nFATAL: koleksi fondasi KOSONG: " + ", ".join(sorted(kosong)))
    print("Sebabnya hampir selalu: backend start SEBELUM mongodb hidup, atau DB")
    print("di-drop sesudah backend berjalan. Obatnya satu perintah:")
    print("    supervisorctl restart backend   # bootstrap jalan ulang (idempotent)")
    sys.exit(1)
print("  fondasi LENGKAP.")
PY
FOUND_EXIT=$?
if [ $FOUND_EXIT -ne 0 ]; then
  echo "=== [6b/7] fondasi kosong → restart backend sekali lagi lalu ukur ulang"
  supervisorctl restart backend 2>&1 | tail -3
  sleep 14
  python - <<'PY'
import sys
from pymongo import MongoClient
db = MongoClient("mongodb://localhost:27017")["test_database"]
sisa = [c for c in ("expense_categories", "uoms", "gl_accounts")
        if db[c].count_documents({}) == 0]
print("  masih kosong:", sisa or "tidak ada — fondasi LENGKAP.")
sys.exit(1 if sisa else 0)
PY
  echo "FOUNDATION_RETRY_EXIT=$?"
fi

echo "=== [7/7] rebuild frontend $(date)"
bash /app/scripts/rebuild_frontend.sh 2>&1 | tail -15
echo "BUILD_EXIT=$?"
echo "=== RESTORE DONE $(date)"
