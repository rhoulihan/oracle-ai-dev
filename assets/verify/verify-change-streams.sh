#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# Deferred-feature probe: does the Oracle API for MongoDB support change streams
# yet? Prints ASSERT:change_streams:PASS|FAIL. Expected FAIL on the current image;
# flips to PASS at GA. Usage: verify-change-streams.sh <mongodb-uri>
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
export OAD_NO_SQL=1  # this script never calls sql — skip SQLcl resolution
# shellcheck source=/dev/null
source "${DIR}/lib.sh"
URI="${1:?usage: verify-change-streams.sh <mongodb-uri>}"
probe() {
  local out
  # Capture-then-match, never `| grep -q`: an early-exiting grep SIGPIPEs the
  # still-writing producer, and pipefail turns that into a false FAIL.
  out="$(mongosh "${URI}" --quiet --eval \
    'const cs = db.getCollection("cs_probe").watch(); cs.close(); print("ok");' \
    2>/dev/null)" || return 1
  grep -q ok <<< "${out}"
}
assert change_streams probe
