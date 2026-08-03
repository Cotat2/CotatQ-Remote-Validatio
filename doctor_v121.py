
"""
CotatQ v1.2.1 strict compatibility doctor.

The strong-rival benchmark MUST NOT start unless all required adapters pass a
small same-query numerical test.

This is intentionally stricter than v1.2.
"""

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

ERROR_TOL = 1e-10


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
        str(HERE / "external_worker_v121.py"),
        "--engine", engine,
        "--family", "random_matching_complex",
        "--n", "12",
        "--depth", "2",
        "--seed", "101",
        "--profile", "random_to_random",
        "--repeats", "3",
        "--peak-limit", str(1 << 24),
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

    first = p.stdout.readline().strip()

    if first != "READY":
        p.kill()
        out, err = p.communicate()
        return {
            "ok": False,
            "error": f"worker did not READY: {first}; {err[-700:]}",
        }

    p.stdin.write("GO\n")
    p.stdin.flush()

    try:
        out, err = p.communicate(timeout=25)
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        return {
            "ok": False,
            "timeout": True,
            "error": "doctor timeout",
        }

    for line in reversed([x for x in out.splitlines() if x.strip()]):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            pass

    return {
        "ok": False,
        "error": f"no JSON; stderr={err[-700:]}",
    }


status = {
    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    "patch": "v1.2.1",
    "packages": {},
    "engines": {},
}

print("=" * 112)
print("CotatQ v1.2.1 — STRICT COMPATIBILITY DOCTOR")
print("Strong-rival benchmark will be blocked if ANY required adapter fails.")
print("=" * 112)

package_fail = False

for label, module_name in PACKAGES.items():
    try:
        importlib.import_module(module_name)
        status["packages"][label] = {
            "available": True,
            "version": version(module_name),
        }
        print(f"{label:<18} OK  {status['packages'][label]['version']}")
    except Exception as exc:
        package_fail = True
        status["packages"][label] = {
            "available": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
        print(f"{label:<18} MISSING  {exc}")

print()
print("Same-query adapter checks:")

amps = {}
engine_fail = False

for engine in REQUIRED_ENGINES:
    r = run_engine(engine)
    status["engines"][engine] = r

    if r.get("ok"):
        amp = complex(r["amp_real"], r["amp_imag"])
        amps[engine] = amp
        print(
            f"{engine:<24} OK  "
            f"one={r['isolated_one_shot_seconds']*1000:9.3f} ms "
            f"warm={r['warm_seconds']*1000:8.3f} ms"
        )
    else:
        engine_fail = True
        print(
            f"{engine:<24} FAIL  "
            f"{r.get('error','unknown error')[:220]}"
        )

accuracy_fail = False

if "cotatq" in amps:
    ref = amps["cotatq"]

    print()
    print("Numerical agreement vs CotatQ:")

    for engine in REQUIRED_ENGINES:
        if engine == "cotatq" or engine not in amps:
            continue

        err = abs(amps[engine] - ref)
        status["engines"][engine]["doctor_abs_error_vs_cotatq"] = err

        good = err <= ERROR_TOL
        if not good:
            accuracy_fail = True

        print(
            f"{engine:<24} |Δamp|={err:.3e} "
            f"{'OK' if good else 'FAIL'}"
        )
else:
    accuracy_fail = True

# Explicit adapter invariants.
for engine in ("cotengra-rg128", "quimb-auto-hq"):
    r = status["engines"].get(engine, {})
    if not r.get("ok"):
        continue

    if engine == "cotengra-rg128" and not r.get("cotengra_direct_api"):
        engine_fail = True
        print("cotengra-rg128 adapter invariant FAIL: direct API marker missing")

    if engine == "quimb-auto-hq":
        if r.get("quimb_parallel") is not False:
            engine_fail = True
            print("quimb adapter invariant FAIL: parallel=False not recorded")
        if r.get("quimb_nested_process_pool") is not False:
            engine_fail = True
            print("quimb adapter invariant FAIL: nested pool not disabled")

status["passed"] = not (package_fail or engine_fail or accuracy_fail)

out = HERE / "doctor_v121_latest.json"
out.write_text(json.dumps(status, indent=2), encoding="utf-8")

print()
print("Saved:", out)
print("=" * 112)

if status["passed"]:
    print("STRICT DOCTOR: PASS")
    print("All required rival adapters are ready. Strong-rival benchmark may run.")
    raise SystemExit(0)

print("STRICT DOCTOR: FAIL")
print("DO NOT RUN the strong-rival benchmark until this doctor passes.")
raise SystemExit(1)
