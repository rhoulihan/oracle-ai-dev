# The tuning loop

A deterministic loop, not guesswork.

1. **Baseline.** Capture the current plan and cost:
   `EXPLAIN PLAN FOR <query>` + `SELECT * FROM TABLE(DBMS_XPLAN.DISPLAY)`, or the
   real cursor plan with `DBMS_XPLAN.DISPLAY_CURSOR`. Turn on `SET AUTOTRACE ON`
   in SQLcl for plan + statistics. For a running statement, use real-time SQL
   Monitor (`/*+ MONITOR */` + `DBMS_SQL_MONITOR.REPORT_SQL_MONITOR`).

   Two capture traps:
   - **PLAN_TABLE is session-private** (a global temporary table). Run the
     `EXPLAIN PLAN` and the `DBMS_XPLAN.DISPLAY` in the SAME session — across
     two connections (or two `exec`s into a container) the display returns
     "cannot fetch plan".
   - **Predicate Information needs the right format.** `DBMS_XPLAN`'s default
     `TYPICAL` prints the predicate list; the `BASIC` format omits it. When the
     question is *where a filter runs* (pre- vs post-filter around an index),
     use `'BASIC +PREDICATE'` or `TYPICAL` — the operation tree alone can't
     answer it.
2. **Hypothesize.** Read the plan for the cost driver — a full scan where an index
   is expected, a bad join order, a cardinality misestimate, a missing predicate
   pushdown.
3. **Change one thing.** Add/adjust an index, add a hint, rewrite the query, or —
   the biggest lever — change the data shape (escalate to the modeling skill).
   Rehearse DDL against a clone schema/PDB first.
4. **Re-measure.** Re-run the baseline capture and compare. Keep the change only
   if the plan and measured cost improved; otherwise revert.

Repeat until the query meets its latency budget. Record what worked so the next
regression starts from evidence.

## Symptom: GATHER_TABLE_STATS fails with ORA-20000 on "SYS"."&lt;table&gt;"

A stats call in a provisioning/init script running as SYS with
`ALTER SESSION SET CURRENT_SCHEMA = app_user` fails trying to analyze
`"SYS".<table>`: the `USER` function resolves to the LOGON user, not the
current schema, so `DBMS_STATS.GATHER_TABLE_STATS(USER, ...)` targets SYS.
Name the schema explicitly — `DBMS_STATS.GATHER_TABLE_STATS('APP_USER', ...)`.
Worth fixing eagerly: fresh stats in init scripts are load-bearing for
deterministic plan choices (without them, dynamic sampling can pick a
different plan per build).

## Symptom: a JSON predicate ignores its multivalue index

Check the predicate FORM before anything else: only simple dot notation (or an
explicit `type(strict)` form) matches a multivalue index's semantics. A scalar
`JSON_VALUE(...)` predicate is a different expression and full-scans beside it;
so does an item method on the predicate side (`.string() =`). Rewrite to plain
dot and re-check the plan (`python -m tooling.plancheck`).

Two sharp corners of the same symptom:
- **Array fields**: dot-equality is not containment — it returns 0 rows,
  fast, and looks like a win. `JSON_EXISTS(t.data, '$.f?(@ == "x")')` is both
  the correct answer and the index-sharing form.
- **The write path**: hand-written UPDATE/DELETE predicates are where
  `JSON_VALUE` sneaks back in unnoticed — one measured cell went 367ms → 2ms
  from adding the index AND rewriting the filter to dot form. The rule holds
  on writes exactly as on reads.

## Sources
- Oracle Database Performance Tuning Guide (26ai) —
  https://docs.oracle.com/en/database/oracle/oracle-database/26/tgdba/
