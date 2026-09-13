# Copyright (c) 2026 Oracle and/or its affiliates.
"""Measured model-optimization analysis.

Pure functions over *measured* costs — the numbers come from the live benchmark
harness, never from here. Given per-(query, shape) median costs and access-pattern
frequencies, pick the per-query optimal shape and weigh cross-query tradeoffs to
find the break-points where a globally-different design wins.
"""


def optimal_shape_per_query(measurements: dict) -> dict:
    """{query: {shape: median_ms}} -> {query: {shape, ms, alternatives}}."""
    out = {}
    for query, by_shape in measurements.items():
        best = min(by_shape, key=by_shape.get)
        out[query] = {
            "shape": best,
            "ms": by_shape[best],
            "alternatives": {s: v for s, v in by_shape.items() if s != best},
        }
    return out


def optimal_shape_with_confidence(measurements: dict, rel_margin: float = 0.05) -> dict:
    """Like optimal_shape_per_query but unit-agnostic and confidence-aware (P11):
    when the winner beats the runner-up by less than `rel_margin` (default 5%), the
    call is flagged `too_close_to_call` so the recommendation reports low confidence
    instead of trusting a difference inside the measurement noise.
    """
    out = {}
    for q, by_shape in measurements.items():
        ordered = sorted(by_shape.items(), key=lambda kv: kv[1])
        best_shape, best = ordered[0]
        runner_shape, runner = (ordered[1] if len(ordered) > 1 else (None, None))
        gap = ((runner - best) / best) if (runner is not None and best) else None
        too_close = gap is not None and gap < rel_margin
        out[q] = {
            "shape": best_shape, "cost": best, "runner_up": runner_shape,
            "gap": gap, "too_close_to_call": too_close,
            "confidence": "low" if too_close else "high",
        }
    return out


def weighted_cost(assignment: dict, measurements: dict, frequencies: dict) -> float:
    """Total cost of a shape assignment: sum of freq[q] * measured_ms[q][shape]."""
    return float(sum(
        frequencies[q] * measurements[q][shape] for q, shape in assignment.items()
    ))


def weighted_cost_rw(assignment, read_meas, write_meas, read_freq, write_freq) -> float:
    """Total resource cost of a shape assignment across reads AND writes:
    sum over queries of read_freq*read_ms + write_freq*write_ms for the chosen shape.

    This is what makes write amplification decide the shape: a shape that is
    read-optimal (embedded document) can lose on a write-heavy path because each
    write rewrites the whole document.
    """
    total = 0.0
    for q, shape in assignment.items():
        total += read_freq.get(q, 0) * read_meas[q][shape]
        total += write_freq.get(q, 0) * write_meas[q][shape]
    return float(total)


def find_breakpoint(query, shape_a, shape_b, measurements, other_query, base_freq):
    """Frequency of `query` at which two GLOBAL uniform designs — all-`shape_a`
    vs all-`shape_b`, applied to both `query` and `other_query` — cost the same,
    with `other_query` fixed at `base_freq`.

    This is Rick's break-point: the common query's optimal shape wins globally
    once it is common enough; below the break-point the uncommon query's penalty
    against that shape makes the alternative design cheaper. Returns the crossover
    frequency, or None if the designs never cross at a positive frequency.
    """
    dq = measurements[query][shape_a] - measurements[query][shape_b]
    do = measurements[other_query][shape_b] - measurements[other_query][shape_a]
    if dq == 0:
        return None
    f = base_freq * do / dq
    return f if f > 0 else None


def _shape_character(query, read_meas, write_meas):
    """Describe each shape's read/write character for the discussion points."""
    notes = {}
    for q in read_meas:
        rbest = min(read_meas[q], key=read_meas[q].get)
        wbest = min(write_meas[q], key=write_meas[q].get)
        for shape in read_meas[q]:
            tag = []
            if shape == rbest:
                tag.append("fastest reads")
            if shape == wbest:
                tag.append("fastest writes")
            if shape == rbest and shape != wbest:
                tag.append("but writes amplify (whole-object rewrite)")
            notes[(q, shape)] = ", ".join(tag) or "middling on both"
    return notes


