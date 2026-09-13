import json
from pathlib import Path


def test_claude_marketplace_lists_plugin(repo_root: Path):
    m = json.loads((repo_root / ".claude-plugin" / "marketplace.json").read_text())
    names = [p["name"] for p in m["plugins"]]
    assert "oracle-ai-dev" in names
    entry = next(p for p in m["plugins"] if p["name"] == "oracle-ai-dev")
    assert entry["source"] == "./"


def test_codex_dev_marketplace_exists(repo_root: Path):
    m = json.loads((repo_root / ".agents" / "plugins" / "marketplace.json").read_text())
    assert "oracle-ai-dev" in json.dumps(m)


def test_codex_marketplace_uses_a_local_source(repo_root: Path):
    """Codex resolves .agents/plugins/marketplace.json FIRST, shadowing the verified
    .claude-plugin fallback — so its entry must be valid on its own. Per
    docs/research/codex-delivery.md §6.4, "url" sources are git repo URLs; an in-tree
    plugin uses {"source": "local", "path": "./..."} ("./"-prefixed, relative to the
    marketplace root). "./" is not a git URL, so the url form breaks installs."""
    m = json.loads((repo_root / ".agents" / "plugins" / "marketplace.json").read_text())
    entry = next(p for p in m["plugins"] if p["name"] == "oracle-ai-dev")
    assert entry["source"] == {"source": "local", "path": "./"}
