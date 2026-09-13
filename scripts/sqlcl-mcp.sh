#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# Launcher for the bundled Oracle SQLcl MCP server.
#
# The plugin's .mcp.json points `command` at this script rather than straight at
# `sql`, so SQLcl becomes a self-healing dependency: we resolve it (user config ->
# PATH -> the plugin's own copy) and install it if it is missing, then exec the real
# SQLcl with whatever MCP args were passed (-mcp -R 4 ...). No required user config,
# no manual install step.
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

if ! SQL="$("${DIR}/ensure-sqlcl.sh")"; then
  echo "oracle-ai-dev: could not obtain Oracle SQLcl for the MCP server." >&2
  echo "The guidance paths still work (modeling, generators, optimizer, vector/RAG," >&2
  echo "data layer). Install SQLcl (or fix the cause named above — usually Java 17+)" >&2
  echo "and set the plugin's sqlcl_path config to enable the database MCP arm." >&2
  exit 1
fi

# The server must see ONLY the plugin's isolated connection store (gap-3 research,
# recommendation 3) — and the SAME store on both platforms, at a path a user can
# reach from a terminal to save connections into. Codex passes args verbatim (no
# ${} expansion) and ${CLAUDE_PLUGIN_DATA} is unreachable from a terminal, so the
# fixed path lives here, not in the manifests. A caller-supplied -home wins.
case " $* " in
  *" -home "*) ;;
  *)
    DBTOOLS_HOME="${HOME}/.oracle-ai-dev/dbtools-home"
    mkdir -p "${DBTOOLS_HOME}"
    set -- "$@" -home "${DBTOOLS_HOME}"
    ;;
esac

exec "${SQL}" "$@"
