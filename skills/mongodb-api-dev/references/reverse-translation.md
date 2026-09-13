# Reverse translation — generated SQL back to the Mongo command

When `explain().queryPlanner.generatedSql`, a SQL-monitor/AWR `sql_text`
payload, or an [access-log `sqlid`](access-logging.md) hands you a SQL
statement the Oracle API for MongoDB generated, this guide reconstructs the
MongoDB command that most likely produced it. Exact bind values, temporary
field names, and some implementation details may be missing — favor a
useful MongoDB equivalent over a literal SQL walkthrough, and always report:

1. the most likely MongoDB command (valid mongosh syntax),
2. a short confidence note,
3. the uncertain parts, called out explicitly.

The generator's common building blocks: `JSON_EXISTS(...)` for filters and
`$match`; `JSON_QUERY(...)`/`JSON_VALUE(...)` for extraction and sorting;
`json_transform(...)` for projection and computed fields; `with "Q1"...`
CTE chains for aggregation pipelines; `json_transform(... assign ... =
json [ select ... ])` for `$lookup`; `insert into "<TMP_TABLE>"` for
write-style aggregation such as `$out`.

## High-level decision tree

- `select "DATA",rawtohex("RESID"),"ETAG" from "<schema>"."<collection>" ...`
  → a plain **`find(...)`** family command (possibly with `.sort()`,
  `.skip()`, `.limit()`, or a projection). Default to `find()` unless
  context says otherwise.
- `with "Q1" ...` → **`db.<collection>.aggregate([...])`** — each `Qn`
  usually corresponds to one pipeline stage or one internal helper stage.
- `insert into "<TMP_TABLE>" with ...` → a **write-style aggregation**,
  observed for `$out` (possibly `$merge` if the context says merge
  semantics).
- `json_patch("DATA", ? project)` in a top-level select → definitely
  `find(filter, projection)`, not an aggregation `$project`.

The source collection comes from `from "<schema>"."<collection>"` — in the
outer select for `find()`, or in `Q1` for an aggregation.

## Mapping rules

**Filters (`$match` / find queries).** Inside
`JSON_EXISTS("DATA",'$?(...)' passing ... type(strict))`:

- `@.f.stringOnly() == $B0` → `{ f: <string> }`
- `@.f.numberOnly() >|>=|<|<= $B0` → `{ f: { $gt|$gte|$lt|$lte: <n> } }`
- `@.f.numberOnly() in ($B0,$B1,...)` → `{ f: { $in: [...] } }`
- `&&` → `$and` · `||` → `$or` · a missing-field check → `$exists: false`
- `@."a"."b"` → the dotted field `"a.b"`
- `@.f bitsAnySet|bitsAllSet|bitsAllClear|bitsAnyClear $B0` →
  `{ f: { $bitsAnySet|... : [<bind>] } }`

**Projection.** `json_patch("DATA", ? project)` = a find projection whose
document is hidden behind a bind — say so. In CTE chains,
`json_transform(..., keep '$."f1"', ...)` maps to `$project`/`$addFields`:
`keep` = included fields, `remove '$."_id"'` = `_id: 0`,
`assign '$."new"' = PATH ...` = a computed or renamed field (after a
grouping stage, `_id`-renames map accordingly, e.g.
`{ $project: { _id: 0, group: "$_id", totalValue: "$total" } }`).

**Sort.** `order by JSON_QUERY("DATA", '$.f[*].min()') asc nulls first` →
`{ $sort: { f: 1 } }`; `...max()') desc nulls last` → `{ f: -1 }`. The
`[*].min()/max()` wrapping is an implementation detail — use the field
name. In a plain select it is `.sort()`, not a stage.

**Skip/limit.** `offset N rows` → `$skip: N`; `fetch first N rows only` →
`$limit: N` (or `.skip(N).limit(M)` on a plain find).

**Group.** The signature is a KEY/ACC extraction CTE, a type-normalization
CTE, a `group by "KEY0"` CTE with `sum(json_value("ACC0", '$.numberOnly()'
...))`, then a `json { '_id': "KEY0", ? value ... }` re-assembly →
`{ $group: { _id: "$key", <acc>: { $sum: "$arg" } } }`. Accumulator field
names are often hidden behind binds — output a `<sumField>` placeholder
rather than guessing. `select json { ? value count(*) } ... having
count(*) > 0` → `{ $count: "<fieldName>" }`.