def _write_breakpoint(q, shape_a, shape_b, read_meas, write_meas, read_freq):
    """The write frequency at which shapes A and B tie for query q (read freq
    fixed), plus which shape wins ABOVE that frequency. As write frequency rises,
    the write-cheaper shape wins. Returns (w_star, winner_above) or None."""
    ra, wa = read_meas[q][shape_a], write_meas[q][shape_a]
    rb, wb = read_meas[q][shape_b], write_meas[q][shape_b]
    denom = wa - wb
    if denom == 0:
        return None
    w = read_freq.get(q, 0) * (rb - ra) / denom
    if w <= 0:
        return None
    winner_above = shape_a if wa < wb else shape_b  # lower write cost wins as writes rise
    return w, winner_above


def recommend_design_options(read_meas, write_meas, read_freq, write_freq, query=None, model=None) -> list:
    """A ranked range of design options — each with its total read+write cost, the
    frequency break-points where a neighbour overtakes it, discussion points, and
    (when `query` is given) the generic pattern name of the winning shape.

    Candidate designs: the per-query-optimal mixed design (by total read+write
    cost) plus each single uniform shape. Ranked cheapest first.
    """
    from tooling.optimize.patterns import pattern_name
    queries = list(read_meas)
    common = set.intersection(*(set(read_meas[q]) for q in queries)) if queries else set()

    # per-query-optimal (mixed) by total read+write unit cost
    mixed = {}
    for q in queries:
        # iterate shapes in sorted order so cost ties break on the shape name,
        # not hash-seed-dependent set order (recommendations are deterministic)
        mixed[q] = min(sorted(common), key=lambda s: read_freq.get(q, 0) * read_meas[q][s]
                       + write_freq.get(q, 0) * write_meas[q][s])

    designs = {"mixed (per-query optimal)": mixed}
    for s in sorted(common):
        designs[f"uniform {s}"] = {q: s for q in queries}

    scored = []
    for name, assign in designs.items():
        cost = weighted_cost_rw(assign, read_meas, write_meas, read_freq, write_freq)
        scored.append((name, assign, cost))
    scored.sort(key=lambda t: t[2])

    chars = _shape_character(queries[0] if queries else None, read_meas, write_meas) if queries else {}
    options = []
    for rank, (name, assign, cost) in enumerate(scored, start=1):
        discussion = []
        for q, shape in assign.items():
            note = f"{q}: {shape} — {chars.get((q, shape), '')}"
            if shape in ("relational", "sql_view", "duality"):
                note += (" — lean into a duality view here (document API over "
                         "write-efficient relational storage); fall back to a "
                         "JSON_OBJECT-wrapped SQL view when the projection needs "
                         "COALESCE/derived columns/aggregation duality can't express")
            discussion.append(note)
        breakpoints = []
        if rank < len(scored):
            nxt = scored[rank]  # the next-ranked design
            for q in queries:
                a_shape, b_shape = assign[q], nxt[1][q]
                if a_shape != b_shape:
                    bp = _write_breakpoint(q, a_shape, b_shape, read_meas, write_meas, read_freq)
                    if bp is not None:
                        w, winner_above = bp
                        loser_above = b_shape if winner_above == a_shape else a_shape
                        breakpoints.append(
                            f"{q}: designs tie at write frequency ≈ {w:g}; above it "
                            f"{winner_above} wins (writes dominate → the write-cheaper shape), "
                            f"below it {loser_above} wins (reads dominate)")
        opt = {
            "design": name, "assignment": assign, "cost": cost, "rank": rank,
            "breakpoints": breakpoints, "discussion": discussion,
        }
        if query is not None and assign:
            shape = assign[next(iter(assign))]
            opt["pattern"] = pattern_name(shape, query, model)
            opt["discussion"] = [f"pattern: {opt['pattern']}"] + discussion
        options.append(opt)
    return options


