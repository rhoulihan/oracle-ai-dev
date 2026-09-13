# Access matrix — how to reach the database through each API

After the stack is up and a `plugin_dev`/app user exists, the database is reachable
through these APIs. Generate ready-to-run connection code with
`scripts/gen-connection-kit.sh <dir>` (the "connection kit").

| API | Port (default) | Service / base | Clients | Kit file(s) |
|---|---|---|---|---|
| **SQL** | 1521 | service `FREEPDB1` | python-oracledb, node-oracledb, JDBC, ODP.NET, godror, SQLcl | `python-oracledb.py`, `node-oracledb.js`, `jdbc-java.java`, `odp-dotnet.cs`, `godror-go.go`, `sqlcl.sh` |
| **MongoDB API** | 27017 | database `<user>` | mongosh, PyMongo, Node mongodb driver | `mongosh.sh`, `pymongo.py`, `mongodb-node.js` |
| **REST / SODA / GraphQL** | 8080 | `http://<host>:8080/ords` | any HTTP client (curl) | `ords-rest.sh` |

## Notes per API
- **SQL** — `<host>:1521/FREEPDB1`. Thin drivers need no Oracle client libraries —
  python-oracledb, node-oracledb, JDBC, ODP.NET (managed), and SQLcl all are. **`godror`
  is not**: it is ODPI-C, so `godror-go.go` needs Oracle Instant Client (`basiclite` has
  no `sqlplus`; on Ubuntu 24.04+/Debian trixie+ symlink `libaio.so.1` → `libaio.so.1t64`;
  register via `/etc/ld.so.conf.d/` + `ldconfig`, not `LD_LIBRARY_PATH`).
- **JDBC pooling** — Oracle UCP (Universal Connection Pool) must be paired with an ojdbc
  driver from the exact same release train. ucp11 23.6.0.24.10 with ojdbc11 23.9.0.25.07
  fails every connection borrow with "cannot resolve or generate proxy" (unaffected by
  `--add-opens`); downgrading UCP alone to 23.4 instead fails with `NoSuchFieldError:
  TransactionState.TRANSACTION_STARTED`. Fix: pin both ucp and ojdbc to the same matched
  version in the build (e.g. one parent POM property pair), not independently.
- **MongoDB API** — served by ORDS; TLS on by default (self-signed locally →
  `--tlsAllowInvalidCertificates` / `tlsAllowInvalidCertificates=true`). The URI
  needs `authMechanism=PLAIN&authSource=$external&tls=true&retryWrites=false&loadBalanced=true`.
  The schema must be ORDS-enabled by its owner (`ORDS.ENABLE_SCHEMA`), not SYSTEM.
- **REST/SODA** — Basic auth with the DB schema credentials; collections live at
  `/ords/<schema>/soda/latest/`.

## Verifying access
The `oracle-ai-setup` verification confirms the stack is online and each requested
API is reachable; `assets/verify/verify-setup.sh` checks the SQL port,
`assets/verify/verify-ords.sh` blocks until the Mongo/REST arm is actually
serviceable (ORDS installs into the database for minutes after the DB reports
healthy), and the gated live install-vetting test exercises SQL + Mongo API +
REST end to end.

## Sources
- Oracle Database API for MongoDB (26ai) — https://docs.oracle.com/en/database/oracle/mongodb-api/mgapi/
- Oracle REST Data Services (26ai) — https://docs.oracle.com/en/database/oracle/oracle-rest-data-services/
