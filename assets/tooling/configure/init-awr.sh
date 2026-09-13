#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# Create PDB-local AWR snapshots so `awr` reports work inside FREEPDB1 (gap-1:
# CDB-root snapshots are invisible from the PDB). Run twice to bracket a workload.
# Usage: init-awr.sh <sqlcl-connection-with-awr-priv>
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "${DIR}/../../verify/lib.sh"
CONN="${1:?usage: init-awr.sh <connection>}"
snap() {
  local out
  out="$(echo "BEGIN DBMS_WORKLOAD_REPOSITORY.CREATE_SNAPSHOT; END;
/
SELECT 'AWR_OK_' || COUNT(*) AS result FROM dba_hist_snapshot;" \
    | sql -S "${CONN}" 2>/dev/null)"
  sql_success "${out}" 'AWR_OK_[1-9]'
}
assert awr_snapshot snap
