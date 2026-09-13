# Copyright (c) 2026 Oracle and/or its affiliates.
"""The union optimizer: pick the single converged model that best serves ALL
access patterns weighted by their rates, and expose the washing-away effect."""
from tooling.optimize.analyze import recommend_model


# A hot read pattern that loves `document`, a rare write pattern that loves
# `relational`. Costs are measured medians (ms); shapes shared across patterns.
READ = {
    "get_order_page": {"document": 1.0, "relational": 5.0},
    "nightly_reprice": {"document": 8.0, "relational": 2.0},
}
WRITE = {
    "get_order_page": {"document": 3.0, "relational": 3.0},
    "nightly_reprice": {"document": 20.0, "relational": 2.0},
}


def _patterns(hot_rate=1000, cold_rate=1):
    return {
        "get_order_page": {"read_rate": hot_rate, "write_rate": 0},
        "nightly_reprice": {"read_rate": 0, "write_rate": cold_rate},
    }


def test_picks_union_optimum_favouring_the_hot_pattern():
    r = recommend_model(_patterns(), READ, WRITE)
    assert r["chosen"]["model"] == "document"
    assert r["chosen"]["rank"] == 1
    # ranked list covers every shape shared by all patterns
    assert {m["model"] for m in r["ranked"]} == {"document", "relational"}


def test_reports_per_pattern_contribution_and_washout():
    r = recommend_model(_patterns(hot_rate=1000, cold_rate=1), READ, WRITE)
    c = r["contributions"]
    # the hot pattern dominates the weighted cost; the rare one is washed away
    assert c["get_order_page"]["fraction"] > 0.9
    assert c["nightly_reprice"]["fraction"] < 0.05
    assert c["nightly_reprice"]["washed_out"] is True
    assert c["get_order_page"]["washed_out"] is False


def test_flags_latency_budget_violation_even_when_washed_out():
    pats = _patterns()
    # the rare reprice also does a point read with a tight 3ms budget; the chosen
    # document model reads it in 8ms -> a violation the weighted sum would hide.
    pats["nightly_reprice"]["read_rate"] = 1
    pats["nightly_reprice"]["latency_budget_ms"] = 3.0
    r = recommend_model(pats, READ, WRITE)
    viol = r["latency_violations"]
    assert any(v["pattern"] == "nightly_reprice" and v["budget_ms"] == 3.0
               and v["measured_ms"] == 8.0 for v in viol)


def test_flags_write_latency_budget_violation_when_reads_are_fast():
    # A pattern that reads AND writes must have BOTH per-op costs checked
    # against its budget: fast 1ms reads must not mask 50ms writes over a
    # 3ms SLA on the write path it runs 1000x.
    pats = {"p": {"read_rate": 1, "write_rate": 1000, "latency_budget_ms": 3.0}}
    read = {"p": {"document": 1.0}}
    write = {"p": {"document": 50.0}}
    r = recommend_model(pats, read, write)
    assert any(v["pattern"] == "p" and v["measured_ms"] == 50.0 and v["budget_ms"] == 3.0
               for v in r["latency_violations"])


def test_rate_breakpoint_where_the_rare_pattern_flips_the_choice():
    r = recommend_model(_patterns(hot_rate=1000, cold_rate=1), READ, WRITE)
    bps = {b["pattern"]: b for b in r["rate_breakpoints"]}
    assert "nightly_reprice" in bps
    # a positive, finite write-rate at which relational overtakes document
    assert bps["nightly_reprice"]["write_rate"] > 1


def test_interval_normalizes_rates_to_a_common_window():
    # same raw count (100) but different windows: A over 1s, B over 100s.
    # A's effective frequency is 100x B's, so A dominates the choice.
    read = {"a": {"document": 1.0, "relational": 5.0},
            "b": {"document": 9.0, "relational": 2.0}}
    write = {"a": {"document": 1.0, "relational": 1.0},
             "b": {"document": 1.0, "relational": 1.0}}
    pats = {
        "a": {"read_rate": 100, "write_rate": 0, "interval": 1.0},
        "b": {"read_rate": 100, "write_rate": 0, "interval": 100.0},
    }
    r = recommend_model(pats, read, write)
    assert r["chosen"]["model"] == "document"


def test_no_shared_shape_raises():
    read = {"a": {"document": 1.0}, "b": {"relational": 1.0}}
    write = {"a": {"document": 1.0}, "b": {"relational": 1.0}}
    pats = {"a": {"read_rate": 1, "write_rate": 0},
            "b": {"read_rate": 1, "write_rate": 0}}
    try:
        recommend_model(pats, read, write)
        assert False, "expected ValueError for no shared shape"
    except ValueError:
        pass
