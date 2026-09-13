#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# Report which oracle-ai-dev features are configured. Usage: doctor.sh <connection>
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "${DIR}/../../verify/lib.sh"   # headless-SQLcl flag; without it every probe
                                      # below fails and reports features as 'absent'
CONN="${1:?usage: doctor.sh <connection>}"
# Return a bare scalar. SQLcl otherwise emits a column heading, a separator rule and
# ANSI colour codes, which made every probe below mis-parse (and report features as
# 'absent' even when present).
q() {
  printf 'SET HEADING OFF\nSET FEEDBACK OFF\nSET PAGESIZE 0\n%s\n' "$2" \
    | sql -S "${CONN}" 2>/dev/null \
    | sed 's/\x1b\[[0-9;]*[A-Za-z]//g' \
    | tr -d '[:space:]'
}

u=$(q plugin_dev "SELECT COUNT(*) FROM all_users WHERE username='PLUGIN_DEV';")
[ "${u}" = "1" ] && echo "plugin_dev user: present" || echo "plugin_dev user: absent"

vm=$(q vmem "SELECT value FROM v\$parameter WHERE name='vector_memory_size';")
if [ -z "${vm}" ] || [ "${vm}" = "0" ]; then
  echo "vector_memory_size: 0 (IVF ok; HNSW needs enable-vector-memory + restart)"
else
  echo "vector_memory_size: ${vm} (HNSW available)"
fi

sa=$(q selectai "SELECT COUNT(*) FROM all_objects WHERE object_name='DBMS_CLOUD_AI';")
[ "${sa:-0}" != "0" ] && echo "select_ai (DBMS_CLOUD_AI): present" || echo "select_ai (DBMS_CLOUD_AI): absent"
