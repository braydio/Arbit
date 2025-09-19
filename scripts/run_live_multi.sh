#!/usr/bin/env bash

# Run live trading concurrently across multiple venues using the CLI.
#
# Usage:
#   VENUES="alpaca,kraken" SYMBOLS="ETH/USDT,ETH/BTC,BTC/USDT" AUTO_SUGGEST_TOP=0 \
#   ./scripts/run_live_multi.sh
#
# Env vars:
#   VENUES            CSV of venues (default: "alpaca,kraken")
#   SYMBOLS           Optional CSV of legs to filter triangles (applied per venue)
#   AUTO_SUGGEST_TOP  If >0, auto-use top N discovered triangles when none configured

set -euo pipefail

VENUES=${VENUES:-"alpaca,kraken"}
ARGS=(live --venues "$VENUES")

if [[ -n "${SYMBOLS:-}" ]]; then
  ARGS+=(--symbols "$SYMBOLS")
fi
if [[ -n "${AUTO_SUGGEST_TOP:-}" ]]; then
  ARGS+=(--auto-suggest-top "$AUTO_SUGGEST_TOP")
fi

exec python -m arbit.cli "${ARGS[@]}"

