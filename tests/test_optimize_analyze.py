import json
import os
import subprocess
import sys
from pathlib import Path


def _a(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    import tooling.optimize.analyze as a
    return a


M = {
    "get_order": {"relational": 8.0, "duality": 5.0, "document": 2.0},
    "order_report": {"relational": 3.0, "duality": 4.0, "document": 9.0},
}


def test_picks_lowest_median(repo_root: Path):
    r = _a(repo_root).optimal_shape_per_query(M)
    assert r["get_order"]["shape"] == "document"
    assert r["order_report"]["shape"] == "relational"


def test_keeps_alternatives(repo_root: Path):
    r = _a(repo_root).optimal_shape_per_query(M)
    assert r["get_order"]["alternatives"]["relational"] == 8.0
    assert r["get_order"]["ms"] == 2.0


def test_weighted_cost_sums_freq_times_ms(repo_root: Path):
    a = _a(repo_root)
    assign = {"get_order": "document", "order_report": "relational"}
    freq = {"get_order": 100, "order_report": 10}
    assert a.weighted_cost(assign, M, freq) == 100 * 2.0 + 10 * 3.0


def test_breakpoint_where_uncommon_penalty_overtakes(repo_root: Path):
    a = _a(repo_root)
    # document is great for get_order (2ms) but bad for order_report (9ms);
    # relational is 8ms/3ms. The two uniform designs cost the same when
    # get_order's frequency equals order_report's base frequency (10).
    bp = a.find_breakpoint("get_order", "document", "relational", M, "order_report", base_freq=10)
    assert bp == 10.0


def test_breakpoint_none_when_no_positive_crossover(repo_root: Path):
    a = _a(repo_root)
    # If document is better for BOTH queries, the designs never cross positively.
    m2 = {"q": {"document": 1.0, "relational": 5.0}, "o": {"document": 1.0, "relational": 5.0}}
    assert a.find_breakpoint("q", "document", "relational", m2, "o", base_freq=10) is None


FREQ = {"get_order": 100, "order_report": 10}


def test_global_design_mixed_beats_or_ties_uniform(repo_root: Path):
    d = _a(repo_root).recommend_global_design(M, FREQ)
    assert d["mixed_design_cost"] <= d["uniform_design_cost"]
    assert d["savings"] >= 0
    assert d["savings"] == d["uniform_design_cost"] - d["mixed_design_cost"]


def test_global_design_matches_per_query_optimal(repo_root: Path):
    a = _a(repo_root)
    d = a.recommend_global_design(M, FREQ)
    assert d["per_query_optimal"]["get_order"]["shape"] == "document"
    # concrete numbers from the docstring example
    assert d["mixed_design_cost"] == 230.0
    assert d["uniform_design_cost"] == 290.0
    assert d["best_uniform_shape"] == "document"


# Read+write model: document is read-fast but write-slow (whole-doc rewrite);
# relational is read-slow but write-fast (one row). The write frequency flips it.
RMEAS = {"cart": {"document": 1.0, "relational": 5.0}}
WMEAS = {"cart": {"document": 50.0, "relational": 2.0}}  # doc write amplification


def test_write_heavy_favors_relational_despite_read_optimal_document(repo_root: Path):
    a = _a(repo_root)
    rf, wf = {"cart": 10}, {"cart": 100}  # write-heavy
    doc = a.weighted_cost_rw({"cart": "document"}, RMEAS, WMEAS, rf, wf)
    rel = a.weighted_cost_rw({"cart": "relational"}, RMEAS, WMEAS, rf, wf)
    assert rel < doc, "write amplification should make document lose on a write-heavy path"


def test_read_heavy_favors_document(repo_root: Path):
    a = _a(repo_root)
    rf, wf = {"cart": 1000}, {"cart": 1}  # read-heavy
    doc = a.weighted_cost_rw({"cart": "document"}, RMEAS, WMEAS, rf, wf)
    rel = a.weighted_cost_rw({"cart": "relational"}, RMEAS, WMEAS, rf, wf)
    assert doc < rel


def test_design_options_are_ranked_with_discussion(repo_root: Path):
    a = _a(repo_root)
    rf, wf = {"cart": 100}, {"cart": 10}
    opts = a.recommend_design_options(RMEAS, WMEAS, rf, wf)
    assert len(opts) >= 2
    # sorted by cost ascending
    assert all(opts[i]["cost"] <= opts[i + 1]["cost"] for i in range(len(opts) - 1))
    assert opts[0]["rank"] == 1
    # every option carries discussion points
    assert all(o["discussion"] for o in opts)


def test_design_options_report_a_write_frequency_breakpoint(repo_root: Path):
    a = _a(repo_root)
    rf, wf = {"cart": 100}, {"cart": 10}
    opts = a.recommend_design_options(RMEAS, WMEAS, rf, wf)
    # the top option should note the write frequency at which the alternative wins
    bps = [bp for o in opts for bp in o.get("breakpoints", [])]
    assert bps, "expected at least one frequency breakpoint between designs"
    assert any("write" in str(bp).lower() for bp in bps)


def test_options_name_the_pattern(repo_root: Path):
    a = _a(repo_root)
    q = {"root": "cart", "returns": ["cart.items"]}
    opts = a.recommend_design_options(RMEAS, WMEAS, {"cart": 100}, {"cart": 10}, query=q)
    text = " ".join(o.get("pattern", "") for o in opts).lower()
    # relational and document realizations should be named as generic patterns
    assert "normalized" in text or "embedded" in text
    assert "mongodb" not in " ".join(str(o) for o in opts).lower()


# Recommendations are documented as deterministic/reproducible: with tied
# measured costs the tie-break must be a stable sort key (shape name), never
# hash-seed-dependent set order. Run under several PYTHONHASHSEED values and
# demand identical, pinned output.
_TIE_SCRIPT = """
import json
from tooling.optimize.analyze import recommend_model, recommend_design_options
read = {"q": {"document": 1.0, "relational": 1.0, "duality": 1.0}}
write = {"q": {"document": 1.0, "relational": 1.0, "duality": 1.0}}
pats = {"q": {"read_rate": 1, "write_rate": 1}}
r = recommend_model(pats, read, write)
opts = recommend_design_options(read, write, {"q": 1}, {"q": 1})
mixed = next(o for o in opts if o["design"].startswith("mixed"))
print(json.dumps({"chosen": r["chosen"]["model"],
                  "ranked": [d["model"] for d in r["ranked"]],
                  "mixed_q": mixed["assignment"]["q"]}))
"""


def test_tied_costs_break_deterministically_across_hash_seeds(repo_root: Path):
    results = []
    for seed in range(5):
        env = {**os.environ, "PYTHONHASHSEED": str(seed), "PYTHONPATH": str(repo_root)}
        out = subprocess.run([sys.executable, "-c", _TIE_SCRIPT], env=env,
                             cwd=repo_root, capture_output=True, text=True, check=True)
        results.append(json.loads(out.stdout))
    assert all(r == results[0] for r in results), results
    # ties break on the stable shape-name key, cheapest-then-lexicographic
    assert results[0]["chosen"] == "document"
    assert results[0]["ranked"] == ["document", "duality", "relational"]
    assert results[0]["mixed_q"] == "document"


def test_relational_win_discussion_leans_into_duality(repo_root: Path):
    # when a relational-family shape is chosen, the discussion should recommend a
    # duality view (keeps the document API) with the SQL-view fallback noted.
    a = _a(repo_root)
    rf, wf = {"cart": 10}, {"cart": 100}  # write-heavy -> relational family wins
    opts = a.recommend_design_options(RMEAS, WMEAS, rf, wf)
    top_text = " ".join(opts[0]["discussion"]).lower()
    assert "duality" in top_text
    assert "sql view" in top_text or "coalesce" in top_text
