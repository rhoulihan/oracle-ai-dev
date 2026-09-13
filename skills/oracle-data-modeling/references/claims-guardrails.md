# Claims guardrails — never claim, always say

This skill quotes measured evidence to skeptical developers. Every claim below has
burned someone before; the guardrails keep the skill's output accurate, sourced, and
shippable. The mechanical ones are CI-enforced (`tests/test_set_locality_blocklist.py`,
`tests/lint/banned_strings.py`); the rest are review rules for any prose or DDL this
skill emits.

## Never emit, never reference

- **Storage-locality clauses on a duality view.** Demo material has circulated a
  non-GA ALTER syntax that declares hot/cold storage placement inside one duality
  view. It is **not GA**: never emit any storage-locality clause in duality DDL,
  never teach the syntax, and never name pre-release proposals. The hot/cold-split
  *concept* is real and shippable with GA machinery only: an embedded or
  JSON-collection shape for the hot window, a relational archive for history, and
  a view unioning the two projections of one truth. CI trip-wires the clause
  repo-wide without spelling it.

## Security placement

- **VPD and RAS are not supported on duality views.** Row/cell policy goes on the
  **base tables** and is inherited through the projection. Never write "put VPD on
  the view"; always "base-table policy enforced through the projection." Field-level
  minimization by projection still stands — it composes with base-table policy, it
  does not replace it.

## Performance-claim discipline

- **O(1) vs O(n) field access is a design property** of the storage format, not a
  measurement. Present the complexity claim as architecture; present any nanosecond
  figure as one benchmark's observation, at the layer it was measured.
- **Every benchmark claim carries its workload context** — data scale, mapping
  cardinality, cache posture, durability settings, and which features were disabled
  on the winner's side. A ratio without its workload is an adjective.
- **Two-sided honesty, always.** Length-prefixed document formats genuinely win
  array appends, sequential end-of-document writes, and append-only logs; some
  engines win point-query throughput in some runs. Concede the wins or forfeit the
  credibility of the losses.
- **No cross-vendor performance numbers without a published, reproducible source.**
  Mechanisms may be taught qualitatively — materialization dams vs streaming
  frontiers, spill behavior, documented caps and their error text — but unpublished
  timings do not ship, in either direction.
- **Hierarchy projections prefer `CONNECT BY` or `GRAPH_TABLE`.** A recursive
  `WITH` CTE materializes each recursion level as an intermediate result; the native
  forms stream. Recursive `WITH` is the portability spelling — use it only when
  portability or non-hierarchical recursion demands it, and plan-check it before
  shipping. State this qualitatively; no ratio is currently citable.
- **The validation-cost objection is answered qualitatively.** Engine-level JSON
  Schema validation compiled once at DDL time is cheap (measured internally;
  benchmark publication forthcoming) — the only slow validation is per-call
  recompilation, i.e. validating in app code or via a compile-per-row extension. No
  numbers until the benchmark is published.

## Standard figures — use these, never the variants

- **The financial-services PoC suite headline is ~0.83 s → ~0.16 s average (−81%,
  all 40 queries faster, 0 regressions)** at production cardinality — and the
  figures ship ROUNDED: exact constants fingerprint their source. The interim
  ~0.11 s average was won at a mapping cardinality over 200× smaller than
  production and its headline tables did not survive the real numbers — it
  appears only inside the wrong-scale cautionary tale, never as a headline.
- The bucket-pattern design-review case standardizes at **~60×** (not 77×).
- The DynamoDB GSI limit is **20** (not 25).
- The product is always **26ai** — the rebranded name never appears as its former
  version string outside an Oracle Version Notes section (lint-enforced).

## Oracle Version Notes

Locality-aware duality had not reached GA as of 26ai (July 2026). Re-check the
JSON-Relational Duality Developer's Guide per release before revisiting the
blocklist; the hot/cold guidance above assumes GA machinery only.

## Sources

- JSON-Relational Duality Developer's Guide (26ai) —
  https://docs.oracle.com/en/database/oracle/oracle-database/26/jsnvu/
- Oracle Database SQL Language Reference (26ai), hierarchical queries —
  https://docs.oracle.com/en/database/oracle/oracle-database/26/sqlrf/
- Field evidence, generalized — field-verified, 2025–2026.
