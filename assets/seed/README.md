# Restaurant seed domain

The single canonical example every oracle-ai-dev skill reuses — the 7-entity
restaurant domain from Unified Model Theory (one canonical form, many projected
shapes). Load the numbered files in order against the `db` compose profile:

| File | Contents |
|---|---|
| `01-canonical.sql` | 7-entity 3NF canonical schema (relational) |
| `02-json-collection.sql` | JSON collection projection of the order document |
| `03-duality.sql` | JSON Relational Duality view over the canonical tables |
| `04-vector.sql` | vector column + IVF index (Free default) on reviews |
| `05-graph.sql` | SQL/PGQ property graph over customers, orders, restaurants |
| `06-seed-data.sql` | deterministic seed rows |

Load into an **app schema on the `USERS` tablespace**, never `SYSTEM`: the JSON
type cannot live in the non-ASSM `SYSTEM` tablespace (**ORA-43853**). The
`create-plugin-user` configurator makes a suitable least-privilege schema for
files 01–04 and 06; `05-graph.sql` additionally needs the `CREATE PROPERTY
GRAPH` system privilege (**ORA-01031** otherwise) — grant it first with
`assets/tooling/configure/enable-property-graph.sh <sysdba-conn> <user>`.

Verify with `assets/verify/verify-seed.sql` — every line must report
`ASSERT:<name>:PASS`.

Entities: `restaurant`, `menu_item`, `customer`, `address`, `orders`,
`order_item`, `review`.
