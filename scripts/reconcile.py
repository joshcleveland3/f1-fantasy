#!/usr/bin/env python3
"""Compare automated scoring with the owner's manual sheet (rounds 1-12)."""
import json, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
snap = json.load(open(ROOT / "tests" / "sheet_snapshot.json"))
data = json.load(open(ROOT / "docs" / "data.json"))
by = {d["key"]: d for d in data["drivers"]}
bad = ok = 0
for key, vals in snap["drivers"].items():
    for rnd, exp in zip(snap["rounds"], vals):
        if exp is None:
            continue
        got = by.get(key, {}).get("by_round", {}).get(str(rnd))
        if got is not None and abs(got - exp) < 1e-9:
            ok += 1
        else:
            bad += 1
            print(f"MISMATCH {key} round {rnd}: sheet={exp} automated={got}")
print(f"Reconciliation: {ok} matches, {bad} mismatches out of {ok + bad} driver-weekends")
