#!/usr/bin/env bash

# Run read-only fitness sampling for two venues concurrently.
#
# Usage:
#   SECS=20 SIMULATE=0 ./scripts/run_fitness_multi.sh
#
# Env vars:
#   VENUES   CSV of venues to run (default: "alpaca,kraken")
#   SECS     Duration in seconds per venue (default: 20)
#   SIMULATE 1 to enable --simulate (default: 0)

set -euo pipefail

VENUES=${VENUES:-"alpaca,kraken"}
SECS=${SECS:-20}
SIMULATE=${SIMULATE:-0}

IFS=',' read -r -a VEN_ARR <<< "$VENUES"

pids=()
for V in "${VEN_ARR[@]}"; do
  if [[ "$SIMULATE" == "1" ]]; then
    ( python -m arbit.cli fitness --venue "$V" --secs "$SECS" --simulate ) &
  else
    ( python -m arbit.cli fitness --venue "$V" --secs "$SECS" ) &
  fi
  pids+=("$!")
done

code=0
for pid in "${pids[@]}"; do
  if ! wait "$pid"; then
    code=1
  fi
done

exit "$code"

