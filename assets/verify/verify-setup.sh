#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# Verify the db profile is up and reachable on 1521.
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
export OAD_NO_SQL=1  # this script never calls sql — skip SQLcl resolution
# shellcheck source=/dev/null
source "${DIR}/lib.sh"
HOST="${1:-localhost}"
PORT="${2:-1521}"
assert db_port_open bash -c "exec 3<>/dev/tcp/${HOST}/${PORT}"
