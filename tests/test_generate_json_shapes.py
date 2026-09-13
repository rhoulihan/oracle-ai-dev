import sys
from pathlib import Path

import pytest

from test_generate_model import MODEL, QUERY


def _sql(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    import tooling.generate.sql as s
    return s


def test_document_targets_collection_and_id_path(repo_root: Path):
    out = _sql(repo_root).generate_document(MODEL, QUERY).lower()
    assert "from order_docs" in out
    assert "json_value" in out and "$._id" in out
    assert "1000" in out


def test_duality_targets_view_and_id_path(repo_root: Path):
    out = _sql(repo_root).generate_duality(MODEL, QUERY).lower()
    assert "from order_dv" in out
    assert "json_value" in out and "1000" in out


def test_missing_projection_raises(repo_root: Path):
    s = _sql(repo_root)
    m = {**MODEL, "projections": {"duality": {}, "document": {}}}
    with pytest.raises(ValueError):
        s.generate_duality(m, QUERY)
    with pytest.raises(ValueError):
        s.generate_document(m, QUERY)
