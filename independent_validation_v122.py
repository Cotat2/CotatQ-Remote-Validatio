
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import queue
import random
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
import psutil

from cotatq_v09 import IncrementalGraphEngine, PreparedIncremental
from cotatq_v11 import (
    CircuitTensorNetworkV11,
    ExactEngineV11,
    cotat_basis_index,
    make_audit_circuit,
    query_profile,
)
from protocol_v12 import (
    ADVANCED_TN_ENGINES,
    ALL_RIVALS,
    ERROR_TOL,
    PEAK_LIMIT,
    PROTOCOL_VERSION,
    SECONDARY_QUANTUM_ENGINES,
    TIMEOUTS,
    VERDICT_THRESHOLDS,
    reproduction_suite,
    strong_rival_suite,
)

HERE = Path(__file__).resolve().parent

parser = argparse.ArgumentParser()
parser.add_argument("--suite", choices=["reproduction", "strong"], required=True)
parser.add_argument("--mode", choices=["standard", "full"], default="standard")
parser.add_argument("--runner-label", default="unlabeled")
parser.add_argument("--import-timeout", type=float, default=45.0)
args = parser.parse_args()

if args.suite == "reproduction":
    CASES, REPEATS = reproduction_suite(args.mode)
    ENGINES = ["cotatq", "opt-greedy"]
else:
    CASES, REPEATS = strong_rival_suite(args.mode)
    ENGINES = ["cotatq", *ALL_RIVALS]


def pkg_version(name):
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:
        return None


def anonymous_environment():
    # Deliberately excludes hostname, username, serial numbers and IP addresses.
    cpu = platform.processor() or platform.machine()
    raw_sig = "|".join([
        platform.system(),
        platform.release(),
        platform.machine(),
        cpu,
        str(psutil.cpu_count(logical=False)),
        str(psutil.cpu_count(logical=True)),
        str(round(psutil.virtual_memory().total / (1024**3))),
    ])
    sig = hashlib.sha256(raw_sig.encode()).hexdigest()[:16]

    return {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "protocol_version": PROTOCOL_VERSION,
        "compatibility_patch": "v1.2.2-exact-aer-mps",
        "runner_label": args.runner_label,
        "environment_signature": sig,
        "privacy_note": "No hostname/username/serial/IP collected.",
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": cpu,
        "cpu_physical": psutil.cpu_count(logical=False),
        "cpu_logical": psutil.cpu_count(logical=True),
        "ram_gib": psutil.virtual_memory().total / (1024**3),
        "python": sys.version,
        "numpy": pkg_version("numpy"),
        "opt_einsum": pkg_version("opt_einsum"),
        "cotengra": pkg_version("cotengra"),
        "quimb": pkg_version("quimb"),
        "qiskit": pkg_version("qiskit"),
        "qiskit_aer": pkg_version("qiskit-aer"),
        "suite": args.suite,
        "mode": args.mode,
        "case_count": len(CASES),
        "repeats": REPEATS,
    }


def readline_timeout(stream, timeout):
    q = queue.Queue(maxsize=1)

    def reader():
        try:
            q.put(stream.readline())
        except Exception as exc:
            q.put(exc)

    threading.Thread(target=reader, daemon=True).start()

    try:
        item = q.get(timeout=timeout)
    except queue.Empty:
        return None

    if isinstance(item, Exception):
        raise item
    return item


def parse_last_json(text):
    for line in reversed([x for x in text.splitlines() if x.strip()]):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            pass
    return None


