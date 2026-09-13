---
name: json-duality-dev
description: Use when one dataset must serve both relational and document consumers, or when creating, querying, or updating JSON Relational Duality views on Oracle. Documents CRUD through SQL, GraphQL, and the MongoDB-compatible API over one canonical model.
---

# JSON Relational Duality

One truth stored in normalized tables, projected as a document that both SQL and
document clients can read and write. See the seeded `order_dv`
([`assets/seed/03-duality.sql`](../../assets/seed/03-duality.sql)).

## Design a duality view
See [duality design](references/duality-design.md) for the rules — most
importantly, array children must project their **full PK** (omitting it triggers
ORA-40477 on read), and duality views are read-time joins, so a write-hot path
belongs in a single collection instead.

## When a duality view can't express it
Duality views can't do COALESCE, derived columns, or aggregation (they must stay
updatable). For those projections keep a traditional **SQL view** — see
[limitations](references/limitations.md).

## Query and change it
- **SQL:** `SELECT data FROM order_dv WHERE JSON_VALUE(data, '$._id' RETURNING NUMBER) = 1000`.
- **GraphQL:** 26ai serves native GraphQL over duality views; see [GraphQL](references/graphql.md).
- **MongoDB API:** a duality view is CRUD-able as a collection (creation is SQL-only;
  unquoted names are uppercase). Route to the `mongodb-api-dev` skill for the wiring.

Etags give optimistic concurrency; a stale update returns a mismatch to retry.

## Sources
- Oracle JSON-Relational Duality Developer's Guide (26ai) —
  https://docs.oracle.com/en/database/oracle/oracle-database/26/jsnvu/
