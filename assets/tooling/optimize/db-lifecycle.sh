#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# Initialize / reset / tear down the optimizer's benchmark schema for a new test
# run, with a hard safety guard: on an EXTERNAL target (easy/wallet) any operation
# that writes or drops is REFUSED unless the developer explicitly overrides with
# OPT_ALLOW_EXTERNAL_WRITES=1 — pre-existing data is never touched by default.
# The local container is disposable, so everything is allowed there.
#
# Mirrors tooling/optimize/safety.py (the single source of truth for the policy).
#
# Usage: db-lifecycle.sh <status|init|load|reset|new-project>
#   status       read-only: what benchmark objects exist and their row counts
#   init         create the benchmark schema if absent (canonical + doc + duality)
#   load         generate the sized sample (scale-seed.sql)
#   reset        drop the benchmark objects and recreate them empty (reload)
#   new-project  drop all benchmark objects and stop (start fresh)
set -euo pipefail

CMD="${1:?usage: db-lifecycle.sh <status|init|load|reset|new-project>}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
RUN="$HERE/run-sql.sh"
SEED="$ROOT/assets/seed"
MODE="${OPT_CONN_MODE:-container}"

# Enforce the policy before any SQL runs. op ∈ read|write|destructive.
guard() {
  local op="$1"
  [ "$MODE" = "container" ] && return 0
  [ "$op" = "read" ] && return 0
  if [ "${OPT_ALLOW_EXTERNAL_WRITES:-0}" = "1" ]; then
    echo "note: $op on external target ($MODE) — explicit override in effect." >&2
    return 0
  fi
  echo "REFUSED: $op on external target ($MODE): pre-existing data is protected." >&2
  echo "Point at a DEDICATED benchmark schema and set OPT_ALLOW_EXTERNAL_WRITES=1 to override." >&2
  exit 3
}

init() { for f in 01-canonical 02-json-collection 03-duality; do bash "$RUN" "$SEED/$f.sql"; done; }

case "$CMD" in
  status)      guard read;        bash "$RUN" "$SEED/scale/status.sql" ;;
  init)        guard write;       init ;;
  load)        guard destructive; bash "$RUN" "$SEED/scale/scale-seed.sql" ;;
  reset)       guard destructive; bash "$RUN" "$SEED/scale/drop-benchmark.sql"; init ;;
  new-project) guard destructive; bash "$RUN" "$SEED/scale/drop-benchmark.sql" ;;
  *) echo "unknown command: $CMD (want status|init|load|reset|new-project)" >&2; exit 2 ;;
esac
