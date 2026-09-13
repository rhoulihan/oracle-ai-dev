# Connecting to the Oracle API for MongoDB

The API listens on port 27017 (the `db+ords` profile maps it). It self-reports as
**MongoDB 7.0.22 / wire v21**.

## Connection string
TLS is **on by default**, so the canonical string includes `tls=true`:
```
mongodb://USER:PASSWORD@localhost:27017/USER?authMechanism=PLAIN&authSource=$external&tls=true&retryWrites=false&loadBalanced=true
```
- `authMechanism=PLAIN` and `authSource=$external` — Oracle authenticates the DB user.
- `tls=true`, `retryWrites=false`, and `loadBalanced=true` are required. For the
  `mongodb://` scheme, drivers default `tls` to false — omit it and the handshake
  fails against the default (TLS-on) stack.
- For mongosh against the local self-signed cert, add `--tlsAllowInvalidCertificates`.
- The database user must be ORDS-enabled (`ords_admin.enable_schema`) and the
  Mongo API user maps to that schema.
- **Omitting `loadBalanced=true` has a signature:** the endpoint answers `MONGO-3032` —
  "This endpoint is configured to accept connections where `loadBalanced=true` is
  specified". Clients that cannot set it typically hang ~30 s before failing, so a *slow*
  connect failure against 27017 is this, not the network.
- **Port 27017 is shared ground.** A local `mongod` or a second ORDS stack binds it too,
  and `--host localhost --port 27017` silently reaches whichever won — a wrong-target
  connection that presents as an auth or TLS error. Set `MONGO_PORT` per stack and
  connect by explicit port.

