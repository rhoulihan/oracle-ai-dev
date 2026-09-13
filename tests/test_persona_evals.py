"""Persona acceptance evals.

Deterministic proxy for skill triggering: each persona prompt should share the
most keyword overlap with its intended skill's description, i.e. descriptions are
discriminative enough to route correctly. This catches vague/overlapping
descriptions without invoking a model.

A real-CLI eval (actual trigger behavior) is a documented, opt-in harness:
drive `claude -p "<prompt>"` / `codex` in a scratch home and assert the expected
skill loads. Not run here to avoid model-token cost and flakiness.
"""
import json
import re
import sys
from pathlib import Path

_STOP = set("""a an the to and or of for on in with my me i want need help this that
your you is are can could would use using build add run set up stand into it its
oracle database app application""".split())


def _tokens(text: str):
    return {w for w in re.findall(r"[a-z_]+", text.lower()) if w not in _STOP and len(w) > 2}


def _skill_descriptions(repo_root: Path):
    sys.path.insert(0, str(repo_root / "tests" / "lint"))
    from skill_frontmatter import _split_frontmatter
    out = {}
    for d in (repo_root / "skills").iterdir():
        sk = d / "SKILL.md"
        if sk.is_file():
            fm, _ = _split_frontmatter(sk.read_text())
            out[d.name] = _tokens(fm.get("description", ""))
    return out


def _cases(repo_root: Path):
    data = json.loads((repo_root / "tests/evals/persona_prompts.json").read_text())
    return data["cases"]


def test_every_expected_skill_exists(repo_root: Path):
    skills = set(_skill_descriptions(repo_root))
    for c in _cases(repo_root):
        assert c["expect"] in skills, f"eval references missing skill: {c['expect']}"


def test_each_prompt_routes_to_its_skill_by_keyword_overlap(repo_root: Path):
    descs = _skill_descriptions(repo_root)
    failures = []
    for c in _cases(repo_root):
        ptoks = _tokens(c["prompt"])
        scores = {name: len(ptoks & dtoks) for name, dtoks in descs.items()}
        best = max(scores.values())
        winners = [n for n, s in scores.items() if s == best]
        if c["expect"] not in winners:
            failures.append(f"{c['prompt']!r} -> {winners} (expected {c['expect']})")
    assert not failures, "non-discriminative descriptions:\n" + "\n".join(failures)
