# MongoDB → SQL translation cookbook

Patterns distilled from a field-validated translation harness (~20 pipeline
stages, ~100 operators, validated against MongoDB 8.0 vs Oracle). Translate against the seeded `order_docs`.

| Pipeline stage | SQL translation |
|---|---|
| `$match` | `WHERE` with `JSON_EXISTS` / `JSON_VALUE` predicates |
| `$project` | `SELECT` with `JSON_VALUE` / `JSON_OBJECT` |
| `$unwind` | `JSON_TABLE(data, '$.arr[*]' COLUMNS (...))` |
| `$group` | `GROUP BY` with `JSON_ARRAYAGG` / aggregate functions |
| `$lookup` | `LATERAL` join + `JSON_ARRAYAGG` to nest the matched array |
| `$graphLookup` | `CONNECT BY` / `GRAPH_TABLE` (recursive `WITH` is the portability spelling — plan-check it; see [graph-table](graph-table.md)) |
| `$facet` | `JSON_OBJECT` over correlated subqueries |
| `$set` / update | `JSON_TRANSFORM` (partial, server-side) |

## Predicate form: dot notation first

Translate scalar `find()` filters to simple dot notation
(`t.data.f = '…'`), not `JSON_VALUE` — dot notation carries the Mongo API's own
comparison semantics (`TYPE(STRICT)`) and shares the multivalue index the Mongo
lane uses, so the translated query performs like the original instead of
full-scanning beside an index it cannot match. Array containment stays
`JSON_EXISTS`; `_id` lookups use `."_id".idOnly()` /
`JSON_SCALAR(HEXTORAW(…) AS ID)`.

## Divergences to surface unprompted
- `$first`/`$last` depend on document order; SQL needs an explicit `ORDER BY`.
- JSON `null` vs a missing field are distinct; `JSON_VALUE` returns NULL for both.
- `[]` vs `NULL` differ in aggregation results.
- `JSON_VALUE` returns VARCHAR2 by default — add `RETURNING NUMBER` for math.
- Sessions can crash with ≥15 chained CTEs — switch to a temp-table procedural
  form for very deep pipelines.

## Sources
- Oracle Database API for MongoDB documentation — https://docs.oracle.com/en/database/oracle/mongodb-api/
- Translation patterns — field-verified against a cross-validated corpus, 2025–2026.
