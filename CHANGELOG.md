# Changelog

## 0.6.0 — 2026-09-13

Two new skills, two CI failures whose causes were worth writing down, and a
knowledge round that ended with every captured fact filed into the skill whose
work it belongs to.

### New skills
- **`adb-dynamodb-api`** — running a DynamoDB workload or AWS SDK against
  Autonomous Database: enabling the API with the `adb$feature` tag (it only
  takes effect as an *update*, never in the create call), minting access keys,
  and the three undocumented client settings that decide whether it works at
  all — the SigV4 signing region is `us-west-2` whatever region the database is
  in, `ConsumedCapacity` returns a non-null object with a null field (an NPE
  that can make every request look failed), and provisioned capacity is capped
  near 9,000 units cumulatively across tables. On the Developer tier
  `CreateTable` returns 200/CREATING and never creates the table.
- **`ords-rest-sql-headless-adb`** — driving a wallet-less Autonomous Database
  from scripts or CI by POSTing SQL to ORDS REST-Enabled SQL, with the
  session-scope trap that splits `EXPLAIN PLAN` from `dbms_xplan.display()`.

### Fixed
- **The live tier's login poller was locking the account it waited for.**
  Oracle's DEFAULT profile locks after 10 failed logins and SYSTEM boots OPEN
  under it, so polling a *password* login through the first-boot ORA-01017
  window locked SYSTEM once boot took longer than ~50s — after which the
  correct password was refused too. Readiness now waits on a bequeath
  `/ as sysdba` probe, which carries no password and cannot touch the counter,
  then tries the real login at most five times and stops at once on ORA-28000.
- **ORDS 26.2.3 aborts its install without `ORACLE_USER_PWD`.** The image
  rebuilt 2026-09-08 made that variable mandatory; its entrypoint now fails
  ahead of the fallback that derived the ORDS schema password from
  `ORACLE_PWD` alone, so ORDS silently never installed and every Mongo-API live
  test timed out on readiness. The compose sets it alongside `ORACLE_PWD`.

### Knowledge
- 18 facts captured, reviewed and filed across 12 skills — including the
  MongoDB Java driver's TLS trust model, the ADB-Free two-certificate trap,
  SQL/JSON `==` being type-lax where mongosh is strict, ORDS AutoREST etag
  quoting (ORA-42626 / HTTP 555), ONNX ranking parity between Free and
  Autonomous, and two defects in this plugin's own MCP wiring.

## 0.5.0 — 2026-08-23

The plugin becomes a mneme knowledge repo, and a customer migration engagement
plus two follow-on sessions add a batch of measured findings.

### Fixed
- **SQLcl unpacked into a directory literally named `${CLAUDE_PLUGIN_DATA}`.**
  Claude Code substitutes `${...}` in `.mcp.json` only when the repo runs as an
  INSTALLED plugin; opened as a plain project the placeholder arrives verbatim,
  so `ensure-sqlcl.sh` saw a non-empty value, never fired its `:-` fallback, and
  installed into a bogus path.

### Knowledge — MongoDB API
- **The Java driver cannot relax certificate trust from the connection string.**
  `tlsInsecure=true` relaxes host-name checking only, and
  `tlsAllowInvalidCertificates` is not a Java option at all (one WARN, then the
  certificate is still validated). Trust must come from a `TrustManager` or a
  custom `SSLContext`. Verified on drivers 4.11.1 / 5.3.1 / 5.5.1 against ORDS
  26.2.2 and the ADB-Free container.
- **ADB-Free ships two certificates and the documented one is wrong for port
  27017.** The Mongo API is ORDS-fronted, so it presents
  `/u01/ords/self-signed.crt`, not the README's `adb_container.cert`. Both carry
  the same subject DN, so importing the documented one fails
  `PKIX path validation failed: signature check failed` rather than a clean
  unknown-CA error.
- **TLS can be turned off on the ADB-Free container** — undocumented but real:
  the ORDS CLI ships in the image. This corrects a claim in 0.4.x that said it
  could not. The setting **does not take effect until ORDS restarts, in both
  directions**, and a client that keeps `tls=true` against the plaintext
  listener hangs rather than failing fast.
