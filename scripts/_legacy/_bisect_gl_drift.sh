#!/usr/bin/env bash
# Ulangi blok POC "uang" lalu SEED + verify: apakah drift GL 1-1300 (ent_kanda)
# muncul kembali? Dipakai untuk memburu WARN INV-GL-DRIFT yang membuat POC G-6b
# (yang menuntut WARN 0) memerah secara sporadis.
set -uo pipefail
cd /app
POCS=(
  "python backend/test_g2_payment_poc.py"
  "python backend/test_g3_variance_poc.py"
  "python backend/test_g8_bank_poc.py"
  "python backend/test_g9_case_poc.py"
  "python backend/test_g7_contrabon_poc.py"
  "cd backend && python -m pytest tests/test_g6_poc.py -q"
  "cd backend && python -m pytest tests/test_g6b_poc.py -q"
)
drift() {
  python scripts/verify_data_integrity.py 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
    | grep -E "INV-GL-DRIFT|PASS [0-9]+  \|" | tail -2
}
echo "=== AWAL ==="; drift
for c in "${POCS[@]}"; do
  ( eval "$c" ) >/dev/null 2>&1
  echo "--- sesudah: $c (rc=$?)"; drift
done
echo "=== SESUDAH SEED ==="
python seed_realistic.py >/dev/null 2>&1
drift
