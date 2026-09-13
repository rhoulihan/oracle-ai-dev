# Copyright (c) 2026 Oracle and/or its affiliates.
"""The setup skill carries its executable spine, not just intentions.

A greenfield agent following "start the chosen profile ... run the setup
verification" had to invent the compose command, guess which script is "the
verification", never learned that a working user must be created, and could
connect system@host into CDB$ROOT. Every step is now a concrete command."""

from pathlib import Path


def test_setup_skill_carries_the_executable_spine(repo_root: Path):
    s = (repo_root / "skills" / "oracle-ai-setup" / "SKILL.md").read_text()
    for needle in (
        "docker compose -p oracle-ai-dev -f",       # the exact bring-up command
        "assets/verify/verify-setup.sh",            # the named verification
        "assets/verify/verify-ords.sh",             # db+ords: DB healthy != Mongo ready
        "create-plugin-user.sh",                    # the working user step
        "FREEPDB1",                                 # the PDB service...
        "CDB$ROOT",                                 # ...and why bare system@host is wrong
        "DB_USER",                                  # the hand-off the tooling reads
        "DB_PASSWORD",
        "DB_DSN",
    ):
        assert needle in s, f"setup skill must state {needle!r}"


def test_access_matrix_names_the_ords_readiness_probe(repo_root: Path):
    m = (repo_root / "skills" / "oracle-ai-setup" / "references" / "access-matrix.md").read_text()
    assert "verify-ords.sh" in m
