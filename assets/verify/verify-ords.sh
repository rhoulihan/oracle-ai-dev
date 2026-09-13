#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# Wait until the MongoDB API / REST arm is actually SERVICEABLE, then assert it.
#
# A healthy database is NOT a ready ORDS: on first boot ORDS installs itself INTO
# the database for several minutes after `compose up --wait` returns, so a client
# pointed at 27017 "right after setup" meets connection resets. The probe is the
# one the live test tier uses (tests/live_helpers.py): the ORDS package compiles
# VALID in the PDB — polled via sqlplus inside the DB container, so nothing needs
# SQLcl or a host client. Usage:
#   verify-ords.sh [db-container] [ords-container] [conn] [timeout-seconds]
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
export OAD_NO_SQL=1  # this script probes through docker exec — skip SQLcl resolution
# shellcheck source=/dev/null
source "${DIR}/lib.sh"

DB="${1:-oracle-ai-dev-db}"
ORDS="${2:-oracle-ai-dev-ords}"
# Through the PDB SERVICE, never bare system@host: a common-user connection
# lands in CDB$ROOT, where the ORDS package (installed into FREEPDB1) is
# invisible and this probe would poll forever.
CONN="${3:-system/devpassword@localhost:1521/FREEPDB1}"
TIMEOUT="${4:-600}"

PROBE="SET HEAD OFF PAGES 0 FEED OFF
SELECT status FROM all_objects WHERE object_name='ORDS' AND object_type='PACKAGE';"

ords_ready() {
  # A container that does not EXIST is a setup mistake, not a slow start —
  # say so now instead of polling nothing for ten minutes.
  local c
  for c in "${DB}" "${ORDS}"; do
    if ! docker inspect "${c}" >/dev/null 2>&1; then
      echo "container '${c}' does not exist — is the db+ords profile up?"
      return 1
    fi
  done
  local deadline=$((SECONDS + TIMEOUT)) status=""
  while [ "${SECONDS}" -lt "${deadline}" ]; do
    if [ "$(docker inspect -f '{{.State.Running}}' "${ORDS}" 2>/dev/null)" = "true" ]; then
      status="$(printf '%s\n' "${PROBE}" \
        | docker exec -i "${DB}" sqlplus -S -L "${CONN}" 2>/dev/null | tr -d '[:space:]')"
      [ "${status}" = "VALID" ] && return 0
    fi
    sleep 5
  done
  echo "ORDS not serviceable within ${TIMEOUT}s (last package status: '${status:-none}')."
  echo "ords container logs:"
  docker logs --tail 20 "${ORDS}" 2>&1
  return 1
}

assert ords_ready ords_ready
