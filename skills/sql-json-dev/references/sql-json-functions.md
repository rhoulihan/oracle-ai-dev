# SQL/JSON functions — quick reference

Against the seeded `order_docs` collection (see `assets/seed/`).

| Task | Function | Example |
|---|---|---|
| Read a scalar | `JSON_VALUE` | `SELECT JSON_VALUE(data, '$.total' RETURNING NUMBER) FROM order_docs` |
| Read a fragment | `JSON_QUERY` | `SELECT JSON_QUERY(data, '$.items') FROM order_docs` |
| Project to rows | `JSON_TABLE` | `SELECT j.* FROM order_docs, JSON_TABLE(data, '$.items[*]' COLUMNS (name PATH '$.name', qty NUMBER PATH '$.qty')) j` |
| Predicate | `JSON_EXISTS` | `SELECT * FROM order_docs WHERE JSON_EXISTS(data, '$.items[*].name?(@ == "Margherita")')` |
| Modify in place | `JSON_TRANSFORM` | `UPDATE order_docs SET data = JSON_TRANSFORM(data, SET '$.total' = 40) WHERE ...` |
| Build a document | `JSON_OBJECT` / `JSON_ARRAYAGG` | `SELECT JSON_OBJECT('id' VALUE order_id, 'total' VALUE total) FROM orders` |

Notes:
- Dot notation (`d.data.total`) is shorthand for `JSON_VALUE` and returns VARCHAR2.
- `JSON_TABLE` is the workhorse for turning arrays into relational rows (the SQL
  equivalent of `$unwind`).
- `JSON_TRANSFORM` does partial, server-side updates without rewriting the whole
  document — an OSON advantage.

## Sources
- Oracle JSON Developer's Guide (26ai) — https://docs.oracle.com/en/database/oracle/oracle-database/26/adjsn/
