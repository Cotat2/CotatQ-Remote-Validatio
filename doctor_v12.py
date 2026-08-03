
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

ENGINE_CHECKS = [
    "cotatq",
    "opt-greedy",
    "opt-rg128",
    "cotengra-rg128",
    "cotengra-hyper2s",
    "quimb-auto-hq",
    "aer-mps",
]


def version(modname):
    try:
        from importlib.metadata import version as pkg_version
        mapping = {
            "qiskit_aer": "qiskit-aer",
        }
        return pkg_version(mapping.get(modname, modname))
    except Exception:
        return None


def run_engine(engine):
    cmd = [
        sys.executable,
        str(HERE / "external_worker_v12.py"),
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
            "error": f"worker did not READY: {first}; {err[-500:]}",
        }

    p.stdin.write("GO\n")
    p.stdin.flush()

    try:
        out, err = p.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        return {"ok": False, "timeout": True}

    for line in reversed([x for x in out.splitlines() if x.strip()]):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            pass

    return {"ok": False, "error": err[-500:]}


status = {
    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    "python": sys.version,
    "packages": {},
    "engines": {},
}

print("=" * 104)
print("CotatQ v1.2 — External Validation Doctor")
print("=" * 104)

for label, module_name in PACKAGES.items():
    try:
        importlib.import_module(module_name)
        status["packages"][label] = {
            "available": True,
            "version": version(module_name),
        }
        print(f"{label:<18} OK  {status['packages'][label]['version']}")
    except Exception as exc:
        status["packages"][label] = {
            "available": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
        print(f"{label:<18} MISSING  {exc}")

print()
print("Tiny same-query engine checks:")

amps = {}
for engine in ENGINE_CHECKS:
    r = run_engine(engine)
    status["engines"][engine] = r

    if r.get("ok"):
        amp = complex(r["amp_real"], r["amp_imag"])
        amps[engine] = amp
        print(
            f"{engine:<24} OK  "
            f"one-shot={r['isolated_one_shot_seconds']*1000:8.3f} ms "
            f"warm={r['warm_seconds']*1000:8.3f} ms"
        )
    elif r.get("unavailable"):
        print(f"{engine:<24} UNAVAILABLE  {r.get('error','')}")
    elif r.get("timeout"):
        print(f"{engine:<24} TIMEOUT")
    else:
        print(f"{engine:<24} ERROR  {r.get('error','')[:180]}")

if "cotatq" in amps:
    ref = amps["cotatq"]
    for engine, amp in amps.items():
        if engine != "cotatq":
            status["engines"][engine]["doctor_abs_error_vs_cotatq"] = abs(amp - ref)

out = HERE / "doctor_v12_latest.json"
out.write_text(json.dumps(status, indent=2), encoding="utf-8")

print()
print("Saved:", out)
print("=" * 104)
print("Doctor completed. Missing optional rivals are recorded, not hidden.")