A password that came out of an Oracle console usually cannot be pasted into
the URI as-is. mongosh rejects an Oracle MongoDB-API connection URI with
'MongoParseError: Password contains unescaped characters' when the DB password
contains URI-reserved characters such as # / : ? [ ] @ — these must be
percent-encoded in the URI (e.g. # -> %23). Oracle-generated passwords
routinely contain such characters, and the error message does not name which
character is at fault.

## TLS from Java is a different problem
`--tlsAllowInvalidCertificates` above is **mongosh-only advice**. In the MongoDB
**Java** driver the connection string cannot relax certificate trust at all
(field-verified 2026-08-13 on drivers 4.11.1 / 5.3.1 / 5.5.1 against ORDS 26.2.2
and the ADB-Free container — identical on all six combinations):

- `tlsInsecure=true` relaxes **host name** checking only. The driver's own
  javadoc says so; against a self-signed cert it still fails
  `SSLHandshakeException ... PKIX path building failed`.
- `tlsAllowInvalidCertificates=true` is **not a Java driver option**. It is not
  rejected either — one `WARN` on `org.mongodb.driver.uri` and the certificate is
  still validated, so it reads as "the flag did nothing".
- Trust must come from a `TrustManager`: import the cert into a trust store
  (`-Djavax.net.ssl.trustStore=...`, or a project-local store loaded in code), or
  pass a custom `SSLContext` via `applyToSslSettings(b -> b.context(ctx))`.
  Host-name relaxation is a **separate** call, `invalidHostNameAllowed(true)` —
  the driver applies `setEndpointIdentificationAlgorithm("HTTPS")` on the socket
  independently of the `SSLContext`. On the reactive driver with the Netty
  transport, the `SSLContext` must go on `NettyTransportSettings` instead.

Node and PyMongo behave like mongosh here; the MongoDB URI spec makes the option
optional per driver, and Java's is the one that opts out. Against cloud
Autonomous Database none of this applies — that endpoint's certificate chains to
a public CA already in the JDK's `cacerts`, so the problem is local-only.

**On the ADB-Free container, the documented certificate is the wrong one.**
Port 27017 is fronted by ORDS, which has its own self-signed cert at
`/u01/ords/self-signed.crt`; the README-documented
`/u01/app/oracle/wallets/tls_wallet/adb_container.cert` is the **database**
cert. Both carry the same subject DN, so the JVM picks the imported one as the
candidate issuer and then fails the signature check, reporting
**`PKIX path validation failed: ... signature check failed`** instead of a clean
unknown-CA error — so it looks like the right certificate was imported (measured
on `adb-free:latest-26ai`; open upstream as `oracle/adb-free` issue #10). Safest extraction is to read whatever the listener
actually presents: `openssl s_client -connect <host>:27017 | openssl x509`.

## Plain (no-TLS) dev alternative
To drop TLS for a plain local connection, set `mongo.tls false` in ORDS config
(24.3+) and use the string without `tls=true`; only the `default` pool is served
in that mode. On Autonomous Database the switch is unreachable — the API is a
managed service with no `ords config` surface.

**It also works on the ADB-Free container, which the docs do not mention**
(measured 2026-08-13 on `adb-free:latest-26ai`, which bundles ORDS 25.3.2). The
`ords` CLI is present at `/usr/local/bin/ords` and the config dir is `/u01/ords`:

```bash
docker exec <container> ords --config /u01/ords config set mongo.tls false
# then restart the ORDS process (or `docker restart <container>`)
```

That restart is load-bearing, not tidiness. On the ADB-Free container
(measured: adb-free:latest-26ai, ORDS 25.3.2), changing 'mongo.tls' with 'ords
config set' does not take effect until ORDS restarts, in both directions: after
setting it false with no restart the port-27017 listener still required TLS, and
after later setting it back to true the listener stayed plaintext until the next
restart. Tooling that toggles mongo.tls must restart ORDS or the change will
appear to be silently ignored.

ORDS then logs `Oracle API for MongoDB listening on port: 27017` with an
`ssl=false` connection-string template, and both mongosh and the Java driver
connect with **no certificate work at all**. The setting survived a
`docker restart`; it will not survive `docker rm` + recreate, since `/u01` is
ordinary container filesystem with no declared volume. ORDS HTTPS on 8443
(APEX, Database Actions) is unaffected — verified still serving after the change.

Two cautions. This path is **undocumented and therefore unsupported** — Oracle's
ADB-Free README and `adb-cli` expose no TLS control, so treat it as a local-dev
convenience, not a configuration to depend on. And it is a bigger trade here than
with stock MongoDB: `authMechanism=PLAIN` puts the Oracle password on the wire in
clear text, so TLS is what protects the credential.

Practical gotcha when flipping it: a client that keeps `tls=true` against the
now-plaintext listener **hangs** rather than failing fast (measured: no error
after 45 s). Every connection string has to drop TLS at the same time.

## Driver minimums
Oracle documents driver floors by `loadBalanced` support (e.g. PyMongo 3.12+,
Java 4.3+, mongosh 0.15.6+) rather than a server version.

## Reaching the same data from SQL

The collection is one table — SQL reads it too, and with the right forms both
lanes share one index (field-verified, 2026):

- **Scalars: plain dot; arrays: `JSON_EXISTS` containment** — the shared-index
  doctrine is owned by the
  [JSON indexing reference](../../sql-json-dev/references/json-indexing.md)
  (measured version: the
  [modeling optimization reference](../../oracle-data-modeling/references/optimization.md)).
  The Mongo-lane trap to remember: array dot-equality silently returns
  nothing (0 rows, fast, wrong — the Mongo lane returned 197 on the same
  data), and scalar `JSON_VALUE(...)` predicates miss the shared index.
- **Through a duality view** the same Mongo filter pushes down to the **base
  table's B-tree** — the relational indexes are the shared ones there.
- **`_id` (ObjectId):** express an ID comparison —
  `WHERE t.data."_id".idOnly() = HEXTORAW('<oid-hex>')` or
  `WHERE t.data."_id" = JSON_SCALAR(HEXTORAW('<oid-hex>') AS ID)` — both hit the
  primary-key index with the identical plan as a Mongo `find({_id})`.
- **`json_id()` is a generator, not a parser:** `json_id('OID')` mints a fresh
  id; feeding it a known hex raises ORA-40444. Convert with `HEXTORAW` as above.
- **Write numerics with an explicit type** (`NumberInt`/`NumberLong`/
  `NumberDecimal`): the JS bare-number default stores a BSON double, which the
  SQL lane's type-strict dot predicates cannot match against the shared
  multivalue index — answers stay correct, but that field full-scans from SQL.
- **Streaming FROM Oracle INTO the Mongo API:** python-oracledb returns JSON
  numbers as `Decimal`, which BSON rejects (`InvalidDocument`). Convert before
  inserting — and integral values to `int`, not `float`, or an id becomes
  `185.0` and stops comparing equal to the SQL lane's `185`.
- **Dates through a duality view are real `DATE`s** — read them with the
  driver's date type and write them as dates, never ISO strings
  (`ORA-40944/JZN-00672`); string-typed code that worked on a native
  collection breaks on both paths.
- Never build on internal/undocumented columns or byte layouts — if the query
  needs one to work, it is not shippable; use the documented forms above.

Naming across the two lanes is looser than it looks, and case is where it
bites. Oracle auto-creates an opposite-case SQL SYNONYM in both directions for
objects shared between the MongoDB API and SQL: a Mongo-created collection
like 'stores' also gets an uppercase STORES synonym, and a SQL-created table
like ORDERS gets a lowercase 'orders' synonym — so
stores/STORES/"stores"/"STORES" all resolve to the same object, and db.orders
in mongosh binds to a SQL-created ORDERS table. Quoted-lowercase naming for
Mongo-created collections is therefore a style convention, not a technical
requirement; the commonly repeated claim that you must quote them is false.

## Sources
- Oracle Database API for MongoDB (26ai) —
  https://docs.oracle.com/en/database/oracle/mongodb-api/mgapi/
