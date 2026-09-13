#!/usr/bin/env python3
"""Compare the five runtime harness outputs; exit non-zero on any inconsistency."""
import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
from tooling.optimize.equivalence import canonical_hash

out_dir = sys.argv[1]
runtimes = ["python", "node", "dotnet", "java", "go"]
data = {rt: json.load(open(os.path.join(out_dir, f"{rt}.json"))) for rt in runtimes}
methods = list(data["python"].keys())

ok = True
for m in methods:
    hashes = {rt: canonical_hash(data[rt][m]) for rt in runtimes}
    consistent = len(set(hashes.values())) == 1
    ok &= consistent
    print(f"{m:22} rows={len(data['python'][m]):>4}  "
          f"{'CONSISTENT' if consistent else 'INCONSISTENT'}")
    if not consistent:
        for rt in runtimes:
            print(f"    {rt}: {hashes[rt][:12]}  first={data[rt][m][:1]}")
print("ALL CONSISTENT" if ok else "FAILED")
sys.exit(0 if ok else 1)
