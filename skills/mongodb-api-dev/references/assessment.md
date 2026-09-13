# Assessing a MongoDB application before migration

Oracle publishes **no assessment tool** or formal compatibility-analysis
methodology — the criteria below are assembled from the verified
compatibility surface, and richer guidance is pending Oracle input. Run
this checklist before choosing a [migration lane](migration-lanes.md).

## 1. Command coverage

Sweep the application (and its admin scripts) for commands the API will
never honor:

- **User/role management** (`createUser`, `createRole`, and family) —
  unsupported; users are SQL-managed ([users-auth.md](users-auth.md)).
- **Sharding commands** — not applicable; there are no shards.
- **Accepted no-ops** — `reIndex`, `setParameter`, `repairDatabase`,
  `compact`, `getLog` succeed but do nothing; harmless unless the app
  depends on their effect.

## 2. The version-gating traps

Feature support is gated by the Oracle Database release behind the API,
and one gate is silent: on 19c-era targets **`createIndexes` is accepted
as a no-op** — the app believes its indexes exist while every query full
scans. Index DDL on those targets must go through SQL
([sql-stage.md](sql-stage.md)). Version-gated features (which side of the
gate a target sits on, incl. `$expr`, `collMod` validators, `createView`,
`renameCollection`) are in the [compatibility matrix](compat-matrix.md);
runtime-verify against the actual target — Free-stack findings there show
docs and probes can disagree.

## 3. Operator restrictions that error at runtime

`$lookup`: the `let` field raises an error; a `localField` missing from
any input document, or array-valued, raises an error (a missing
`foreignField` merely returns no matches). Grep pipelines for these
before cutover, not after.

## 4. Client fleet

Every driver/tool must meet the load-balanced-connection minimums in the
[compatibility matrix](compat-matrix.md) — an old client fails at
connect, not at first missing feature.

## 5. Connection and auth deltas

`retryWrites=false` is mandatory; auth is PLAIN-over-TLS against Oracle
credentials — apps hardcoding SCRAM or connection-pool assumptions need
a config pass ([connect.md](connect.md), [users-auth.md](users-auth.md)).

## 6. Collection validators

`$jsonSchema` is unsupported as a *query* operator, but a `$jsonSchema` **validator** has
a real Oracle target — Oracle JSON Schema, attached at collection creation or via
`collMod` (26ai). The translation is lossy in ways that must be found before cutover:

- **`validationAction: "warn"` has no equivalent.** Oracle enforcement is error-only, so
  a warn-mode validator becomes a hard reject and writes MongoDB merely logged now fail.
- **Keywords with no Oracle equivalent can pass through untranslated and enforce
  nothing** — a validator that is present is not a validator that enforces.
  `additionalItems` and `dependencies` are the known cases: JSON Schema 2020-12, which
  Oracle implements, replaced them with `prefixItems`/`items` and
  `dependentRequired`/`dependentSchemas`, while MongoDB's `$jsonSchema` still uses the
  draft-4 spellings.
- **Oracle's `extendedType` keyword matches the stored OSON scalar tag, not the JSON
  text.** A number parsed from JSON text is a generic NUMBER: `{"v":5}` satisfies
  `type:"integer"` but **fails** `extendedType:"integer32"`, and `{"v":5.5}` fails
  `extendedType:"double"` (measured with `DBMS_JSON_SCHEMA.IS_VALID`). A `bsonType:"int"`
  translated to `extendedType:"integer32"` therefore rejects every document inserted as
  JSON text. Probe the translated validator with a real document before attaching it.

Sweep `getCollectionInfos()` across the source for `validator` and `validationAction`
before choosing a lane.

## Sizing — undocumented

No published sizing guidance exists for API workloads beyond the ORDS
pool-tuning starting points in [enable-configure.md](enable-configure.md);
measure with the [performance workflow](performance.md).

## Sources

- Oracle Database API for MongoDB Guide — Feature Support (compatibility
  matrix); absence of assessment tooling verified 2026-08.
