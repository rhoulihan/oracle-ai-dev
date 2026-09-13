import json
from pathlib import Path

FORM = "assets/tooling/intake/intake-form.html"


def test_form_exists_and_self_contained(repo_root: Path):
    html = (repo_root / FORM).read_text()
    assert html.strip().lower().startswith("<!doctype html")
    # self-contained: no external scripts/styles/fonts
    for bad in ("http://", "https://", "src=\"//", "<link rel=\"stylesheet\" href"):
        assert bad not in html, f"form must be self-contained (found {bad})"


def test_form_covers_the_schema_fields(repo_root: Path):
    html = (repo_root / FORM).read_text().lower()
    schema = json.loads((repo_root / "tooling/intake/schema.json").read_text())
    for field in ("workload", "entities", "access_patterns", "required_features", "deployment"):
        assert field in html, f"form missing schema field {field}"
    # feature enum values should appear as choices
    for feat in schema["properties"]["required_features"]["items"]["enum"]:
        assert feat in html


def test_form_exports_requirements_json(repo_root: Path):
    html = (repo_root / FORM).read_text()
    assert "requirements.json" in html
    assert "application/json" in html  # a Blob/download of JSON