def run_fresh(engine, case):
    cmd = [
        sys.executable,
        str(HERE / "external_worker_v122.py"),
        "--engine", engine,
        "--family", case["family"],
        "--n", str(case["n"]),
        "--depth", str(case["depth"]),
        "--seed", str(case["seed"]),
        "--profile", case["profile"],
        "--repeats", str(REPEATS),
        "--peak-limit", str(PEAK_LIMIT),
        "--bond", "128",
    ]

    outer0 = time.perf_counter()
    p = subprocess.Popen(
        cmd,
        cwd=HERE,
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )

    ready = readline_timeout(p.stdout, args.import_timeout)
    if ready is None or ready.strip() != "READY":
        try:
            p.kill()
        except Exception:
            pass
        out, err = p.communicate()
        return {
            "ok": False,
            "engine": engine,
            "error": f"worker failed READY: {ready!r}; {err[-700:]}",
            "outer_process_wall_seconds": time.perf_counter() - outer0,
        }

    p.stdin.write("GO\n")
    p.stdin.flush()

    budget = TIMEOUTS[engine]
    go0 = time.perf_counter()

    try:
        out, err = p.communicate(timeout=budget)
    except subprocess.TimeoutExpired:
        try:
            p.kill()
        except Exception:
            pass
        out, err = p.communicate()
        return {
            "ok": False,
            "engine": engine,
            "timeout": True,
            "error": f"TIMEOUT >{budget:.1f}s AFTER READY/GO",
            "benchmark_wall_seconds_after_go": time.perf_counter() - go0,
            "outer_process_wall_seconds": time.perf_counter() - outer0,
        }

    data = parse_last_json(out)
    if data is None:
        data = {
            "ok": False,
            "engine": engine,
            "error": f"no JSON; stdout={out[-500:]}; stderr={err[-700:]}",
        }

    data.update({
        "benchmark_wall_seconds_after_go": time.perf_counter() - go0,
        "outer_process_wall_seconds": time.perf_counter() - outer0,
        "returncode": p.returncode,
    })
    if err.strip():
        data["stderr_tail"] = err[-1000:]
    return data


def exact_validation():
    tests = [
        ("random_matching_complex", 12, 2, 101, "zero_to_zero"),
        ("small_world_complex", 12, 2, 202, "random_to_random"),
        ("hub_spoke_complex", 12, 2, 303, "checker_to_random"),
        ("dense_longrange_complex", 12, 2, 404, "random_to_random"),
        ("local_brickwork_complex", 12, 4, 505, "checker_to_random"),
        ("grid2d_complex", 16, 4, 606, "random_to_random"),
    ]

    engine = IncrementalGraphEngine(max_peak_rank=24)
    exact_engine = ExactEngineV11()
    out = []

    for family, n, depth, seed, profile in tests:
        c = make_audit_circuit(family, n, depth, seed)
        ib, ob = query_profile(profile, n, seed)
        nodes = CircuitTensorNetworkV11(c, ib, ob).build()
        plan = engine.planner.plan(nodes)
        result = engine.execute(PreparedIncremental(nodes=nodes, plan=plan))
        exact = exact_engine.run(c, ib)
        exact_amp = complex(exact[cotat_basis_index(ob)])
        out.append({
            "family": family,
            "n": n,
            "profile": profile,
            "absolute_error": abs(result.amplitude - exact_amp),
            "amp_imag": result.amplitude.imag,
        })

    return out


def geomean(values):
    vals = [
        float(x) for x in values
        if x is not None and float(x) > 0 and math.isfinite(float(x))
    ]
    if not vals:
        return None
    return math.exp(sum(math.log(x) for x in vals) / len(vals))


def bootstrap_ci(values, samples=5000, seed=12026):
    vals = np.asarray(
        [float(x) for x in values if x is not None and float(x) > 0],
        dtype=float,
    )
    if len(vals) < 2:
        return None, None

    logs = np.log(vals)
    rng = np.random.default_rng(seed)
    boots = np.empty(samples)

    for i in range(samples):
        boots[i] = math.exp(float(np.mean(rng.choice(logs, size=len(logs), replace=True))))

    return float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


def outcome(speedup):
    if speedup is None:
        return "UNSCORABLE"
    if speedup > 1.05:
        return "WIN"
    if speedup >= 0.95:
        return "TIE"
    return "LOSS"


environment = anonymous_environment()
exact_checks = exact_validation()

outdir = HERE / f"results_v122_{args.suite}_{args.mode}"
outdir.mkdir(exist_ok=True)

print()
print("=" * 150)
print("COTATQ v1.2.2 — EXACT AER MPS VALIDATION")
print(
    f"suite={args.suite} | mode={args.mode} | cases={len(CASES)} | repeats={REPEATS} "
    f"| runner={args.runner_label}"
)
print("Frozen CotatQ subject | locked cases | fresh process per engine")
if args.suite == "strong":
    print("Strong score = CotatQ vs BEST finished numerically-valid rival")
print("=" * 150)
print()

print("Exact mini-validation:")
for e in exact_checks:
    print(
        f"  {e['family']:<28} n={e['n']:<2} "
        f"error={e['absolute_error']:.3e} imag={e['amp_imag']:.3e}"
    )
print()

rows = []
case_rows = []
engine_globally_unavailable = set()

