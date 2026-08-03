
from __future__ import annotations

import argparse
import gc
import json
import math
import os
import statistics
import sys
import time

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")

parser = argparse.ArgumentParser()
parser.add_argument("--engine", required=True)
parser.add_argument("--family", required=True)
parser.add_argument("--n", type=int, required=True)
parser.add_argument("--depth", type=int, required=True)
parser.add_argument("--seed", type=int, required=True)
parser.add_argument("--profile", required=True)
parser.add_argument("--repeats", type=int, default=7)
parser.add_argument("--peak-limit", type=int, default=1 << 24)
parser.add_argument("--bond", type=int, default=128)
args = parser.parse_args()

import numpy as np
import opt_einsum as oe

from cotatq_v09 import IncrementalGraphEngine, PreparedIncremental
from cotatq_v11 import (
    CircuitTensorNetworkV11,
    make_audit_circuit,
    query_profile,
    qiskit_basis_index,
)

# Optional imports happen BEFORE READY so package import time is not benchmarked.
OPTIONAL = {}
IMPORT_ERROR = None

try:
    if args.engine.startswith("cotengra-"):
        import cotengra as ctg
        OPTIONAL["cotengra"] = ctg

    elif args.engine.startswith("quimb-"):
        import quimb
        import quimb.tensor as qtn
        OPTIONAL["quimb"] = quimb
        OPTIONAL["qtn"] = qtn

    elif args.engine.startswith("aer-"):
        from qiskit import QuantumCircuit, transpile
        from qiskit_aer import AerSimulator
        OPTIONAL["QuantumCircuit"] = QuantumCircuit
        OPTIONAL["transpile"] = transpile
        OPTIONAL["AerSimulator"] = AerSimulator

except Exception as exc:
    IMPORT_ERROR = f"{type(exc).__name__}: {exc}"


def neutral_numpy_warmup():
    a = np.asarray([[1 + 0j, 2 + 0j], [3 + 0j, 4 + 0j]], dtype=np.complex128)
    b = np.asarray([[0.5 + 0j, 0.25j], [1 - 0.5j, 2 + 0j]], dtype=np.complex128)
    _ = np.tensordot(a, b, axes=([1], [0]))
    _ = a @ b
    gc.collect()


def repeated_warm(fn, repeats, first_hint):
    one = max(float(first_hint), 1e-7)
    loops = max(1, min(128, int(math.ceil(0.030 / one))))
    samples = []
    last = None
    old_gc = gc.isenabled()
    gc.disable()
    try:
        for _ in range(repeats):
            t0 = time.perf_counter()
            for _ in range(loops):
                last = fn()
            samples.append((time.perf_counter() - t0) / loops)
    finally:
        if old_gc:
            gc.enable()
    return statistics.median(samples), last, loops


def build_case():
    circuit = make_audit_circuit(args.family, args.n, args.depth, args.seed)
    input_bits, output_bits = query_profile(args.profile, args.n, args.seed)
    nodes = CircuitTensorNetworkV11(circuit, input_bits, output_bits).build()
    return circuit, input_bits, output_bits, nodes


def build_opt_inputs(nodes):
    operands = []
    shape_operands = []
    arrays = []
    for node in nodes:
        operands.extend([node.data, list(node.labels)])
        shape_operands.extend([node.data.shape, list(node.labels)])
        arrays.append(node.data)
    operands.append([])
    shape_operands.append([])
    return operands, shape_operands, arrays


def normalize_scalar(value):
    if hasattr(value, "data") and not isinstance(value, np.ndarray):
        try:
            value = value.data
        except Exception:
            pass
    return complex(np.asarray(value).reshape(()))


def finish_precompiled(label, conversion, planning, compile_s, expr, arrays,
                       peak_elements=None, extra=None):
    t0 = time.perf_counter()
    first = expr(*arrays)
    first_kernel = time.perf_counter() - t0

    warm, last, loops = repeated_warm(
        lambda: expr(*arrays),
        args.repeats,
        first_kernel,
    )
    value = last if last is not None else first
    amp = normalize_scalar(value)

    setup = conversion + planning + compile_s
    out = {
        "ok": True,
        "engine": label,
        "conversion_seconds": conversion,
        "planning_seconds": planning,
        "compile_seconds": compile_s,
        "setup_seconds": setup,
        "first_kernel_seconds": first_kernel,
        "isolated_one_shot_seconds": setup + first_kernel,
        "warm_seconds": warm,
        "inner_loops": loops,
        "peak_elements_est": peak_elements,
        "amp_real": amp.real,
        "amp_imag": amp.imag,
    }
    if extra:
        out.update(extra)
    return out


