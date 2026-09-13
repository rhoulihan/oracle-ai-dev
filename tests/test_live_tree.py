import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("ORACLE_AI_DEV_LIVE") != "1",
    reason="set ORACLE_AI_DEV_LIVE=1 to run the live hierarchy traversal test",
)

CONTAINER = "oracle-ai-dev-db"
BOOTSTRAP = """
DECLARE n INTEGER;
BEGIN
  SELECT COUNT(*) INTO n FROM all_users WHERE username = 'DEMO';
  IF n = 0 THEN
    EXECUTE IMMEDIATE 'CREATE USER demo IDENTIFIED BY Demo_pw_12345 '
      || 'DEFAULT TABLESPACE USERS QUOTA UNLIMITED ON USERS';
    EXECUTE IMMEDIATE 'GRANT CONNECT, RESOURCE, CREATE PROPERTY GRAPH TO demo';
  END IF;
END;
/
"""
TRAVERSE = {
    "root": "Employee", "returns": ["Employee.name"],
    "traversal": {"start": {"ref": "Employee.name", "op": "=", "value": "CEO"},
                  "direction": "down"},
}


def _sql(text, user="demo/Demo_pw_12345"):
    p = subprocess.run(["docker", "exec", "-i", CONTAINER, "sqlplus", "-S",
                        f"{user}@localhost:1521/FREEPDB1"],
                       input=text, capture_output=True, text=True)
    return p.stdout + p.stderr


def _count(sql):
    out = _sql(f"SET PAGES 0 FEED OFF\nSELECT COUNT(*) FROM ({sql});")
    m = re.search(r"\b(\d+)\b", out)
    return int(m.group(1)) if m and "ORA-" not in out else -1, out


@pytest.mark.live
def test_connect_by_and_recursive_cte_agree(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    from tooling.generate.sql import (generate_connect_by, generate_recursive_cte,
                                      generate_graph_table, generate_property_graph_ddl)
    model = json.loads((repo_root / "tests/fixtures/orgchart_model.json").read_text())

    compose = str(repo_root / "assets/compose/db.compose.yml")
    env = {**os.environ, "DB_HOST_PORT": "1599"}
    subprocess.run(["docker", "compose", "-p", "oadtree", "-f", compose, "up", "-d"], check=True, env=env)
    try:
        for _ in range(72):
            if subprocess.run(["docker", "inspect", "-f", "{{.State.Health.Status}}", CONTAINER],
                              capture_output=True, text=True).stdout.strip() == "healthy":
                break
            time.sleep(5)
        else:
            pytest.fail("db not healthy")
        assert "ORA-" not in _sql(BOOTSTRAP, user="system/devpassword")
        assert "ORA-" not in _sql((repo_root / "assets/seed/patterns/org-chart.sql").read_text())

        # Deploy the generated SQL/PGQ property graph — the third Tree realization.
        assert "ORA-" not in _sql(generate_property_graph_ddl(model, "Employee") + ";")

        cb, cb_out = _count(generate_connect_by(model, TRAVERSE))
        cte, cte_out = _count(generate_recursive_cte(model, TRAVERSE))
        gt, gt_out = _count(generate_graph_table(model, TRAVERSE))
        assert cb > 0, f"connect by failed:\n{cb_out}"
        assert cte > 0, f"recursive cte failed:\n{cte_out}"
        assert gt > 0, f"graph_table failed:\n{gt_out}"
        # All three Tree realizations return the same CEO subtree (the whole tree of 6).
        assert cb == cte == gt == 6, f"traversals disagree: connect_by={cb} cte={cte} graph_table={gt}"
    finally:
        subprocess.run(["docker", "compose", "-p", "oadtree", "-f", compose, "down", "-v"], env=env)