for idx, case in enumerate(CASES, 1):
    case_id = (
        f"{case['family']}|n{case['n']}|d{case['depth']}|"
        f"s{case['seed']}|p{case['profile']}"
    )

    # Randomized deterministic engine launch order. Every engine still gets
    # its own process, so order can only expose machine drift.
    rng = random.Random(int(hashlib.sha256(case_id.encode()).hexdigest()[:16], 16))
    engines = list(ENGINES)

    # Aer statevector is not useful/safe above 20q.
    if "aer-statevector" in engines and case["n"] > 20:
        engines.remove("aer-statevector")

    # Aer Auto/MPS are sampled on >40 only for zero-output queries.
    if case["n"] > 40 and case["profile"] != "zero_to_zero":
        for e in ("aer-mps", "aer-auto"):
            if e in engines:
                engines.remove(e)

    rng.shuffle(engines)

    print(
        f"[{idx:>3}/{len(CASES)}] {case['family']:<28} "
        f"n={case['n']:<3} d={case['depth']:<2} s={case['seed']:<3} "
        f"profile={case['profile']:<18}"
    )

    results = {}

    for launch_index, engine in enumerate(engines):
        if engine in engine_globally_unavailable:
            r = {
                "ok": False,
                "unavailable": True,
                "engine": engine,
                "error": "engine unavailable from earlier dependency/API check",
            }
        else:
            r = run_fresh(engine, case)

        if r.get("unavailable"):
            engine_globally_unavailable.add(engine)

        r.update({
            "case_id": case_id,
            "case_index": idx,
            "target": case["target"],
            "launch_index": launch_index,
        })
        rows.append(r)
        results[engine] = r

        if r.get("ok"):
            print(
                f"    {engine:<24} one={r['isolated_one_shot_seconds']*1000:9.3f}ms "
                f"warm={r['warm_seconds']*1000:9.3f}ms"
            )
        elif r.get("unavailable"):
            print(f"    {engine:<24} UNAVAILABLE {r.get('error','')[:140]}")
        elif r.get("timeout"):
            print(f"    {engine:<24} TIMEOUT")
        elif r.get("skip"):
            print(f"    {engine:<24} SKIP {r.get('error','')[:140]}")
        else:
            print(f"    {engine:<24} ERROR {r.get('error','')[:140]}")

    cot = results.get("cotatq", {})
    cot_amp = (
        complex(float(cot["amp_real"]), float(cot["amp_imag"]))
        if cot.get("ok") else None
    )

    rival_validity = {}
    valid_rivals = []

    for engine, r in results.items():
        if engine == "cotatq" or not r.get("ok") or cot_amp is None:
            continue

        amp = complex(float(r["amp_real"]), float(r["amp_imag"]))
        err = abs(amp - cot_amp)
        is_valid = err <= ERROR_TOL

        rival_validity[engine] = {
            "error_vs_cotatq": err,
            "numerically_valid": is_valid,
        }

        if is_valid:
            valid_rivals.append(r)

    opt = results.get("opt-greedy", {})
    opt_err = None
    if opt.get("ok") and cot_amp is not None:
        opt_amp = complex(float(opt["amp_real"]), float(opt["amp_imag"]))
        opt_err = abs(opt_amp - cot_amp)

    if cot.get("ok") and opt.get("ok") and opt_err is not None and opt_err <= ERROR_TOL:
        opt_cold = float(opt["isolated_one_shot_seconds"]) / float(cot["isolated_one_shot_seconds"])
        opt_warm = float(opt["warm_seconds"]) / float(cot["warm_seconds"])
    else:
        opt_cold = opt_warm = None

    if cot.get("ok") and valid_rivals:
        best_cold = min(valid_rivals, key=lambda r: float(r["isolated_one_shot_seconds"]))
        best_warm = min(valid_rivals, key=lambda r: float(r["warm_seconds"]))

        best_cold_speedup = (
            float(best_cold["isolated_one_shot_seconds"])
            / float(cot["isolated_one_shot_seconds"])
        )
        best_warm_speedup = (
            float(best_warm["warm_seconds"])
            / float(cot["warm_seconds"])
        )
    else:
        best_cold = best_warm = None
        best_cold_speedup = best_warm_speedup = None

    advanced_valid = [
        e for e in ADVANCED_TN_ENGINES
        if e in results
        and results[e].get("ok")
        and rival_validity.get(e, {}).get("numerically_valid")
    ]

    case_row = {
        **case,
        "case_id": case_id,
        "cotatq_ok": bool(cot.get("ok")),
        "cotatq_one_shot": cot.get("isolated_one_shot_seconds"),
        "cotatq_warm": cot.get("warm_seconds"),
        "cotatq_amp_real": cot.get("amp_real"),
        "cotatq_amp_imag": cot.get("amp_imag"),
        "opt_greedy_cold_speedup": opt_cold,
        "opt_greedy_warm_speedup": opt_warm,
        "best_valid_cold_rival": best_cold.get("engine") if best_cold else None,
        "best_valid_warm_rival": best_warm.get("engine") if best_warm else None,
        "best_valid_cold_speedup": best_cold_speedup,
        "best_valid_warm_speedup": best_warm_speedup,
        "best_valid_cold_outcome": outcome(best_cold_speedup),
        "best_valid_warm_outcome": outcome(best_warm_speedup),
        "advanced_valid_engines": advanced_valid,
        "advanced_valid_count": len(advanced_valid),
        "rival_validity": rival_validity,
        "valid_rival_count": len(valid_rivals),
    }
    case_rows.append(case_row)

    if args.suite == "strong" and best_cold:
        print(
            f"    BEST VALID: cold={best_cold_speedup:.2f}x vs {best_cold['engine']} "
            f"| warm={best_warm_speedup:.2f}x vs {best_warm['engine']} "
            f"| {case_row['best_valid_cold_outcome']}/{case_row['best_valid_warm_outcome']}"
        )
    elif opt_cold is not None:
        print(
            f"    REPLICATION: Opt/Cot cold={opt_cold:.2f}x warm={opt_warm:.2f}x"
        )
    print()


