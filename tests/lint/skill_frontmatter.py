# Copyright (c) 2026 Oracle and/or its affiliates.
"""Validate agentskills.io SKILL.md frontmatter against spec constraints."""
import re
from pathlib import Path

import yaml

_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _split_frontmatter(text: str):
    if not text.startswith("---"):
        return None, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None, text
    return yaml.safe_load(parts[1]) or {}, parts[2]


def validate_skill(skill_dir: Path) -> list:
    v = []
    fm, body = _split_frontmatter((skill_dir / "SKILL.md").read_text())
    if fm is None:
        return ["missing YAML frontmatter"]
    if set(fm) != {"name", "description"}:
        v.append(f"frontmatter keys must be exactly name+description, got {sorted(fm)}")
    name = fm.get("name", "")
    if name != skill_dir.name:
        v.append(f"name {name!r} must equal directory {skill_dir.name!r}")
    if not _NAME_RE.match(str(name)):
        v.append(f"name {name!r} must be lowercase-hyphen")
    if len(str(fm.get("description", ""))) > 500:
        v.append("description exceeds 500 chars")
    if len(body.split()) >= 500:
        v.append("SKILL.md body must be < 500 words")
    return v
