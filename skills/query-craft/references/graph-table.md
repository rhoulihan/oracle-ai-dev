# Graph queries with GRAPH_TABLE (SQL/PGQ)

Traverse the seeded `dining_graph` (customers place orders at restaurants; see
`assets/seed/05-graph.sql`) with `GRAPH_TABLE`.

## Pattern
```sql
SELECT *
FROM GRAPH_TABLE (dining_graph
  MATCH (c IS customer) -[e IS placed]-> (o IS orders) -[r IS at_restaurant]-> (rest IS restaurant)
  COLUMNS (c.customer_id AS customer, rest.name AS restaurant));
```

- `MATCH` describes the path with vertex/edge patterns; `IS <label>` filters by
  the vertex/edge label (label defaults to the table name).
- `COLUMNS` projects vertex/edge properties into a relational result you can join,
  filter, and aggregate like any table.

## When to use it
Real graph traversals (paths, reachability, "customers who also ordered…").
Simple parent/child hierarchies are better as a multivalue-indexed path column;
`GRAPH_TABLE` earns its keep on genuine multi-hop traversal.

## Hierarchies: CONNECT BY over WITH RECURSIVE
For hierarchy projections on Oracle, emit `CONNECT BY` (or `GRAPH_TABLE`) by
default — they are **not** performance-equivalent to a recursive CTE. A recursive
`WITH` materializes each recursion level as a true intermediate result the
optimizer can barely reorder; `CONNECT BY` streams a single traversal frontier.
The recursive CTE is the **portability spelling**: use it only when portability
or non-hierarchical recursion demands it, and plan-check it before shipping
(qualitative rule; no ratio is currently citable).

```sql
SELECT employee_id, LEVEL AS depth
FROM employees
START WITH manager_id IS NULL
CONNECT BY PRIOR employee_id = manager_id;
```

Whether hierarchy data should be adjacency rows at all is a modeling call — the
`oracle-data-modeling` skill's pattern catalog owns tree-shape selection.

## Sources
- Oracle Property Graph Developer's Guide (26ai) —
  https://docs.oracle.com/en/database/oracle/oracle-database/26/spgdg/
- Oracle Database SQL Language Reference (26ai), hierarchical queries —
  https://docs.oracle.com/en/database/oracle/oracle-database/26/sqlrf/
- Field evidence, generalized — field-verified, 2025–2026
