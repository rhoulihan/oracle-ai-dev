# Copyright (c) 2026 Oracle and/or its affiliates.
"""The optimizer report's Phase-1 contract additions (spec §4, decided 2026-07-31).

(a) The Exadata transferability disclosure: every election states which side
of the access-path split its winning margin sits on. Verified basis (research
R0c, 3-0): Smart Scan offload applies ONLY to direct-path full-segment scans —
buffer-cache point reads never offload — so a point-read-decided verdict
carries to Exadata-class deployments, while a scan-decided one is
environment-conditional. (b) The mechanized deciding-pattern row-count check
(operating principle: benchmark at production cardinality or call the verdict
provisional): a deciding pattern that answered fewer rows than the workload
declared it should is flagged !! PROVISIONAL, by mechanism.
"""

from tooling.optimize.runner import build_result, format_report

MODEL = {
    "entities": {"Order": {"table": "orders", "pk": "order_id",
                           "columns": {"total": "total", "status": "status"}}},
    "relationships": [],
    "projections": {"document": {"Order": {"collection": "order_docs"}}},
}

PATTERNS = [
    {"name": "point_read", "kind": "read", "rate": 100.0,
     "query": {"root": "Order", "returns": ["Order.total"],
               "predicates": [{"ref": "Order.order_id", "op": "=", "value": 1}]}},
    {"name": "scan_report", "kind": "read", "rate": 1.0,
     "query": {"root": "Order", "group_by": ["Order.status"],
               "aggregates": [{"name": "t", "fn": "SUM", "ref": "Order.total"}]}},
]

MEAS = {"point_read": {"relational": 10.0, "document": 50.0},
        "scan_report": {"relational": 100.0, "document": 500.0}}


def _detail(point_access, scan_access, point_rows=1, scan_rows=8):
    return {"point_read": {"relational": {"cv": 0.01, "access": point_access,
                                          "rows": point_rows}},
            "scan_report": {"relational": {"cv": 0.01, "access": scan_access,
                                           "rows": scan_rows}}}


# ------------------------------------------------- decided-by disclosure

def test_point_read_decided_election_carries_to_exadata():
    res = build_result(MODEL, PATTERNS, MEAS,
                       detail=_detail("IDX UNIQUE", "IDX RANGE"))
    assert res["decided_by"]["label"] == "point", res["decided_by"]
    report = format_report(res)
    assert "decided by: point reads" in report, report
    assert "carries to Exadata" in report, report


def test_scan_decided_election_is_environment_conditional():
    # the rate-weighted contribution sits on the point read; flip the rates so
    # the scan pattern dominates the chosen design's cost
    pats = [dict(PATTERNS[0], rate=1.0), dict(PATTERNS[1], rate=100.0)]
    res = build_result(MODEL, pats, MEAS,
                       detail=_detail("IDX UNIQUE", "FULL SCAN"))
    assert res["decided_by"]["label"] == "scan", res["decided_by"]
    report = format_report(res)
    assert "decided by: scan economics" in report, report
    assert "environment-conditional" in report, report


def test_the_classifier_never_calls_a_full_scan_a_point_read():
    # the planted defect: a drivers/detail fixture whose every deciding cell
    # is a FULL SCAN must never classify as point — if this passes wrongly,
    # the disclosure would promise production transfer for scan-decided
    # verdicts, which is exactly the claim R0c refuted.
    res = build_result(MODEL, PATTERNS, MEAS,
                       detail=_detail("FULL SCAN", "FULL SCAN"))
    assert res["decided_by"]["label"] == "scan", res["decided_by"]


def test_no_access_data_means_no_disclosure_not_a_wrong_one():
    res = build_result(MODEL, PATTERNS, MEAS,
                       detail=_detail(None, None))
    assert res.get("decided_by") is None
    assert "decided by:" not in format_report(res)


# ---------------------------------------------- provisional (cardinality)

def test_deciding_pattern_under_expected_rows_flags_provisional():
    pats = [dict(PATTERNS[0], expect_rows=1), dict(PATTERNS[1], expect_rows=1000)]
    res = build_result(MODEL, pats, MEAS,
                       detail=_detail("IDX UNIQUE", "IDX RANGE", scan_rows=3))
    assert res["provisional"], res
    hit = res["provisional"][0]
    assert hit["pattern"] == "scan_report" and hit["rows"] == 3
    report = format_report(res)
    assert "!! PROVISIONAL" in report, report
    assert "scan_report" in report and "production cardinality" in report


def test_magnitude_met_raises_no_flag():
    pats = [dict(PATTERNS[0], expect_rows=1), dict(PATTERNS[1], expect_rows=5)]
    res = build_result(MODEL, pats, MEAS,
                       detail=_detail("IDX UNIQUE", "IDX RANGE", scan_rows=8))
    assert not res.get("provisional")
    assert "!! PROVISIONAL" not in format_report(res)


def test_no_expectation_declared_means_no_flag():
    res = build_result(MODEL, PATTERNS, MEAS,
                       detail=_detail("IDX UNIQUE", "IDX RANGE"))
    assert not res.get("provisional")
