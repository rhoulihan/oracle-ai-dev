# Copyright (c) 2026 Oracle and/or its affiliates.
"""The safety policy for operating against a target database.

The optimizer's lifecycle tooling can create, load, reset, and drop benchmark
objects. That is fine on the local Free container — it is disposable — but against
an EXTERNAL system (a developer's real database reached by easy-connect or wallet)
the rule is absolute: never touch pre-existing data without an explicit override.

This module is the single source of truth for that decision; the shell tooling
mirrors it. `container` mode is local; `easy`/`wallet` are external.
"""

READ = "read"                # SELECT, timing a query, capturing a plan, status
WRITE = "write"              # any DML, even the roll-back timing harness
DESTRUCTIVE = "destructive"  # DDL / DELETE / reload / reset / drop objects

_OPS = (READ, WRITE, DESTRUCTIVE)
_LOCAL = ("container",)
_EXTERNAL = ("easy", "wallet")

OVERRIDE_ENV = "OPT_ALLOW_EXTERNAL_WRITES"

_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def dsn_mode(dsn):
    """Classify a DB_DSN under the same policy as the connection modes above.

    The local container — a localhost easy-connect string — is the only LOCAL
    target. Anything else (a remote host, an ADB tcps:// string, a full connect
    descriptor, an empty/unknown value) gets `easy` semantics: reads only,
    unless the developer explicitly overrides. Unknown means external — the
    policy fails safe.
    """
    s = (dsn or "").strip().lower()
    if not s or s.startswith("("):
        return "easy"                    # descriptor or unknown: never the local default
    s = s.split("//", 1)[1] if "//" in s else s     # strip tcp:// / tcps://
    hostport = s.split("/", 1)[0]
    if hostport.startswith("["):
        host = hostport[1:].split("]", 1)[0]        # bracketed IPv6
    else:
        host = hostport.split(":", 1)[0]
    return "container" if host in _LOCAL_HOSTS else "easy"


def check_operation(mode, op, allow_external=False):
    """Return (allowed: bool, reason: str) for running `op` against `mode`.

    - Local container: everything is permitted.
    - External + read: permitted (reads never mutate).
    - External + write/destructive: refused unless `allow_external` is set
      (the developer explicitly asserting a dedicated benchmark target).
    """
    if op not in _OPS:
        raise ValueError(f"unknown operation class: {op!r} (want {_OPS})")

    if mode in _LOCAL:
        return True, "local container: all operations permitted"

    if op == READ:
        return True, "read-only on external target: permitted"

    if allow_external:
        return True, (f"{op} on external target: explicit override in effect "
                      f"({OVERRIDE_ENV}=1) — assuming a dedicated benchmark schema")

    return False, (
        f"{op} refused on external target ({mode}): pre-existing data is protected. "
        f"Point at a DEDICATED benchmark schema and set {OVERRIDE_ENV}=1 to override.")
