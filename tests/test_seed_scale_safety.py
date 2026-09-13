# Copyright (c) 2026 Oracle and/or its affiliates.
"""The airline seed must survive the documented x10 production scale-up.

LPAD truncates: at width 4, flight 20000 collides with flight 2000, the PK
violation kills the flights insert, and the cascade zeroes out every leg —
exactly what happened on the 2026-07-14 production-volume run. The flight-number
pad must be wide enough for ten times the checked-in pool, and the producer
(flight_schedules) and consumer (legs) must agree on it.
"""
import re
from pathlib import Path

SEED = Path(__file__).parent / "integration" / "airline" / "airline-seed.sql"


def test_flight_number_pad_survives_x10_scale():
    text = SEED.read_text()
    flights_n = int(re.search(r"DEFINE flights_n = (\d+)", text).group(1))
    widths = [int(w) for w in re.findall(r"'FL' \|\| LPAD\(.+?, (\d+), '0'\)", text)]
    assert len(widths) >= 2, "expected LPAD flight-number expressions in producer and consumer"
    assert len(set(widths)) == 1, f"producer/consumer pad widths disagree: {widths}"
    need = len(str(flights_n * 10))
    assert widths[0] >= need, (
        f"flight-number pad width {widths[0]} cannot express {flights_n * 10} "
        f"(needs {need}) — LPAD truncation causes PK collisions at scaled volume")
