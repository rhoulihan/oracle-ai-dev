import sys
from pathlib import Path

BENCH = "assets/bench"


def test_candidate_queries_target_their_shapes(repo_root: Path):
    rel = (repo_root / BENCH / "get_order.relational.sql").read_text().lower()
    dua = (repo_root / BENCH / "get_order.duality.sql").read_text().lower()
    doc = (repo_root / BENCH / "get_order.document.sql").read_text().lower()
    assert "order_item" in rel and "join" in rel
    assert "order_dv" in dua
    assert "order_docs" in doc


def test_timing_harness_measures_and_emits_bench(repo_root: Path):
    h = (repo_root / BENCH / "time-query.sql").read_text().lower()
    # server-side logical reads (P1), not the 10ms wall-clock
    assert "consistent gets" in h
    assert "systimestamp" in h            # µs secondary metric (P2)
    assert "&warmup" in h                 # discard cold/hard-parse run (P3)
    assert "median" in h and "&trials" in h  # median of K trials (P4)
    assert "result_cache_mode" in h       # cache controlled (P8)
    assert "dbms_utility.get_time" not in h  # the coarse clock is gone
    assert ":cg=" in h and ":cv=" in h    # extended BENCH contract
    assert "bench:" in h


def test_dml_harness_measures_rolls_back_and_emits_bench(repo_root: Path):
    h = (repo_root / BENCH / "time-dml.sql").read_text().lower()
    assert "redo size" in h               # write amplification via redo (P5)
    assert "&warmup" in h and "median" in h and "&trials" in h
    assert h.count("rollback") >= 2       # warmup AND each trial roll back
    assert "dbms_utility.get_time" not in h
    assert ":cg=" in h and ":cv=" in h
    assert "bench:" in h


def test_explain_harness_captures_actual_plan(repo_root: Path):
    h = (repo_root / BENCH / "explain-query.sql").read_text().lower()
    assert "display_cursor" in h              # actual plan, not just EXPLAIN PLAN
    assert "allstats" in h                    # A-Rows vs E-Rows + Buffers
    assert "statistics_level" in h            # rowsource stats enabled
    assert "set serveroutput off" in h        # so DISPLAY_CURSOR(NULL) finds the query
    assert "&query_text" in h and "&label" in h


def test_bench_clean_of_banned_terms(repo_root: Path):
    sys.path.insert(0, str(repo_root / "tests" / "lint"))
    from banned_strings import scan_tree
    assert not scan_tree(repo_root / BENCH)
