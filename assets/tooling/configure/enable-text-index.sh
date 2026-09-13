#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# Create a JSON search index with read-your-writes sync. SEARCH INDEX defaults to
# deferred sync, so fresh docs are not searchable until a sync — SYNC (ON COMMIT)
# fixes that for development. Idempotent. Needs the full image (slim strips Oracle
# Text, ORA-29833). Usage: enable-text-index.sh <conn> <table> <json-column> <index-name>
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "${DIR}/../../verify/lib.sh"
CONN="${1:?usage: enable-text-index.sh <conn> <table> <json-column> <index-name>}"
TBL="${2:?table required}"
COL="${3:?json column required}"
IDX="${4:?index name required}"
create() {
  local out
  out="$(echo "DECLARE n INTEGER;
BEGIN
  SELECT COUNT(*) INTO n FROM user_indexes WHERE index_name = UPPER('${IDX}');
  IF n = 0 THEN
    EXECUTE IMMEDIATE 'CREATE SEARCH INDEX ${IDX} ON ${TBL} (${COL}) FOR JSON '
      || 'PARAMETERS (''SYNC (ON COMMIT)'')';
  END IF;
END;
/
SELECT 'TEXT_INDEX_OK_' || COUNT(*) AS result FROM user_indexes
 WHERE index_name = UPPER('${IDX}');" \
    | sql -S "${CONN}" 2>/dev/null)"
  sql_success "${out}" 'TEXT_INDEX_OK_[1-9]'
}
assert text_index create
