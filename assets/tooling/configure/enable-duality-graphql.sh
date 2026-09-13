#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# REST-enable a schema so ORDS serves GraphQL over its duality views at
# /ords/{schema}/_/graphql. Idempotent. Usage:
#   enable-duality-graphql.sh <sqlcl-connection> <schema>
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "${DIR}/../../verify/lib.sh"
CONN="${1:?usage: enable-duality-graphql.sh <connection> <schema>}"
SCHEMA="${2:?schema required}"
enable() {
  local out
  out="$(echo "BEGIN
  ORDS.ENABLE_SCHEMA(p_enabled => TRUE, p_schema => UPPER('${SCHEMA}'),
    p_url_mapping_type => 'BASE_PATH', p_url_mapping_pattern => LOWER('${SCHEMA}'),
    p_auto_rest_auth => FALSE);
  COMMIT;
END;
/
SELECT 'GRAPHQL_OK_' || COUNT(*) AS result FROM user_ords_schemas;" \
    | sql -S "${CONN}" 2>/dev/null)"
  sql_success "${out}" 'GRAPHQL_OK_[1-9]'
}
assert duality_graphql enable
