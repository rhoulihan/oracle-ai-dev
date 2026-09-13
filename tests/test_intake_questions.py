import json
import re
from pathlib import Path

# field names may contain digits (e.g. scale.doc_size_p99_kb)
_FIELD = re.compile(r"^\s*-?\s*field:\s*([a-z0-9_.]+)\s*$", re.MULTILINE)


def _schema_fields(repo_root: Path):
    schema = json.loads((repo_root / "tooling/intake/schema.json").read_text())
    top = set(schema["properties"])
    ap = set(schema["properties"]["access_patterns"]["items"]["properties"])
    return top, ap


def _referenced(path: Path):
    return set(_FIELD.findall(path.read_text()))


def test_both_banks_exist(repo_root: Path):
    assert (repo_root / "tooling/intake/questions-architecture.md").is_file()
    assert (repo_root / "tooling/intake/questions-modeling.md").is_file()


def test_architecture_bank_covers_required_top_fields(repo_root: Path):
    top, _ = _schema_fields(repo_root)
    refs = _referenced(repo_root / "tooling/intake/questions-architecture.md")
    for required in ("workload", "required_features", "deployment"):
        assert required in refs, f"architecture bank must ask about {required}"
    assert refs <= top, f"architecture bank references unknown fields: {refs - top}"


def test_modeling_bank_covers_access_pattern_fields(repo_root: Path):
    top, ap = _schema_fields(repo_root)
    refs = _referenced(repo_root / "tooling/intake/questions-modeling.md")
    for required in ("entities", "access_patterns"):
        assert required in refs
    ap_refs = {r.split(".", 1)[1] for r in refs if r.startswith("access_patterns.")}
    for sub in ("returns", "frequency"):
        assert sub in ap_refs, f"modeling bank must ask about access_patterns.{sub}"


def test_modeling_bank_covers_field_memory_dials(repo_root: Path):
    # The field-memories fold added dials: fields-touched, consistency-moment,
    # document-size distribution (typical + P99), hot-set, sizing-basis.
    refs = _referenced(repo_root / "tooling/intake/questions-modeling.md")
    for required in (
        "access_patterns.fields_touched",
        "access_patterns.consistency_moment",
        "scale.doc_size_p99_kb",
        "scale.hot_set_pct",
        "scale.sizing_basis",
    ):
        assert required in refs, f"modeling bank must ask about {required}"


def test_modeling_bank_field_refs_resolve_to_schema(repo_root: Path):
    # Every `field:` reference in the modeling bank must exist in the shared schema.
    schema = json.loads((repo_root / "tooling/intake/schema.json").read_text())
    top = set(schema["properties"])
    ap = set(schema["properties"]["access_patterns"]["items"]["properties"])
    scale = set(schema["properties"]["scale"]["properties"])
    for r in _referenced(repo_root / "tooling/intake/questions-modeling.md"):
        if r.startswith("access_patterns."):
            assert r.split(".", 1)[1] in ap, f"unknown access_patterns field: {r}"
        elif r.startswith("scale."):
            assert r.split(".", 1)[1] in scale, f"unknown scale field: {r}"
        else:
            assert r in top, f"unknown top-level field: {r}"
