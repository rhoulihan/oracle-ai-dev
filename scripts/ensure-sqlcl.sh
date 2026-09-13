#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# Resolve Oracle SQLcl, installing it if missing — SQLcl is a self-healing dependency
# of the bundled MCP server, not something the developer must install by hand.
#
# Prints the absolute path to `sql` on STDOUT (and nothing else); all progress and
# diagnostics go to STDERR, so callers can do:  SQL="$(ensure-sqlcl.sh)"
#
# Resolution order:
#   1. $SQLCL_PATH        — the plugin's optional `sqlcl_path` user config (an absolute
#                           path, or a name to look up on PATH)
#   2. `sql` on PATH      — a SQLcl the developer already has
#   3. the plugin's own copy under $CLAUDE_PLUGIN_DATA (persists across plugin updates),
#      falling back to ~/.oracle-ai-dev when running outside the plugin runtime
#   4. otherwise: download + unpack it (~143 MB), then use that
#
# Idempotent, and safe to run concurrently (the MCP launcher and the SessionStart
# pre-warm hook can race) — the install is guarded by an atomic lock that self-heals:
# a lock whose recorded holder is no longer alive is reclaimed, so a SIGKILL'd or
# power-lost install can never wedge future runs.
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

# Claude Code substitutes ${...} in .mcp.json only when this repo is running as an
# INSTALLED plugin. Opened as a plain project, the placeholders arrive verbatim, so a
# variable can be set and still be meaningless — `CLAUDE_PLUGIN_DATA` literally equal to
# the string "${CLAUDE_PLUGIN_DATA}". The `:-` fallbacks below then never fire, because
# the value is non-empty, and SQLcl installs into a directory named after the unexpanded
# variable in whatever directory happens to be current. Two of those were found in the
# wild at 128 MB and 155 MB, inside unrelated git repos.
#
# Unset anything still carrying a placeholder, so "outside the plugin runtime" takes the
# path it was always documented to take.
for _var in SQLCL_PATH CLAUDE_PLUGIN_DATA TNS_ADMIN SQLCL_HOME; do
  # shellcheck disable=SC2016  # the un-expanded '${' is precisely what we are looking FOR
  case "${!_var:-}" in
    *'${'*|*'$('*) unset "${_var}" ;;
  esac
done
unset _var

TARGET="${SQLCL_HOME:-${CLAUDE_PLUGIN_DATA:-${HOME}/.oracle-ai-dev}/sqlcl}"
BUNDLED="${TARGET}/sqlcl/bin/sql"
LOCK="${TARGET}.lock"
JAVA_MIN=17

# --- Java: SQLcl's runtime dependency ------------------------------------------
# SQLcl is a Java program. Without a new-enough JRE it installs happily and then dies
# with a cryptic JVM error, so check up front and say exactly what's wrong — and never
# download 143 MB we can't run.
java_bin() {
  if [ -n "${JAVA_HOME:-}" ] && [ -x "${JAVA_HOME}/bin/java" ]; then
    echo "${JAVA_HOME}/bin/java"
    return 0
  fi
  command -v java 2>/dev/null
}