- `$strLenCP` / `$strLenBytes` are unsupported while the rest of the string
  family works; `$sql` with `LENGTH()` is the bridge.
- Implicit database creation works, but only for a user holding CREATE / ALTER /
  DROP USER — the first behavioural difference a migrating app meets.
- Schema-level supplemental logging turns implicit schema creation into
  ORA-00600, which is exactly the configuration a GoldenGate target carries.

### Knowledge — SODA and tooling
- New `oracle-ai-dev/references/sqlplus-scripting.md`: the `&`-consumes-the-next
  -script-line trap (`SET DEFINE OFF` is the only guard), `SET MARKUP CSV`
  silently swallowing rows on a LONG column, and the sqlplus pipe deadlock being
  driven by script size rather than response size.
- SODA: collection names collide on a case-folded PUBLIC synonym (ORA-00955),
  and `USER_SODA_COLLECTIONS` has no `SCHEMA_NAME` column — it is
  `OBJECT_SCHEMA` (ORA-00904).

### Knowledge pipeline
- The repo is now a mneme knowledge plugin: `MNEME.md` scope charter, a
  `knowledge-index` skill, a `facts/` capture path, and a validate workflow
  (knowledge lint + secret scan) on every push. Facts captured during work are
  reviewed, then filed into the skill whose work they belong to.

## 0.4.1 — 2026-08-10

- **Fixed the `grep -q` pipefail race** in the shell helpers: an
  early-exiting `grep -q` consumer SIGPIPE'd the still-writing producer,
  and `set -o pipefail` reported the successful match as a failure — an
  intermittent false `ASSERT:FAIL` in `create-plugin-user.sh`,
  `enable-mongo-api.sh`, `verify-change-streams.sh`, and `sql_success`.
  All four sites now capture-then-match (the doctrine 0.4.0 documented
  for podman readiness loops), with a deterministic slow-tail regression
  test.
- Nightly live tier: job ceiling 60 → 120 minutes (a slow-infrastructure
  morning ran pass 1 alone to 59 minutes and starved pass 2), both
  passes report `--durations=10`.

## 0.4.0 — 2026-08-09

- **New operating principle §21 — capture learnings at the moment of
  confirmation.** The injected corpus (now 24 principles) tells the agent
  to append evidence-graded entries (exact versions, verbatim ORA codes,
  what did not work, UNVERIFIED/docs-status flags) to the project's
  `.oracle-ai-dev/lessons.md` the moment a finding is confirmed, with
  user-gated review and an upstream contribution path — never direct
  skill edits. The §D non-overridable principles renumber to §22–§24.
- **Eleven measured additions and corrections from the mongora parity
  work** (all live-verified on Free 23.26.2 + ORDS): the post-migration
  cutover gate is a `$type`-per-field differential against a reference
  mongod, never an eyeball (BSON types with no Oracle JSON scalar read
  back intact but answer `$type` differently); bespoke ODPI-C loaders
  lose numeric type tags — use the documented loader; `$jsonSchema`
  *validators* get a real Oracle target with three lossy-translation
  traps (warn→reject, untranslated draft-4 keywords, `extendedType` vs
  JSON-text scalars); connect failure signatures (MONGO-3032 slow-hang
  without `loadBalanced=true`; shared-port 27017 mistargeting);
  `ORDS.ENABLE_SCHEMA` cannot run from the DB container's init scripts;
  `DBMS_SODA.DROP_COLLECTION` is a function (PLS-00221 with exit 0 —
  cleanup scripts must assign and verify); slim/lite images strip Oracle
  Text (ORA-29833 is packaging, not product); DBMS_SODA `SAVE` raises
  ORA-03001 outright; collection-table anatomy (EMBEDDED_OID `RESID` PK
  — no separate `_id` index); readiness-loop capture-then-match (grep -q
  + pipefail spins forever).

