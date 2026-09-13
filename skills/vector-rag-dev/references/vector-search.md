# Vector search on Free

## Index types
- **IVF (inverted file, `ORGANIZATION NEIGHBOR PARTITIONS`)** — builds with zero
  config on Free and is the practical default. The seed creates
  `review_vec_ivf` this way.
- **HNSW (`ORGANIZATION INMEMORY NEIGHBOR GRAPH`)** — raises **ORA-51962** until
  `VECTOR_MEMORY_SIZE` is set (Free ships it at 0). Set it via SPFILE + restart
  (the `enable-vector-memory` configurator) within the ~2 GB Free cap, then HNSW
  builds. Verified in gap-3.

## Querying
```sql
SELECT r.review_id, r.body
FROM review r
ORDER BY VECTOR_DISTANCE(r.embedding, :query_vec, COSINE)
FETCH APPROX FIRST 5 ROWS ONLY;
```
`FETCH APPROX` uses the vector index; omit `APPROX` for an exact scan.

## Distance functions
`COSINE`, `EUCLIDEAN`, `DOT`, `MANHATTAN` — match the metric your embedding model
was trained for (all-MiniLM-L12-v2 → COSINE).

## Sources
- Oracle AI Vector Search User's Guide (26ai) —
  https://docs.oracle.com/en/database/oracle/oracle-database/26/vecse/
