# MongoDB API access logs — record families and field guide

What the API's access log records mean and how to query them. On standalone
ORDS the log is enabled with `mongo.access.log` (see
[enable & configure](enable-configure.md)); on Autonomous Database the same
record families appear in the managed service's JSON access logs. Fields
noted as service-side appear only in the managed-service form.

## Record families

- **Command records** — signal: `cmd` present. Common fields: `client`,
  `port`, `h`, `db`, `cmd`, `coll`, `elapsed`, `received`, `sent`, `id`,
  `sqlid`, `err`.
- **Connection open** — signal: `con=OPEN`. Fields: `client`, `port`,
  `h`, `con`, `lbport`.
- **Connection close** — signal: `con=CLOSE`. Fields: `client`, `port`,
  `h`, `con`, `reason`, `msg`.

The normal lifecycle of one connection (identified by the `client` +
`port` pair) is one `con=OPEN`, zero or more `cmd` records, one
`con=CLOSE`.

## Query rules

- "Errors" means records where `err` is present — aggregate on `err`
  first, then add top `h`, `cmd`, or `src_host_name` values when they
  explain the pattern.
- Command behavior: aggregate on `cmd`, break down by `db`, `coll`, `h`,
  or `err`.
- Connection debugging: pivot on `con`, `reason`, `msg`, `client`, `port`.
- Node-local issues (service): compare `src_host_name`.

## Field dictionary

| Field | When | Meaning / use |
|---|---|---|
| `client` / `port` | conn + cmd | client IP and port; the pair identifies one connection |
| `h` | all | hostname of the target database (service form: `<tenant>-<dbname>.adb.<region>.oraclecloudapps.com` — each hostname is a distinct PDB); per-database grouping |
| `db` | cmd | the MongoDB database — maps to the Oracle schema of the same name |
| `cmd` | cmd | the MongoDB command executed |
| `coll` | collection-scoped cmds | the target collection (a JSON collection table) |
| `elapsed` | cmd | command elapsed time, milliseconds — latency analysis |
| `received` / `sent` | cmd | wire-protocol request/response sizes in bytes |
| `id` | cmd | MongoDB request id — request correlation |
| `sqlid` | cmd | **the SQL_ID of the statement executed for the command** — the join key from a Mongo command to Oracle SQL monitoring (an array when one command ran several statements, e.g. updates). Feed it to AWR/SQL-monitor tooling, and [reverse-translation](reverse-translation.md) maps the SQL back to the command |
| `err` | failures | the error message returned to the client |
| `fullstack` | some errors | full server-side stack trace; deliberately rate-limited because it is large — commonly seen on `saslStart` errors |
| `data` | `hello`/`isMaster` | handshake metadata: driver name/version, platform, OS — driver-inventory analysis |
| `con` | lifecycle | `OPEN` or `CLOSE` |
| `lbport` | `con=OPEN` | whether the connection used the `loadBalanced=true` port (27017) or the deprecated HASH-IP port (27016) |
| `reason` | `con=CLOSE` | the close-reason enum below |
| `msg` | some closes | additional close context |
| `lsId` / `txnNumber` | transactional cmds | session id and transaction number — always appear together; transaction correlation |
| `n` | count-like results | documents returned/affected — meaning depends on `cmd` (find/getMore/distinct: returned; insert/delete: affected; listIndexes/listDatabases: object counts) |
| `nModified` / `nUpsert` / `nError` | updates | rows updated / upsert-inserted / errored |
| `nScanned` | `distinct` | documents scanned |
| `upsert` | updates | whether the update was an upsert |
| `req` | some errors | the command as logged, with strings and integers REDACTED (`S0`, `I4` placeholders) and long commands truncated — error reproduction without data exposure |
| `release` | some errors | whether the connection pool to the database was released because of this error — severe-error investigation |
| `src_host_name` | service records | which API node served the request — the field that shows whether an error is isolated to one backend node |
| `user` | `saslStart` | the authenticating user — auth troubleshooting |
| `tags` / `type` | all | record family (`jsonaccesslog`) and format (`json`) confirmation |

## Connection close reasons

| `reason` | Meaning |
|---|---|
| `IDLE` | idle timeout (`mongo.idle.timeout`) |
| `READ_TIMEOUT` | read timeout |
| `FAILURE` | an exception was caught |
| `TOTAL_EXCEEDED` | the host's connection limit was exceeded |
| `RATE_EXCEEDED` | the host's connection-creation rate was exceeded |
| `HOST_NOT_FOUND` | host lookup for the connection failed |
| `INPUT_SHUTDOWN` | the client shut down input / EOF |
| `INVALID` | an external provider declared the connection invalid |
| `DATABASE_CHANGED` | the underlying database changed |
| `SEVERE` | severe unexpected failure |

## Sources

- ORDS Installation and Configuration Guide — MongoDB API access logging
  (`mongo.access.log`).
- Oracle API for MongoDB engineering guidance (access-log field guide,
  2026), edited to documented fields only.
