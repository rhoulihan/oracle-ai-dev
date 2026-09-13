#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# Shared helpers for the configurators and the verify harness.

# SQLcl is a JVM/jline app: with no controlling TTY it aborts with
#   java.lang.IllegalStateException: Unable to create a terminal
# The configurators are run NON-INTERACTIVELY (by the agent, and in CI), so every
# `sql -S ...` call would fail and report ASSERT:<name>:FAIL. Force the dumb terminal
# provider — the same flag .mcp.json already sets for the bundled MCP server. Any
# caller-supplied JAVA_TOOL_OPTIONS wins.
export JAVA_TOOL_OPTIONS="${JAVA_TOOL_OPTIONS:--Dorg.jline.terminal.provider=dumb}"

# --- SQLcl: resolved the same self-healing way as the MCP arm -------------------
# These scripts used to call bare `sql` and fail OPAQUELY on a fresh machine: the
# plugin's self-installed SQLcl deliberately lives off PATH (it must survive plugin
# updates), so every configurator reported a bare ASSERT:FAIL with `command not
# found` swallowed. Resolve through ensure-sqlcl.sh (user config -> the plugin's
# own copy -> a PATH sql that actually runs -> download) and expose the result as
# a `sql` FUNCTION, so every `... | sql -S` call site works unchanged.
#
# Eager, at source time: the call sites redirect stderr away, so the actionable
# failure (almost always: no Java 17+) must land on VISIBLE stderr here, before
# any redirection. Scripts that never touch sql (port probes, docker-exec-only
# configurators) set OAD_NO_SQL=1 before sourcing and stay dependency-free.
if [ -z "${OAD_NO_SQL:-}" ]; then
  _OAD_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  if _OAD_SQL="$("${_OAD_LIB_DIR}/../../scripts/ensure-sqlcl.sh")"; then
    sql() { "${_OAD_SQL}" "$@"; }
  else
    sql() {
      echo "oracle-ai-dev: no usable SQLcl — the message above (from ensure-sqlcl.sh) names the cause." >&2
      return 127
    }
  fi
fi

# Verify raw SQLcl/sqlplus output. Usage: sql_success <output> <marker-regex>
# SQLcl prints SQL statement errors to STDOUT and exits 0 (WHENEVER SQLERROR
# defaults to CONTINUE), so exit codes lie — and bare digits false-match, because
# every ORA-xxxxx message contains digits. Success therefore requires the
# script's explicit marker AND no error report anywhere in the output.
sql_success() {
  local out="$1" marker="$2"
  # Herestrings, not `printf | grep -q`: an early-exiting grep would SIGPIPE
  # the printf, and a pipefail caller would see a false failure.
  if grep -qE 'ORA-[0-9]+|PLS-[0-9]+|SP2-[0-9]+' <<< "${out}"; then
    return 1
  fi
  grep -qE "${marker}" <<< "${out}"
}

# Shared assertion helper. Usage: assert <name> <command...>
# On FAIL the command's captured output goes to stderr: a bare ASSERT:FAIL with
# the cause swallowed cost a whole greenfield debugging session.
assert() {
  local name="$1" out; shift
  if out="$("$@" 2>&1)"; then
    echo "ASSERT:${name}:PASS"
  else
    echo "ASSERT:${name}:FAIL"
    [ -n "${out}" ] && printf '%s\n' "${out}" | sed 's/^/  /' >&2
    return 1
  fi
}
