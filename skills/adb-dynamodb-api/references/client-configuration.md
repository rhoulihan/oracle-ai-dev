# Client configuration and the four failure modes

Endpoint: `https://dataaccess.adb.{region}.oraclecloudapps.com/adb/keyvaluestore/v1/{db-ocid}`

```java
DynamoDbClient.builder()
    .region(Region.US_WEST_2)                 // NOT the database's region -- see below
    .endpointOverride(URI.create(endpoint))
    .credentialsProvider(StaticCredentialsProvider.create(
        AwsBasicCredentials.create(accessKeyId, secretAccessKey)))
    .build();
```

Three settings are load-bearing and none are documented:

**Signing region.** The Autonomous Database DynamoDB-compatible endpoint validates the SigV4 credential-scope region and accepts only us-west-2, regardless of which OCI region the database is in. Signing with us-east-1, us-west-1, eu-west-1, ap-southeast-2, or the database's own region returns 401 Invalid credential. This is undocumented, so an AWS SDK client configured with the database's actual region fails authentication for a reason the error does not explain.

**Consumed capacity.** The Autonomous Database DynamoDB-compatible API never populates ConsumedCapacity, and it returns a non-null ConsumedCapacity OBJECT whose capacityUnits field is null rather than omitting the object. Client code that only null-checks the object throws NullPointerException on unboxing; if that exception is caught and classified as a request failure, every request appears to fail while the service is answering correctly, and any throughput derived from consumed capacity reads as zero. Check the field, not the object:

```java
ConsumedCapacity cc = resp.consumedCapacity();
double cu = (cc == null || cc.capacityUnits() == null)
    ? modelledCostOf(item)      // derive it; the service will not tell you
    : cc.capacityUnits();
```

**Provisioned capacity.** The Autonomous Database DynamoDB-compatible API rejects tables whose provisioned capacity exceeds roughly 9,000 units with ValidationException: Provisioned throughput exceeds maximum capacity. Measured on an empty 64-ECPU database: 9,000 accepted; 10,000, 11,000, 12,000, 16,000, 20,000 and 30,000 rejected. Scaling the database from 48 to 64 ECPUs barely moved the ceiling, so it is a service cap rather than a sizing problem. The cap is also cumulative across tables, so leftover tables from earlier work consume headroom. The cap is cumulative across tables, so delete leftovers before sizing a new one.

## Failure pattern

Four failures, each presenting as something other than its cause.

**Tier — a success response for an operation that never happens.** On Autonomous Database for Developers, the DynamoDB-compatible API's CreateTable returns HTTP 200 with TableStatus=CREATING but never creates the table: ListTables stays empty and DescribeTable returns ResourceNotFoundException indefinitely, with no error surfaced in the response, work requests, or lifecycle-details. An otherwise identical non-dev-tier database creates the same table in about five seconds. Oracle's documentation states Developer tier supports up to 2 DynamoDB tables; in practice zero can be created. Ruled out before finding the cause: capacity (5/25/100 behaved identically), permissions (`ADMIN_ANY` and an explicit `CREATE_TABLE` key both failed), and feature enablement. An otherwise identical non-dev-tier database in the same tenancy and region created the table in five seconds. Oracle's documentation states Developer tier supports up to 2 DynamoDB tables.

**Enablement — a tag that persists but does nothing.** The adb$feature tag that enables the DynamoDB-compatible API only takes effect when applied as an UPDATE to an existing Autonomous Database. Passing it in the create call persists the tag on the resource but fires no enablement work request, so the feature is never provisioned while DescribeAutonomousDatabase shows the tag present. Work-request history after a create-with-tag contains only the create.

**Signing region — an auth error that blames the key.** Any region other than `us-west-2` returns `401 Invalid credential`. Verified against six, including the database's own. The message points at the credential, not the region, so the natural fix (re-mint the key) never works.

**ConsumedCapacity — every request appearing to fail while the service works.** A client that null-checks the object but not the field throws `NullPointerException`, which generic error handling classifies as a failed request. The observable result is a run where completions climb, successes stay at zero, and any throughput derived from consumed capacity reads 0.00, with no error explaining why. Diagnosing it required adding first-occurrence error logging; until then the symptom was indistinguishable from a slow service.

## Two more places it diverges from DynamoDB

Table metadata and size limits are the first, and code ported from DynamoDB
may depend on both. Two DynamoDB behaviours differ on the Autonomous Database
DynamoDB-compatible API: DescribeTable returns null for ItemCount and
TableSizeBytes (DynamoDB populates both on a roughly six-hour refresh), and
the 400 KB item-size limit is not enforced — a 450 KB item was accepted. Code
that relies on DescribeTable for dataset size, or on the 400 KB ceiling for
validation, behaves differently here.

Read consistency is the second, and it matters most to anyone porting a cost
model. The Autonomous Database DynamoDB-compatible API has no eventually
consistent read path: ConsistentRead=false returns the same strongly
consistent result over the same code path. Benchmarks or cost models ported
from DynamoDB that treat eventual reads as a distinct operation at half the
capacity cost will double-count throughput and report strongly consistent
latency under an eventual label.