def bench_cotatq():
    gc.collect()
    t0 = time.perf_counter()
    _, _, _, nodes = build_case()
    conversion = time.perf_counter() - t0

    engine = IncrementalGraphEngine(max_peak_rank=63)

    t0 = time.perf_counter()
    plan = engine.planner.plan(nodes)
    planning = time.perf_counter() - t0

    if plan.estimated_peak_elements > args.peak_limit:
        return {
            "ok": False,
            "skip": True,
            "engine": "cotatq-frozen-v1.0",
            "error": f"peak {plan.estimated_peak_elements} > limit {args.peak_limit}",
            "peak_elements_est": plan.estimated_peak_elements,
        }

    prepared = PreparedIncremental(nodes=nodes, plan=plan)

    t0 = time.perf_counter()
    first = engine.execute(prepared)
    first_kernel = time.perf_counter() - t0

    warm, last, loops = repeated_warm(
        lambda: engine.execute(prepared),
        args.repeats,
        first_kernel,
    )
    result = last if last is not None else first

    setup = conversion + planning
    return {
        "ok": True,
        "engine": "cotatq-frozen-v1.0",
        "conversion_seconds": conversion,
        "planning_seconds": planning,
        "compile_seconds": 0.0,
        "setup_seconds": setup,
        "first_kernel_seconds": first_kernel,
        "isolated_one_shot_seconds": setup + first_kernel,
        "warm_seconds": warm,
        "inner_loops": loops,
        "peak_elements_est": plan.estimated_peak_elements,
        "peak_elements_actual": result.actual_peak_elements,
        "amp_real": result.amplitude.real,
        "amp_imag": result.amplitude.imag,
    }


def bench_oe(policy, label):
    gc.collect()
    t0 = time.perf_counter()
    _, _, _, nodes = build_case()
    operands, shape_operands, arrays = build_opt_inputs(nodes)
    conversion = time.perf_counter() - t0

    t0 = time.perf_counter()
    path, info = oe.contract_path(*operands, optimize=policy)
    planning = time.perf_counter() - t0
    largest = int(info.largest_intermediate)

    if largest > args.peak_limit:
        return {
            "ok": False,
            "skip": True,
            "engine": label,
            "error": f"largest intermediate {largest} > limit {args.peak_limit}",
            "peak_elements_est": largest,
        }

    t0 = time.perf_counter()
    expr = oe.contract_expression(*shape_operands, optimize=path)
    compile_s = time.perf_counter() - t0

    return finish_precompiled(
        label, conversion, planning, compile_s, expr, arrays,
        peak_elements=largest,
        extra={"path_policy": str(policy)},
    )


def bench_cotengra(kind):
    if IMPORT_ERROR:
        return {
            "ok": False,
            "unavailable": True,
            "engine": args.engine,
            "error": IMPORT_ERROR,
        }

    ctg = OPTIONAL["cotengra"]

    gc.collect()
    t0 = time.perf_counter()
    _, _, _, nodes = build_case()
    operands, shape_operands, arrays = build_opt_inputs(nodes)
    conversion = time.perf_counter() - t0

    if kind == "rg128":
        optimizer = ctg.RandomGreedyOptimizer(
            max_repeats=128,
            seed=args.seed,
            parallel=False,
        )
        label = "cotengra-rg128"

    elif kind == "hyper2s":
        # Deliberately uses only built-in greedy + random hyperparameter search:
        # no kahypar/optuna requirement. Planning budget is fixed by protocol.
        optimizer = ctg.HyperOptimizer(
            methods=["greedy"],
            minimize="combo",
            max_repeats=64,
            max_time=2.0,
            parallel=False,
            reconf_opts={},
            optlib="random",
            progbar=False,
        )
        label = "cotengra-hyper2s"

    else:
        raise ValueError(kind)

    t0 = time.perf_counter()
    path, info = oe.contract_path(*operands, optimize=optimizer)
    planning = time.perf_counter() - t0
    largest = int(info.largest_intermediate)

    if largest > args.peak_limit:
        return {
            "ok": False,
            "skip": True,
            "engine": label,
            "error": f"largest intermediate {largest} > limit {args.peak_limit}",
            "peak_elements_est": largest,
        }

    t0 = time.perf_counter()
    expr = oe.contract_expression(*shape_operands, optimize=path)
    compile_s = time.perf_counter() - t0

    return finish_precompiled(
        label, conversion, planning, compile_s, expr, arrays,
        peak_elements=largest,
        extra={
            "optimizer_class": type(optimizer).__name__,
            "optimizer_module": type(optimizer).__module__,
        },
    )


