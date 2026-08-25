#!/usr/bin/env bash
# Pelacak residu `system_settings` di blok POC FASE (gate.sh 807..848).
set -uo pipefail
cd /app
export $(grep -v '^#' backend/.env | xargs) >/dev/null 2>&1

count() {
  python - <<'PY'
import os
from pymongo import MongoClient
db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
print(db.system_settings.count_documents({}))
PY
}

# D3 (2026-08-25) — alat ini dipindahkan dari `scripts/` ke `scripts/_legacy/` dan
# parsernya diperbaiki: pembacaan baris `run_gate` sekarang lewat
# `scripts/_legacy/_parse_run_gate.py` yang mengerti baris berlanjut (`\`) dan
# BERISIK (`LEWAT: …` ke stderr) bila satu baris tak bisa dibaca. Versi lama memakai
# `shlex.split(...)[2]` dan melewatkan dua POC tanpa berkata apa-apa.
mapfile -t GATES < <(python scripts/_legacy/_parse_run_gate.py scripts/gate.sh 807 848)
PREV=$(count)
echo "AWAL system_settings=$PREV"
for baris in "${GATES[@]}"; do
  label="${baris%%$'\t'*}"
  cmd="${baris#*$'\t'}"
  eval "$cmd" >/dev/null 2>&1
  rc=$?
  NOW=$(count)
  printf 'delta=%+d rc=%s :: %s\n' "$((NOW-PREV))" "$rc" "$label"
  PREV=$NOW
done
echo "SELESAI system_settings=$PREV"
