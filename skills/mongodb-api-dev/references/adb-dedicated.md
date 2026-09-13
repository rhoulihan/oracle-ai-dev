# MongoDB API on Autonomous Database Dedicated / Cloud@Customer

Deliberately short: this page records what the primary documentation
actually establishes, and flags the rest as gaps rather than guessing.

## What is documented

The ORDS Installation and Configuration Guide states the API supports
**Autonomous Database 19c or later — serverless, dedicated, and
cloud@customer**. So Dedicated and Cloud@Customer deployments are
in-support targets.

## What is not

How enablement and connectivity **differ from Serverless** on Dedicated /
Cloud@Customer — console surface, network path, whether the
Tool-configuration flow applies — is **undocumented** in the pages
verified (2026-08). Treat the [Serverless procedure](adb-serverless.md)
as the closest documented analogue, verify against the target
environment, and do not present Serverless steps as Dedicated facts.
Detailed guidance is **pending** input from the Oracle ADB-D team.

## Sources

- ORDS Installation and Configuration Guide — Oracle API for MongoDB
  Support (platform statement).