## 0.3.0 — 2026-08-04

The MongoDB API skill absorbs an SME review round and a fact-checked
research pass, reorganized along seven topic areas.

- **Seven-topic reorganization** of `mongodb-api-dev` (ORDS deployment ·
  ADB Serverless · ADB Dedicated/Cloud@Customer · developer surface ·
  performance diagnosis · migration · assessment), with four new
  references: `adb-serverless.md`, `adb-dedicated.md`, `users-auth.md`,
  `performance.md`, `assessment.md` — plus SME-contributed
  `reverse-translation.md` (generated SQL → originating Mongo command)
  and `access-logging.md` (record families and field guide, documented
  fields only).
- **Verified-facts pass** (25/25 claims confirmed against primary Oracle
  docs): concrete ORDS pool-tuning values, version floors incl. a
  primary-doc conflict, minimum driver table, 26ai-vs-19c feature gating
  (the silent 19c `createIndexes` no-op), the `$native`/MONITOR
  diagnosis path, ADB-S enablement and privilege facts, documented
  migration flags. Topics the docs leave open are shipped as explicit
  gaps, not inferences.

## 0.2.0 — 2026-08-03

The measured election grows from four designs to seven, gains four storage
dimensions, and the plugin learns to carry its own operating principles.

### The measured optimizer
- **Two new designs**: `hybrid` (a relational core + one JSON flex column
  per entity on its own lane, the flex column emitted with an enforced
  `JSON (OBJECT LIMIT n)` inline guarantee) and `summary` (declared
  `REFRESH FAST ON COMMIT` aggregate materialized views over a relational
  lane, with maintenance measured and charged to the write cells). Both
  auto-nominated by heuristic; the walk is now document → single
  collection → hybrid → duality → summary → relational.
- **Four per-entity storage dimensions**, probe-grounded and live-verified:
  `partition` (interval / auto_list / hash, `--no-partition`),
  `organization: "index"` (IOT with an unconditional OVERFLOW segment,
  `--no-iot`), `compress: "advanced"` (`--no-compress`), and the hybrid
  flex limit (`--flex-limit` / `--no-flex-limit`). Engine-rejected
  combinations are refused at validation time naming the ORA they prevent.
- **Three new report disclosures**: `decided by:` (point-read-decided
  margins carry to Exadata-class deployments; scan-decided ones are
  environment-conditional), `!! PROVISIONAL` (a deciding cell answered
  fewer rows than the pattern's declared `expect_rows`), and
  `SUMMARY MAINTENANCE` (per-write-pattern deltas, bias disclosed).

### Local knowledge (agent tier)
- The `.oracle-ai-dev/` project store (`standards.md` governs,
  `lessons.md` informs), a shipped 23-principle operating corpus, a
  one-time gap-fill at the router recording adopt/decline decisions as
  `category: process` standards, precedence with three non-overridable
  carve-outs, and superpowers companion skills as soft dependencies with
  inline fallbacks. The compiled `standards.json` tier remains spec'd.

### Skills & docs
- New modeling references: `storage-mechanics.md`,
  `operating-principles.md`, `local-knowledge.md`.
- MongoDB API deep-dive: new `enable-configure.md` (ORDS config surface,
  TLS ladder and pool caveat, deployment topology and pool sizing, ADB
  private-endpoint access) and `sql-stage.md` (the `$sql` stage in full —
  binds, mid-pipeline `input`, the sole-stage DDL bridge, plan visibility
  via `explain()`).
- Documentation refreshed end to end (README, architecture, walkthrough,
  reference docs, the how-it-works figure).

### Reliability
- The nightly live tier runs as two serialized passes under a
  lint-enforced `shared_container` contract (fixes the container-name
  race); 768 offline tests, 57 live-gated.

## 0.1.0 — 2026-07

Initial release: 12 dual-platform skills (Claude Code + Codex), the
four-design measured election with equivalence and noise gates, the
generated data layer in five languages, the bundled SQLcl MCP server, and
the self-provisioning 26ai Free container stack.