def bench_quimb():
    if IMPORT_ERROR:
        return {
            "ok": False,
            "unavailable": True,
            "engine": "quimb-auto-hq",
            "error": IMPORT_ERROR,
        }

    qtn = OPTIONAL["qtn"]

    gc.collect()
    t0 = time.perf_counter()
    _, _, _, nodes = build_case()

    tensors = []
    arrays = []
    for i, node in enumerate(nodes):
        inds = tuple(f"i{int(x)}" for x in node.labels)
        tensors.append(qtn.Tensor(data=node.data, inds=inds, tags=(f"T{i}",)))
        arrays.append(node.data)
    conversion = time.perf_counter() - t0

    # Current quimb documents get='tree' and get='expression'.
    t0 = time.perf_counter()
    tree = qtn.tensor_contract(
        *tensors,
        output_inds=(),
        optimize="auto-hq",
        get="tree",
    )
    planning = time.perf_counter() - t0

    # Guard against excessive exact intermediates if current tree API exposes max_size.
    peak = None
    try:
        peak = int(tree.max_size())
    except Exception:
        pass

    if peak is not None and peak > args.peak_limit:
        return {
            "ok": False,
            "skip": True,
            "engine": "quimb-auto-hq",
            "error": f"tree max_size {peak} > limit {args.peak_limit}",
            "peak_elements_est": peak,
        }

    t0 = time.perf_counter()
    expr = qtn.tensor_contract(
        *tensors,
        output_inds=(),
        optimize=tree,
        get="expression",
    )
    compile_s = time.perf_counter() - t0

    return finish_precompiled(
        "quimb-auto-hq",
        conversion,
        planning,
        compile_s,
        expr,
        arrays,
        peak_elements=peak,
        extra={
            "quimb_version": getattr(OPTIONAL["quimb"], "__version__", None),
            "quimb_expression_api": "tensor_contract(get='expression')",
        },
    )


def to_qiskit(circuit, input_bits, output_bits):
    QuantumCircuit = OPTIONAL["QuantumCircuit"]
    qc = QuantumCircuit(circuit.n)

    for q, bit in enumerate(input_bits):
        if bit:
            qc.x(q)

    for g in circuit.gates:
        if g.name == "H":
            qc.h(g.a)
        elif g.name == "X":
            qc.x(g.a)
        elif g.name == "RY":
            qc.ry(g.theta, g.a)
        elif g.name == "RX":
            qc.rx(g.theta, g.a)
        elif g.name == "RZ":
            qc.rz(g.theta, g.a)
        elif g.name == "P":
            qc.p(g.theta, g.a)
        elif g.name == "S":
            qc.s(g.a)
        elif g.name == "T":
            qc.t(g.a)
        elif g.name == "CNOT":
            qc.cx(g.a, g.b)
        elif g.name == "CZ":
            qc.cz(g.a, g.b)
        else:
            raise ValueError(g.name)

    qc.save_amplitudes([qiskit_basis_index(output_bits)], label="amp")
    return qc


def transpile_aer_no_target(qc, sim):
    transpile = OPTIONAL["transpile"]
    try:
        basis = list(sim.configuration().basis_gates or [])
        return transpile(
            qc,
            basis_gates=basis if basis else None,
            coupling_map=None,
            optimization_level=0,
        ), "basis_only_no_target"
    except Exception as exc:
        return qc, f"direct_no_target_fallback:{type(exc).__name__}"


