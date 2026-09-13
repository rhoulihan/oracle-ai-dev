#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# Grant the roles an app user needs for SODA (in-database document API). Idempotent.
# Usage: enable-soda.sh <sysdba-connection> <user>
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "${DIR}/../../verify/lib.sh"
CONN="${1:?usage: enable-soda.sh <sysdba-connection> <user>}"
USR="${2:?user required}"
grant() {
  local out
  out="$(echo "GRANT SODA_APP TO ${USR};
SELECT 'SODA_OK_' || COUNT(*) AS result FROM dba_role_privs
 WHERE grantee = UPPER('${USR}') AND granted_role = 'SODA_APP';" \
    | sql -S "${CONN}" 2>/dev/null)"
  sql_success "${out}" 'SODA_OK_[1-9]'
}
assert soda grant
