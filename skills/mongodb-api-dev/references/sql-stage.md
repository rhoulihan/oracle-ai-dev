# The $sql aggregation stage — proper SQL without leaving the Mongo lane

Oracle's own pipeline stage: submit SQL from any MongoDB client, get
documents back. It closes the gaps wire compatibility leaves open — joins to
relational tables, window functions, PL/SQL, DDL — without switching tools.

## Two syntax forms

String form, as the pipeline's opening stage (database-level entry via
`db.aggregate`, no collection required):

```javascript
db.aggregate([{ $sql: `
  select fiscal_year, sum(amount_sold) as sum_amount
  from   sh.times t join sh.sales s on (t.time_id = s.time_id)
  group  by fiscal_year order by 1` }])
```

Object form when the statement takes binds:

```javascript
db.aggregate([{ $sql: {
  statement: `select ... where fiscal_year = :1 ...`,
  binds: [ { index: 1, value: 2019 } ]
}}])
```

The full object form takes `statement` (required) plus `binds`,
`dialect`, `format`, `resetSession`, and `input`. **Named binds are
supported only when $sql is the pipeline's only stage** — mid-pipeline,
use positional binds. Rows come back as documents; use
`select json{col1, col2, ...}` (or `json_object`) in the SQL to control
the document shape explicitly.

## Mid-pipeline: the prior stage as a table called `input`

`$sql` does not have to open the pipeline. Placed after other stages, the
documents flowing in are queryable as a table named **`input`** (the
default — the object form's `input` field renames it), with each
document in a column named `DATA` — which turns any pipeline into a SQL
join point:

```javascript
db.movies.aggregate([
  {$match: {year: 2019, gross: {$ne: null}}},
  {$sql: `select json_mergepatch(i.data,
            json{'rank': rank() over (order by i.data."gross" desc)})
          from input i`},
  {$project: {rank: 1, title: 1, gross: 1, _id: 0}},
  {$match: {rank: {$le: 10}}},
  {$sort: {rank: 1}}
])
```

That composes freely with `$out` (materialize SQL results as a collection),
enriches documents from relational tables (`from input e, dept d where ...`),
and calls stored PL/SQL functions in the projection — the pattern that
closed the geo-operator gap in the [migration lanes](migration-lanes.md).

## Sole stage: DDL and DML through the API

When `$sql` is the pipeline's only stage, DDL and DML are allowed — which
makes it the **index-creation bridge** on deployments where the Mongo-lane
`createIndex` is not available (Autonomous Database and 19c-era targets):

```javascript
db.aggregate([{ $sql: `
  create index i_movies_sku on movies
    (json_value(data, '$.sku.stringOnly()' ERROR ON ERROR))` }])
```

Limits worth knowing: a duality view cannot be created through the API
(create it from SQL), and on this plugin's local 26ai Free stack the native
`createIndex` path exists — prefer it there, and see the
[shared-index doctrine](../../sql-json-dev/references/json-indexing.md) for
which index form serves both lanes (the measured version lives in the
[modeling optimization reference](../../oracle-data-modeling/references/optimization.md)).

Binds behave differently in this position, and the failures are type errors
rather than syntax errors. A sole-stage $sql aggregation pipeline stage
against the Oracle API for MongoDB accepts DML (not just SELECT) when given a
named-bind map ({name: value}); the same named bind may be reused multiple
times, the statement runs inside the driver's ClientSession transaction, and
it returns [{result: n}]. A positional-bind array fails if a placeholder index
is reused, raising ORA-17041 (Missing IN or OUT parameter at index: N). PL/SQL
blocks execute through this stage but OUT binds are refused with ORA-06550 /
PLS-00382 (expression is of wrong type); get an existence or count result via
a preceding SELECT COUNT(*) instead of an OUT bind. Unquoted column aliases in
$sql results come back uppercased.

## The plan is visible from the Mongo lane

`getIndexes()` lists SQL-created indexes beside Mongo-created ones, and
`find(...).explain()` returns the REAL Oracle execution plan — access path,
index name, and the exact `JSON_VALUE ... ERROR ON ERROR` expression the
index serves. That is the same read-the-plan-not-the-clock discipline the
modeling skill's optimizer enforces, available without leaving mongosh: a
filtered find whose explain shows a full table scan is a missing or
mismatched index, exactly as it would be in SQL. To go the other way —
from generated SQL back to the command that produced it — see
[reverse translation](reverse-translation.md).

A sibling Oracle-only stage, **`$external`** (fields: location /
directory / credential / path), queries external data through the same
pipeline surface — see the [compatibility matrix](compat-matrix.md) for
its version gate.

## Oracle Version Notes

- Mid-pipeline `$sql` (the `input` table over prior-stage documents)
  requires the 23ai code line; it reached Autonomous Database Serverless in
  May 2024. On earlier targets, `$sql` opens the pipeline or stands alone.
- `$external` is a 26ai-era addition.
- Sole-stage DDL/DML (including `create index`) works on 19c-era and
  Autonomous targets — the bridge predates native index support in the
  Mongo lane.

## Sources

- Oracle Database Insider: "Proper SQL comes to MongoDB applications ..
  with the Oracle Database!" (the $sql walkthrough).
- Oracle Database API for MongoDB Guide — aggregation pipeline support.
