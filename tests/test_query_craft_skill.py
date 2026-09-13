from pathlib import Path

S = "skills/query-craft"


def test_skill_exists(repo_root: Path):
    assert (repo_root / S / "SKILL.md").is_file()


def test_mongo_to_sql_cookbook(repo_root: Path):
    m = (repo_root / S / "references/mongo-to-sql.md").read_text().lower()
    assert "json_table" in m
    assert "$unwind" in m and "$lookup" in m


def test_graph_table_reference(repo_root: Path):
    g = (repo_root / S / "references/graph-table.md").read_text().lower()
    assert "graph_table" in g and "dining_graph" in g


def test_hierarchies_prefer_connect_by_over_recursive_cte(repo_root: Path):
    g = (repo_root / S / "references/graph-table.md").read_text().lower()
    assert "connect by" in g
    assert "portability" in g          # recursive WITH = the portability spelling
    assert "plan-check" in g
    m = (repo_root / S / "references/mongo-to-sql.md").read_text().lower()
    assert "connect by" in m           # $graphLookup routes to the native form
