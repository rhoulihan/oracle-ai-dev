---
name: query-craft
description: Use when writing or translating queries for Oracle — SQL, SQL/JSON path expressions, GRAPH_TABLE over property graphs, or converting MongoDB queries and aggregation pipelines to SQL. Every generated query is plan-checked before delivery.
---

# Query craft

Author idiomatic Oracle queries and translate MongoDB ones. Verify before you
deliver — never hand over an unchecked query. The plan-check is a command, not
a habit:

```bash
export DB_USER=... DB_PASSWORD=... DB_DSN=localhost:1521/FREEPDB1
python -m tooling.plancheck "SELECT ..."      # or `-` to read stdin
```

Exit 0 = checked and clean; exit 1 = a filtered query full-scans — fix the
query or create the index it implies before delivering. It prints the plan and
the access summary (`EXPLAIN PLAN` + `DBMS_XPLAN` under the hood, enforced by
`tooling/plancheck/check.py` — the same path the measured optimizer reads
plans through). No reachable database, no plan-check: say so explicitly rather
than delivering the query as verified.

## SQL/JSON
Query JSON with dot notation, `JSON_VALUE`/`JSON_QUERY`/`JSON_TABLE`, and path
predicates. See [SQL/JSON paths](references/sql-json-paths.md).

## Translating from MongoDB
The [Mongo-to-SQL cookbook](references/mongo-to-sql.md) maps pipeline stages to
SQL (`$unwind` → `JSON_TABLE`, `$lookup` → `LATERAL` + `JSON_ARRAYAGG`,
`$graphLookup` → recursive CTE) and flags the semantic divergences.

## Graphs
Traverse the property graph with `GRAPH_TABLE` / SQL-PGQ; see
[graph queries](references/graph-table.md) over the seeded `dining_graph`.

## Sources
- Oracle SQL Language Reference (26ai) —
  https://docs.oracle.com/en/database/oracle/oracle-database/26/sqlrf/
