# JSON indexing on Oracle

Choosing the index is a throughput decision. The two main options behave very
differently.

**The mantra: dot notation first; preserve the type with item methods;
`JSON_VALUE RETURNING` is a last resort.** A plain-dot predicate
(`t.data.f = '…'`) compiles to a `JSON_VALUE(... TYPE(STRICT))` recheck over a
multivalue index — the same semantics the Mongo API uses — so one multivalue
index serves SQL and Mongo `find()` alike (a SQL-created multivalue index and a
Mongo `createIndex` are interchangeable). A scalar `JSON_VALUE` predicate or
functional index splits the lanes; an item method ON a predicate (`.string() =`)
loses the index match. Item methods belong where a SQL type is genuinely needed:
the index definition (`t.data.f.string()` / `.numberOnly()` / `.dateTimeOnly()`),
aggregation arguments, ORDER BY. Two caveats, both field-verified: numeric
matching is type-strict, so numbers written as BSON doubles (the JS bare-number
default) do not match from SQL — write numerics as
`NumberInt`/`NumberLong`/`NumberDecimal` on shared collections; and ARRAY
fields are the exception to plain dot — dot-equality on an array silently
returns nothing, and `JSON_EXISTS('$.f?(@ == "x")')` is the containment form
that shares the index. Composite multivalue indexes over scalar paths are
invalid (ORA-44981) — one index per field. (Enforced for generated code by
`tooling/generate/ddl.py`.)

## Multivalue index vs JSON search index

- **Multivalue function-based index** — indexes a specific path across array
  elements. For point/range lookups on a known field it is dramatically faster
  than a search index (measured ~7× higher throughput in Rick's benchmarks:
  ~4,110 q/s vs ~572 q/s). Use it when you query a **known** field.
  The `JSON_EXISTS` predicate must match the indexed path expression exactly for
  the index to be used.
- **JSON search index** — a general index over the whole document, for ad-hoc
  path queries and full-text. Flexible, but slower for a hot known-field lookup.

Rule: index the specific hot paths with multivalue indexes; add a search index
only for genuinely ad-hoc querying.

## Gotchas

- **`JSON_VALUE` returns VARCHAR2 by default.** If a `JSON_VALUE` site is
  genuinely unavoidable (the last resort), add `RETURNING NUMBER` (or the right
  type) — otherwise comparisons are string comparisons. Prefer the typed item
  method (`.numberOnly()`), which preserves the JSON type without `RETURNING`.
- **Search index deferred sync.** A `SEARCH INDEX` defaults to deferred
  synchronization, so freshly inserted docs are not searchable until a sync.
  Create it with `SYNC (ON COMMIT)` for read-your-writes behavior in development.
- On the slim image, Oracle Text is stripped (ORA-29833) — search indexes need
  the full image.

## Sources
- Oracle JSON Developer's Guide (26ai), Indexes for JSON Data —
  https://docs.oracle.com/en/database/oracle/oracle-database/26/adjsn/
