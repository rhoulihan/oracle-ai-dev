#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# Usage: create-plugin-user.sh <sqlcl-connection> [password]
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "${DIR}/../../verify/lib.sh"
CONN="${1:?usage: create-plugin-user.sh <connection> [password]}"
PW="${2:-Plugin_dev_pw1}"
# The password is interpolated into SQL via SQLcl &-substitution, which is a raw
# textual rewrite performed before parsing. Reject anything but a safe charset so
# a quote or ampersand cannot break out of the CREATE USER literal (injection) or
# trigger an interactive substitution prompt that would hang the non-interactive pipe.
if ! [[ "${PW}" =~ ^[A-Za-z0-9_#]{8,30}$ ]]; then
  echo "ASSERT:plugin_user:FAIL (unsafe password: use 8-30 chars of A-Za-z0-9_# only)"
  exit 1
fi
run_check() {
  local out
  echo "@${DIR}/create-plugin-user.sql ${PW}" | sql -S "${CONN}" >/dev/null 2>&1 || return 1
  # Capture-then-match, never `| grep -q`: an early-exiting grep SIGPIPEs the
  # still-writing producer, and pipefail turns that into a false FAIL.
  out="$(echo "SELECT COUNT(*) FROM all_users WHERE username='PLUGIN_DEV';" \
    | sql -S "${CONN}" 2>/dev/null)" || return 1
  grep -q "1" <<< "${out}"
}
assert plugin_user run_check
