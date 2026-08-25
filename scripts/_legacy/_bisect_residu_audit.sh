#!/usr/bin/env bash
# Pelacak residu audit_logs: jalankan tiap gate runtime satu-satu dan ukur
# selisih jumlah dokumen audit_logs sebelum/sesudah. Dipakai sekali untuk
# menemukan pemilik residu +2 pada INV-GATE-01 (bukan bagian dari gate.sh).
set -uo pipefail
cd /app
export $(grep -v '^#' backend/.env | xargs) >/dev/null 2>&1

count() {
  python - <<'PY'
import os
from pymongo import MongoClient
db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
print(db.audit_logs.count_documents({}))
PY
}

# Ambil daftar perintah runtime dari gate.sh (blok AUTH_READY, baris 499..782).
mapfile -t CMDS < <(sed -n '499,782p' scripts/gate.sh \
  | grep -oP '^\s*run_gate "\K[^"]+(?=" ")' )
# D3 (2026-08-25) — parser lama (`shlex.split(...)[2]`) GAGAL pada baris `run_gate`
# yang berlanjut (`\`) dan melewatkan dua POC tanpa berkata apa-apa. Sekarang lewat
# `_parse_run_gate.py`: mengerti baris berlanjut & berisik bila tak bisa dibaca.
mapfile -t GATES < <(python scripts/_legacy/_parse_run_gate.py scripts/gate.sh 499 782)

PREV=$(count)
echo "AWAL audit_logs=$PREV"
for baris in "${GATES[@]}"; do
  label="${baris%%$'\t'*}"
  cmd="${baris#*$'\t'}"
  out=$(eval "$cmd" 2>&1)
  rc=$?
  NOW=$(count)
  D=$((NOW - PREV))
  printf 'delta=%+d rc=%s :: %s\n' "$D" "$rc" "$label"
  if [ "$D" -ne 0 ]; then
    echo "  ^^^ PENYUMBANG RESIDU: $cmd"
  fi
  PREV=$NOW
done
echo "SELESAI audit_logs=$PREV"
