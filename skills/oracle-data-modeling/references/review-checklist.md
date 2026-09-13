# Model review checklist

Gate the final `data_model.md` on every item. For a brownfield review, report
each failing item with a severity (blocker / important / minor).

- [ ] Every access pattern is enumerated with frequency, cardinality, latency
      budget, and write intensity.
- [ ] Patterns are ranked by frequency; the most common has the optimized shape.
- [ ] Each entity has exactly one chosen physical strategy, with the UMT rule cited.
- [ ] No write-hot pattern is served by a duality view (read-time join on write).
- [ ] Embedded children are bounded and owned; unbounded/shared children are referenced.
- [ ] Duality-view array children project their full PK — the failure is SILENT:
      CREATE and COUNT(*) succeed, the first document read dies ORA-40477.
- [ ] Every column used as a GROUP BY key or aggregate argument has an explicit
      declared type (`column_types`) — structural inference typing a VARCHAR2
      code as NUMBER turns the aggregation into one NULL bucket, silently.
- [ ] Indexes match the predicates (multivalue vs JSON search index chosen deliberately).
- [ ] If both a Mongo-API and a SQL/view consumer read a collection, the SQL side
      filters with dot notation (`t.data.f`, `.dateTimeOnly()` for native dates,
      `."_id".idOnly()` for ObjectIds) — not `JSON_VALUE` — so both lanes share
      one multivalue index.
- [ ] Index existence AND semantics (unique, partial/sparse filter expressions) are
      verified on the deployed target — listed from the database, not inferred from
      ORM/driver declarations. Index DDL ships as an idempotent, verifying
      ensure-indexes script run as a deploy gate.
- [ ] Every uniqueness/exclusivity invariant ("at most one open X per Y") is a
      partial unique index the target platform actually honors; duplicate-key maps
      to a domain conflict (409). A platform that downgrades the partial filter
      silently degrades race protection to an app-level check — prove it survived.
- [ ] No per-record overflow branch: an `is_outlier` flag (a second code path for
      the fat tail) is the model announcing it broke — normalized to rows, the whale
      is just more rows on the same access path.
- [ ] Each embedded aggregate has a size estimate at typical AND P99, checked
      against the OSON inline-storage threshold (~7,950 bytes since 21c — verify the
      current figure on 26ai); past it the document falls to LOB storage, a cliff,
      not a slope.
- [ ] Every collection/table has a designed growth bound (TTL with a sweep proven to
      run on the target, rolling partition drop, bucketing) or an explicit
      "unbounded by design" justification — and the purge path for a live collection
      on the Mongo API is `deleteMany`, never `drop()`.
- [ ] Fields compared in predicates use natively comparable types (minutes-since-
      midnight as NUMBER, not "15:30"; dates as DATE; money as NUMBER; embeddings as
      VECTOR); states with plausible intermediates are enums, not booleans.
- [ ] Any validator migrated from a MongoDB `$jsonSchema` is re-verified by probe insert,
      not assumed — Oracle enforcement is error-only (an advisory
      `validationAction: "warn"` becomes a hard reject on every write) and untranslatable
      keywords can survive translation enforcing nothing.
- [ ] Polymorphic collections have a load-bearing discriminator set consistently on
      every write; type-routed (CASE-gated) partial indexes keep each row out of
      other types' indexes.
- [ ] Integrity mechanisms are tiered to the cost of the violation, and exactly-once
      paths keep the idempotency check in the same transaction as the write.
- [ ] Any precomputed/summary shape passes read-freq × read-cost > write-freq × maintenance-cost.
- [ ] Features used are available on the target deployment (e.g. not vector search
      through the Mongo API on Free).
- [ ] The model fits the deployment envelope (Free: 2 CPU / 2 GB / 12 GB data).
- [ ] Runnable DDL is provided and loads into an app schema on the USERS tablespace.

## Sources
- Oracle JSON Developer's Guide (26ai) — https://docs.oracle.com/en/database/oracle/oracle-database/26/adjsn/
- Outlier smell, index-verified-on-target, growth bounds, and the inline-threshold
  rule — field-verified, 2025–2026.

## Oracle Version Notes
- The OSON inline-vs-LOB threshold rose to ~7,950 bytes in 21c (from ~3,964 before);
  re-verify the current figure against the 26ai JSON Developer's Guide before citing
  it in a review verdict.
