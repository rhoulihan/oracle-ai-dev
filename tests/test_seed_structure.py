import sys
from pathlib import Path

TABLES = ["restaurant", "menu_item", "customer", "orders", "order_item", "address", "review"]


def _canonical(repo_root: Path) -> str:
    return (repo_root / "assets/seed/01-canonical.sql").read_text().lower()


def test_all_seven_entities_defined(repo_root: Path):
    sql = _canonical(repo_root)
    missing = [t for t in TABLES if f"table if not exists {t} " not in sql and f"table if not exists {t}(" not in sql]
    assert not missing, f"missing canonical tables: {missing}"


def test_ddl_is_idempotent(repo_root: Path):
    sql = _canonical(repo_root)
    # Every CREATE TABLE must be guarded with IF NOT EXISTS (26ai-native).
    assert sql.count("create table") == sql.count("create table if not exists")


def test_seed_sql_clean_of_banned_terms(repo_root: Path):
    sys.path.insert(0, str(repo_root / "tests" / "lint"))
    from banned_strings import scan_tree
    problems = scan_tree(repo_root / "assets/seed")
    assert not problems, problems


def test_verify_seed_emits_assert(repo_root: Path):
    v = (repo_root / "assets/verify/verify-seed.sql").read_text()
    assert "ASSERT:" in v


def test_json_collection_projection_exists(repo_root: Path):
    sql = (repo_root / "assets/seed/02-json-collection.sql").read_text().lower()
    assert "json collection table" in sql


def test_duality_projects_full_child_pk(repo_root: Path):
    # gap-3: a duality view whose composite-PK array child omits a PK column
    # throws ORA-40477 on read. The order items array must project order_item_id.
    sql = (repo_root / "assets/seed/03-duality.sql").read_text().lower()
    assert "duality view" in sql
    assert "order_item_id" in sql, "array child must project its full PK (ORA-40477 workaround)"


def test_vector_uses_ivf_not_hnsw_on_free(repo_root: Path):
    sql = (repo_root / "assets/seed/06-seed-data.sql").read_text().lower() \
        + (repo_root / "assets/seed/04-vector.sql").read_text().lower()
    assert "neighbor partitions" in sql, "Free default is IVF (NEIGHBOR PARTITIONS)"
    assert "inmemory neighbor graph" not in sql, "HNSW needs VECTOR_MEMORY_SIZE; not the Free default"


def test_seed_readme_matches_plugin_user_grants(repo_root: Path):
    """05-graph.sql runs CREATE PROPERTY GRAPH, a distinct system privilege that
    create-plugin-user does NOT grant (it is feature-gated behind the
    enable-property-graph configurator — see tooling/recommend/plan.py). The
    README must not claim the plugin user alone can load 01-06: either the
    grant joins create-plugin-user.sql or the README names the configurator."""
    readme = (repo_root / "assets/seed/README.md").read_text().lower()
    grants = (repo_root / "assets/tooling/configure/create-plugin-user.sql").read_text().lower()
    assert "create property graph" in grants or "enable-property-graph" in readme, (
        "seed README's documented path fails at 05-graph.sql with ORA-01031: "
        "plugin_dev lacks CREATE PROPERTY GRAPH and the README never mentions "
        "the enable-property-graph configurator")


def test_graph_defines_property_graph(repo_root: Path):
    sql = (repo_root / "assets/seed/05-graph.sql").read_text().lower()
    assert "property graph" in sql