**Lookup.** `json_transform(r."DATA", assign '$."orders"' = json [ select
f."DATA" from "Qn" f where json_exists(f."DATA", '$?(@."cid" == $x)'
passing json_query(r."DATA", '$."_id"') as "x") ])` →

```javascript
{ $lookup: { from: "orders", localField: "_id",
             foreignField: "cid", as: "orders" } }
```

(`assign` names `as`; the inner CTE's ultimate source table names `from`;
the outer `json_query` path is `localField`; the foreign predicate is
`foreignField`.) Filters/sorts on the foreign CTE before the correlated
subquery become `$lookup.pipeline` stages; a nested `assign ... = json [...]`
inside the foreign side is a nested `$lookup` in that pipeline.

**$expr.** A filter passing a `treat(json_transform("DATA", ... set '$tmp'
= PATH '$tmp1.domCompare() > $b1' ...) as json)` boolean is `$expr`:
`domCompare() ==|>|>=|<|<=` → `$eq|$gt|$gte|$lt|$lte`, with `arrayagg
("wrap")` scaffolding ignored — e.g. `{ $expr: { $gt: ["$a", <bind>] } }`.

**Regex.** `stringOnly() like_regex $bN` → `$regexMatch` (no flags);
`ci_like_regex` → `options: "i"`.

**$map / $reduce.** Marked explicitly with `/* begin $map */` …
`/* end $map */` (and `$reduce`) comments around `nested path '$tmp1[*]'`
blocks — reverse them directly to `$map`/`$reduce` inside a projection.

**$out.** `insert into "<TMP_TABLE>" with ... select "DATA" from "Qn"` →
the pipeline ends `{ $out: "<collection>" }`; if the target name is not
visible in the fragment, output `<outputCollection>`.

## Generator internals to ignore

Never carry these into the MongoDB answer except to explain uncertainty:
`Q1, Q2, …`; `KEY0, ACC0, TYPS0`; `$tmp, $tmp1, $tmpP0`; bind labels
(`B0`, `b1`, `EXT_Q1_LET1`); `arrayagg("wrap")`; `domCompare()`; numeric
type-normalization scaffolding.

## Worked examples

```sql
select "DATA",rawtohex("RESID"),"ETAG" from "SCOTT"."bitwise"
where JSON_EXISTS("DATA",'$?(@.a bitsAnySet $B0)' passing ? as "B0" type(strict))
```
→ `db.bitwise.find({ a: { $bitsAnySet: [<bind0>] } })`

```sql
select /*+ FIRST_ROWS(1) */ json_patch("DATA",? project ),rawtohex("RESID"),"ETAG"
from "SCOTT"."orders"
where JSON_EXISTS("DATA",'$?(@.a.numberOnly() > $B0)' passing ? as "B0" type(strict))
order by JSON_QUERY("DATA", '$.a[*].max()') desc nulls last
offset 1 rows fetch next 1 rows only
```
→ `db.orders.find({ a: { $gt: <bind0> } }, /* projection bind not visible */)
.sort({ a: -1 }).skip(1).limit(1)`

A `with "Q1"..."Q7"` chain that filters `field1 in (...)`, extracts
KEY0/ACC0, groups with a sum, and sorts by `_id` →

```javascript
db.foo.aggregate([
  { $match: { field1: { $in: [<bind0>, <bind1>] } } },
  { $group: { _id: "$field1", <sumField>: { $sum: "$field2" } } },
  { $sort: { _id: 1 } }
])
```

When uncertain, prefer the correct command family (`find` vs `aggregate`),
the correct collection, and the correct stage ORDER over guessing bind
values or bind-hidden field names — placeholders beat fabrications.

## Sources

- Oracle API for MongoDB engineering guidance (reverse-mapping field
  guide, 2026), generalized for this reference.
- Oracle Database API for MongoDB Guide — `explain()` and generated SQL.
