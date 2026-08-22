#!/usr/bin/env bash

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PATENTLOOP_PYTHON:-$ROOT/.venv/bin/python}"
RUNS_DIR="${PATENTLOOP_RUNS_DIR:-$ROOT/runs}"
STAMP="$(date +%Y%m%d-%H%M%S)-$$"

run_proof() {
    local label="$1"
    local idea_file="$2"
    local run_id="proof-${label}-${STAMP}"
    local run_dir="$RUNS_DIR/$run_id"
    local status

    printf '\n=== Proof run %s ===\n' "$label"
    set +e
    "$PYTHON" "$ROOT/run.py" \
        --idea-file "$ROOT/scripts/ideas/$idea_file" \
        --run-id "$run_id" \
        --runs-dir "$RUNS_DIR"
    status=$?
    set -e
    printf 'run folder: %s\n' "$run_dir"
    printf 'exit status: %s\n' "$status"
    return "$status"
}

status_a=0
status_b=0
run_proof "survivor" "survivor.txt" || status_a=$?
run_proof "crowded-space" "crowded_space.txt" || status_b=$?

if (( status_a != 0 || status_b != 0 )); then
    exit 1
fi
