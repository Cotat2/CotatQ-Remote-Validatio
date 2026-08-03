
import importlib
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

PACKAGES = {
    "numpy": "numpy",
    "psutil": "psutil",
    "opt_einsum": "opt_einsum",
    "qiskit": "qiskit",
    "qiskit_aer": "qiskit_aer",
    "cotengra": "cotengra",
    "quimb": "quimb",
}

REQUIRED_ENGINES = [
    "cotatq",
    "opt-greedy",
    "opt-rg128",
    "cotengra-rg128",
    "cotengra-hyper2s",
    "quimb-auto-hq",
    "aer-mps",
    "aer-auto",
    "aer-statevector",
]

TOL = 1e-10


def version(modname):
    try:
        from importlib.metadata import version as pkg_version
        mapping = {"qiskit_aer": "qiskit-aer"}
        return pkg_version(mapping.get(modname, modname))
    except Exception:
        return None


def run_engine(engine):
    cmd = [
        sys.executable,
        str(HERE / "external_worker_v122.py"),
        "--engine", engine,
        "--family", "random_matching_complex",
        "--n", "12",
        "--depth", "2",
        "--seed", "101",
        "--profile", "random_to_random",
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
        return {"ok": False, "engine": engine, "error": f"worker did not READY: {ready}; {err[-700:]}"}

    p.stdin.write("GO\n")
    p.stdin.flush()

    try:
        out, err = p.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        return {"ok": False, "engine": engine, "timeout": True, "error": "doctor timeout"}

    for line in reversed([x for x in out.splitlines() if x.strip()]):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            pass

    return {"ok": False, "engine": engine, "error": f"no JSON; {err[-700:]}"}


status = {
    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    "patch": "v1.2.2-exact-aer-mps",
    "packages": {},
    "engines": {},
}

print("=" * 118)
print("CotatQ v1.2.2 — STRICT COMPATIBILITY DOCTOR")
print("Aer MPS is now exact/no-bond-cap and queried through the native MPS representation.")
print("=" * 118)

package_fail = False

for label, module_name in PACKAGES.items():
    try:
        importlib.import_module(module_name)
        status["packages"][label] = {"available": True, "version": version(module_name)}
        print(f"{label:<18} OK  {status['packages'][label]['version']}")
    except Exception as exc:
        package_fail = True
        status["packages"][label] = {"available": False, "error": f"{type(exc).__name__}: {exc}"}
        print(f"{label:<18} MISSING  {exc}")

print()
print("Same-query adapter checks:")

amps = {}
engine_fail = False

for engine in REQUIRED_ENGINES:
    r = run_engine(engine)
    status["engines"][engine] = r

    if r.get("ok"):
        amps[engine] = complex(r["amp_real"], r["amp_imag"])
        route = ""
        if engine == "aer-mps":
            route = f" route={r.get('mps_query_route')} bond={r.get('mps_bond_cap')}"
        print(
            f"{engine:<24} OK  "
            f"one={r['isolated_one_shot_seconds']*1000:9.3f} ms "
            f"warm={r['warm_seconds']*1000:8.3f} ms{route}"
        )
    else:
        engine_fail = True
        print(f"{engine:<24} FAIL  {r.get('error','unknown')[:220]}")

accuracy_fail = False

if "cotatq" not in amps:
    accuracy_fail = True
else:
    ref = amps["cotatq"]

    print()
    print("Numerical agreement vs CotatQ:")

    for engine in REQUIRED_ENGINES:
        if engine == "cotatq" or engine not in amps:
            continue

        err = abs(amps[engine] - ref)
        status["engines"][engine]["doctor_abs_error_vs_cotatq"] = err
        good = err <= TOL

        if not good:
            accuracy_fail = True

        print(f"{engine:<24} |Δamp|={err:.3e} {'OK' if good else 'FAIL'}")

# Adapter invariants.
mps = status["engines"].get("aer-mps", {})
if mps.get("ok"):
    if mps.get("mps_bond_cap") is not None:
        engine_fail = True
        print("AER MPS INVARIANT FAIL: scored MPS still has a bond cap")
    if mps.get("mps_query_route") != "save_matrix_product_state+manual_single_amplitude":
        engine_fail = True
        print("AER MPS INVARIANT FAIL: wrong query route")
    if float(mps.get("mps_truncation_threshold", -1)) != 0.0:
        engine_fail = True
        print("AER MPS INVARIANT FAIL: truncation threshold is not 0")

status["passed_basic"] = not (package_fail or engine_fail or accuracy_fail)

out = HERE / "doctor_v122_latest.json"
out.write_text(json.dumps(status, indent=2), encoding="utf-8")

print()
print("Saved:", out)
print("=" * 118)

if not status["passed_basic"]:
    print("STRICT DOCTOR: FAIL")
    raise SystemExit(1)

print("Basic strict doctor: PASS")
print()
print("Running multi-topology Aer MPS route diagnostic...")

diag = subprocess.run(
    [sys.executable, str(HERE / "diagnose_aer_mps_v122.py")],
    cwd=HERE,
)

if diag.returncode != 0:
    print("STRICT DOCTOR: FAIL — Aer MPS route diagnostic failed.")
    raise SystemExit(1)

print()
print("STRICT DOCTOR: PASS")
print("All adapters are correct. Strong-rival STANDARD may now run.")
