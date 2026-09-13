# Troubleshooting — errors, causes, fixes

The errors developers actually hit on Oracle AI Database 26ai Free, each verified.

| Error | Cause | Fix |
|---|---|---|
| **ORA-40477** | A JSON Relational Duality view whose composite-PK array child omits a PK column — CREATE and `COUNT(*)` both succeed; the doc is unreadable on read. | Project the child's **full PK** (or use a surrogate single-column PK) in the duality view. |
| **ORA-42679** | An `@unnest` sub-object given a field name/alias — unnest flattens into the parent. | Write `table @unnest { ... }` with no alias before it. |
| **ORA-42550** | An `@unnest` block that omits its linking (join) column. | Project the linking column inside the `@unnest` block. |
| **ORA-44981** | A composite `MULTIVALUE` index over scalar dot paths — composite multivalue columns must come from `JSON_TABLE`. | Create **one single-field multivalue index per field** (also the form a Mongo `createIndex` produces). |
| **ORA-02267** | An FK typed `NUMBER` pointing at a natural (VARCHAR2 code) primary key. | Declare the key's real type (`column_types`/`pk_type`); the generators now honour it. |
| **ORA-40944 / JZN-00672** | Writing a date as an ISO **string** through a duality view — the view projects the real `DATE` column. | Send the driver's date type (UTC-anchored), not a string. |
| **ORA-06598** | `ORDS.ENABLE_SCHEMA` run as `SYSTEM` — ORDS_METADATA can't inherit SYSTEM's privileges. | Enable the schema **as its owner** (connect as the schema, run `ORDS.ENABLE_SCHEMA(p_enabled=>TRUE)`). |
| **ORA-01403** | Transient during ORDS install: the ORDS package compiled but its metadata isn't populated yet. | Retry `ENABLE_SCHEMA` for a couple of minutes after the ORDS package is VALID. |
| **ORA-43853** | A JSON-type column/collection created in the non-ASSM `SYSTEM` tablespace. | Create JSON in an app schema on the **`USERS`** tablespace, never SYSTEM. |
| **ORA-51962** | HNSW vector index built while `VECTOR_MEMORY_SIZE = 0` (the Free default). | Use **IVF** (zero-config) or run `enable-vector-memory` (sets VECTOR_MEMORY_SIZE via SPFILE + restart) for HNSW. |
| **ORA-00054** | `create_index` on a SODA collection inside the same uncommitted transaction (SODA's recursive DDL). | **Commit** the inserts before creating the index. |
| **ORA-12954** | Exceeded the Free 12 GB user-data cap. | Trim data or move to ADB/EE (Free is 2 CPU / 2 GB SGA+PGA / 12 GB data). |
| **ORA-29833** | Oracle Text index on the **slim** image (Text stripped). | Use the full `database/free` image, not `-lite`/slim. |
| **QSM-00794** | SQL Access Advisor on a SYS-owned table. | Run advisors as a regular app user against your own objects. |

## ORDS surfaces on Autonomous Database

Copying an etag straight out of curl is the trap here, because the value
arrives already quoted. For ORDS AutoREST ETag-based concurrency control,
`curl -w '%header{etag}'` returns the etag value WITH its surrounding double
quotes still attached. Passing that raw value into an If-Match header
double-quotes it and the engine raises ORA-42626 (surfacing as HTTP 555).
Strip the quotes first (e.g. `tr -d '"'`) — If-Match must carry exactly one
quoted hex string.

Getting into APEX on a wallet-less ADB is a different route than on-premises,
and the workspace login you are looking for is not there. On Oracle Autonomous
AI Database, every APEX entry point (/ords/apex, /ords/f?p=4550:1,
/ords/f?p=4550:20, and the workspace-sign-in path) 302-redirects
unauthenticated requests to the ADB database sign-in gateway
(/adb/auth/v1/connect/login), which has only username+password fields. There
is no reachable APEX workspace sign-in page with a workspace-name field;
workspace users authenticate with username+password first and pick their
workspace on a following page.

## Mongo API notes
- Vector/text search and change streams don't work through the Mongo API on Free —
  route vector/text to native SQL; change streams are a deferred placeholder.
- Connection needs `tls=true` (default), `authMechanism=PLAIN`, `authSource=$external`,
  `retryWrites=false`, `loadBalanced=true`.

See the per-skill references for topic-specific detail.
