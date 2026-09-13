# The user and authentication model

A MongoDB "database" IS an Oracle schema, and Mongo credentials ARE
Oracle credentials. That one mapping explains everything below.

## Authentication: PLAIN only

The API supports **only `authMechanism=PLAIN`** — the SCRAM-SHA-*
mechanisms are explicitly unsupported — and PLAIN requires
`authSource=$external` in the connection string. Because the password
crosses the wire in plain text, TLS is mandatory (the ladder is in
[enable-configure.md](enable-configure.md); connection-string specifics
in [connect.md](connect.md)).

## Databases are schemas

Connecting to database `foo` reads and writes ORDS-enabled schema `FOO`.
Web-enablement is `ORDS.enable_schema` run as the schema owner (the ORDS
side, including the admin-session variant and its error signatures, is
in [enable-configure.md](enable-configure.md)). On current on-prem
releases the documented minimum role is **`DB_DEVELOPER_ROLE`** (version
context below); the ADB Serverless privilege set differs — see
[adb-serverless.md](adb-serverless.md).

## Ordinary users vs administrative users

An ordinary user is confined to their own schema — their MongoDB world
is exactly one database. A user holding **CREATE USER, ALTER USER, and
DROP USER** is different in two documented ways:

1. They can access **any** ORDS-enabled schema through the API.
2. Writing to a nonexistent database **implicitly creates** the schema.

That second behavior is the mechanism migration tooling relies on: run
`mongorestore` as an administrative user and target schemas come into
existence automatically ([migration-lanes.md](migration-lanes.md)).
Live-verified 2026-08-13 on the ADB-Free container: connecting as `ADMIN` and
inserting into a database that did not exist created it, and it appeared in
`listDatabases`.

**This is the behavior difference a migrating MongoDB app notices first.** In
MongoDB any user can bring a database into existence by writing to it; here the
privilege set above is the gate, and an ordinary application user — correctly —
does not hold it. So either pre-create the schema (and ORDS-enable it) as part
of provisioning, or run the bootstrap/migration step as a privileged user and
let the application connect as itself afterwards. A pre-created schema behaves
identically from then on.

## What has no counterpart

All MongoDB **user-management and role-management commands**
(`createUser`, `createRole`, and family) are unsupported — users and
grants are managed in SQL. All **sharding commands** are marked not
applicable: there are no shards to manage.

## Oracle Version Notes

- The `DB_DEVELOPER_ROLE` minimum is stated by the current API guide in
  a 23ai-and-later context; on earlier on-prem targets use the explicit
  grant set in [enable-configure.md](enable-configure.md).

## Sources

- Oracle Database API for MongoDB Guide — Users and Authentication.
- Autonomous Database Serverless documentation — MongoDB API privileges.
