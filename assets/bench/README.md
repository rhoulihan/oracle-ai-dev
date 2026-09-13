# Benchmark harness

The same logical query (fetch order 1000 with its items and restaurant) expressed
against three physical shapes of the seeded restaurant domain:

| File | Shape | Object |
|---|---|---|
| `get_order.relational.sql` | normalized relational | joins over `orders`/`order_item`/`restaurant` |
| `get_order.duality.sql` | JSON Relational Duality | `order_dv` |
| `get_order.document.sql` | embedded document | `order_docs` |

## Measurement methodology
The harnesses follow the disciplines distilled in
`docs/research/benchmark-methodology-notes.md` (surveyed from Rick's existing
benchmark repos). Both emit:

```
BENCH:<label>:<median_cost>:cg=<median_gets>:us=<median_us>:cv=<cv>
```

parsed by `tooling/optimize/benchparse.py`.

- **Primary cost is a deterministic server-side metric, not wall-clock.**
  `time-query.sql` reports per-execution **logical reads** (`consistent gets`
  from `V$MYSTAT`); `time-dml.sql` reports per-iteration **redo size** — the
  sharpest signal for write amplification (whole-document rewrite vs single-row
  update). At the tiny seed a 10 ms clock reads 0 for every shape; logical reads
  separate them. Needs `SELECT_CATALOG_ROLE` (granted in the live-test bootstrap);
  without it the harness degrades to microseconds (`cg=0`).
- **Warmup discarded** (`&warmup`, default 5) so hard-parse and cold cache are
  excluded. The DML warmup rolls back.
- **Median of K trials** (`&trials`, default 7) with the **coefficient of
  variation** — `parse_bench` flags `noisy` when `cv > 0.10` so a coin-flip
  difference is not trusted as a real winner (see `optimal_shape_with_confidence`).
- **`RESULT_CACHE_MODE = MANUAL`** so a cached result can't mask execution; warm
  steady-state is the deliberate comparison lane.
- **Execution-plan capture (the 'why').** `explain-query.sql` runs a shape once
  off the timing path with `STATISTICS_LEVEL=ALL` and prints the ACTUAL plan via
  `DBMS_XPLAN.DISPLAY_CURSOR('ALLSTATS LAST')` — real A-Rows vs E-Rows and
  per-operation Buffers, so a cost difference is explained by its plan (index
  range scan vs full scan, nested-loop vs hash join, single LOB fetch). This is
  the free, always-available per-statement stand-in for SQL Monitor / AWR, which
  need the Tuning / Diagnostics Pack license and are unavailable on Free.
- **Gather stats first** (`DBMS_STATS.GATHER_SCHEMA_STATS`, DOP ≤ 2 on Free) so
  the CBO plans on real cardinality — done in the live-test setup.

The measured medians feed the pure analysis in `tooling/optimize/` to pick the
per-query optimal shape, weigh read+write tradeoffs, and converge on the single
model for the union of all patterns. See `tests/test_live_optimize.py` and
`tests/test_live_write.py` for the end-to-end loops.

This benchmarks the canonical domain's shapes; adding a new shape is a matter of
dropping in another `get_order.<shape>.sql`, and general query generation for
arbitrary user models is handled by `tooling/generate/`.
