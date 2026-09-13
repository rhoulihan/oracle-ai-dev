# Capstone adversarial review — findings (all live on 26ai Free)

> ⚠️ **HISTORICAL.** This review records the harness as it was at the time, and several of
> its conclusions have since been **disproved** — notably that the document design is far
> worse un-indexed *and* indexed. It was measuring missing indexes: we derived them from
> `WHERE` clauses only, never from `GROUP BY`. With an aggregate index the document reads
> *fewer logical reads than the relational table*. See
> [RESULTS.md](./RESULTS.md) for the current, validated findings and the full list of
> seventeen defects. Kept as a record of how the harness was wrong.


End-to-end validation of every feature against the real airline-reservations model.
Bugs found are fixed with regression tests; features are verified live.

## Bugs caught and fixed
| # | Feature | Defect | Fix |
|---|---|---|---|
| 1 | DDL gen | FK column that is also a projected column typed VARCHAR2 (ORA-02267) | force FK columns to the referenced PK type |
| 2 | DDL gen | substring type inference (country→count, tail_number→num, fare_class→fare, ORA-01722) | whole-token matching |
| 3 | Datalayer (C#) | escaped quotes inside an interpolated string (compile error) | read env vars into locals |
| 4 | ensure_schema | FK ALTERs not idempotent → failed on partial schema | tolerate already-exists codes |
| 5 | Index naming | truncated to 30 chars (collision risk) | 128-char (26ai limit) |

## Design findings (methodology)
- **Units:** read cost (logical reads) and write cost (redo bytes) are NOT additive;
  read/write-mix comparisons must use a consistent unit (per-op µs).
- **Index-first:** interpreting performance without the access-pattern-derived indexes
  is misleading — document looked 16× worse un-indexed, only ~2× worse indexed. Analyze
  index requirements first; multi-column indexes on both tables and documents.
- **Selectivity × scale:** a low-selectivity filter (agent → many rows) correctly kept a
  full scan at 3000 rows but would use the index at production scale → size the sample.
- **Write floor:** a JSON-collection update rewrites the whole doc (~2500-byte floor);
  breaking the aggregate into containers helps read scope more than write cost. The
  write-amplification cure for write-hot data is relational/duality storage.
- **Candidates from reasoning:** the "meaningful containers" decomposition was reasoned
  (LLM), not rule-derived; the tooling measured it. Candidate models = reasoning;
  ranking = measurement.

## Features verified live (real model)
DDL (typed/composite PK, code FK) deploy · ingestion (DDL→ModelSpec) · SQL gen
(=, IN, BETWEEN, IS NULL, multi-hop joins through junctions) · write amplification ·
plan capture · optimizer (recommend_model, confidence, design_options, full-workload
union + flip sweep) · index derivation (tables + documents, composite) · sizing ·
run-sql.sh · db-lifecycle (init/load/status/new-project) · safety guard ·
ensure_schema auto-deploy · datalayer for the reservation patterns · **cross-runtime
consistency across all 5 runtimes**.

## Not verifiable in this environment
Wallet/easy connection modes (no external ADB); Oracle Instant Client for godror
(go-ora used as the pure-Go stand-in — the generated SQL + bind logic is validated).
