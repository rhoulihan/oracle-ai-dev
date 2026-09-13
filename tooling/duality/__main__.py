# Copyright (c) 2026 Oracle and/or its affiliates.
"""Review a ModelSpec against the duality design gates.

    python -m tooling.duality model.json [--root R]

One line per finding; exit 1 on blockers. Accepts a bare ModelSpec or the
datalayer's spec envelope ({"model": ...}).
"""

import argparse
import json
import sys

from tooling.duality.validate import validate_duality


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m tooling.duality",
                                 description="duality design-gate review")
    ap.add_argument("model", help="ModelSpec JSON (or a {'model': ...} envelope)")
    ap.add_argument("--root", help="validate one projection root only")
    a = ap.parse_args(argv)
    with open(a.model) as f:
        data = json.load(f)
    model = data["model"] if "entities" not in data and "model" in data else data
    found = validate_duality(model, root=a.root)
    for v in found:
        print(v)
    blockers = sum(1 for v in found if v.severity == "blocker")
    print(f"{blockers} blocker(s), {len(found) - blockers} warning(s)")
    return 1 if blockers else 0


if __name__ == "__main__":
    sys.exit(main())
