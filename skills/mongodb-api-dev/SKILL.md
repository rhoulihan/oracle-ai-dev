---
name: mongodb-api-dev
description: Use when running a MongoDB app, driver, or mongosh against Oracle, or migrating a workload from MongoDB. Covers the Oracle API for MongoDB across seven areas — ORDS deployment, Autonomous Database, the developer surface, performance diagnosis, migration, and assessment.
---

# MongoDB-compatible API

Oracle serves the MongoDB wire protocol through ORDS (the `db+ords`
profile) on port 27017, so Mongo drivers and `mongosh` talk to Oracle
unchanged. This skill is organized into seven areas; go straight to the
one that matches the task.

## 1. Deploy on ORDS (on-premises)
[Enable & configure](references/enable-configure.md): the `mongo.*`
config surface, version floors, the TLS ladder, pool tuning, deployment
topologies, schema enablement. [Access logging](references/access-logging.md):
the log's record families and field guide. Locally, the
`enable-mongo-api` configurator does the setup.

## 2–3. Autonomous Database
[Serverless](references/adb-serverless.md): enablement, the mandatory
ACL/private-endpoint network prerequisite, the DWROLE privilege set,
private-endpoint connectivity. [Dedicated / Cloud@Customer](references/adb-dedicated.md):
what is documented (little) and what is pending.

## 4. Develop
[Connect](references/connect.md) for the exact connection string;
[users & auth](references/users-auth.md) for the PLAIN/$external model
and admin users; the [compatibility matrix](references/compat-matrix.md)
before relying on any feature (vector/text search route to native SQL on
Free; change streams deferred; version gating incl. the 19c
createIndexes no-op). For joins, window functions, PL/SQL, and DDL
without leaving the Mongo lane: the [$sql stage](references/sql-stage.md).

## 5. Diagnose performance
[Performance](references/performance.md): the `$native` MONITOR hint,
SQL_ID correlation, SQL-monitor reports.
[Reverse translation](references/reverse-translation.md): generated SQL
back to the Mongo command that produced it.

## 6. Migrate
[Migration lanes](references/migration-lanes.md): drop-in (change the
URI), translate (aggregation → SQL), or remodel (the highest-payoff lane
— hand off to the modeling skill), plus the documented
mongodump/mongorestore and GoldenGate data paths.

## 7. Assess first
[Assessment](references/assessment.md): the pre-migration checklist —
command coverage, version-gating traps, operator restrictions, client
fleet, auth deltas.

## Sources
- Oracle Database API for MongoDB (26ai) —
  https://docs.oracle.com/en/database/oracle/mongodb-api/mgapi/
