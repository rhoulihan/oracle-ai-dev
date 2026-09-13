# Copyright (c) 2026 Oracle and/or its affiliates.
"""CLI: run the measured optimization against a live database.

  python -m tooling.optimize <workload.json> [--out DIR] [--shapes relational,document]

The workload is {"model": ModelSpec, "patterns": [...], "seed": "<sql>"} where each
pattern is {"name", "kind": "read"|"write", "rate", "category", "query", "write": {...}}.
The agent proposes the candidate models (the projections in the ModelSpec); this
measures whatever it declares.

The database is already deployed, so the connection comes from the environment —
the same DB_USER / DB_PASSWORD / DB_DSN the generated data layer uses:

  export DB_USER=plugin_dev DB_PASSWORD=... DB_DSN=localhost:1521/FREEPDB1

It runs the six steps end to end: derive+deploy the access-pattern indexes, deploy every
candidate shape, seed, measure every pattern against every shape, build the full cost
matrix, decide — then write the winning schema's DDL.
"""
import argparse
import json
import os
import sys
from pathlib import Path

from tooling.optimize.runner import format_report, optimize
from tooling.optimize.safety import DESTRUCTIVE, OVERRIDE_ENV, check_operation, dsn_mode


def _connect():
    try:
        import oracledb
    except ImportError:
        # The generation paths are stdlib-only; only the LIVE paths need the
        # driver — say so instead of handing greenfield a traceback.
        sys.exit("the measured optimizer talks to a live database and needs the "
                 "python-oracledb driver:\n  pip install oracledb")
    missing = [v for v in ("DB_USER", "DB_PASSWORD", "DB_DSN") if not os.environ.get(v)]
    if missing:
        sys.exit(f"set {', '.join(missing)} (the database you just deployed), e.g.\n"
                 "  export DB_USER=plugin_dev DB_PASSWORD=... DB_DSN=localhost:1521/FREEPDB1")
    return oracledb.connect(user=os.environ["DB_USER"],
                            password=os.environ["DB_PASSWORD"],
                            dsn=os.environ["DB_DSN"])


def main(argv=None):
    ap = argparse.ArgumentParser(prog="tooling.optimize",
                                 description="Measure every candidate shape on the live "
                                             "DB and choose the schema.")
    ap.add_argument("workload", help="workload spec JSON (model + patterns + seed)")
    ap.add_argument("--out", help="directory to write the winning schema DDL into")
    ap.add_argument("--shapes", help="restrict candidates, e.g. relational,document")
    ap.add_argument("--trials", type=int, default=7, help="measured executions per cell")
    ap.add_argument("--warmup", type=int, default=2, help="discarded executions per cell")
    ap.add_argument("--no-seed", action="store_true", help="skip the seed step")
    ap.add_argument("--fresh", action="store_true",
                    help="drop and rebuild every object first — DELETE leaves the "
                         "high-water mark of a previous, larger seed behind, and "
                         "every full scan then reads it")
    ap.add_argument("--json", action="store_true", help="emit the raw result as JSON")
    ap.add_argument("--write-scale", type=float, default=1.0,
                    help="multiply every write row's rate in the election — model a "
                         "heavier (or lighter) write mix without re-measuring")
    ap.add_argument("--walk-scales", default=None,
                    help="comma-separated write-rate multipliers for the consolidation "
                         "walk (default 0.1,1,3,10,30,100); reported as `walk`")
    ap.add_argument("--no-sparse", action="store_true",
                    help="single-table: plain per-type indexes instead of sparse "
                         "(CASE-filtered) ones")
    ap.add_argument("--no-partition-by-type", action="store_true",
                    help="single-table: skip automatic list partitioning by the "
                         "discriminator")
    ap.add_argument("--no-partition", action="store_true",
                    help="suppress every per-entity partition block (the "
                         "partition dimension) — measure the same designs "
                         "unpartitioned")
    ap.add_argument("--no-iot", action="store_true",
                    help="suppress every per-entity organization block (the "
                         "IOT dimension) — measure the same designs "
                         "heap-organized")
    ap.add_argument("--no-compress", action="store_true",
                    help="suppress every per-entity compress block (the row "
                         "compression dimension) — measure the same designs "
                         "uncompressed")
    ap.add_argument("--flex-limit", type=int, default=8192,
                    help="hybrid: the flex column's JSON ... LIMIT n inline "
                         "guarantee (default 8192)")
    ap.add_argument("--no-flex-limit", action="store_true",
                    help="hybrid: drop the LIMIT clause from the flex column "
                         "(inline storage no longer guaranteed)")
    args = ap.parse_args(argv)

    wl = Path(args.workload)
    spec = json.loads(wl.read_text())

    # `seed` may be inline SQL, a .sql path, or a list of them (relational overlay first,
    # then whatever populates the candidate document/single-table shapes).
    s = spec.get("seed")
    files = [s] if isinstance(s, str) else (s or [])
    parts = []
    for f in files:
        parts.append((wl.parent / f).read_text()
                     if isinstance(f, str) and f.strip().lower().endswith(".sql") else f)
    spec["seed"] = "\n".join(parts) if parts else None

    shapes = [s.strip() for s in args.shapes.split(",")] if args.shapes else None

    # --fresh runs drop_all: DROP TABLE ... CASCADE CONSTRAINTS PURGE on every model
    # table. On any target that is not the local disposable container that is exactly
    # what safety.py exists to refuse — check BEFORE connecting, not after dropping.
    dsn = os.environ.get("DB_DSN")
    if args.fresh and dsn:
        ok, reason = check_operation(dsn_mode(dsn), DESTRUCTIVE,
                                     allow_external=os.environ.get(OVERRIDE_ENV) == "1")
        if not ok:
            sys.exit(f"--fresh would drop every model table on {dsn}: {reason}")

    conn = _connect()
    try:
        walk = ([float(s) for s in args.walk_scales.split(",")]
                if args.walk_scales else None)
        result = optimize(conn, spec, shapes=shapes, trials=args.trials,
                          warmup=args.warmup, do_seed=not args.no_seed,
                          fresh=args.fresh, write_scale=args.write_scale,
                          walk_scales=walk, sparse=not args.no_sparse,
                          partition_by_type=not args.no_partition_by_type,
                          partition=not args.no_partition,
                          iot=not args.no_iot, compress=not args.no_compress,
                          flex_limit=None if args.no_flex_limit else args.flex_limit,
                          progress=lambda m: print(f"[optimize] {m}", file=sys.stderr))
    finally:
        conn.close()

    if args.json:
        print(json.dumps({k: v for k, v in result.items() if k != "detail"},
                         indent=2, default=str))
    else:
        print(format_report(result, sweep=result.get("sweep"),
                            detail=result.get("detail"),
                            scenarios=result.get("scenarios")))

    if args.out and result.get("ddl"):
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        p = out / f"schema.{result['chosen']}.sql"
        p.write_text(result["ddl"] + "\n")
        print(f"winning schema ({result['chosen']}) written to {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
