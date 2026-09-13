---
name: soda-dev
description: Use when doing document CRUD or QBE from inside the database (PL/SQL, MLE JavaScript, SQLcl), bridging one collection across APIs, or migrating legacy OSON collections. SODA is Oracle's in-database document API.
---

# SODA — in-database document API

SODA (Simple Oracle Document Access) gives you MongoDB-style collections, CRUD, and
query-by-example without SQL. On 26ai it is **not deprecated**, but its role has
narrowed — see [SODA status](references/soda-status.md).

## Where SODA fits
- **In-database CRUD/QBE** — from PL/SQL (`DBMS_SODA`), MLE JavaScript, and SQLcl.
  See [the in-DB API](references/in-db-api.md).
- **Interop bridge** — one JSON collection is readable and writable through
  DBMS_SODA, SQL/JSON, the MongoDB API, SODA for REST, MLE JS, and SQLcl at once.
- **Legacy migration** — the OSON→JSON online-redefinition suite migrates older
  collections.

## What to route elsewhere
Modern Python/Node **application** code should use the MongoDB API over the same
collections — SODA is thick-mode-only in python-oracledb and node-oracledb.

## Duality-collection hook
26ai's `CREATE_DUALV_COLLECTION` makes a SODA collection over a duality view — a
direct bridge from the modeling skill's duality designs.

## Sources
- Oracle SODA documentation (26ai) —
  https://docs.oracle.com/en/database/oracle/oracle-database/26/adsdi/
