from pathlib import Path

S = "skills/mongodb-api-dev"


def test_skill_exists(repo_root: Path):
    assert (repo_root / S / "SKILL.md").is_file()


def test_compat_matrix_reports_server_version_and_free_limits(repo_root: Path):
    c = (repo_root / S / "references/compat-matrix.md").read_text().lower()
    assert "7.0.22" in c
    assert "native sql" in c  # vector/text search routed to native SQL on Free


def test_change_streams_marked_deferred(repo_root: Path):
    c = (repo_root / S / "references/compat-matrix.md").read_text().lower()
    assert "change stream" in c
    assert "placeholder" in c or "deferred" in c or "preview" in c
    assert "not shipped" in c or "not released" in c or "ga" in c


def test_three_migration_lanes(repo_root: Path):
    m = (repo_root / S / "references/migration-lanes.md").read_text().lower()
    assert "drop-in" in m and "translate" in m and "remodel" in m


def test_connect_string_params(repo_root: Path):
    c = (repo_root / S / "references/connect.md").read_text().lower()
    assert "authmechanism=plain" in c and "retrywrites=false" in c


def test_java_driver_tls_semantics_are_called_out(repo_root: Path):
    # Field-verified 2026-08-13 against ORDS 26.2.2 and adb-free:latest-26ai,
    # drivers 4.11.1/5.3.1/5.5.1: tlsInsecure relaxes HOSTNAME checking only and
    # tlsAllowInvalidCertificates is not a Java option at all (silent WARN), so
    # the shipped "add --tlsAllowInvalidCertificates" advice is mongosh-only.
    c = (repo_root / S / "references/connect.md").read_text().lower()
    assert "java" in c
    assert "tlsinsecure" in c
    assert "sslcontext" in c or "trust store" in c or "truststore" in c
    assert "pkix" in c                      # the signature of the failure
    assert "host name" in c or "hostname" in c


def test_adb_free_tls_can_be_disabled_locally(repo_root: Path):
    # Measured 2026-08-13: the ords CLI IS present in adb-free:latest-26ai
    # (/usr/local/bin/ords, ORDS 25.3.2, config dir /u01/ords) and
    # `config set mongo.tls false` + an ORDS restart really does serve 27017
    # in plaintext, surviving `docker restart`. Undocumented != unavailable.
    c = (repo_root / S / "references/connect.md").read_text().lower()
    # the retracted claim must be gone
    assert "the switch does not exist on the adb-free" not in c
    # and the measured mechanism present
    assert "/usr/local/bin/ords" in c
    assert "config set mongo.tls false" in c
    assert "docker restart" in c                    # persistence, as measured
    assert "hangs" in c                             # tls=true vs plaintext listener


def test_adb_free_two_certificate_trap(repo_root: Path):
    # The Mongo API port is ORDS-fronted: /u01/ords/self-signed.crt is the cert
    # it presents, NOT the documented adb_container.cert. Both share a subject
    # DN, so importing the documented one fails "signature check failed".
    c = (repo_root / S / "references/connect.md").read_text().lower()
    assert "adb-free" in c
    assert "self-signed.crt" in c
    assert "adb_container.cert" in c
    assert "signature check failed" in c


def test_migration_lanes_carry_the_field_calibrations(repo_root: Path):
    m = (repo_root / S / "references/migration-lanes.md").read_text().lower()
    # the API tax is pipeline-shaped: finds at parity, pipelines slower
    assert "pipeline-shaped" in m
    assert "parity" in m
    # wire-compatible is not identical: retry shim + command monitoring
    assert "wire-compatible" in m
    assert "retry shim" in m and "command monitoring" in m
    # read-only views force denormalization; unwind into relational + duality
    assert "read-only" in m and "denormaliz" in m
    assert "oracle-data-modeling" in m
    # hierarchy translation prefers native forms; CTE is the portability spelling
    assert "connect by" in m and "portability" in m


def test_enable_configure_reference(repo_root: Path):
    # the six-source review (2026-08): the ORDS config surface, the TLS
    # ladder with its default-pool caveat, and schema enablement must ship
    c = (repo_root / S / "references/enable-configure.md").read_text().lower()
    assert "mongo.enabled" in c and "ords config set" in c
    assert "default" in c and "pool" in c and "mongo.tls" in c
    assert "enable_schema" in c
    assert "27017" in c
    # deployment/pooling best practices — first coverage in the repo
    assert "standalone" in c and "pool size" in c or "pool sizing" in c
    # verified report (2026-08-04): the concrete "Achieving High
    # Performance" pool values and the ORDS version floor
    assert "maxconnectionreusecount" in c and "5000" in c
    assert "22.3" in c
    # health checks are a VERIFIED documentation absence — flag, not infer
    assert "health" in c and "undocumented" in c


def test_adb_serverless_reference(repo_root: Path):
    # Josh topic 2 — ADB-S enablement, privileges, private endpoint
    c = (repo_root / S / "references/adb-serverless.md").read_text().lower()
    # enablement path + the mandatory network prerequisite
    assert "tool configuration" in c
    assert "allowed ips" in c or "acl" in c
    # the ADB-S privilege set
    assert "dwrole" in c and "soda_app" in c
    # private-endpoint connectivity (moved here from enable-configure)
    assert "private endpoint" in c and "bastion" in c
    assert "oraclecloudapps.com" in c
    # AJD/ATP/ADW comparison is undocumented — flagged, not invented
    assert "undocumented" in c


def test_adb_dedicated_reference(repo_root: Path):
    # Josh topic 3 — thin by design: documented support + explicit gaps
    c = (repo_root / S / "references/adb-dedicated.md").read_text().lower()
    assert "dedicated" in c and "cloud@customer" in c
    assert "undocumented" in c and "pending" in c


