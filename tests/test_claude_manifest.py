import json
from pathlib import Path


def _load(repo_root: Path) -> dict:
    return json.loads((repo_root / ".claude-plugin" / "plugin.json").read_text())


def test_manifest_is_valid_json_and_named(repo_root: Path):
    m = _load(repo_root)
    assert m["name"] == "oracle-ai-dev"
    # semver, and the two platform manifests must agree — a hardcoded literal
    # here just breaks every release; drift BETWEEN manifests is the real bug
    import json
    import re
    assert re.fullmatch(r"\d+\.\d+\.\d+", m["version"]), m["version"]
    codex = json.loads((repo_root / ".codex-plugin/plugin.json").read_text())
    assert codex["version"] == m["version"], \
        "the Claude and Codex manifests must ship the same version"
    assert m["license"] == "UPL-1.0"


def test_mcp_servers_points_to_shared_file(repo_root: Path):
    assert _load(repo_root)["mcpServers"] == "./.mcp.json"


def test_every_user_config_entry_has_title(repo_root: Path):
    uc = _load(repo_root).get("userConfig", {})
    assert uc, "userConfig must be present"
    missing = [k for k, v in uc.items() if not v.get("title")]
    assert not missing, f"userConfig entries missing required 'title': {missing}"


def test_no_user_config_entry_blocks_install(repo_root: Path):
    """Install must never be blocked on tooling the plugin can provide itself.

    SQLcl is only needed by the MCP arm, and the plugin ships its own installer
    (scripts/install-sqlcl.sh). Marking sqlcl_path `required` makes the config
    unsavable for anyone who doesn't already have SQLcl — i.e. it blocks install.
    """
    uc = _load(repo_root).get("userConfig", {})
    required = [k for k, v in uc.items() if v.get("required")]
    assert not required, f"userConfig entries marked required block install: {required}"


def test_every_user_config_entry_has_a_usable_default(repo_root: Path):
    uc = _load(repo_root).get("userConfig", {})
    missing = [k for k, v in uc.items() if "default" not in v]
    assert not missing, f"userConfig entries need a default so install works unattended: {missing}"
