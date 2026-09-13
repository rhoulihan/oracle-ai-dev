---
name: oracle-ai-setup
description: Use when installing, deploying, connecting to, or troubleshooting Oracle AI Database 26ai Free in Docker or Podman, or when enabling an Oracle AI feature on it. Picks a compose profile, runs the configurators, and verifies the stack.
---

# Set up Oracle AI Database 26ai Free

Bring up a working, feature-enabled stack from one place. Install is script-driven — pick a profile, run the configurators, then verify.

## Choose a profile
- **db** — the database alone. Start here for SQL, JSON, duality, vector, and modeling work. See [db profile](../../assets/compose/db.compose.yml).
- **db+ords** — adds ORDS for the MongoDB-compatible API (port 27017), REST, and GraphQL. See [db+ords profile](../../assets/compose/db-ords.compose.yml).

More detail in [compose profiles](references/compose-profiles.md).

## Bring it up
From the plugin root (paths are relative to it):

```bash
docker compose -p oracle-ai-dev -f assets/compose/db-ords.compose.yml up -d --wait
```

(`db.compose.yml` for the db-only profile.) Ports and the admin password are
env-overridable: `DB_HOST_PORT` (1521), `ORDS_HTTP_PORT` (8080), `MONGO_PORT`
(27017), `ORACLE_PWD` (devpassword). Image pulls are anonymous, amd64+arm64.
`--wait` returns when the DATABASE is healthy — tens of seconds warm, several
minutes on a first-time (empty-volume) build.

**Podman host?** (docker banned, or by preference): same stack, three traps —
compose needs a provider, corporate TLS can poison docker.io pulls, and
Apple-silicon Dockerfile pitfalls. Commands and workarounds in
[podman](references/podman.md).

## Verify
```bash
assets/verify/verify-setup.sh localhost 1521      # SQL port reachable
assets/verify/verify-ords.sh                      # db+ords ONLY: Mongo/REST arm
```
A healthy database is NOT a ready ORDS — it installs itself into the database
for several minutes after `--wait` returns; `verify-ords.sh` blocks until the
Mongo API is actually serviceable. Every ASSERT line must report PASS before
moving on.

## Create the working user
Configurators and the app connect as a normal user, not SYSTEM:

```bash
assets/tooling/configure/create-plugin-user.sh "system/devpassword@localhost:1521/FREEPDB1"
```

Always connect through the **FREEPDB1 service** — a bare `system@host`
connection lands in `CDB$ROOT`, where nothing you configure is visible.

## Enable features
Run the matching configurator under `assets/tooling/configure/` — each is safe to re-run and prints an `ASSERT:<name>:PASS|FAIL` line (SQLcl is resolved automatically; nothing to install by hand). Run the feature report (`doctor.sh <connection>`) to see what is already on. Confirm any state-changing action with the developer before running it against a non-container database.

## Hand off to the tooling
The optimizer, plancheck, and every generated data layer read one triplet:

```bash
export DB_USER=plugin_dev DB_PASSWORD=Plugin_dev_pw1 DB_DSN=localhost:1521/FREEPDB1
```

## Hand off access
Once the stack is online, tell the developer how to connect: see the
[access matrix](references/access-matrix.md) (which API on which port) and generate
a **connection kit** — ready-to-run connection code for their language/platform —
with `scripts/gen-connection-kit.sh <dir>`. Confirm the requested APIs (SQL,
MongoDB API, REST) are reachable before declaring done.

## Free limits & gotchas
See [free limits](references/free-limits.md) and, for podman hosts,
[podman](references/podman.md). When you are driving the database from a script or an
agent rather than a terminal, read
[SQL*Plus scripting](references/sqlplus-scripting.md) first — substitution, CSV markup
and stdin buffering each fail silently there.

## Sources
- Oracle AI Database Free container — https://container-registry.oracle.com/ords/ocr/ba/database/free
