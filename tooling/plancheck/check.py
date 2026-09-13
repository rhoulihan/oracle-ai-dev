# Copyright (c) 2026 Oracle and/or its affiliates.
"""Plan-check a query: pull its EXPLAIN plan and say how it will be served.

This is the mechanism behind query-craft's "every generated query is
plan-checked before delivery" — and the SAME explain path the measured
optimizer reads its per-cell access summaries through (`optimize/runner.py`
imports from here), so the delivery gate and the measurement can never drift.

A number without its access path is not evidence, and neither is a query: a
TABLE ACCESS FULL under a filtered read means the index the pattern implies is
missing or unused, and production will pay for it as the table grows. An
unpredicated read legitimately scans — that is the query, not a defect.
"""

import re


def _placeholder_binds(sql):
    """{name: None} for every :name placeholder — EXPLAIN needs bind METADATA,
    not values, but python-oracledb refuses unbound placeholders outright
    (DPY-4010), which made the datalayer's generated bind-form queries
    uncheckable. Colons inside quoted literals (timestamps) don't match: a
    bind name must start with a letter."""
    stripped = re.sub(r"'[^']*'", "''", sql)          # colons in literals are not binds
    return {m: None for m in set(re.findall(r":([A-Za-z]\w*)", stripped))}


def explain(conn, sql):
    """The execution plan for one statement, as operation lines."""
    with conn.cursor() as cur:
        cur.execute(f"EXPLAIN PLAN FOR {sql}", _placeholder_binds(sql))
        return [l.strip() for (l,) in cur.execute(
            "SELECT plan_table_output FROM TABLE(DBMS_XPLAN.DISPLAY(NULL, NULL, 'BASIC'))")
            if l and l.strip()]


# Access methods, worst first: a full scan anywhere dominates the summary, because it is the
# thing that will hurt as the table grows.
_ACCESS = [("TABLE ACCESS FULL", "FULL SCAN"),
           ("INDEX FAST FULL SCAN", "IDX FFS"),
           ("INDEX FULL SCAN", "IDX FULL"),
           ("INDEX SKIP SCAN", "IDX SKIP"),
           ("INDEX UNIQUE SCAN", "IDX UNIQUE"),
           ("INDEX RANGE SCAN", "IDX RANGE"),
           ("TABLE ACCESS BY INDEX ROWID", "BY ROWID")]


def plan_access(plan):
    """HOW the design served the pattern, in two words. The capstone analysis did this by
    hand; doing it by default is what turns a stopwatch into a design tool — a number without
    its access path explains nothing and can be quietly wrong."""
    up = " | ".join(plan or []).upper()
    for needle, label in _ACCESS:
        if needle in up:
            return label
    return "?" if not plan else "OTHER"


def _scanned_tables(lines):
    """The object each `TABLE ACCESS FULL` line scans. DBMS_XPLAN's BASIC format is a pipe
    table — `|  1 |  TABLE ACCESS FULL| ITINERARY_RESERVATIONS |` — so the name is the field
    AFTER the operation, not the last one (which is empty)."""
    out = set()
    for l in lines:
        parts = [c.strip() for c in l.split("|")]
        for i, c in enumerate(parts):
            if "TABLE ACCESS FULL" in c.upper() and i + 1 < len(parts) and parts[i + 1]:
                out.add(parts[i + 1])
    return out


def summarize_plan(plan, sql=None):
    """The verdict on one plan -> {plan, access, uses_index, full_scans, warnings}.

    Pure — feed it explain() output (or any DBMS_XPLAN lines). `sql` decides
    whether a full scan is a defect: with a WHERE / JSON_EXISTS filter it is a
    warning; without one the scan is the honest plan and stays silent."""
    scans = sorted(_scanned_tables(plan or []))
    filtered = bool(sql) and bool(re.search(r"\bWHERE\b|JSON_EXISTS", sql, re.I))
    warnings = []
    if scans and filtered:
        warnings.append(
            f"FULL SCAN of {', '.join(scans)} on a filtered query — the index the "
            f"predicate implies is missing or unused; this will hurt as the table grows")
    return {"plan": list(plan or []),
            "access": plan_access(plan),
            "uses_index": any("INDEX" in l.upper() for l in plan or []),
            "full_scans": scans,
            "warnings": warnings}


def plan_check(conn, sql):
    """EXPLAIN one statement on the connected database and summarize it."""
    return summarize_plan(explain(conn, sql), sql=sql)
