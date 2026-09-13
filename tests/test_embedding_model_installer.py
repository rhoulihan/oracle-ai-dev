# Copyright (c) 2026 Oracle and/or its affiliates.
"""Contract for the ONNX embedding-model auto-installer.

`setup-embedding-model.sh` must download Oracle's prebuilt all-MiniLM-L12-v2 model,
stage it into the container, grant the privileges the load needs, load it, and be
idempotent — so server-side `VECTOR_EMBEDDING()` (agent memory + RAG) works with one
command. The live proof is `tests/test_stack_validation.py::test_server_side_vector_embedding`,
which flips from skip to pass once this installer has run.
"""
import os
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "assets/tooling/configure/setup-embedding-model.sh"


@pytest.fixture(scope="module")
def body():
    assert SCRIPT.exists(), f"{SCRIPT} must exist"
    return SCRIPT.read_text()


def test_is_executable():
    assert SCRIPT.stat().st_mode & stat.S_IXUSR, "installer must be executable"


def test_has_copyright(body):
    assert "Copyright (c) 2026 Oracle" in body


def test_defaults_to_oracle_model_and_has_stable_fallback(body):
    # a concrete default download URL to Oracle's object storage...
    assert "objectstorage" in body and "all_MiniLM_L12_v2_augmented.zip" in body
    # ...and the stable docs-lookup entry point to recover a fresh URL when the PAR rotates
    assert "id=oml_ai_models_object_storage" in body


def test_url_is_overridable(body):
    # the rotating PAR must be overridable (arg or env) — not a hard-coded dead end
    assert "ONNX_MODEL_URL" in body


def test_grants_required_privileges(body):
    # loading an ONNX model needs CREATE MINING MODEL + READ on the staged directory
    assert "CREATE MINING MODEL" in body
    assert "GRANT READ ON DIRECTORY" in body


def test_creates_directory_object_and_stages_into_container(body):
    assert "CREATE OR REPLACE DIRECTORY" in body
    assert "docker cp" in body            # stage the .onnx where the DB can read it


def test_idempotent_load(body):
    # must not re-load if the model is already present
    assert "user_mining_models" in body
    assert "LOAD_ONNX_MODEL" in body


def test_verifies_with_vector_embedding(body):
    assert "VECTOR_EMBEDDING" in body


def test_referenced_by_docs():
    emb = (ROOT / "skills/vector-rag-dev/references/embeddings.md").read_text()
    mem = (ROOT / "skills/ai-agent-dev/references/agent-memory.md").read_text()
    assert "setup-embedding-model" in emb, "embeddings.md should point at the auto-installer"
    assert "setup-embedding-model" in mem, "agent-memory.md should point at the auto-installer"
