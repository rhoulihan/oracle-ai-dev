#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# Download and unpack Oracle SQLcl (needed for the bundled MCP server). The Oracle
# Free Use Terms permit downloading/redistributing the unmodified program. Prints
# the absolute path to `sql` on success, or ASSERT:sqlcl:FAIL. Idempotent: skips
# the download if SQLcl is already unpacked at the target.
# Usage: install-sqlcl.sh [install-dir]   (default: ~/.oracle-ai-dev/sqlcl)
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# OAD_NO_SQL breaks a CYCLE, not just noise: lib.sh resolves SQLcl via
# ensure-sqlcl.sh, and ensure-sqlcl.sh runs THIS script to install it — sourcing
# lib.sh here without the opt-out recurses ensure->install->lib->ensure until the
# install lock's wait loop times it out, minutes later.
export OAD_NO_SQL=1
# shellcheck source=/dev/null
source "${DIR}/../assets/verify/lib.sh"
TARGET="${1:-${HOME}/.oracle-ai-dev/sqlcl}"
URL="https://download.oracle.com/otn_software/java/sqldeveloper/sqlcl-latest.zip"
SQL_BIN="${TARGET}/sqlcl/bin/sql"

install() {
  if [ -x "${SQL_BIN}" ]; then
    return 0
  fi
  mkdir -p "${TARGET}"
  local zip="${TARGET}/sqlcl-latest.zip"
  curl -fsSL "${URL}" -o "${zip}" || return 1
  unzip -q -o "${zip}" -d "${TARGET}" || return 1
  rm -f "${zip}"
  [ -x "${SQL_BIN}" ]
}

if install; then
  echo "ASSERT:sqlcl:PASS"
  echo "SQLcl installed. Add to PATH or set the plugin's sqlcl_path config:"
  echo "  ${SQL_BIN}"
else
  echo "ASSERT:sqlcl:FAIL (download/unpack failed; needs curl, unzip, and Java 17+)"
  exit 1
fi
