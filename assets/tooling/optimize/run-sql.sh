#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# Run a SQL script against the target the optimizer should measure — the local
# Free container, a remote database by easy-connect, or an Autonomous Database by
# mTLS wallet. This is the one execution seam the benchmark harness goes through,
# so the SAME time-query.sql / time-dml.sql / explain-query.sql / scale-seed.sql
# run unchanged whether you optimize against the toy seed or a large real system.
#
# Usage: run-sql.sh <script.sql>            (reads OPT_* from the environment)
#
# Connection modes (OPT_CONN_MODE):
#   container (default) — local Free container via docker exec + sqlplus.
#       OPT_CONTAINER   (default: oracle-ai-dev-db)
#       OPT_CONNECT     (default: demo/Demo_pw_12345@localhost:1521/FREEPDB1)
#   easy — remote DB by easy-connect, using SQLcl (`sql`) on this host.
#       OPT_CONNECT     e.g. app_user/pw@//db.example.com:1521/PDB1
#   wallet — Autonomous Database by mTLS wallet, using SQLcl `-cloudconfig`.
#       OPT_WALLET      path to the wallet .zip (or unzipped dir)
#       OPT_CONNECT     e.g. admin/pw@myadb_tp   (the tnsnames alias in the wallet)
#
# Emits whatever the script prints (BENCH:/PLAN: lines) on stdout, unchanged, so
# the Python analysis layer is identical across targets.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
# lib.sh exports the dumb-jline-terminal flag: the easy/wallet modes run SQLcl,
# which otherwise dies with 'Unable to create a terminal' (and exit code 0!)
# when run non-interactively — the agent/CI case.
# shellcheck source=/dev/null
source "${DIR}/../../verify/lib.sh"

SCRIPT="${1:?usage: run-sql.sh <script.sql>}"
[ -f "$SCRIPT" ] || { echo "no such script: $SCRIPT" >&2; exit 2; }

MODE="${OPT_CONN_MODE:-container}"
CONNECT="${OPT_CONNECT:-demo/Demo_pw_12345@localhost:1521/FREEPDB1}"

case "$MODE" in
  container)
    CONTAINER="${OPT_CONTAINER:-oracle-ai-dev-db}"
    # -L: fail fast instead of prompting on a bad connect (never hang a benchmark).
    exec docker exec -i "$CONTAINER" sqlplus -S -L "$CONNECT" < "$SCRIPT"
    ;;
  easy)
    command -v sql >/dev/null 2>&1 || { echo "SQLcl (sql) not on PATH; run install-sqlcl.sh" >&2; exit 3; }
    exec sql -S "$CONNECT" < "$SCRIPT"
    ;;
  wallet)
    : "${OPT_WALLET:?wallet mode needs OPT_WALLET (path to the wallet .zip/dir)}"
    command -v sql >/dev/null 2>&1 || { echo "SQLcl (sql) not on PATH; run install-sqlcl.sh" >&2; exit 3; }
    # SQLcl consumes the wallet directly; no need to unzip or set TNS_ADMIN.
    exec sql -S -cloudconfig "$OPT_WALLET" "$CONNECT" < "$SCRIPT"
    ;;
  *)
    echo "unknown OPT_CONN_MODE: $MODE (want: container | easy | wallet)" >&2
    exit 2
    ;;
esac
