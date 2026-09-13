# Copyright (c) 2026 Oracle and/or its affiliates.
"""Parse the benchmark harness output line.

Contract (P4): `BENCH:<label>:<primary>:cg=<consistent_gets>:us=<elapsed_us>:cv=<cv>`
where `primary` is the deterministic per-execution cost fed to analyze.py (logical
reads when available, else rounded microseconds). The `:cg=…:us=…:cv=…` tail is
optional so an older `BENCH:<label>:<int>` line still parses.
"""
import re

# The cv tail accepts BOTH '.' and ',' as the decimal character. time-query.sql emits
# cv via TO_CHAR with the session's NLS_NUMERIC_CHARACTERS, and run-sql.sh easy/wallet
# mode execs the host SQLcl with whatever locale the host has — so a German-locale
# session prints 'cv=,22'. Rejecting that here silently dropped cg/us/cv and reported
# noisy=False: the noise gate defeated by a locale. The parser is the robust place to
# fix it — it must cope with every producer, including copies of the .sql asset already
# deployed in user projects.
_BENCH = re.compile(r"BENCH:(\w+):(\d+)(?::cg=(\d+):us=(\d+):cv=([\d.,]+))?")

# the field-proven noise gate: a coefficient of variation above this means the trials
# disagree enough that the measurement should not be trusted as a real difference.
CV_GATE = 0.10


def parse_bench(out: str):
    """Return the parsed metrics dict for the first BENCH line, or None."""
    m = _BENCH.search(out)
    if not m:
        return None
    d = {
        "label": m.group(1),
        "primary": int(m.group(2)),
        "consistent_gets": None,
        "elapsed_us": None,
        "cv": None,
        "noisy": False,
    }
    if m.group(3) is not None:
        cv = float(m.group(5).replace(",", "."))     # 'cv=,22' / 'cv=1,5' — NLS commas
        d.update(consistent_gets=int(m.group(3)), elapsed_us=int(m.group(4)),
                 cv=cv, noisy=cv > CV_GATE)
    return d