def test_sql_stage_reference(repo_root: Path):
    c = (repo_root / S / "references/sql-stage.md").read_text().lower()
    # both syntax forms and the mid-pipeline table
    assert "$sql" in c and "binds" in c and "from input" in c
    # sole-stage DDL/DML — the index-creation bridge
    assert "sole stage" in c or "only stage" in c
    assert "create index" in c
    # plan visibility through the Mongo lane
    assert "explain" in c and "getindexes" in c
    # verified report (2026-08-04): full object form + bind restriction
    assert "resetsession" in c
    assert "named binds" in c
    assert "$external" in c


def test_string_length_operators_marked_unsupported(repo_root: Path):
    # Live-verified 2026-08-13: $strLenCP/$strLenBytes answer "Operator ... is
    # not supported" while $toUpper/$substrCP/$concat/$split/$regexMatch/$trim
    # all work — so the gap is the length family, not string operators at large.
    c = (repo_root / S / "references/compat-matrix.md").read_text().lower()
    assert "$strlencp" in c and "$strlenbytes" in c
    assert "$substrcp" in c or "$toupper" in c     # the ones that DO work
    assert "length(" in c                          # the $sql workaround


def test_compat_matrix_carries_version_gating_and_driver_floors(repo_root: Path):
    # verified report (2026-08-04): 26ai-vs-19c gating and driver minimums
    c = (repo_root / S / "references/compat-matrix.md").read_text().lower()
    assert "createindexes" in c and "no-op" in c
    assert "100.5.2" in c          # the stricter of the two primary docs
    assert "mongosh" in c and "0.15.6" in c
    assert "$lookup" in c and "let" in c


def test_users_auth_reference(repo_root: Path):
    # Josh topic 4 (user model) — carved out of enable-configure
    c = (repo_root / S / "references/users-auth.md").read_text().lower()
    assert "$external" in c and "plain" in c
    assert "db_developer_role" in c
    assert "implicitly create" in c   # the mongorestore admin mechanism
    assert "scram" in c               # explicitly unsupported


def test_users_auth_records_the_implicit_creation_privilege_gate(repo_root: Path):
    # Live-verified 2026-08-13 on adb-free:latest-26ai: writing to a nonexistent
    # database as ADMIN created the schema; an ordinary app user cannot, which is
    # the behaviour difference migrating apps notice first.
    c = (repo_root / S / "references/users-auth.md").read_text().lower()
    assert "implicitly create" in c
    assert "pre-create" in c or "pre-created" in c


def test_supplemental_logging_ora600_trap_is_recorded(repo_root: Path):
    # Live-hit 2026-08-13: implicit schema creation through the API on a database
    # carrying schema-level supplemental logging raised ORA-00600
    # [kklmSchLevelSuplog:usr] from DBMS_SODA_ADMIN. GoldenGate setups enable
    # exactly that logging, so migration work can walk into it.
    c = (repo_root / S / "references/migration-lanes.md").read_text().lower()
    assert "ora-00600" in c
    assert "supplemental logging" in c


def test_performance_reference(repo_root: Path):
    # Josh topic 5 — $native/MONITOR is THE documented mechanism
    c = (repo_root / S / "references/performance.md").read_text().lower()
    assert "$native" in c and "monitor" in c
    assert "v$all_sql_monitor" in c
    assert "report_sql_monitor" in c
    assert "sqlid" in c               # ties in the access-log join key
    assert "no $monitor" in c         # states the operator does not exist


def test_assessment_reference(repo_root: Path):
    # Josh topic 7 — criteria assembled from verified facts only
    c = (repo_root / S / "references/assessment.md").read_text().lower()
    assert "no-op" in c               # the 19c createIndexes trap
    assert "sharding" in c
    assert "no assessment tool" in c or "no published assessment" in c
    assert "undocumented" in c or "pending" in c


def test_migration_lanes_carry_the_verified_offline_and_live_facts(repo_root: Path):
    m = (repo_root / S / "references/migration-lanes.md").read_text().lower()
    assert "numparallelcollections" in m
    assert "administrative user" in m or "admin user" in m
    assert "goldengate" in m


def test_new_references_are_linked_from_the_skill(repo_root: Path):
    s = (repo_root / S / "SKILL.md").read_text().lower()
    assert "enable-configure.md" in s and "sql-stage.md" in s
    # the seven-topic reorganization: every topic reference linked
    for ref in ("adb-serverless.md", "adb-dedicated.md", "users-auth.md",
                "performance.md", "assessment.md", "migration-lanes.md",
                "access-logging.md", "reverse-translation.md"):
        assert ref in s, f"SKILL.md does not link {ref}"


def test_reverse_translation_reference(repo_root: Path):
    # SME-provided guide: generated SQL back to the Mongo command
    c = (repo_root / S / "references/reverse-translation.md").read_text().lower()
    assert "generatedsql" in c and "json_exists" in c
    assert "find(" in c and "aggregate(" in c and "$lookup" in c
    # the default-choice rule between the two command families
    assert "json_patch" in c and "insert into" in c


def test_access_logging_reference_ships_only_documented_fields(repo_root: Path):
    c = (repo_root / S / "references/access-logging.md").read_text().lower()
    assert "sqlid" in c and "elapsed" in c
    assert "con=open" in c.replace(" ", "") or "con is open" in c or "open" in c
    assert "read_timeout" in c and "idle" in c        # the close-reason enum
    # negative pins — the pulled internals must STAY out (undocumented +
    # ingestion metadata, per the SME edit instruction)
    for banned in ("@version", "@timestamp", "adwc_logstash_host", "jsonaccesslog_id"):
        assert banned not in c, f"internal/undocumented field shipped: {banned}"
