# Enabling and configuring the MongoDB API

How the API gets turned on, secured, and deployed — the ORDS side of the
story. Connection strings and drivers live in [connect.md](connect.md); what
works once you're in lives in [compat-matrix.md](compat-matrix.md). This
plugin's local stack does all of the below for you (`db+ords` compose
profile + `assets/tooling/configure/enable-mongo-api.sh`); this reference is
for standing it up anywhere else.

## The ORDS configuration surface

The API is part of ORDS since release **22.3**, standalone mode only —
WebLogic and Tomcat deployments do not serve the MongoDB API, and only
non-CDB or PDB database installations are supported. One mandatory
switch, a handful of tunables, all set with
`ords config set <key> <value>`:

| Key | Default | What it does |
|---|---|---|
| `mongo.enabled` | `false` | the mandatory switch — `true` turns the API on |
| `mongo.port` | `27017` | the wire-protocol listen port |
| `mongo.host` | `0.0.0.0` | comma-separated bind hostnames/IPs |
| `mongo.tls` | `true` | TLS on the Mongo listener (see the ladder below) |
| `mongo.idle.timeout` | `30m` | max idle time per connection |
| `mongo.op.timeout` | `10m` | max time per database operation |
| `mongo.access.log` | unset | directory for API access logs (created on startup; relative paths resolve under the ORDS config dir) — record semantics in [access-logging.md](access-logging.md) |

On startup, `ords serve` logs `Oracle API for MongoDB listening on port:
27017` and prints the connection-string template — the fastest way to
confirm the switch took.

## Users and schema enablement

A MongoDB "database" IS an ORDS-enabled Oracle schema: connecting to
database `foo` reads and writes schema `FOO`. Two steps make a schema
reachable:

1. **Grants.** The live-verified floor is `CONNECT, RESOURCE, SODA_APP` (+
   quota). For application schemas that will also create views, sequences,
   procedures, or jobs through SQL, the documented fuller set adds `CREATE
   VIEW, CREATE SEQUENCE, CREATE PROCEDURE, CREATE JOB, UNLIMITED
   TABLESPACE`.
2. **Enablement.** `EXEC ORDS.ENABLE_SCHEMA;` **as the schema owner** (or
   `ORDS_ADMIN.ENABLE_SCHEMA(true, '<user>')` from an admin session). Run
   it as SYSTEM against another schema and it fails — and freshly enabled
   schemas can take a couple of minutes to appear in the API's mapping, so
   retry the first connection rather than re-running enablement. The error
   signatures (ORA-06598, transient ORA-01403) are in the
   [troubleshooting reference](../../oracle-ai-dev/references/troubleshooting.md).
   The ORDS PL/SQL packages do not exist until the ORDS container installs them on first
   start, so this cannot run from `/container-entrypoint-initdb.d` — it errors or fails
   silently depending on how the script is invoked. Enable schemas as a
   post-ORDS-healthy step; no ORDS restart is needed afterwards.

The user MODEL — PLAIN-only auth, ordinary vs administrative users,
implicit schema creation — is in [users-auth.md](users-auth.md).

## The TLS ladder

Authentication is Oracle credentials over `authMechanism=PLAIN` — the
password crosses the wire, so TLS is the default and the production
requirement. Four rungs, strongest first:

1. **CA-signed certificate** on the listener
   (`standalone.https.cert` / `standalone.https.cert.key`) — the only
   production configuration.
2. **Self-signed (the out-of-the-box state)** — standard MongoDB tools
   refuse it; clients must opt in per tool: `mongosh
   --tlsAllowInvalidCertificates`, `mongoimport --tlsInsecure`, driver
   equivalents.
3. **`mongo.tls false`** — plain-text listener for local dev only
   (connection strings switch to `ssl=false`). Never production.
4. **The caveat that bites:** with `mongo.tls false`, ORDS serves **only
   the `default` connection pool**. Multi-pool routing — a
   `databases/<pool>/hostnames` file per pool, with the connection-string
   hostname selecting the pool — requires TLS on.

**Certificate rotation** has no documented procedure of its own: rotate
by replacing the `standalone.https.cert` / `standalone.https.cert.key`
files and restarting standalone ORDS.

## Deployment topology and throughput

Where to run ORDS is a real decision (the API scales with ORDS, not with
the database):

- **ORDS beside each application node** — scales automatically with the
  app tier, small per-node pools, inherits the app's HA story, and only
  the SQL*Net port needs to reach the database. The default choice when
  the API serves one application.
- **Central ORDS tier** — one shared pool serving many apps/databases,
  scaled independently; needs its own load-balancer HA and sizing for the
  aggregate load.
- **Throughput is pool-shaped.** Out-of-the-box ORDS pool settings suit
  light use; high throughput requires raising the JDBC pool size. The
  guide's "Achieving High Performance" section gives concrete starting
  points — `jdbc.MaxConnectionReuseCount 5000`,
  `jdbc.MaxConnectionReuseTime 900`,
  `jdbc.SecondsToTrustIdleConnection 1`, `jdbc.InitialLimit 100`,
  `jdbc.MaxLimit 100` — with the caveat that optimal values depend on
  the application. Size the client side to match — a driver
  `maxPoolSize` far above the ORDS pool just queues inside ORDS.
- **Health checks are undocumented.** No health-check endpoint or probe
  is documented for the Mongo listener (a verified absence, not a
  research miss). Probe the ORDS HTTP endpoint for process liveness and
  treat a scripted `mongosh --eval "db.runCommand({ping: 1})"` as the
  listener check.

Autonomous Database is a different world — managed enablement, ACL
prerequisites, and private-endpoint connectivity live in
[adb-serverless.md](adb-serverless.md) (Dedicated/Cloud@Customer:
[adb-dedicated.md](adb-dedicated.md)).

## Oracle Version Notes

- The `mongo.tls false` plain-text mode arrived with ORDS 24.3 (September
  2024); earlier ORDS releases require TLS.
- The configuration surface above matches the ORDS 26.2 documentation; on
  23ai-line databases the API is available via ORDS for any supported
  database, and built-in on Autonomous Database.
- **The two primary docs disagree on the on-prem database floor.** The
  ORDS guides (24.2 and 26.2) state Oracle Database 21c or later
  on-premises and Autonomous Database 19c or later; the current API
  guide (F44905-25, July 2026) states the API "is available with Oracle
  Database 23ai and later." Read 21c as the historical floor and 23ai as
  Oracle's current positioning — verify against the target's actual
  release.

## Sources

- ORDS Installation and Configuration Guide (26.2) — Enabling and
  Configuring the Oracle Database API for MongoDB; "Achieving High
  Performance" (pool values).
- Oracle Database API for MongoDB Guide — Overview.
- Oracle Database Insider: MongoDB API best practices (field write-ups,
  2024–2025).
