# Copyright (c) 2026 Oracle and/or its affiliates.
"""A missing driver gets an instruction, not a traceback.

The generation paths run on pure stdlib; only the live paths (optimizer,
plancheck, generated Python layer) need python-oracledb — and a greenfield
machine meets that as a raw ModuleNotFoundError. The CLIs must name the fix."""

import sys

import pytest


def _blocked_oracledb(monkeypatch):
    monkeypatch.setitem(sys.modules, "oracledb", None)  # import -> ImportError


def test_optimize_connect_names_the_fix(monkeypatch):
    _blocked_oracledb(monkeypatch)
    monkeypatch.setenv("DB_USER", "u")
    monkeypatch.setenv("DB_PASSWORD", "p")
    monkeypatch.setenv("DB_DSN", "d")
    from tooling.optimize.__main__ import _connect
    with pytest.raises(SystemExit, match="pip install oracledb"):
        _connect()


def test_plancheck_connect_names_the_fix(monkeypatch):
    _blocked_oracledb(monkeypatch)
    monkeypatch.setenv("DB_USER", "u")
    monkeypatch.setenv("DB_PASSWORD", "p")
    monkeypatch.setenv("DB_DSN", "d")
    from tooling.plancheck.__main__ import _connect
    with pytest.raises(SystemExit, match="pip install oracledb"):
        _connect()
