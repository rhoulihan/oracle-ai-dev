# Three-lane migration framework

Choose the lane by how much the workload should change — and be honest about
where each lane pays off (backed by Rick's MongoDB-vs-Oracle benchmarks).

## Lane 1 — drop-in
Change the connection URI to the Oracle API for MongoDB and run the app. Work
through the [compatibility matrix](compat-matrix.md) checklist first: confirm no
unsupported operators, no vector/text search via the API, no change streams.
Fastest path; best when the app uses mainstream CRUD + aggregation.

**Wire-compatible is not identical.** Parity is high, but the defects that do
exist are edge-shaped and may only reproduce under production topology
(field-verified, 2025–2026: one small production app's migration had exactly one
gap — a geo operator — closed with `$sql`). Budget the cutover accordingly: keep
an app-level retry shim so user impact is decoupled from fix timelines, turn on
driver command monitoring so a vague error becomes a reportable defect, and route
operator gaps to `$sql` or a native SQL rewrite.

**Moving the data.** The documented offline path is
`mongodump`/`mongorestore` — a fast binary BSON export/import that
preserves collections, JSON indexes, and metadata; the documented flags
are `--archive`, `--gzip`, and `--numParallelCollections=4`. Run
`mongorestore` **as an administrative user** so target schemas are
created automatically ([users-auth.md](users-auth.md) explains why; the
Database Tools floor is in the [compatibility matrix](compat-matrix.md)).
**Verify queries, not documents.** Read-back fidelity and query behaviour can diverge: a
field can print correctly and still answer `$type` differently. BSON types with no Oracle
JSON scalar — regex, BSON timestamp, min/max key, JavaScript, binary subtypes other than
`0x00` and `0x04` — can only land as ordinary nested extended JSON
(`{"$regularExpression":{…}}`, `{"$timestamp":{…}}`), so `{$type: "regex"}` matches on
MongoDB and returns **zero** on Oracle while the document still reads back intact
(measured 2026-08 on 23.26.2 + ORDS). Make the cutover gate a differential, not an
eyeball: restore the same `mongodump` into a reference `mongod` **and** into the Oracle
target, compare **`$type` per field** — raw values are not sufficient evidence — then
replay the application's own predicates against both. Equal document counts prove nothing.

**Use the documented loader.** A bespoke bulk loader built on ODPI-C's `dpiJsonNode` API
cannot tag a NUMBER with an integer width or a decimal type, so `int32`/`int64`/
`Decimal128` land untagged and `Int64` loses exactness (`9223372036854775807` →
`9223372036854776000`). That is a limit of that client API, **not** of Oracle —
`mongorestore` through the Mongo API does not use it. If a custom loader is unavoidable,
plan on writing OSON directly and gate it on the `$type` differential above.

**Supplemental logging can turn implicit schema creation into ORA-00600.**
Live-hit 2026-08-13 on 26ai Free + ORDS 26.2.2: with schema-level supplemental
logging configured on the target database, a write to a nonexistent database by
a privileged user failed with `ORA-00600 [kklmSchLevelSuplog:usr]` raised from
`XDB.DBMS_SODA_ADMIN`, instead of creating the schema. The same operation
succeeded on a database without it. GoldenGate setups enable supplemental
logging by design, so a live-migration target is exactly where this lands —
pre-create and ORDS-enable target schemas explicitly rather than relying on
implicit creation, and treat any ORA-00600 as a defect to report to Oracle
Support rather than a configuration error to work around.

When the application must stay up, **Oracle GoldenGate** is the
documented live path — it keeps source and target synchronized "for days
or even weeks, enabling delayed cutovers." GoldenGate topology,
supported MongoDB source versions, and the cutover procedure are
undocumented in the pages verified (2026-08) — plan those against the
GoldenGate docs for the target release, not from this reference.

## Lane 2 — translate
Rewrite hot aggregations as SQL for speed and coverage. Field-validated
translation patterns:
- `$unwind` → `JSON_TABLE`
- `$lookup` → `LATERAL` + `JSON_ARRAYAGG`
- `$graphLookup` → `CONNECT BY` / `GRAPH_TABLE` (a recursive CTE is the
  portability spelling — plan-check it; see the `query-craft` graph reference)
Surface the semantic-divergence caveats unprompted ($first/$last ordering,
JSON-null vs missing field, `[]` vs NULL in aggregation). The `query-craft` skill
carries the full cookbook.

**The API tax is pipeline-shaped, not wire-shaped.** Field-verified on a
financial-services PoC (nine production-derived queries, results validated equal
across targets before timing): simple indexed finds through the API ran at parity
or better than hand-written SQL/JSON over JDBC, while aggregation pipelines ran
roughly 3–15× slower with heavier tails. Route by shape: CRUD and indexed finds
stay on the API; pipeline-shaped work (unwind/group/window) is what this lane
translates to SQL.

## Lane 3 — remodel (highest payoff)
Re-model the data for the access patterns on the converged engine — hand off to
the `oracle-data-modeling` skill. This is where the big wins live: relationship-
shaped workloads ran up to 30–0 against MongoDB in the complex-join suite, and RAG
patterns 13–152× as single Oracle CTE queries. Model shape, not engine, decides
performance.

**Embeds in the source may be forced, not chosen.** MongoDB views are read-only —
a `$lookup` view cannot be written through, and its pipeline cannot include
`$out`/`$merge` — so the only writable path to a joined shape on the source was
pre-denormalizing and owning the update anomalies. When reviewing a heavily
embedded source model, ask whether each embed was a design decision or the
read-only-view constraint; forced denormalization is the prime candidate to
unwind into relational + duality (`oracle-data-modeling` owns that call).

## Sources
- Oracle Database API for MongoDB Guide — Migrating Data and
  Applications (mongodump/mongorestore, GoldenGate positioning).
- MongoDB documentation, views (read-only; no `$out`/`$merge`) —
  https://www.mongodb.com/docs/manual/core/views/
- Field evidence, generalized — field-verified, 2025–2026
