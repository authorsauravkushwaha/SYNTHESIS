#!/usr/bin/env bash
# Verify the SYNTHESIS tamper-evident evidence chain end-to-end.
# Usage: ./scripts/verify_chain.sh [host]     (default http://localhost:8000)
set -euo pipefail
HOST="${1:-http://localhost:8000}"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$DIR/tools/ledgercheck/ledgercheck"

if [[ ! -x "$BIN" ]]; then
  echo "building ledgercheck (C)…"
  gcc -O2 -o "$BIN" "$DIR/tools/ledgercheck/ledgercheck.c"
fi

curl -fsS "$HOST/api/ledger/export" | "$BIN"
