
import json
import math
import sys
from pathlib import Path

if len(sys.argv) != 3:
    print("Usage:")
    print("  python compare_two_runs_v12.py run_A_raw.json run_B_raw.json")
    raise SystemExit(2)

A = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
B = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))

def map_cases(data):
    return {r["case_id"]: r for r in data.get("cases", [])}

a = map_cases(A)
b = map_cases(B)
common = sorted(set(a) & set(b))

cold_a = []
cold_b = []
warm_a = []
warm_b = []

for cid in common:
    ra, rb = a[cid], b[cid]
    ca = ra.get("best_valid_cold_speedup")
    cb = rb.get("best_valid_cold_speedup")
    wa = ra.get("best_valid_warm_speedup")
    wb = rb.get("best_valid_warm_speedup")
    if all(x is not None and x > 0 for x in (ca, cb, wa, wb)):
        cold_a.append(ca)
        cold_b.append(cb)
        warm_a.append(wa)
        warm_b.append(wb)

def gm(xs):
    return math.exp(sum(math.log(x) for x in xs) / len(xs)) if xs else None

def corr(xs, ys):
    if len(xs) < 2:
        return None
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    num = sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    dx = sum((x-mx)**2 for x in xs)
    dy = sum((y-my)**2 for y in ys)
    if dx == 0 or dy == 0:
        return None
    return num / (dx*dy)**0.5

print("=" * 90)
print("CotatQ v1.2 cross-machine comparison")
print("=" * 90)
print("A environment:", A.get("environment", {}).get("environment_signature"))
print("B environment:", B.get("environment", {}).get("environment_signature"))
print("Common fully-scorable strong cases:", len(cold_a))
print("A cold geo:", gm(cold_a))
print("B cold geo:", gm(cold_b))
print("Cold speedup correlation:", corr(cold_a, cold_b))
print("A warm geo:", gm(warm_a))
print("B warm geo:", gm(warm_b))
print("Warm speedup correlation:", corr(warm_a, warm_b))
print()
if A.get("environment", {}).get("environment_signature") == B.get("environment", {}).get("environment_signature"):
    print("WARNING: environment signatures match. This is replication, not evidence from a distinct environment.")
else:
    print("Environment signatures differ. This supports cross-environment reproduction,")
    print("but does not by itself prove the runs were performed by independent people.")
