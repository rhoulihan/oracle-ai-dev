import json
from pathlib import Path


def _j(repo_root, rel):
    return json.loads((repo_root / rel).read_text())


def test_name_identical_across_manifests(repo_root: Path):
    claude = _j(repo_root, ".claude-plugin/plugin.json")["name"]
    codex = _j(repo_root, ".codex-plugin/plugin.json")["name"]
    mkt = _j(repo_root, ".claude-plugin/marketplace.json")["plugins"][0]["name"]
    assert claude == codex == mkt == "oracle-ai-dev"


def test_version_identical_across_plugin_manifests(repo_root: Path):
    claude = _j(repo_root, ".claude-plugin/plugin.json")["version"]
    codex = _j(repo_root, ".codex-plugin/plugin.json")["version"]
    assert claude == codex