def bench_aer(method, label):
    if IMPORT_ERROR:
        return {
            "ok": False,
            "unavailable": True,
            "engine": label,
            "error": IMPORT_ERROR,
        }

    AerSimulator = OPTIONAL["AerSimulator"]

    gc.collect()
    t0 = time.perf_counter()
    circuit = make_audit_circuit(args.family, args.n, args.depth, args.seed)
    input_bits, output_bits = query_profile(args.profile, args.n, args.seed)
    qc = to_qiskit(circuit, input_bits, output_bits)
    conversion = time.perf_counter() - t0

    kwargs = {
        "method": method,
        "max_parallel_threads": 1,
    }
    if method == "matrix_product_state":
        kwargs.update({
            "matrix_product_state_max_bond_dimension": args.bond,
            "matrix_product_state_truncation_threshold": 0.0,
            "mps_omp_threads": 1,
        })

    sim = AerSimulator(**kwargs)

    t0 = time.perf_counter()
    tqc, transpile_mode = transpile_aer_no_target(qc, sim)
    planning = time.perf_counter() - t0

    t0 = time.perf_counter()
    rr = sim.run(tqc, shots=None).result()
    first_kernel = time.perf_counter() - t0
    if not rr.success:
        raise RuntimeError(str(rr.status))
    first_amp = complex(np.asarray(rr.data(0)["amp"])[0])

    def once():
        r = sim.run(tqc, shots=None).result()
        if not r.success:
            raise RuntimeError(str(r.status))
        return complex(np.asarray(r.data(0)["amp"])[0])

    warm, amp, loops = repeated_warm(
        once,
        min(args.repeats, 5),
        first_kernel,
    )
    if amp is None:
        amp = first_amp

    setup = conversion + planning
    return {
        "ok": True,
        "engine": label,
        "conversion_seconds": conversion,
        "planning_seconds": planning,
        "compile_seconds": 0.0,
        "setup_seconds": setup,
        "first_kernel_seconds": first_kernel,
        "isolated_one_shot_seconds": setup + first_kernel,
        "warm_seconds": warm,
        "inner_loops": loops,
        "amp_real": amp.real,
        "amp_imag": amp.imag,
        "aer_method": method,
        "aer_target_used": False,
        "aer_transpile_mode": transpile_mode,
        "mps_bond_cap": args.bond if method == "matrix_product_state" else None,
    }


neutral_numpy_warmup()

print("READY", flush=True)
if sys.stdin.readline().strip() != "GO":
    print(json.dumps({
        "ok": False,
        "engine": args.engine,
        "error": "missing GO",
    }), flush=True)
    raise SystemExit(2)

wall0 = time.perf_counter()

try:
    if IMPORT_ERROR and (
        args.engine.startswith("cotengra-")
        or args.engine.startswith("quimb-")
        or args.engine.startswith("aer-")
    ):
        result = {
            "ok": False,
            "unavailable": True,
            "engine": args.engine,
            "error": IMPORT_ERROR,
        }

    elif args.engine == "cotatq":
        result = bench_cotatq()
    elif args.engine == "opt-greedy":
        result = bench_oe("greedy", "opt-greedy")
    elif args.engine == "opt-rg128":
        result = bench_oe("random-greedy-128", "opt-rg128")
    elif args.engine == "cotengra-rg128":
        result = bench_cotengra("rg128")
    elif args.engine == "cotengra-hyper2s":
        result = bench_cotengra("hyper2s")
    elif args.engine == "quimb-auto-hq":
        result = bench_quimb()
    elif args.engine == "aer-mps":
        result = bench_aer("matrix_product_state", "aer-mps")
    elif args.engine == "aer-auto":
        result = bench_aer("automatic", "aer-auto")
    elif args.engine == "aer-statevector":
        result = bench_aer("statevector", "aer-statevector")
    else:
        raise ValueError(args.engine)

    result.update({
        "family": args.family,
        "n": args.n,
        "depth": args.depth,
        "seed": args.seed,
        "profile": args.profile,
        "repeats": args.repeats,
        "fresh_process": True,
        "neutral_numpy_warmup": True,
        "worker_wall_seconds_after_go": time.perf_counter() - wall0,
    })
    print(json.dumps(result), flush=True)

except Exception as exc:
    print(json.dumps({
        "ok": False,
        "engine": args.engine,
        "family": args.family,
        "n": args.n,
        "depth": args.depth,
        "seed": args.seed,
        "profile": args.profile,
        "error": f"{type(exc).__name__}: {exc}",
        "worker_wall_seconds_after_go": time.perf_counter() - wall0,
    }), flush=True)
