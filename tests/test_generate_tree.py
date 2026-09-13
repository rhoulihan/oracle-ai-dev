import sys
from pathlib import Path

import pytest

ORG = {
    "entities": {
        "Employee": {"table": "employee", "pk": "emp_id",
                     "columns": {"name": "name", "managerId": "manager_id"}},
    },
    "relationships": [
        {"from": "Employee", "to": "Employee", "from_key": "emp_id",
         "to_key": "manager_id", "kind": "hierarchy"},
    ],
    "projections": {},
}
TRAVERSE = {
    "root": "Employee",
    "returns": ["Employee.name"],
    "traversal": {"start": {"ref": "Employee.name", "op": "=", "value": "CEO"},
                  "direction": "down"},
}


def _sql(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    import tooling.generate.sql as s
    return s


def test_connect_by_generation(repo_root: Path):
    out = _sql(repo_root).generate_connect_by(ORG, TRAVERSE).lower()
    assert "start with name = 'ceo'" in out
    assert "connect by prior emp_id = manager_id" in out


def test_recursive_cte_generation(repo_root: Path):
    out = _sql(repo_root).generate_recursive_cte(ORG, TRAVERSE).lower()
    assert "with" in out and "union all" in out
    assert "manager_id = " in out  # the recursive join on the parent ref


def test_traversal_on_non_hierarchy_raises(repo_root: Path):
    s = _sql(repo_root)
    flat = {"entities": {"Employee": {"table": "employee", "pk": "emp_id", "columns": {"name": "name"}}},
            "relationships": [], "projections": {}}
    with pytest.raises(ValueError):
        s.generate_connect_by(flat, TRAVERSE)


def test_generate_property_graph_ddl(repo_root: Path):
    ddl = _sql(repo_root).generate_property_graph_ddl(ORG, "Employee")
    assert "CREATE PROPERTY GRAPH" in ddl
    assert "VERTEX TABLES" in ddl and "EDGE TABLES" in ddl
    assert "SOURCE KEY (emp_id)" in ddl and "DESTINATION KEY (manager_id)" in ddl


def test_generate_graph_table_descendants(repo_root: Path):
    out = _sql(repo_root).generate_graph_table(ORG, TRAVERSE)
    up = out.upper()
    assert "GRAPH_TABLE" in up and "MATCH" in up and "COLUMNS" in up
    assert "'CEO'" in out          # the start-node predicate value


def test_candidates_include_three_tree_realizations(repo_root: Path):
    cands = _sql(repo_root).generate_candidates(ORG, TRAVERSE)
    assert set(cands) == {"connect_by", "recursive_cte", "graph_table"}