def summarize_speedups(case_rows, cold_key, warm_key):
    scorable = [
        r for r in case_rows
        if r.get(cold_key) is not None and r.get(warm_key) is not None
    ]

    cold = [r[cold_key] for r in scorable]
    warm = [r[warm_key] for r in scorable]

    cold_out = [outcome(v) for v in cold]
    warm_out = [outcome(v) for v in warm]
    lo, hi = bootstrap_ci(cold)

    return {
        "cases": len(case_rows),
        "scorable": len(scorable),
        "cold_wins": cold_out.count("WIN"),
        "cold_ties": cold_out.count("TIE"),
        "cold_losses": cold_out.count("LOSS"),
        "cold_win_rate": cold_out.count("WIN") / len(scorable) if scorable else None,
        "cold_geomean": geomean(cold),
        "cold_ci95_low": lo,
        "cold_ci95_high": hi,
        "warm_wins": warm_out.count("WIN"),
        "warm_ties": warm_out.count("TIE"),
        "warm_losses": warm_out.count("LOSS"),
        "warm_win_rate": warm_out.count("WIN") / len(scorable) if scorable else None,
        "warm_geomean": geomean(warm),
    }


replication_summary = summarize_speedups(
    case_rows,
    "opt_greedy_cold_speedup",
    "opt_greedy_warm_speedup",
)

strong_summary = summarize_speedups(
    case_rows,
    "best_valid_cold_speedup",
    "best_valid_warm_speedup",
)

exact_failures = [x for x in exact_checks if x["absolute_error"] > ERROR_TOL]

# Rival accuracy failures are visible but a bad rival is not allowed to become
# "best valid". We separately count any CotatQ-vs-opt-greedy disagreement.
opt_accuracy_failures = []
for r in case_rows:
    v = r.get("rival_validity", {}).get("opt-greedy")
    if v and not v["numerically_valid"]:
        opt_accuracy_failures.append((r["case_id"], v["error_vs_cotatq"]))

advanced_types_available = sorted({
    e for e in ADVANCED_TN_ENGINES
    if any(
        e in row.get("advanced_valid_engines", [])
        for row in case_rows
    )
})

advanced_case_coverage = (
    sum(r["advanced_valid_count"] > 0 for r in case_rows) / len(case_rows)
    if case_rows else 0.0
)

if args.suite == "reproduction":
    verdict = "REPRODUCTION COMPLETE"
    if exact_failures or opt_accuracy_failures:
        verdict = "REPRODUCTION ACCURACY FAILURE"

