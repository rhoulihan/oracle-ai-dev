# Copyright (c) 2026 Oracle and/or its affiliates.
"""A re-runnable shape comparison for the iterative modeling loop.

The developer proposes or implements a model change — add an index, change a
projection, try the single-table variant, embed vs reference — and re-runs the
comparison to see the updated per-pattern winners and the converged union model.
Everything here is a pure function of the (possibly edited) ModelSpec plus the
measured costs, so re-running after a change is a single call.
"""
from tooling.generate.sql import generate_candidates
from tooling.optimize.analyze import recommend_model
from tooling.optimize.decide import decide_model


def compare(model, patterns, read_meas, write_meas):
    """Compare every candidate shape for a set of access patterns.

    Args:
      model: the (possibly just-edited) ModelSpec.
      patterns: {name: {"query": QuerySpec, "read_rate": r, "write_rate": w}}.
      read_meas / write_meas: {pattern: {shape: cost}} — the measured numbers
        (same unit for read and write; see recommend_model's note).

    Returns:
      {
        "per_pattern": {name: {available_shapes, measured_shapes, winner, costs}},
        "union": recommend_model(...) over the shapes measured for EVERY pattern,
        "notes": [...]
      }
    Re-run it after any model change to get the new ranking.
    """
    per_pattern = {}
    for name, p in patterns.items():
        try:
            available = sorted(generate_candidates(model, p["query"]).keys())
        except Exception:
            available = []
        rm = read_meas.get(name, {})
        wm = write_meas.get(name, {})
        rr, wr = p.get("read_rate", 0), p.get("write_rate", 0)
        shapes = set(rm) | set(wm)
        # A missing cell means the shape was never MEASURED for that component — not
        # that the component is free. A shape lacking a cell the pattern's rates
        # actually weight is incomparable: keep it out of the ranking, and say so.
        comparable = {s for s in shapes if (not rr or s in rm) and (not wr or s in wm)}
        costs = {s: rr * rm.get(s, 0) + wr * wm.get(s, 0) for s in comparable}
        winner = min(costs, key=costs.get) if costs else None
        per_pattern[name] = {
            "available_shapes": available,
            "measured_shapes": sorted(shapes),
            "unmeasured": sorted(shapes - comparable),
            "winner": winner,
            "costs": costs,
        }

    # Writes are access patterns too: split each pattern into first-class read and
    # write ROWS of the cost matrix, each with its own rate — so the write rows are
    # visible drivers, not a side input folded into the read.
    matrix_patterns, matrix_cost = {}, {}
    for name in patterns:
        rr = patterns[name].get("read_rate", 0)
        wr = patterns[name].get("write_rate", 0)
        if rr and read_meas.get(name):
            matrix_patterns[f"{name}#read"] = {"kind": "read", "rate": rr}
            matrix_cost[f"{name}#read"] = dict(read_meas[name])
        if wr and write_meas.get(name):
            matrix_patterns[f"{name}#write"] = {"kind": "write", "rate": wr}
            matrix_cost[f"{name}#write"] = dict(write_meas[name])

    rows = [{"pattern": p, "kind": matrix_patterns[p]["kind"],
             "rate": matrix_patterns[p]["rate"], "costs": matrix_cost[p]}
            for p in matrix_patterns]

    # The matrix fuels the decision.
    decision = decide_model(matrix_patterns, matrix_cost) if matrix_patterns else None

    notes = []
    union = None
    if patterns and all(read_meas.get(n) for n in patterns):
        common = set.intersection(*(set(read_meas[n]) for n in patterns))
        # Never price an unmeasured write at the shape's READ cost — that silently
        # hands a write-amplified shape a fabricated cheap write and flips the
        # recommendation. A shape whose write was never measured is incomparable
        # for any pattern that writes: drop it from the union and say so.
        dropped = set()
        for n in patterns:
            if patterns[n].get("write_rate", 0):
                measured_w = set(write_meas.get(n) or {})
                dropped |= common - measured_w
                common &= measured_w
        if dropped:
            notes.append("excluded from the union (write cost never measured, so the "
                         "shape is incomparable for a writing pattern): "
                         + ", ".join(sorted(dropped)))
        if common:
            pats = {n: {"read_rate": patterns[n].get("read_rate", 0),
                        "write_rate": patterns[n].get("write_rate", 0)} for n in patterns}
            rm = {n: {s: read_meas[n][s] for s in common} for n in patterns}
            # The 0 default only ever applies to a pattern with write_rate == 0 (a
            # placeholder recommend_model's schema demands, weighted by nothing) —
            # any writing pattern's shapes were just intersected with its
            # measured writes above.
            wm = {n: {s: (write_meas.get(n) or {}).get(s, 0) for s in common}
                  for n in patterns}
            union = recommend_model(pats, rm, wm)
        else:
            notes.append("no shape is measured for every pattern; showing per-pattern "
                        "winners only (a converged single model needs a common shape).")
    return {"per_pattern": per_pattern, "rows": rows, "decision": decision,
            "union": union, "notes": notes}