java_major() {
  local raw major
  # `java -version` prints to stderr, e.g. openjdk version "21.0.1" / "1.8.0_401".
  # Select the version line, not line 1: with JAVA_TOOL_OPTIONS set (lib.sh sets
  # the dumb-terminal flag) the FIRST line is "Picked up JAVA_TOOL_OPTIONS: ..."
  # and a head-1 parse rejects a perfectly good JVM.
  raw="$("$1" -version 2>&1 | sed -n 's/.*version "\([0-9][^"]*\)".*/\1/p' | head -1)"
  [ -n "${raw}" ] || return 1
  major="${raw%%.*}"
  [ "${major}" = "1" ] && major="$(echo "${raw}" | cut -d. -f2)"   # legacy 1.8 -> 8
  case "${major}" in ''|*[!0-9]*) return 1 ;; esac
  echo "${major}"
}

require_java() {
  local jb major
  if ! jb="$(java_bin)" || [ -z "${jb}" ]; then
    {
      echo "oracle-ai-dev: Oracle SQLcl requires Java ${JAVA_MIN}+, but no \`java\` was found"
      echo "  (not on PATH, and JAVA_HOME is unset or invalid)."
      echo "  Install a JDK/JRE ${JAVA_MIN}+ — e.g. \`sdk install java 21-tem\`,"
      echo "  \`apt install openjdk-21-jre\`, or \`brew install openjdk@21\` — or point"
      echo "  JAVA_HOME at one you already have."
    } >&2
    return 1
  fi
  if ! major="$(java_major "${jb}")"; then
    echo "oracle-ai-dev: could not read the Java version from ${jb}; Oracle SQLcl requires Java ${JAVA_MIN}+." >&2
    return 1
  fi
  if [ "${major}" -lt "${JAVA_MIN}" ]; then
    {
      echo "oracle-ai-dev: Oracle SQLcl requires Java ${JAVA_MIN}+, but ${jb} is Java ${major}."
      echo "  Upgrade it (e.g. \`sdk install java 21-tem\`) or point JAVA_HOME at a ${JAVA_MIN}+ JDK."
    } >&2
    return 1
  fi
  return 0
}

# A `sql` that EXISTS is not a `sql` that WORKS. On a developer machine `sql` is often
# something else entirely — a shim, a wrapper, another tool of the same name. Adopt it
# blindly and the plugin's self-install never fires: every SQLcl-backed configurator then
# fails, and the failure looks like a database problem rather than a PATH problem.
# (Found in demo rehearsal: a `sql` on PATH was a docker shim bound to a compose network
# that no longer existed. `create-plugin-user` reported FAIL and `doctor` said the user was
# absent — for a user that plainly existed.)
#
# So: prove it. Run it, and require it to identify itself as SQLcl.
works() {
  # Pure bash — no grep, no timeout on the critical path. This runs on whatever a developer
  # machine happens to have, so it depends on as little of it as possible; `timeout` is used
  # only when present, as a guard against a candidate that hangs.
  local candidate="$1" out rc
  [ -x "${candidate}" ] || command -v "${candidate}" >/dev/null 2>&1 || return 1
  if command -v timeout >/dev/null 2>&1; then
    out="$(timeout 90 "${candidate}" -version 2>&1 </dev/null)"; rc=$?
  else
    out="$("${candidate}" -version 2>&1 </dev/null)"; rc=$?
  fi
  [ "${rc}" -eq 0 ] || return 1
  case "${out}" in
    *SQLcl*|*sqlcl*|*SQLCL*) return 0 ;;
    *) return 1 ;;
  esac
}

usable() {
  local candidate="$1"
  if works "${candidate}"; then
    return 0
  fi
  echo "oracle-ai-dev: ignoring ${candidate} — it is on PATH but does not run as SQLcl." >&2
  return 1
}

resolve() {
  # 1. explicit override from the plugin's user config
  if [ -n "${SQLCL_PATH:-}" ]; then
    if [ -x "${SQLCL_PATH}" ] && usable "${SQLCL_PATH}"; then
      echo "${SQLCL_PATH}"
      return 0
    fi
    if command -v "${SQLCL_PATH}" >/dev/null 2>&1 && usable "$(command -v "${SQLCL_PATH}")"; then
      command -v "${SQLCL_PATH}"
      return 0
    fi
  fi
  # 3. our own previously-installed copy — preferred over an unproven PATH entry, because
  #    we know exactly what it is
  if [ -x "${BUNDLED}" ] && works "${BUNDLED}"; then
    echo "${BUNDLED}"
    return 0
  fi
  # 2. a SQLcl the developer already has — only if it actually runs
  if command -v sql >/dev/null 2>&1 && usable "$(command -v sql)"; then
    command -v sql
    return 0
  fi
  return 1
}

