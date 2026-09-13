---
name: adb-dynamodb-api
description: Use when running a DynamoDB workload, AWS SDK, or DynamoDB-compatible client against Oracle Autonomous Database, or migrating a DynamoDB table design. Covers enabling the DynamoDB-compatible API with the adb$feature tag, minting access keys, the undocumented SigV4 signing region, the ConsumedCapacity null-field trap, and the provisioned-capacity ceiling.
---
# adb-dynamodb-api

## Procedure

### 1. Provision a database that can actually host tables

- Workload must be **Transaction Processing**, and the database must **not** be in an elastic pool.
- It must **not** be Autonomous Database for Developers. On Developer tier `CreateTable` returns success and never creates the table — see the failure pattern.

### 2. Enable the DynamoDB API

Apply a free-form tag as an **UPDATE** to the existing database, not in the create call:

- Key `adb$feature`, value `{"name":"DynamoDB_API","enable":true}`

Lifecycle goes to UPDATING and a work request appears; allow up to 10 minutes. Passing the tag at create time persists it but enables nothing.

### 3. Mint an access key

There is no console UI. POST with database Basic auth from a user holding `PDB_DBA` (typically ADMIN):

```
POST https://dataaccess.adb.{region}.oraclecloudapps.com/adb/auth/v1/databases/{db-ocid}/accesskeys
{"name":"...","permissions":[{"actions":["ADMIN_ANY"]}],"expiration_minutes":1440}
```

The response carries `access_key_id` and `secret_access_key` in AWS's own shape. Redirect it straight to a `0600` file — the request carries the database password and the response carries the secret, so neither belongs in a shell transcript.

### 5. Verify

`CreateTable` returns CREATING; the table should appear in `ListTables` within seconds and reach ACTIVE in about a minute. If it never appears, the database is on the wrong tier — nothing else produces that symptom.

## The three settings that decide whether it works

None of them are documented, and each fails as something other than itself:
the SigV4 **signing region must be `us-west-2`** whatever region the database
is in; **`ConsumedCapacity` comes back as a non-null object with a null field**,
so null-checking the object alone throws and can make every request look failed;
and **provisioned capacity is capped near 9,000 units**, cumulatively across
tables. Full detail, with the client snippet and the four failure modes, is in
[client configuration](references/client-configuration.md).
