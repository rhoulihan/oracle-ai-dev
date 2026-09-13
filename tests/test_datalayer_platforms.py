# Copyright (c) 2026 Oracle and/or its affiliates.
"""Render a full data-access layer (one method per access pattern) per platform."""
import json
from pathlib import Path

from tooling.datalayer.platforms import ALL_PLATFORMS, render_all

MODEL = json.loads(Path("tests/fixtures/restaurant_model.json").read_text())
SPEC = {
    "model": MODEL,
    "patterns": [
        {"name": "get_order_by_id", "shape": "document",
         "query": {"root": "Order", "returns": ["Order.order_id"],
                   "predicates": [{"ref": "Order.order_id", "op": "=", "value": 0}]}},
        {"name": "orders_over_total", "shape": "relational",
         "query": {"root": "Order", "returns": ["Order.order_id", "Order.total"],
                   "predicates": [{"ref": "Order.total", "op": ">", "value": 0}]}},
    ],
}


def test_default_renders_all_platforms():
    files = render_all(SPEC)
    exts = {Path(p).suffix for p in files}
    assert {".py", ".js", ".java", ".go", ".cs"} <= exts
    assert len(ALL_PLATFORMS) == 5


def test_subset_platforms_only():
    files = render_all({**SPEC, "platforms": ["python", "node"]})
    exts = {Path(p).suffix for p in files}
    # the two platforms + README + schema.sql/deploy.sh (patterns need a schema)
    assert {".py", ".js", ".md", ".sql", ".sh"} == exts
    assert ".java" not in exts and ".go" not in exts and ".cs" not in exts


def test_each_pattern_becomes_a_method_with_binds():
    files = render_all({**SPEC, "platforms": ["python"]})
    py = next(v for k, v in files.items() if k.endswith(".py"))
    # a method per access pattern
    assert "get_order_by_id" in py and "orders_over_total" in py
    # binds threaded through, not inlined
    assert "b0" in py
    # the generated SQL is embedded
    assert "JSON_VALUE" in py or "order_docs" in py
    assert "order_item" in py or "orders" in py  # relational pattern's SQL


def test_node_and_dotnet_bind_by_name():
    files = render_all({**SPEC, "platforms": ["node", "dotnet"]})
    cs = next(v for k, v in files.items() if k.endswith(".cs"))
    assert "BindByName" in cs               # ODP.NET must bind :b0 by name
    assert "b0" in cs


def test_unknown_platform_rejected():
    try:
        render_all({**SPEC, "platforms": ["cobol"]})
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_cli_writes_archive_with_readme(tmp_path):
    import json as _json
    from tooling.datalayer import __main__ as cli
    spec = tmp_path / "spec.json"
    spec.write_text(_json.dumps({**SPEC, "platforms": ["python", "go"]}))
    out = tmp_path / "kit"
    cli.main([str(spec), str(out), "--platforms", "py,golang"])
    names = {p.name for p in out.iterdir()}
    assert "repository.py" in names and "repository.go" in names
    assert "README.md" in names
    assert "get_order_by_id" in (out / "README.md").read_text()


def test_archive_includes_schema_and_deploy():
    files = render_all({**SPEC, "platforms": ["python"]})
    assert "schema.sql" in files and "deploy.sh" in files
    # schema covers the shapes used by the patterns (document collection + relational)
    assert "CREATE JSON COLLECTION TABLE" in files["schema.sql"]
    assert "CREATE TABLE IF NOT EXISTS orders" in files["schema.sql"]
    assert "sql -S" in files["deploy.sh"] or "sqlplus" in files["deploy.sh"]


def test_python_auto_deploys_when_schema_absent():
    files = render_all({**SPEC, "platforms": ["python"]})
    py = files["repository.py"]
    assert "def ensure_schema(conn)" in py
    assert "SCHEMA_DDL" in py
    # probes for a real object before deploying
    assert "WHERE ROWNUM = 1" in py


def test_generated_python_still_parses_with_schema():
    import ast
    files = render_all({**SPEC, "platforms": ["python"]})
    ast.parse(files["repository.py"])   # embedded DDL must not break the module


def test_dotnet_connect_has_no_nested_quotes_in_interpolation():
    # escaped quotes inside a C# interpolated string are a compile error; the
    # generator must read env vars into locals first.
    files = render_all({**SPEC, "platforms": ["dotnet"]})
    cs = files["Repository.cs"]
    assert '\\"' not in cs, "no escaped quotes inside interpolated strings"
    assert 'GetEnvironmentVariable("DB_USER")' in cs


def test_ensure_schema_is_idempotent_tolerates_already_exists():
    files = render_all({**SPEC, "platforms": ["python"]})
    py = files["repository.py"]
    assert "exc.args[0].code not in" in py   # ignores name/constraint-already-exists
    assert "955" in py


def test_schema_includes_indexes_derived_from_patterns():
    files = render_all({**SPEC, "platforms": ["python"]})
    s = files["schema.sql"]
    # SPEC's orders_over_total filters Booking.total (non-PK) -> an index is derived
    assert "CREATE INDEX" in s


def test_a_zero_bind_pattern_renders_a_valid_python_function():
    """A pattern with no binds (an aggregation) rendered `def f(conn, *):` —
    a SyntaxError that broke the WHOLE generated module. Caught live by the
    dot-doctrine e2e exercise: one KPI pattern poisoned every generated
    function. The module must compile and the function must take conn alone."""
    from tooling.datalayer.platforms import render_all
    spec = {"model": {"entities": {"O": {"table": "orders", "pk": "order_id",
                                         "columns": {"status": "status", "total": "total"}}},
                      "relationships": [],
                      "projections": {"document": {"O": {"collection": "o_docs"}}}},
            "platforms": ["python"],
            "patterns": [{"name": "revenue_by_status", "shape": "document",
                          "query": {"root": "O", "group_by": ["O.status"],
                                    "aggregates": [{"fn": "SUM", "ref": "O.total",
                                                    "name": "revenue"}]}}]}
    py = render_all(spec)["repository.py"]
    compile(py, "repository.py", "exec")           # must not SyntaxError
    assert "def revenue_by_status(conn):" in py, py


def test_deploy_sh_probes_sql_before_trusting_it():
    """The e2e exercise hit a docker-shim `sql` bound to a dead network: the
    generated deploy.sh trusted the first `sql` on PATH and failed opaquely.
    A `sql` that exists is not a `sql` that works — the generated script must
    require it to identify as SQLcl, fall back to sqlplus, and name the
    problem when neither exists."""
    from tooling.datalayer.platforms import render_all
    spec = {"model": {"entities": {"O": {"table": "orders", "pk": "order_id",
                                         "columns": {"status": "status"}}},
                      "relationships": [],
                      "projections": {"document": {"O": {"collection": "o_docs"}}}},
            "platforms": ["python"],
            "patterns": [{"name": "by_status", "shape": "document",
                          "query": {"root": "O", "returns": ["O.status"],
                                    "predicates": [{"ref": "O.status", "op": "=",
                                                    "value": "OPEN"}]}}]}
    sh = render_all(spec)["deploy.sh"]
    assert "grep -qi sqlcl" in sh, "must verify `sql` identifies as SQLcl"
    assert "sqlplus" in sh, "must fall back to sqlplus"
    assert "no usable" in sh, "must name the failure when no client exists"
