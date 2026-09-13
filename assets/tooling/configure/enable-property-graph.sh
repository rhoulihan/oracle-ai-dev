#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# Grant the CREATE PROPERTY GRAPH privilege to an app user so it can build SQL/PGQ
# property graphs. Idempotent (GRANT is safe to repeat). Usage:
#   enable-property-graph.sh <sysdba-connection> <user>
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "${DIR}/../../verify/lib.sh"
CONN="${1:?usage: enable-property-graph.sh <sysdba-connection> <user>}"
USR="${2:?user required}"
grant() {
  local out
  out="$(echo "GRANT CREATE PROPERTY GRAPH TO ${USR};
SELECT 'PROPERTY_GRAPH_OK_' || COUNT(*) AS result FROM dba_sys_privs
 WHERE grantee = UPPER('${USR}') AND privilege = 'CREATE PROPERTY GRAPH';" \
    | sql -S "${CONN}" 2>/dev/null)"
  sql_success "${out}" 'PROPERTY_GRAPH_OK_[1-9]'
}
assert property_graph grant
