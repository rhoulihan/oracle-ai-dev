# Copyright (c) 2026 Oracle and/or its affiliates.
"""Flag banned terminology outside sanctioned Version Notes sections, and flag
confidential engagement/customer/person names via a hashed token register."""
import re
from pathlib import Path

_BANNED = [re.compile(r"(?<![\w.])23ai\b", re.IGNORECASE)]


def scan(text: str) -> list:
    violations = []
    in_version_notes = False
    for n, line in enumerate(text.splitlines(), start=1):
        if line.startswith("#"):
            in_version_notes = "oracle version notes" in line.lower()
        if in_version_notes:
            continue
        for pat in _BANNED:
            if pat.search(line):
                violations.append(f"line {n}: banned term in {line.strip()!r}")
    return violations


def scan_tree(root) -> dict:
    """Scan every *.md under root (recursively). Returns {path: violations}."""
    problems = {}
    for md in sorted(Path(root).rglob("*.md")):
        v = scan(md.read_text())
        if v:
            problems[str(md)] = v
    return problems


# --- Confidential-token lint --------------------------------------------------
#
# Field evidence in this repo ships GENERALIZED ("a financial-services PoC", "an
# insurance carrier's assessment") and the underlying engagement pseudonyms,
# must never appear in shipped content. Spelling those names in a public blocklist
# would itself be the leak — and (2026-07-15 adversarial review) so would shipping
# unsalted hashes of them: single-word SHA-256 is a trivially reversible
# confirmation oracle. The register therefore lives ENTIRELY OUTSIDE the
# repository: a maintainer-local plaintext file (one lowercased token per line;
# two-word lines are matched as adjacent word pairs; '#' comments allowed) at
# ~/.oracle-ai-dev/confidential-register.txt, overridable via the
# ORACLE_AI_DEV_CONFIDENTIAL_REGISTER environment variable. When the file is
# absent (every public clone, public CI) the scan is a clean no-op; maintainer
# machines and private release CI install the register, where the scan gates
# every release. The repo ships only the mechanism.

import os


def _register_path():
    return os.environ.get(
        "ORACLE_AI_DEV_CONFIDENTIAL_REGISTER",
        os.path.expanduser("~/.oracle-ai-dev/confidential-register.txt"))


def _load_register():
    """(words, pairs) from the maintainer-local register; empty when absent."""
    words, pairs = set(), set()
    try:
        with open(_register_path()) as fh:
            for line in fh:
                tok = line.split("#", 1)[0].strip().lower()
                if not tok:
                    continue
                (pairs if " " in tok else words).add(tok)
    except OSError:
        pass
    return frozenset(words), frozenset(pairs)


_CONFIDENTIAL_WORDS, _CONFIDENTIAL_PAIRS = _load_register()

_TOKEN = re.compile(r"[a-z][a-z0-9]{2,}")


def scan_confidential(text: str, words=_CONFIDENTIAL_WORDS,
                      pairs=_CONFIDENTIAL_PAIRS) -> list:
    """Flag words (and adjacent word pairs) present in the maintainer register."""
    violations = []
    for n, line in enumerate(text.splitlines(), start=1):
        tokens = _TOKEN.findall(line.lower())
        # A registered hostname PREFIX must also catch numbered instances
        # (prefix01, prefix02, ...), so the digit-stripped form is tested too.
        hits = [t for t in tokens
                if t in words or t.rstrip("0123456789") in words]
        hits += [f"{a} {b}" for a, b in zip(tokens, tokens[1:])
                 if f"{a} {b}" in pairs]
        violations += [f"line {n}: confidential token {h!r}" for h in hits]
    return violations


# Internal dossiers/specs that legitimately discuss the sanitization targets they
# mandate — never shipped as skill content. Everything else under docs/ is fair
# game for the scan.
_CONFIDENTIAL_SCAN_EXCLUDE = (
    "docs/research/",
    "docs/specs/2026-07-15-modeling-field-memories.md",
)


def _shipped_files(repo_root):
    """(rel_path, text) for every shipped-content file: skills/** (every text
    file), README.md, docs/**/*.md minus the internal-dossier exclusions."""
    root = Path(repo_root)
    candidates = [root / "README.md"]
    if (root / "skills").is_dir():
        candidates += sorted(p for p in (root / "skills").rglob("*") if p.is_file())
    if (root / "docs").is_dir():
        candidates += sorted((root / "docs").rglob("*.md"))
    for f in candidates:
        if not f.is_file():
            continue
        rel = f.relative_to(root).as_posix()
        if any(rel == x or rel.startswith(x) for x in _CONFIDENTIAL_SCAN_EXCLUDE):
            continue
        try:
            yield rel, f.read_text()
        except (UnicodeDecodeError, OSError):
            continue


def scan_confidential_tree(repo_root, words=_CONFIDENTIAL_WORDS,
                           pairs=_CONFIDENTIAL_PAIRS) -> dict:
    """Scan shipped content for registered tokens. {path: violations}."""
    problems = {}
    for rel, text in _shipped_files(repo_root):
        v = scan_confidential(text, words=words, pairs=pairs)
        if v:
            problems[rel] = v
    return problems


# --- Do-not-cite figure lint ---------------------------------------------------
#
# Engagement-derived bench figures that must never ship: the scenario count and
# the headline multiplier fingerprint their source even with every name scrubbed
# (2026-07-15 PII review). Digit boundaries keep ORA-40477 and port numbers from
# false-positiving; the multiplier requires its x/× suffix and a boundary after
# it ("165 xml" is not a citation). The unrounded-seconds SHAPE guard stays
# scoped to field-lessons.md (test_modeling_skill.py): sub-second constants are
# legitimate elsewhere; the exact figures are not legitimate anywhere.
_DO_NOT_CITE = [re.compile(r"(?<!\d)477(?!\d)"),
                re.compile(r"(?<!\d)165\s*[x×](?![a-z0-9])", re.IGNORECASE)]


def scan_do_not_cite(text: str) -> list:
    """Flag do-not-cite engagement figures. Returns violation strings."""
    violations = []
    for n, line in enumerate(text.splitlines() or [text], start=1):
        for pat in _DO_NOT_CITE:
            for m in pat.finditer(line):
                violations.append(f"line {n}: do-not-cite figure {m.group(0)!r}")
    return violations


def scan_do_not_cite_tree(repo_root) -> dict:
    """Scan shipped content for do-not-cite figures. {path: violations}."""
    problems = {}
    for rel, text in _shipped_files(repo_root):
        v = scan_do_not_cite(text)
        if v:
            problems[rel] = v
    return problems
