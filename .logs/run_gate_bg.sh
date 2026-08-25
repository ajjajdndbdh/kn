#!/usr/bin/env bash
# Pelari gate LATAR BELAKANG yang aman dipanggil alat ber-timeout.
#
# Pelajaran 2026-08-23 (tercatat di gate.sh): alat pemanggil yang kena timeout
# MENGULANG perintahnya, sehingga `gate.sh --full` menyala dua kali, keduanya
# menyemai ulang data uji, dan hasilnya 30+ gate MERAH PALSU. Kunci di gate.sh
# sudah menolak gate kedua — tetapi pelari ini menambah satu lapis lagi supaya
# pengulangan itu bahkan tidak sampai memanggil gate: ia menaruh PID-nya sendiri
# di /tmp/kn_gate_runner.pid dan langsung keluar bila pelari lain masih hidup.
#
# Pemakaian: bash .logs/run_gate_bg.sh <label> [argumen gate...]
#   Log     : /app/.logs/gate_<label>.log
#   Penanda : /app/.logs/gate_<label>.done  (berisi kode keluar gate)
set -uo pipefail
cd /app || exit 1

LABEL="${1:-run}"; shift || true
RUNNER_PID_FILE=/tmp/kn_gate_runner.pid
LOG="/app/.logs/gate_${LABEL}.log"
DONE="/app/.logs/gate_${LABEL}.done"

if [ -e "$RUNNER_PID_FILE" ]; then
  OLD="$(cat "$RUNNER_PID_FILE" 2>/dev/null || echo '')"
  if [ -n "$OLD" ] && kill -0 "$OLD" 2>/dev/null; then
    echo "TOLAK: pelari gate lain masih hidup (PID $OLD)." >&2
    exit 3
  fi
fi

rm -f "$DONE"
(
  echo $$ > "$RUNNER_PID_FILE"
  trap 'rm -f "$RUNNER_PID_FILE"' EXIT
  bash scripts/gate.sh "$@" > "$LOG" 2>&1
  echo $? > "$DONE"
) < /dev/null > /dev/null 2>&1 &
disown
echo "pelari gate DIMULAI (label=$LABEL, log=$LOG)"
