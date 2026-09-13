# Copyright (c) 2026 Oracle and/or its affiliates.
"""Size a synthetic sample for the measured optimizer.

When the optimizer runs against a large or external system (via a wallet), you do
not benchmark the whole production dataset — you generate a *representative but
bounded* sample. This picks a root-row count that is big enough to separate the
shapes (multi-block scans, real index depth) yet fits a storage cap (the 12 GB
Free user-data limit, or whatever headroom the target system allows).
"""

FREE_DATA_CAP_BYTES = 12 * 1024 * 1024 * 1024  # Oracle AI Database 26ai Free cap

# Below this many root rows the data lives in too few blocks for logical-read
# counts to reliably separate shapes — the measurement risks being noise.
_MIN_REPRESENTATIVE_ROOT_ROWS = 1_000

# Rough multiplier for secondary structures (indexes, the duality/document JSON
# overhead beyond raw column bytes) on top of the raw row bytes.
_OVERHEAD_FACTOR = 1.3


def _est_bytes(root_rows, avg_row_bytes, fanout, shapes):
    total_rows = root_rows * (1 + fanout)
    return int(total_rows * avg_row_bytes * shapes * _OVERHEAD_FACTOR)


def recommend_sample_size(root_rows, avg_row_bytes, fanout,
                          storage_cap_bytes=FREE_DATA_CAP_BYTES, shapes=3):
    """Recommend how many root rows to generate for the benchmark sample.

    Args:
      root_rows: how many root (aggregate) rows you'd like.
      avg_row_bytes: estimated average bytes per row (root or child).
      fanout: average child rows per root row.
      storage_cap_bytes: the storage ceiling to stay under (default: Free's 12 GB).
      shapes: how many physical shapes hold the same logical content (relational +
        duality + document = 3), each consuming storage.

    Returns a dict: root_rows (possibly reduced), total_rows, est_bytes, capped,
    and notes (warnings about cap-scaling or too-small samples).
    """
    if root_rows <= 0 or avg_row_bytes <= 0 or fanout < 0:
        raise ValueError("root_rows/avg_row_bytes must be > 0 and fanout >= 0")

    notes = []
    capped = False
    est = _est_bytes(root_rows, avg_row_bytes, fanout, shapes)
    if est > storage_cap_bytes:
        # Scale the root count down proportionally to fit, with a little headroom.
        per_root = est / root_rows
        fit = int((storage_cap_bytes * 0.95) // per_root)
        root_rows = max(fit, 1)
        est = _est_bytes(root_rows, avg_row_bytes, fanout, shapes)
        capped = True
        notes.append(
            f"Requested sample exceeds the {storage_cap_bytes / (1024**3):.1f} GB cap "
            f"across {shapes} shapes; scaled down to {root_rows:,} root rows "
            f"(~{est / (1024**2):.0f} MB).")

    if root_rows < _MIN_REPRESENTATIVE_ROOT_ROWS:
        notes.append(
            f"{root_rows:,} root rows is small — the data may fit in too few blocks "
            f"for logical-read counts to separate shapes representatively; prefer "
            f"≥ {_MIN_REPRESENTATIVE_ROOT_ROWS:,} where the cap allows.")

    return {
        "root_rows": root_rows,
        "total_rows": root_rows * (1 + fanout),
        "est_bytes": est,
        "capped": capped,
        "notes": notes,
    }
