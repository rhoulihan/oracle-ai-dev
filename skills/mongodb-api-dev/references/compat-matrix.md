# MongoDB API compatibility matrix (26ai Free)

Runtime-verified on `database/ords:latest` against `database/free:latest`
(gap-3). The endpoint reports **MongoDB 7.0.22 / wire v21**.

## Works
- Full CRUD, ACID transactions (sessions honor the mandatory
  `retryWrites=false`), most aggregation pipeline stages.
- Index management through the Mongo lane: `createIndex` builds the shared
  multivalue index (one per field — a composite over scalars is ORA-44981;
  see the [troubleshooting notes](../../oracle-ai-dev/references/troubleshooting.md));
  `getIndexes()` lists SQL-created indexes too, and `explain()` returns the
  real Oracle plan.
- The Oracle-only `$sql` stage (a SQL escape hatch inside the pipeline) —
  full treatment, including mid-pipeline SQL over prior stages and the
  sole-stage DDL bridge, in [sql-stage.md](sql-stage.md).

## Does NOT work on Free — route elsewhere
- **Vector search** (`$vectorSearch`) and **text search** (`$search`) — the stages
  are recognized but their Atlas parameters are unimplemented, and
  `createSearchIndexes` is unknown. **Route vector/text search to native SQL**
  (the `vector-rag-dev` and `sql-json-dev` skills).
- **Change streams — deferred placeholder (not shipped in this release).** Per
  Oracle they are in **preview**, expected to work on Free and **GA-bound soon**;
  our 2026-07-10 smoke test on 23.26.2 saw them fail, so the two signals disagree.
  We ship **no** change-streams guidance until GA and keep a probe
  (`assets/verify/verify-change-streams.sh`) to flip this section on once it passes.

## Unsupported operators
**String length: `$strLenCP` and `$strLenBytes`** answer `Operator $strLenCP is
not supported` (field-verified 2026-08-13, ORDS 26.2.2 on 26ai). The gap is the
length family specifically — `$toUpper`, `$substrCP`, `$concat`, `$split`,
`$regexMatch`, and `$trim` all worked in the same run. It bites migration
tooling that computes lengths in a pipeline; the escape hatch is
[`$sql`](sql-stage.md) with `LENGTH()` (or `LENGTHB()` for bytes) over the
prior stage's documents.

`$expr`, `$jsonSchema` **as a query operator** (a `$jsonSchema` *validator* is a
different story — Oracle JSON Schema is a real target; see
[assessment.md](assessment.md#6-collection-validators)), `$graphLookup`, `$geoNear`,
`2d`/`2dsphere` indexes, server-side JS. (Oracle's matrix gates `$expr` at 26ai, but
our gap-3 runtime probe on 26ai Free saw it rejected — the two signals disagree;
re-probe before relying on it.)

Over a duality view the surface narrows again, and the first failure is silent
rather than loud. Equality filters on a CHAR(1) column through the Oracle API
for MongoDB over a JSON Relational Duality view return zero rows: the driver
rewrites the predicate to .stringOnly() == $B type(strict) and the execution
plan shows filter(NULL IS NOT NULL), so it matches nothing. $ne and $regex on
the same column work correctly and still use base-table indexes. $type is
unsupported on duality-view collections (error code 3038: 'Operator $type is
not supported for duality view collections'). Workaround: filter the CHAR flag
client-side, or invert equality to $ne when the column is CHECK-constrained to
two values.

The `$type` half of that is worth separating out, because it is the one
operator here that is not broken everywhere — it is specifically the duality
surface that refuses it. The Oracle API for MongoDB's `$type` query operator
fails against JSON Relational Duality view collections with error code 3038
('Operator $type is not supported for duality view collections'), even though
`$type` works on ordinary (non-duality) document collections.

## Version gating — which database is behind the API matters

Oracle's own matrix gates features by database release, and one gate is
silent: on 19c-era targets **`createIndexes` is accepted as a no-op** —
no error, no index; on 26ai it is a real operation. `collMod`
(validator only), `createView`, and `renameCollection` are likewise
26ai-only, and `$external` (the external-data pipeline stage) is a
26ai-era addition. `reIndex`, `setParameter`, `repairDatabase`,
`compact`, and `getLog` are accepted as no-ops everywhere. `$lookup`
carries documented restrictions on every release: the `let` field raises
an error, and a `localField` that is missing from any input document or
is array-valued raises an error (a missing `foreignField` merely yields
no matches).

## Minimum client/driver versions

The API requires clients that support load-balanced connections. Floors
from the primary docs (the list is explicitly non-exhaustive): mongosh
0.15.6 · Java 4.3.0 · PyMongo 3.12.0 · Node.js 4.1.0 · C# 2.13.0 · Go
1.6.0 · C 1.19.0 · Ruby 2.16.0 · Rust 2.1.0 · Compass 1.28.1 · Database
Tools (mongodump/mongorestore/mongoexport) **100.5.2** — the two primary
docs disagree here (API guide: 100.5.0; ORDS guide: 100.5.2), so use the
stricter floor.

## Performance note
The API/`$sql` layer costs ~2–8× vs direct drivers for hot paths — route hot paths
to python-oracledb / JDBC.

## Sources
- Oracle Database API for MongoDB (26ai) —
  https://docs.oracle.com/en/database/oracle/mongodb-api/mgapi/
