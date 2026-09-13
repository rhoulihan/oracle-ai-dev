# SODA status on 26ai (verified)

**Not deprecated** — zero mentions in the 26ai Upgrade Guide deprecation lists, and
the JSON Developer's Guide positions SODA and the MongoDB API as peer document APIs
over JSON collections. But it is visibly maintenance-mode: SODA for REST is still
"Release 1", and the drivers have narrowed.

## Per-driver reality
- **PL/SQL (`DBMS_SODA`)** — the recommended in-DB path. One hole: `SAVE` (upsert)
  raises **ORA-03001 "unimplemented feature"** on Free 23.26.2 — for a new key as
  well as an existing one, so the call is unimplemented, not just the upsert path.
  CRUD, QBE, and indexing are unaffected. Emulate with `INSERT_ONE` + catch **ORA-00001**.
- **SODA for Java (orajsoda 1.1.29)** — works against 26ai native collections.
- **python-oracledb / node-oracledb** — SODA is **thick-mode only**. Modern app
  code should use the **Mongo API** over the same collections instead.
- **MLE in-database JavaScript** — works with a direct grant on `XDB.DBMS_SODA_ADMIN`.
- **SODA for REST (ORDS 26.x)** — works out of the box after `ords.enable_schema`.

## Positioning rule (the router enforces)
New document *application* code → Mongo API or SQL/JSON. SODA → in-database CRUD/QBE
(PL/SQL, MLE JS, SQLcl), interop bridging, and legacy migration. Never claim SODA is
deprecated — it is verified not to be.

## Oracle Version Notes
A SODA driver older than the 23ai release cannot access JSON-type collections
created on 23ai or later — it raises **ORA-61754**. Use a 26ai-era driver against
26ai collections.

## Sources
- Oracle SODA documentation — https://docs.oracle.com/en/database/oracle/simple-oracle-document-access/
- Oracle JSON Developer's Guide (26ai) — https://docs.oracle.com/en/database/oracle/oracle-database/26/adjsn/
