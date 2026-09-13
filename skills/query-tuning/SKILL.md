---
name: query-tuning
description: Use when a query is slow, a plan regresses, or indexes and statistics need analysis on Oracle. Runs a measure-driven tuning loop with Oracle's own plan tooling and advisors — which are licensed and working on Free.
---

# Measure-driven query tuning

Tune with evidence, not guesses: baseline → hypothesis → change → re-measure →
keep or revert. Oracle's Diagnostics and Tuning packs are **included on Free**, so
the full toolset is available.

## The loop
See [the tuning loop](references/tuning-loop.md): capture the plan
(`DBMS_XPLAN.DISPLAY_CURSOR`, autotrace) and real-time SQL Monitor, form a
hypothesis, change one thing (index / hint / rewrite / shape change — escalate to
the modeling skill for a shape change), and re-measure. Rehearse risky DDL against
a clone schema before applying.

## Advisors
[Advisors](references/advisors.md): SQL Tuning Advisor, SQL Access Advisor, AWR,
ASH, ADDM — all licensed on Free. Do not reach for the features Free does not
license (Real Application Testing, Automatic Indexing, real-time SPM).

## AWR on Free
FREEPDB1 needs PDB-local snapshots before `awr` reports work — see
[AWR on Free](references/awr-on-free.md).

## Driving it through MCP
The whole loop works through the SQLcl MCP server at restrict level 4; the
advisor APIs flow through `sql_run`.

## Sources
- Oracle Database Performance Tuning Guide (26ai) —
  https://docs.oracle.com/en/database/oracle/oracle-database/26/tgdba/