else:
    T = VERDICT_THRESHOLDS

    if exact_failures or opt_accuracy_failures:
        verdict = "VALIDATION ACCURACY FAILURE"

    elif (
        len(advanced_types_available) < T["advanced_engine_types_available_min"]
        or advanced_case_coverage < T["advanced_case_coverage_min"]
    ):
        verdict = "INSUFFICIENT ADVANCED RIVAL COVERAGE"

    elif (
        strong_summary["cold_win_rate"] is not None
        and strong_summary["cold_win_rate"] >= T["cold_win_rate_min"]
        and strong_summary["cold_geomean"] is not None
        and strong_summary["cold_geomean"] >= T["cold_geomean_min"]
        and strong_summary["cold_ci95_low"] is not None
        and strong_summary["cold_ci95_low"] > T["cold_ci95_low_min"]
        and strong_summary["warm_win_rate"] is not None
        and strong_summary["warm_win_rate"] >= T["warm_win_rate_min"]
        and strong_summary["warm_geomean"] is not None
        and strong_summary["warm_geomean"] > T["warm_geomean_min"]
    ):
        verdict = "STRONG-RIVAL VALIDATION SURVIVED"

    elif (
        strong_summary["cold_geomean"] is not None
        and strong_summary["cold_geomean"] > 1.0
    ):
        verdict = "SPECIALIZED / MIXED SIGNAL"

    else:
        verdict = "STRONG-RIVAL VALIDATION DID NOT CONFIRM"


engine_coverage = {}
for e in ENGINES:
    erows = [r for r in rows if r.get("engine") == e or (
        e == "cotatq" and r.get("engine") == "cotatq-frozen-v1.0"
    )]
    engine_coverage[e] = {
        "attempt_rows": len(erows),
        "ok": sum(bool(r.get("ok")) for r in erows),
        "timeouts": sum(bool(r.get("timeout")) for r in erows),
        "unavailable": sum(bool(r.get("unavailable")) for r in erows),
        "skips": sum(bool(r.get("skip")) for r in erows),
        "errors": sum(
            not r.get("ok")
            and not r.get("timeout")
            and not r.get("unavailable")
            and not r.get("skip")
            for r in erows
        ),
    }

stamp = time.strftime("%Y%m%d_%H%M%S")

raw_path = outdir / f"raw_v122_{args.suite}_{args.mode}_{stamp}.json"
case_csv = outdir / f"cases_v122_{args.suite}_{args.mode}_{stamp}.csv"
rows_csv = outdir / f"rows_v122_{args.suite}_{args.mode}_{stamp}.csv"
report_path = outdir / f"REPORT_v122_{args.suite}_{args.mode}_{stamp}.md"
env_path = outdir / f"environment_v122_{stamp}.json"

payload = {
    "protocol_version": PROTOCOL_VERSION,
    "environment": environment,
    "suite": args.suite,
    "mode": args.mode,
    "verdict": verdict,
    "verdict_thresholds": VERDICT_THRESHOLDS,
    "exact_checks": exact_checks,
    "replication_summary": replication_summary,
    "strong_summary": strong_summary,
    "advanced_types_available": advanced_types_available,
    "advanced_case_coverage": advanced_case_coverage,
    "engine_coverage": engine_coverage,
    "exact_failures": exact_failures,
    "opt_accuracy_failures": opt_accuracy_failures,
    "cases": case_rows,
    "rows": rows,
}

raw_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
env_path.write_text(json.dumps(environment, indent=2, ensure_ascii=False), encoding="utf-8")

def flatten_case(r):
    out = dict(r)
    out["advanced_valid_engines"] = json.dumps(out.get("advanced_valid_engines", []))
    out["rival_validity"] = json.dumps(out.get("rival_validity", {}), ensure_ascii=False)
    return out

if case_rows:
    flat = [flatten_case(r) for r in case_rows]
    fields = sorted({k for r in flat for k in r})
    with case_csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(flat)

if rows:
    fields = sorted({k for r in rows for k in r})
    with rows_csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

def fx(v):
    return "N/A" if v is None else f"{v:.2f}x"

def pct(v):
    return "N/A" if v is None else f"{100*v:.1f}%"

R = replication_summary
S = strong_summary

report = [
    "# CotatQ v1.2.2 — Exact Aer MPS Validation Report",
    "",
    f"**Verdict: {verdict}**",
    "",
    "## Scope",
    "",
    "This benchmark evaluates exact classical single-amplitude tensor-network queries.",
    "It is not a physical quantum computer and does not establish general quantum advantage.",
    "",
    "## Environment",
    "",
]
for k, v in environment.items():
    report.append(f"- **{k}:** {v}")