# SQLcl cannot run at all without a suitable JRE — fail loudly here rather than
# handing back a `sql` that will die on the first invocation (or downloading 143 MB
# we could never execute).
require_java || exit 1

if SQL="$(resolve)"; then
  echo "${SQL}"
  exit 0
fi

# 4. Not found anywhere -> install it. SQLCL_NO_INSTALL opts out (air-gapped
# hosts, and tests that must never reach the network): report and stop instead
# of surprising the caller with a 143 MB download.
if [ -n "${SQLCL_NO_INSTALL:-}" ]; then
  echo "oracle-ai-dev: no usable SQLcl found and SQLCL_NO_INSTALL is set — not downloading." >&2
  exit 1
fi

# Lock so a concurrent launcher + hook don't both download 143 MB.
#
# The lock is an atomic mkdir holding the acquirer's PID, freed by its EXIT trap.
# Traps never run on SIGKILL/OOM/power loss (e.g. Codex killing the launcher at its
# startup timeout mid-download), so the lock must be SELF-HEALING or one killed
# install wedges every later run into a wait-then-fail forever. Staleness is judged
# by holder liveness (`kill -0` on the recorded PID) rather than lock age: a slow
# download is legitimately long-lived, so any age threshold either steals live locks
# or leaves dead ones in place for minutes. (PID reuse can make a dead lock look
# live for one boot cycle — the wait loop below bounds that to a single 6-minute
# wait, after which the next run re-checks. Locks live under the user's own
# CLAUDE_PLUGIN_DATA/HOME, so the holder PID is always ours to signal-probe.)
acquire_lock() {
  mkdir "${LOCK}" 2>/dev/null || return 1
  echo "$$" > "${LOCK}/pid"
  trap 'rm -rf "${LOCK}" 2>/dev/null || true' EXIT
}

lock_is_stale() {
  local pid
  pid="$(cat "${LOCK}/pid" 2>/dev/null || true)"
  if [ -z "${pid}" ]; then
    # A live acquirer writes its PID right after mkdir — give that window a
    # moment before declaring a PID-less lock dir (or a pre-PID-file orphan) dead.
    sleep 2
    pid="$(cat "${LOCK}/pid" 2>/dev/null || true)"
    [ -z "${pid}" ] && return 0
  fi
  ! kill -0 "${pid}" 2>/dev/null
}

reclaim_lock() {
  # Atomic takeover: exactly one contender wins the rename; losers keep waiting.
  local grave="${LOCK}.stale.$$"
  mv "${LOCK}" "${grave}" 2>/dev/null || return 1
  rm -rf "${grave}" 2>/dev/null || true
}

grab_lock() {
  acquire_lock && return 0
  if lock_is_stale; then
    echo "oracle-ai-dev: found a stale SQLcl install lock (its holder is gone); reclaiming it." >&2
    reclaim_lock || true
    acquire_lock && return 0
  fi
  return 1
}

run_install() {
  echo "oracle-ai-dev: Oracle SQLcl not found — installing it for the bundled MCP server (~143 MB, one time)..." >&2
  if ! "${DIR}/install-sqlcl.sh" "${TARGET}" >&2; then
    echo "oracle-ai-dev: SQLcl install failed (needs curl, unzip and Java 17+)." >&2
    exit 1
  fi
}

mkdir -p "$(dirname "${TARGET}")"
if grab_lock; then
  run_install
else
  echo "oracle-ai-dev: SQLcl install already in progress; waiting..." >&2
  for _ in $(seq 1 180); do
    [ -x "${BUNDLED}" ] && break
    # The holder can die mid-download too — take over instead of waiting out 6 min.
    if grab_lock; then
      run_install
      break
    fi
    sleep 2
  done
fi

if SQL="$(resolve)"; then
  echo "${SQL}"
  exit 0
fi
echo "oracle-ai-dev: SQLcl is still unavailable after the install attempt." >&2
exit 1
