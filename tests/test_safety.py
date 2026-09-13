# Copyright (c) 2026 Oracle and/or its affiliates.
"""Never touch pre-existing data on an external system without an explicit
override. Local container: anything goes (it's disposable)."""
import pytest

from tooling.optimize.safety import READ, WRITE, DESTRUCTIVE, check_operation, dsn_mode


def test_local_container_permits_everything():
    for op in (READ, WRITE, DESTRUCTIVE):
        ok, _ = check_operation("container", op)
        assert ok is True


def test_external_reads_are_always_allowed():
    for mode in ("easy", "wallet"):
        ok, _ = check_operation(mode, READ)
        assert ok is True


def test_external_writes_refused_without_override():
    for mode in ("easy", "wallet"):
        for op in (WRITE, DESTRUCTIVE):
            ok, reason = check_operation(mode, op, allow_external=False)
            assert ok is False
            assert "override" in reason.lower() or "protect" in reason.lower()


def test_external_writes_allowed_with_explicit_override():
    ok, reason = check_operation("wallet", DESTRUCTIVE, allow_external=True)
    assert ok is True
    assert "override" in reason.lower()


def test_unknown_op_rejected():
    with pytest.raises(ValueError):
        check_operation("container", "frobnicate")


def test_dsn_mode_classifies_only_the_local_container_as_local():
    for local in ("localhost:1521/FREEPDB1", "127.0.0.1:1521/FREEPDB1",
                  "tcp://localhost:1521/FREEPDB1", "[::1]:1521/FREEPDB1"):
        assert dsn_mode(local) == "container", local
    for external in ("prod-db.internal:1521/ORDERS",
                     "tcps://adb.eu-frankfurt-1.oraclecloud.com:1522/x_high",
                     "(DESCRIPTION=(ADDRESS=(HOST=localhost)(PORT=1521)))",
                     ""):
        assert dsn_mode(external) == "easy", external


def test_cli_fresh_is_refused_on_an_external_dsn(tmp_path, monkeypatch):
    """`python -m tooling.optimize wl.json --fresh` runs drop_all — DROP TABLE ...
    CASCADE CONSTRAINTS PURGE on every model table. Pointed at anything that is not
    the local disposable container, that must be refused (before even connecting)
    unless the developer explicitly overrides."""
    from tooling.optimize.__main__ import main
    wl = tmp_path / "wl.json"
    wl.write_text("{}")
    monkeypatch.setenv("DB_USER", "app")
    monkeypatch.setenv("DB_PASSWORD", "x")
    monkeypatch.setenv("DB_DSN", "prod-db.internal:1521/ORDERS")
    monkeypatch.delenv("OPT_ALLOW_EXTERNAL_WRITES", raising=False)
    with pytest.raises(SystemExit) as e:
        main([str(wl), "--fresh"])
    assert "OPT_ALLOW_EXTERNAL_WRITES" in str(e.value)
