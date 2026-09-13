# Performance diagnosis — from Mongo command to Oracle SQL and back

Every API command becomes Oracle SQL, so the whole Oracle diagnostic
stack applies — once you can name the statement. This page is the bridge.

## The $native hint

The API's documented hint mechanism is `$native`: it appends any Oracle
optimizer hint to the SQL generated for hint-honoring commands (`find`,
`aggregate`):

```javascript
db.orders.find({...}, {...}).hint({ "$native": "PARALLEL" })
db.orders.aggregate([...], { hint: { "$native": "MONITOR" } })
```

## Monitoring: MONITOR through $native — there is no $monitor

The documented way to put an API statement under Real-Time SQL
Monitoring is the standard `MONITOR` hint delivered via `$native` (no
`$monitor` operator exists in the API). A statement is monitored when it
runs longer than **five seconds**, carries the **MONITOR** hint, or
executes **in parallel** — so short point reads need the hint to show up
at all.

## Finding your SQL_ID

- **Developers, no extra privileges:** `V$ALL_SQL_MONITOR` shows all
  monitored statements visible to the current user — query it right
  after running the hinted command to grab the SQL_ID, and call
  `DBMS_SQLTUNE.REPORT_SQL_MONITOR(sql_id => :id, type => 'ACTIVE')` for
  your own statements.
- **Administrators:** grants are `SELECT` on `V$SQL` and
  `V$SQL_MONITOR`, `ADVISOR`, and `EXECUTE ON DBMS_SQL_MONITOR`; the
  same `REPORT_SQL_MONITOR` call renders the active HTML report for any
  statement.
- **From the access log:** each command record carries `sqlid` — the
  SQL_ID(s) the command executed — so production correlation needs no
  hint at all ([access-logging.md](access-logging.md)).

## The round trip

The full diagnostic loop this skill supports:

1. A slow command → `MONITOR` via `$native` (or pull `sqlid` from the
   access log).
2. SQL monitor / AWR names the statement and its plan.
3. `explain()` from the Mongo lane shows the same plan without leaving
   mongosh — verify predicates land on indexes
   ([sql-stage.md](sql-stage.md), "The plan is visible from the Mongo
   lane").
4. Given only generated SQL from a report, map it back to the command
   that produced it with [reverse-translation.md](reverse-translation.md).

## Sources

- Oracle Database API for MongoDB Guide — Performance Tuning ($native,
  MONITOR, V$ALL_SQL_MONITOR, DBMS_SQLTUNE.REPORT_SQL_MONITOR).
