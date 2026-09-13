---
name: sql-json-dev
description: Use when storing or querying JSON in Oracle with SQL — JSON collection tables, JSON_TABLE, JSON_VALUE, JSON_TRANSFORM, JSON path expressions, or JSON indexing. The SQL-native document path.
---

# JSON with SQL

Store and query documents with Oracle's SQL/JSON, backed by OSON (binary JSON
with constant-time field access — a design property of the format — and partial
`JSON_TRANSFORM` updates).

## Collections and queries
Create a JSON collection table for documents, or add a `JSON`-typed column to a
relational table. Query with dot notation, `JSON_VALUE` (scalars), `JSON_QUERY`
(fragments), `JSON_TABLE` (project to rows), and `JSON_EXISTS` (predicates). See
[SQL/JSON functions](references/sql-json-functions.md).

## Indexing — read this before you index
Index choice is a performance decision, not a formality. The
[indexing guide](references/json-indexing.md) covers the multivalue-index vs
JSON-search-index tradeoff (a large throughput gap), the `JSON_VALUE` VARCHAR2
default, and the deferred-sync gotcha (`SYNC (ON COMMIT)`).

## Verify
Run your statements against the seeded `db` profile and confirm results before
delivering. Every snippet in this skill is CI-validated against a live container.

## Sources
- Oracle JSON Developer's Guide (26ai) — https://docs.oracle.com/en/database/oracle/oracle-database/26/adjsn/
