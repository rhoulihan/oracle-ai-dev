#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# Enable HNSW vector indexes on Free by sizing the vector pool. Free ships
# VECTOR_MEMORY_SIZE=0 (IVF works; HNSW raises ORA-51962 until this is set).
# Sets it in the SPFILE (a restart is required for it to take effect) within the
# ~2GB Free cap. Usage: enable-vector-memory.sh <sysdba-connection> [size]
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "${DIR}/../../verify/lib.sh"
CONN="${1:?usage: enable-vector-memory.sh <sysdba-connection> [size, default 512M]}"
SIZE="${2:-512M}"
if ! [[ "${SIZE}" =~ ^[0-9]+[MG]$ ]]; then
  echo "ASSERT:vector_memory:FAIL (size must look like 512M or 1G)"
  exit 1
fi
set_param() {
  local out
  # Verify against v$spparameter: this script changes SPFILE scope only, so
  # v$parameter keeps showing the running value (0) until the restart.
  out="$(echo "ALTER SYSTEM SET VECTOR_MEMORY_SIZE = ${SIZE} SCOPE=SPFILE;
SELECT 'VECMEM_OK_' || COUNT(*) AS result FROM v\$spparameter
 WHERE name = 'vector_memory_size' AND isspecified = 'TRUE';" \
    | sql -S "${CONN}" 2>/dev/null)"
  sql_success "${out}" 'VECMEM_OK_[1-9]'
}
# The NOTE must not mask assert's exit status (and a restart note on a FAILED
# change would mislead), so print it only on success.
assert vector_memory set_param || exit 1
echo "NOTE: restart the database for VECTOR_MEMORY_SIZE to take effect (HNSW needs it; IVF does not)."
