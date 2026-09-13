#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# Prepare in-database Select AI: the DBMS_CLOUD family is not preinstalled on Free
# (install scripts ship with the DB since RU 23.7). This runs the provided install
# script and confirms DBMS_CLOUD_AI is present. Usage:
#   enable-select-ai.sh <sysdba-connection> <path-to-dbms_cloud_install.sql>
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "${DIR}/../../verify/lib.sh"
CONN="${1:?usage: enable-select-ai.sh <sysdba-connection> <install-script.sql>}"
SCRIPT="${2:?path to the DBMS_CLOUD install script is required}"
if [ ! -f "${SCRIPT}" ]; then
  echo "ASSERT:select_ai:FAIL (install script not found: ${SCRIPT})"
  exit 1
fi
install() {
  local out
  sql -S "${CONN}" <"${SCRIPT}" >/dev/null 2>&1
  out="$(echo "SELECT 'SELECT_AI_OK_' || COUNT(*) AS result FROM all_objects
 WHERE object_name = 'DBMS_CLOUD_AI';" | sql -S "${CONN}" 2>/dev/null)"
  sql_success "${out}" 'SELECT_AI_OK_[1-9]'
}
assert select_ai install