report.extend([
    "",
    "## Replication vs opt_einsum greedy",
    "",
    f"- Cases/scorable: {R['cases']}/{R['scorable']}",
    f"- Cold W/T/L: {R['cold_wins']}/{R['cold_ties']}/{R['cold_losses']}",
    f"- Cold geo: {fx(R['cold_geomean'])}",
    f"- Cold 95% CI: {fx(R['cold_ci95_low'])} — {fx(R['cold_ci95_high'])}",
    f"- Warm W/T/L: {R['warm_wins']}/{R['warm_ties']}/{R['warm_losses']}",
    f"- Warm geo: {fx(R['warm_geomean'])}",
])

if args.suite == "strong":
    report.extend([
        "",
        "## Strong-rival score",
        "",
        "Each case is scored against the fastest finished rival whose amplitude agrees within tolerance.",
        "",
        f"- Cases/scorable: {S['cases']}/{S['scorable']}",
        f"- Cold W/T/L: {S['cold_wins']}/{S['cold_ties']}/{S['cold_losses']}",
        f"- Cold win rate: {pct(S['cold_win_rate'])}",
        f"- Cold geo vs best valid rival: {fx(S['cold_geomean'])}",
        f"- Cold 95% CI: {fx(S['cold_ci95_low'])} — {fx(S['cold_ci95_high'])}",
        f"- Warm W/T/L: {S['warm_wins']}/{S['warm_ties']}/{S['warm_losses']}",
        f"- Warm win rate: {pct(S['warm_win_rate'])}",
        f"- Warm geo vs best valid rival: {fx(S['warm_geomean'])}",
        f"- Advanced rival types available: {', '.join(advanced_types_available) or 'NONE'}",
        f"- Advanced-rival case coverage: {pct(advanced_case_coverage)}",
    ])

report.extend([
    "",
    "## Engine coverage",
    "",
    "| Engine | OK | Timeout | Missing | Skip | Error |",
    "|---|---:|---:|---:|---:|---:|",
])
for e, c in engine_coverage.items():
    report.append(
        f"| {e} | {c['ok']} | {c['timeouts']} | {c['unavailable']} | "
        f"{c['skips']} | {c['errors']} |"
    )

report.extend([
    "",
    "## Accuracy",
    "",
    f"- Exact mini-validation failures: {len(exact_failures)}",
    f"- CotatQ vs opt_einsum greedy disagreements: {len(opt_accuracy_failures)}",
    f"- Tolerance: {ERROR_TOL:.1e}",
    "",
    "## Locked verdict thresholds",
    "",
    "Thresholds were written into PROTOCOL_LOCK.json before running v1.2.",
])

for k, v in VERDICT_THRESHOLDS.items():
    report.append(f"- **{k}:** {v}")

report_path.write_text("\n".join(report), encoding="utf-8")

print()
print("=" * 150)
print("VERDICT:", verdict)
print("Environment signature:", environment["environment_signature"])
print()
print("REPLICATION vs opt_einsum greedy")
print(
    f"Cold W/T/L {R['cold_wins']}/{R['cold_ties']}/{R['cold_losses']} "
    f"| geo={fx(R['cold_geomean'])} "
    f"| CI={fx(R['cold_ci95_low'])}-{fx(R['cold_ci95_high'])}"
)
print(
    f"Warm W/T/L {R['warm_wins']}/{R['warm_ties']}/{R['warm_losses']} "
    f"| geo={fx(R['warm_geomean'])}"
)

if args.suite == "strong":
    print()
    print("BEST VALID RIVAL SCORE")
    print(
        f"Cold W/T/L {S['cold_wins']}/{S['cold_ties']}/{S['cold_losses']} "
        f"| geo={fx(S['cold_geomean'])} "
        f"| CI={fx(S['cold_ci95_low'])}-{fx(S['cold_ci95_high'])}"
    )
    print(
        f"Warm W/T/L {S['warm_wins']}/{S['warm_ties']}/{S['warm_losses']} "
        f"| geo={fx(S['warm_geomean'])}"
    )
    print("Advanced rivals:", advanced_types_available)
    print("Advanced case coverage:", pct(advanced_case_coverage))

print("=" * 150)
print("Report:", report_path)
print("Raw   :", raw_path)
print("Cases :", case_csv)
print("Rows  :", rows_csv)
