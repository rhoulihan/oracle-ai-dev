#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# Enable the Oracle API for MongoDB on a running ORDS instance and confirm it.
# The official database/ords container sets mongo.enabled=true automatically;
# this makes it explicit and verifies the config. Usage:
#   enable-mongo-api.sh <ords-container-name>
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
export OAD_NO_SQL=1  # this script never calls sql — skip SQLcl resolution
# shellcheck source=/dev/null
source "${DIR}/../../verify/lib.sh"
ORDS="${1:?usage: enable-mongo-api.sh <ords-container-name>}"
enable() {
  local out
  docker exec "${ORDS}" ords config set mongo.enabled true >/dev/null 2>&1
  # Capture-then-match, never `| grep -q`: an early-exiting grep SIGPIPEs the
  # still-writing producer, and pipefail turns that into a false FAIL.
  out="$(docker exec "${ORDS}" ords config get mongo.enabled 2>/dev/null)" || return 1
  grep -qi true <<< "${out}"
}
assert mongo_api enable
