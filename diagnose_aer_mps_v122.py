
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOL = 1e-10

CASES = [
    ("random_matching_complex", 12, 2, 101, "random_to_random"),
    ("small_world_complex", 12, 2, 202, "checker_to_random"),
    ("hub_spoke_complex", 12, 2, 303, "random_to_random"),
    ("dense_longrange_complex", 12, 2, 404, "random_to_random"),
    ("grid2d_complex", 16, 4, 505, "checker_to_random"),
]

VARIANTS = [
    "aer-statevector",
    "aer-mps-direct-capped",
    "aer-mps-direct-uncapped",
    "aer-mps",
    "aer-mps-fullsv",
]


def run(engine, case):
    family, n, depth, seed, profile = case

    cmd = [
        sys.executable,
        str(HERE / "external_worker_v122.py"),
        "--engine", engine,
        "--family", family,
        "--n", str(n),
        "--depth", str(depth),
        "--seed", str(seed),
        "--profile", profile,
        "--repeats", "3",
        "--peak-limit", str(1 << 24),
        "--bond", "128",
    ]

    p = subprocess.Popen(
        cmd,
        cwd=HERE,
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )

    ready = p.stdout.readline().strip()
    if ready != "READY":
        p.kill()
        out, err = p.communicate()
        return {"ok": False, "engine": engine, "error": f"no READY: {ready}; {err[-500:]}"}

    p.stdin.write("GO\n")
    p.stdin.flush()

    try:
        out, err = p.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        return {"ok": False, "engine": engine, "timeout": True}

    for line in reversed([x for x in out.splitlines() if x.strip()]):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            pass

    return {"ok": False, "engine": engine, "error": err[-700:]}


results = []
native_fail = False
fullsv_fail = False

print("=" * 126)
print("CotatQ v1.2.2 — AER MPS ROUTE DIAGNOSTIC")
print("Reference = Aer Statevector. Each MPS variant runs in its own fresh process.")
print("=" * 126)

for case in CASES:
    family, n, depth, seed, profile = case
    print()
    print(f"{family} n={n} d={depth} seed={seed} profile={profile}")

    case_results = {engine: run(engine, case) for engine in VARIANTS}

    ref_row = case_results["aer-statevector"]
    if not ref_row.get("ok"):
        print("  STATEVECTOR REFERENCE FAILED:", ref_row.get("error"))
        native_fail = True
        fullsv_fail = True
        continue

    ref = complex(ref_row["amp_real"], ref_row["amp_imag"])

    for engine in VARIANTS:
        r = case_results[engine]
        item = {
            "case": {
                "family": family,
                "n": n,
                "depth": depth,
                "seed": seed,
                "profile": profile,
            },
            "engine": engine,
            "result": r,
        }

        if r.get("ok"):
            amp = complex(r["amp_real"], r["amp_imag"])
            err = abs(amp - ref)
            item["absolute_error_vs_statevector"] = err

            print(
                f"  {engine:<26} "
                f"|Δ|={err:.3e} "
                f"one={r['isolated_one_shot_seconds']*1000:9.3f}ms "
                f"{'OK' if err <= TOL else 'FAIL'}"
            )

            if engine == "aer-mps" and err > TOL:
                native_fail = True
            if engine == "aer-mps-fullsv" and err > TOL:
                fullsv_fail = True

        else:
            print(f"  {engine:<26} ERROR {r.get('error','')[:180]}")
            if engine == "aer-mps":
                native_fail = True
            if engine == "aer-mps-fullsv":
                fullsv_fail = True

        results.append(item)

summary = {
    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    "tolerance": TOL,
    "native_mps_manual_pass": not native_fail,
    "mps_full_statevector_pass": not fullsv_fail,
    "results": results,
}

out = HERE / "aer_mps_diagnostic_v122_latest.json"
out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

print()
print("=" * 126)
print("Native MPS + manual single-amplitude:", "PASS" if not native_fail else "FAIL")
print("MPS -> full statevector cross-check: ", "PASS" if not fullsv_fail else "FAIL")
print("Saved:", out)

if native_fail or fullsv_fail:
    print("AER MPS DIAGNOSTIC: FAIL")
    raise SystemExit(1)

print("AER MPS DIAGNOSTIC: PASS")
