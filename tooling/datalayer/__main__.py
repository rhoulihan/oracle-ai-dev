# Copyright (c) 2026 Oracle and/or its affiliates.
"""CLI: render a data-access layer archive from a spec.

  python -m tooling.datalayer <spec.json> <out_dir> [--platforms py,node,...]

The spec is {"model": ModelSpec, "patterns": [{"name","shape","query"}, ...]}.
Default renders every supported platform; --platforms selects a subset.
"""
import argparse
import json
import sys

from tooling.datalayer.platforms import ALL_PLATFORMS, write_datalayer

# accept short aliases on the command line
_ALIAS = {"py": "python", "js": "node", "cs": "dotnet", "golang": "go"}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="tooling.datalayer")
    ap.add_argument("spec", help="path to the datalayer spec JSON")
    ap.add_argument("out_dir", help="directory to write the generated archive into")
    ap.add_argument("--platforms", help="comma-separated subset (default: all): "
                    + ", ".join(ALL_PLATFORMS))
    args = ap.parse_args(argv)

    spec = json.loads(open(args.spec).read())
    if args.platforms:
        spec["platforms"] = [_ALIAS.get(p.strip(), p.strip())
                             for p in args.platforms.split(",") if p.strip()]

    written = write_datalayer(spec, args.out_dir)
    for p in written:
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
