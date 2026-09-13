import importlib
import sys
from pathlib import Path


def test_package_has_init_at_each_level(repo_root: Path):
    for rel in ("tooling/__init__.py", "tooling/intake/__init__.py",
                "tooling/recommend/__init__.py"):
        assert (repo_root / rel).is_file(), f"missing {rel}"


def test_modules_import_cleanly(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    for mod in ("tooling.intake.validate", "tooling.recommend.shapes",
                "tooling.recommend.plan"):
        importlib.import_module(mod)


def test_schema_is_valid_json(repo_root: Path):
    import json
    json.loads((repo_root / "tooling/intake/schema.json").read_text())