def _effective_freq(spec, key):
    """A pattern's rate normalized to a common time window: rate / interval.
    `interval` (default 1.0) lets patterns measured over different windows —
    1000/hour vs 10/day — be compared on one base."""
    interval = float(spec.get("interval", 1.0))
    if interval <= 0:
        raise ValueError(f"interval must be > 0, got {interval!r}")
    return float(spec.get(key, 0)) / interval


def recommend_model(patterns: dict, read_meas: dict, write_meas: dict,
                    washout_threshold: float = 0.05) -> dict:
    """Mechanically choose the single converged model that best serves the UNION
    of all access patterns, weighting each pattern's measured cost by its rate.

    Once every pattern's per-shape cost is measured, choosing the model is a
    deterministic optimization: for each candidate model, sum rate*cost across all
    patterns and take the minimum. Because the sum is rate-weighted, a high-
    frequency pattern dominates and a low-frequency one is *washed away* — so this
    also reports each pattern's cost contribution and, critically, flags any
    pattern whose per-op latency violates its budget under the chosen model even
    though its weighted cost is negligible.

    Args:
      patterns: {name: {"read_rate", "write_rate", "interval"?, "latency_budget_ms"?}}
        rates are ops per interval; interval (default 1) normalizes to a common window.
      read_meas / write_meas: {pattern: {shape: median_ms}} from the live harness.

    A converged model realizes the shared dataset as ONE shape, so candidate models
    are the shapes shared by every pattern. Raises ValueError if that set is empty.

    IMPORTANT — consistent units: read_meas and write_meas are summed together, so
    they must be in the SAME unit. The benchmark harness reports logical reads for
    reads but redo bytes for writes — those are NOT additively comparable. For a
    read+write mix comparison, feed both in a common unit (per-op elapsed µs, which
    the harness also reports); reserve logical-reads / redo-bytes for same-kind
    comparisons (read-vs-read, write-vs-write).
    """
    names = list(patterns)
    if not names:
        raise ValueError("no access patterns given")
    shared = set.intersection(*(set(read_meas[p]) & set(write_meas[p]) for p in names))
    if not shared:
        raise ValueError("no physical shape is available for every access pattern; "
                         "cannot converge on a single model")

    rfreq = {p: _effective_freq(patterns[p], "read_rate") for p in names}
    wfreq = {p: _effective_freq(patterns[p], "write_rate") for p in names}

    def model_cost(shape):
        return float(sum(rfreq[p] * read_meas[p][shape] + wfreq[p] * write_meas[p][shape]
                         for p in names))

    # tie-break on the model name so equal costs rank deterministically
    # regardless of set iteration order (hash seed)
    ranked = sorted(({"model": s, "cost": model_cost(s)} for s in shared),
                    key=lambda d: (d["cost"], d["model"]))
    for i, d in enumerate(ranked, start=1):
        d["rank"] = i
    chosen = ranked[0]
    cm = chosen["model"]
    total = chosen["cost"] or 1.0  # avoid /0 when every rate is 0

    contributions = {}
    for p in names:
        c = rfreq[p] * read_meas[p][cm] + wfreq[p] * write_meas[p][cm]
        frac = c / total
        contributions[p] = {"cost": c, "fraction": frac,
                            "washed_out": frac < washout_threshold}

    # per-op latency budget: checked against the raw measured cost, NOT weighted —
    # a rare pattern washed out of the sum can still blow its own SLA.
    latency_violations = []
    for p in names:
        budget = patterns[p].get("latency_budget_ms")
        if budget is None:
            continue
        # check every op kind the pattern actually performs — a fast read must
        # not mask a write path that blows the same budget
        for op, freq, meas in (("read", rfreq, read_meas), ("write", wfreq, write_meas)):
            if freq[p] <= 0:
                continue
            op_ms = meas[p][cm]
            if op_ms > budget:
                latency_violations.append({
                    "pattern": p, "shape": cm, "op": op, "measured_ms": op_ms, "budget_ms": budget,
                    "note": (f"{p} needs ≤{budget:g}ms but the chosen {cm} model serves its "
                             f"{op}s in {op_ms:g}ms — washed out of the weighted sum yet over "
                             f"budget; consider a secondary materialization (a summary MV, "
                             f"a duality view, or an index) for this pattern."),
                })

    # rate break-points: how far a washed-out pattern's rate must rise before the
    # runner-up model overtakes the chosen one (all else fixed).
    rate_breakpoints = []
    if len(ranked) > 1:
        alt = ranked[1]["model"]
        for p in names:
            for op, freq, meas in (("read_rate", rfreq, read_meas), ("write_rate", wfreq, write_meas)):
                dm = meas[p][cm] - meas[p][alt]
                if dm <= 0:
                    continue  # chosen already ≤ alt for this pattern/op; raising it can't flip
                base_cm = model_cost(cm) - freq[p] * meas[p][cm]
                base_alt = model_cost(alt) - freq[p] * meas[p][alt]
                r = (base_alt - base_cm) / dm  # freq at which cm and alt tie
                interval = float(patterns[p].get("interval", 1.0))
                if r > freq[p]:  # only report a flip that requires MORE than today's rate
                    rate_breakpoints.append({
                        "pattern": p, "vs_model": alt, op: r * interval,
                        "note": (f"if {p}'s {op.replace('_', ' ')} rises past ≈{r * interval:g} "
                                 f"(now {freq[p] * interval:g}), the {alt} model overtakes {cm}."),
                    })

    notes = [
        f"Chosen model: {cm} (weighted cost {total:g}). "
        f"The rate-weighted sum favours the highest-frequency pattern(s); "
        f"low-frequency patterns are washed out — see contributions."
    ]
    if latency_violations:
        notes.append(f"{len(latency_violations)} pattern(s) violate their latency budget "
                     f"under {cm} despite being washed out — see latency_violations.")

    return {
        "chosen": chosen,
        "ranked": ranked,
        "contributions": contributions,
        "latency_violations": latency_violations,
        "rate_breakpoints": rate_breakpoints,
        "notes": notes,
    }


