# Copyright (c) 2026 Oracle and/or its affiliates.
"""Verify relative markdown links resolve to files on disk."""
import re
from pathlib import Path

_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def check_links(root: Path, md_file: Path) -> list:
    broken = []
    for m in _LINK.finditer(md_file.read_text()):
        target = m.group(1).split("#", 1)[0].strip()
        if not target or target.startswith(("http://", "https://", "mailto:")):
            continue
        resolved = (md_file.parent / target).resolve()
        if not resolved.exists():
            broken.append(f"{md_file.name}: broken link -> {target}")
    return broken
