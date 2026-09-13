# Copyright (c) 2026 Oracle and/or its affiliates.
"""The cost matrix fuels the model decision.

`decide_model` consumes the measured cost matrix — every access pattern a row
(reads AND writes, each with a rate), every candidate design a column — and
mechanically elects the design that minimizes the frequency-weighted total. A
design is viable only if it can serve *every* pattern (a document store with no
`GROUP BY` cell is simply excluded from a workload that aggregates). Writes are
first-class: their rows are what make denormalization expensive, so as the write
rate climbs the decision walks from the denormalized document toward the
write-cheap design — the measured consolidation knob, not a rule.
"""


def _viable_designs(patterns, cost):
    """Designs that have a cost cell for every pattern (can serve the whole workload)."""
    if not patterns:
        return []
    sets = [set(cost.get(p, {})) for p in patterns]
    return sorted(set.intersection(*sets)) if sets and all(sets) else []


def _total(patterns, cost, design, write_scale):
    return sum(patterns[p]["rate"] * (write_scale if patterns[p]["kind"] == "write" else 1)
               * cost[p][design] for p in patterns)


def decide_model(patterns, cost, write_scale=1.0, walk_scales=(0.1, 1, 3, 10, 30, 100)):
    """Elect the design from the cost matrix.

    Args:
      patterns: {name: {"kind": "read"|"write", "rate": r}} — reads and writes both.
      cost: {pattern: {design: cost}} — the measured matrix (same unit). A missing
        (pattern, design) cell means the design cannot serve that pattern.
      write_scale: multiply every write row's rate (model a heavier write mix).
      walk_scales: write-rate multipliers to sweep for the consolidation walk.

    Returns the chosen design, the ranked designs with totals, the read/write cost
    split per design, the patterns driving the pick, and the walk (how the choice
    moves as writes get heavier).
    """
    viable = _viable_designs(patterns, cost)
    # NO SILENT CAPS: a missing cell excludes the whole design — which quietly
    # turned a 4-design benchmark into a 3-design one (hotel capstone). Name
    # every excluded design and the pattern(s) that disqualified it.
    all_designs = {d for costs in cost.values() for d in costs}
    excluded = {d: sorted(p for p in patterns if d not in (cost.get(p) or {}))
                for d in sorted(all_designs - set(viable))}
    if not viable:
        return {"chosen": None, "ranked": [], "read_cost": {}, "write_cost": {},
                "drivers": [], "walk": [], "excluded": excluded,
                "notes": ["no single design serves every pattern; materialize more "
                          "than one shape or split the workload."]}

    totals = {d: _total(patterns, cost, d, write_scale) for d in viable}
    ranked = sorted(totals.items(), key=lambda kv: kv[1])
    chosen = ranked[0][0]

    def split(kind, design):
        return sum(patterns[p]["rate"] * (write_scale if kind == "write" else 1) * cost[p][design]
                   for p in patterns if patterns[p]["kind"] == kind)
    read_cost = {d: split("read", d) for d in viable}
    write_cost = {d: split("write", d) for d in viable}

    contrib = {p: patterns[p]["rate"] * (write_scale if patterns[p]["kind"] == "write" else 1)
               * cost[p][chosen] for p in patterns}
    drivers = [{"pattern": p, "kind": patterns[p]["kind"], "cost": c}
               for p, c in sorted(contrib.items(), key=lambda kv: -kv[1])]

    walk = []
    for s in walk_scales:
        v = _viable_designs(patterns, cost)
        if v:
            walk.append((s, min(v, key=lambda d: _total(patterns, cost, d, s))))

    notes = [f"chosen {chosen}: read cost {read_cost[chosen]:g}, write cost "
             f"{write_cost[chosen]:g} at write_scale={write_scale:g}. Writes are "
             f"first-class rows — heavier writes walk the choice toward the write-cheap "
             f"design (see walk)."]
    return {"chosen": chosen, "ranked": ranked, "read_cost": read_cost,
            "write_cost": write_cost, "drivers": drivers, "walk": walk,
            "excluded": excluded, "notes": notes}