def recommend_global_design(measurements: dict, frequencies: dict) -> dict:
    """Compare the per-query-optimal (mixed) design against the best single
    uniform-shape design, weighted by frequency, and report the savings.
    """
    per_query = optimal_shape_per_query(measurements)
    mixed_assignment = {q: per_query[q]["shape"] for q in measurements}
    mixed_cost = weighted_cost(mixed_assignment, measurements, frequencies)

    # Shapes available for a uniform design must exist for every query.
    common_shapes = set.intersection(*(set(by_shape) for by_shape in measurements.values()))
    uniform_costs = {
        shape: weighted_cost({q: shape for q in measurements}, measurements, frequencies)
        for shape in common_shapes
    }
    best_uniform_shape = min(uniform_costs, key=uniform_costs.get)
    uniform_cost = uniform_costs[best_uniform_shape]
    savings = uniform_cost - mixed_cost

    notes = []
    if savings > 0:
        notes.append(
            f"Mixed design saves {savings:g} weighted-ms vs the best uniform shape "
            f"({best_uniform_shape}); use the per-query optimal shapes."
        )
    else:
        notes.append(
            f"A uniform {best_uniform_shape} design is as cheap as the mixed design "
            f"at these frequencies — prefer it for simplicity."
        )

    return {
        "per_query_optimal": per_query,
        "mixed_design_cost": mixed_cost,
        "uniform_design_cost": uniform_cost,
        "best_uniform_shape": best_uniform_shape,
        "uniform_costs": uniform_costs,
        "savings": savings,
        "notes": notes,
    }
