# Copyright (c) 2026 Oracle and/or its affiliates.
"""Plan-check a query before delivery.

    export DB_USER=... DB_PASSWORD=... DB_DSN=localhost:1521/FREEPDB1
    python -m tooling.plancheck "SELECT ..."     # or `-` to read stdin

Prints the plan, the access summary, and any warning. Exit 0 means checked and
clean; exit 1 means a filtered query full-scans (fix the query or the index
before delivering it); exit 2 means the check itself could not run.
"""

import argparse
import os
import sys

from tooling.plancheck.check import plan_check


def _connect():
    try:
        import oracledb
    except ImportError:
        raise SystemExit("plan-checking talks to a live database and needs the "
                         "python-oracledb driver:\n  pip install oracledb")
    missing = [v for v in ("DB_USER", "DB_PASSWORD", "DB_DSN") if not os.environ.get(v)]
    if missing:
        raise SystemExit(f"set {', '.join(missing)} — e.g. "
                         "export DB_USER=plugin_dev DB_PASSWORD=... DB_DSN=localhost:1521/FREEPDB1")
    return oracledb.connect(user=os.environ["DB_USER"],
                            password=os.environ["DB_PASSWORD"],
                            dsn=os.environ["DB_DSN"])


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m tooling.plancheck",
                                 description="pull a query's execution plan and report "
                                             "how it will be served")
    ap.add_argument("sql", help="the statement to plan-check ('-' reads stdin)")
    a = ap.parse_args(argv)
    sql = sys.stdin.read() if a.sql == "-" else a.sql
    sql = sql.strip().rstrip(";")
    try:
        s = plan_check(_connect(), sql)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"plan check failed: {exc}")
        return 2
    for line in s["plan"]:
        print(line)
    print(f"access: {s['access']}")
    for w in s["warnings"]:
        print(f"WARNING: {w}")
    return 1 if s["warnings"] else 0


if __name__ == "__main__":
    sys.exit(main())
