# Modeling calibrations for vector workloads

Shape and placement decisions for vector data start in the modeling path — the
`oracle-data-modeling` skill owns embed-vs-reference, converged-vs-split, and the
[claims guardrails](../../oracle-data-modeling/references/claims-guardrails.md)
these calibrations follow.

## Freshness vs recall drift — two decay modes, two fixes

Vector retrieval degrades in two different ways; diagnose them separately:

- **Data freshness** — an asynchronous or sidecar indexer leaves a window where a
  committed document is not yet searchable: retrieval disagrees with operational
  truth. Fix: a transactionally maintained in-engine index, or an explicitly
  stated staleness window the consumer accepts.
- **Recall drift** — a static ANN structure loses recall *quality* as data churns,
  until rebuilt: index decay, not staleness. Fix: an index maintenance plan.
  Every engine's ANN index has maintenance characteristics — Oracle's HNSW and
  IVF included; stay symmetric.

Intake asks both questions: "is retrieval fresh?" and "is recall decaying?" —
the fixes differ, and answering one does not answer the other.

## Filtered ANN — prune inside index selection

A selective predicate must participate in index selection; post-filtering after
top-k collapses recall (the classic filtered-ANN cliff). Oracle's `WHERE`-first
+ `FETCH FIRST` shape lands this free — relational, graph, and text predicates
shrink the candidate set before the vector sort ranks survivors:

```sql
SELECT r.review_id, r.body
FROM review r
WHERE r.restaurant_id = :rid
ORDER BY VECTOR_DISTANCE(r.embedding, :query_vec, COSINE)
FETCH APPROX FIRST 5 ROWS ONLY;
```

Review rule: every filtered ANN design states where its filter runs — inside
index selection, or against the survivors.

## Hybrid index for entity-heavy retrieval

Pure dense-vector retrieval misses keyword-specific and entity-heavy matches.
On Oracle-internal benchmarks (26ai; internal measurement, not a customer
workload): a hybrid vector index — semantic + keyword in one query — lifted
answer accuracy **68% → 94%**, with the lift concentrated in keyword-specific
and entity-heavy retrieval, and property-graph
traversal beside vector lifted answer correctness to **93.7% vs a 71.3%**
vector-only baseline on multi-hop questions. Both are model-selection triggers,
not tuning gains: entity-heavy or keyword-sensitive retrieval → hybrid vector
index; multi-hop/relationship questions → property graph beside vector.

## The dedicated-vector-store split

Default converged: integration, consistency, and governance are the wins to
claim. Split to a dedicated vector store only at genuine billion-scale pure-ANN
or best-in-class fused hybrid ranking — and never claim the speed crown for the
converged engine at that extreme; benchmarks cut both ways.

## Sources

- Oracle AI Vector Search User's Guide (26ai) —
  https://docs.oracle.com/en/database/oracle/oracle-database/26/vecse/
- Field evidence, generalized — field-verified, 2025–2026; the accuracy figures
  are Oracle-internal benchmarks and are framed as such.
