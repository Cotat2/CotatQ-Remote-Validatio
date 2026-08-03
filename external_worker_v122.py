
"""
CotatQ v1.2.2 — exact Aer MPS compatibility worker.

PATCH SCOPE:
- CotatQ frozen implementation unchanged.
- Cases/seeds/profiles unchanged.
- Verdict thresholds unchanged.
- Timeouts unchanged.
- Peak limits unchanged.
- cotengra/quimb v1.2.1 compatibility fixes retained.
- ONLY the Aer MPS correctness route changes.

Scored Aer MPS route in v1.2.2:
    exact matrix_product_state simulation
    + no max bond-dimension cap
    + truncation threshold 0.0
    + save native MPS representation
    + contract ONLY the requested basis amplitude in Python

This avoids relying on Aer MPS save_amplitudes for the scored MPS rival.

Diagnostic-only aliases are also provided:
- aer-mps-direct-capped
- aer-mps-direct-uncapped
- aer-mps-fullsv

They are never part of the locked benchmark engine list.
"""

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
parser.add_argument("--bond", type=int, default=128)  # kept for protocol CLI compatibility
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

OPTIONAL = {}
IMPORT_ERROR = None

try:
    if args.engine.startswith("cotengra-") or args.engine.startswith("quimb-"):
        import cotengra as ctg
        OPTIONAL["cotengra"] = ctg

    if args.engine.startswith("quimb-"):
        import quimb
        import quimb.tensor as qtn
        OPTIONAL["quimb"] = quimb
        OPTIONAL["qtn"] = qtn

    if args.engine.startswith("aer-"):
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


def build_cotengra_geometry(nodes):
    inputs = []
    size_dict = {}

    for node in nodes:
        inds = tuple(node.labels)
        inputs.append(inds)

        for ind, dim in zip(inds, node.data.shape):
            dim = int(dim)
            old = size_dict.get(ind)
            if old is not None and old != dim:
                raise ValueError(f"inconsistent dimension for index {ind}: {old} vs {dim}")
            size_dict[ind] = dim

    return tuple(inputs), tuple(), size_dict


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
    amp = normalize_scalar(last if last is not None else first)

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
        "compatibility_patch": "v1.2.2",
    }

    if extra:
        out.update(extra)

    return out


def path_info_from_explicit_path(operands, path):
    _, info = oe.contract_path(*operands, optimize=path)
    return info


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
            "compatibility_patch": "v1.2.2",
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
        "compatibility_patch": "v1.2.2",
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
            "compatibility_patch": "v1.2.2",
        }

    t0 = time.perf_counter()
    expr = oe.contract_expression(*shape_operands, optimize=path)
    compile_s = time.perf_counter() - t0

    return finish_precompiled(
        label,
        conversion,
        planning,
        compile_s,
        expr,
        arrays,
        peak_elements=largest,
        extra={"path_policy": str(policy)},
    )


def bench_cotengra_rg128():
    if IMPORT_ERROR:
        return {"ok": False, "unavailable": True, "engine": "cotengra-rg128", "error": IMPORT_ERROR}

    ctg = OPTIONAL["cotengra"]

    gc.collect()

    t0 = time.perf_counter()
    _, _, _, nodes = build_case()
    operands, shape_operands, arrays = build_opt_inputs(nodes)
    inputs, output, size_dict = build_cotengra_geometry(nodes)
    conversion = time.perf_counter() - t0

    optimizer = ctg.RandomGreedyOptimizer(
        max_repeats=128,
        seed=args.seed,
        parallel=False,
    )

    t0 = time.perf_counter()
    path = optimizer(inputs, output, size_dict)
    info = path_info_from_explicit_path(operands, path)
    planning = time.perf_counter() - t0

    largest = int(info.largest_intermediate)

    if largest > args.peak_limit:
        return {
            "ok": False,
            "skip": True,
            "engine": "cotengra-rg128",
            "error": f"largest intermediate {largest} > limit {args.peak_limit}",
            "peak_elements_est": largest,
        }

    t0 = time.perf_counter()
    expr = oe.contract_expression(*shape_operands, optimize=path)
    compile_s = time.perf_counter() - t0

    return finish_precompiled(
        "cotengra-rg128",
        conversion,
        planning,
        compile_s,
        expr,
        arrays,
        peak_elements=largest,
        extra={
            "cotengra_direct_api": True,
            "cotengra_call_signature_used": "(inputs, output, size_dict)",
        },
    )


def bench_cotengra_hyper2s():
    if IMPORT_ERROR:
        return {"ok": False, "unavailable": True, "engine": "cotengra-hyper2s", "error": IMPORT_ERROR}

    ctg = OPTIONAL["cotengra"]

    gc.collect()

    t0 = time.perf_counter()
    _, _, _, nodes = build_case()
    operands, shape_operands, arrays = build_opt_inputs(nodes)
    conversion = time.perf_counter() - t0

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

    t0 = time.perf_counter()
    path, info = oe.contract_path(*operands, optimize=optimizer)
    planning = time.perf_counter() - t0

    largest = int(info.largest_intermediate)

    if largest > args.peak_limit:
        return {
            "ok": False,
            "skip": True,
            "engine": "cotengra-hyper2s",
            "error": f"largest intermediate {largest} > limit {args.peak_limit}",
            "peak_elements_est": largest,
        }

    t0 = time.perf_counter()
    expr = oe.contract_expression(*shape_operands, optimize=path)
    compile_s = time.perf_counter() - t0

    return finish_precompiled(
        "cotengra-hyper2s",
        conversion,
        planning,
        compile_s,
        expr,
        arrays,
        peak_elements=largest,
        extra={"parallel": False},
    )


def bench_quimb_hq_serial():
    if IMPORT_ERROR:
        return {"ok": False, "unavailable": True, "engine": "quimb-auto-hq", "error": IMPORT_ERROR}

    ctg = OPTIONAL["cotengra"]
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

    optimizer = ctg.ReusableHyperOptimizer(
        methods=["greedy"],
        minimize="combo",
        max_repeats=64,
        max_time=2.0,
        parallel=False,
        reconf_opts={},
        optlib="random",
        progbar=False,
    )

    t0 = time.perf_counter()

    tree = qtn.tensor_contract(
        *tensors,
        output_inds=(),
        optimize=optimizer,
        get="tree",
    )

    planning = time.perf_counter() - t0

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
            "quimb_optimizer": "cotengra.ReusableHyperOptimizer",
            "quimb_parallel": False,
            "quimb_nested_process_pool": False,
            "quimb_planning_budget_seconds": 2.0,
        },
    )


# ---------------------------------------------------------------------------
# Qiskit / Aer
# ---------------------------------------------------------------------------

def to_qiskit_base(circuit, input_bits):
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


def native_mps_amplitude(mps_state, output_bits):
    """
    Extract one computational-basis amplitude from Aer's native MPS.

    Aer documents its MPS as:
        Gamma[0] lambda[0] Gamma[1] lambda[1] ... Gamma[n-1]

    The first element of mps_state is one (Gamma_0, Gamma_1) pair per qubit.
    The second is one Schmidt-value vector between adjacent qubits.

    output_bits is indexed by logical Qiskit qubit number q0, q1, ...
    matching the order of the native MPS tensors.
    """
    gammas, lambdas = mps_state

    if len(gammas) != len(output_bits):
        raise ValueError(
            f"MPS qubit count mismatch: {len(gammas)} tensors vs "
            f"{len(output_bits)} output bits"
        )

    if len(gammas) == 0:
        return 1.0 + 0.0j

    bit0 = int(output_bits[0])
    if bit0 not in (0, 1):
        raise ValueError("output bit must be 0 or 1")

    current = np.asarray(gammas[0][bit0], dtype=np.complex128)

    if current.ndim == 1:
        current = current.reshape(1, -1)

    for i in range(len(gammas) - 1):
        lam = np.asarray(lambdas[i], dtype=np.complex128).reshape(-1)

        # Gamma[i] right bond must match lambda[i].
        if current.shape[-1] != lam.shape[0]:
            raise ValueError(
                f"MPS bond mismatch at {i}: current {current.shape}, lambda {lam.shape}"
            )

        # Multiply the lambda diagonally without materializing diag(lambda).
        current = current * lam.reshape(1, -1)

        bit = int(output_bits[i + 1])
        nxt = np.asarray(gammas[i + 1][bit], dtype=np.complex128)

        if nxt.ndim == 1:
            nxt = nxt.reshape(-1, 1)

        current = current @ nxt

    return complex(np.asarray(current).reshape(()))


def make_mps_sim(*, capped):
    AerSimulator = OPTIONAL["AerSimulator"]

    kwargs = {
        "method": "matrix_product_state",
        "max_parallel_threads": 1,
        "matrix_product_state_truncation_threshold": 0.0,
        "mps_omp_threads": 1,
    }

    # The scored v1.2.2 route is UNBOUNDED / exact with respect to bond dimension.
    if capped:
        kwargs["matrix_product_state_max_bond_dimension"] = int(args.bond)

    return AerSimulator(**kwargs)


def bench_aer_mps_native_exact():
    """
    Scored Aer MPS rival.

    No max bond cap. The query amplitude is computed from Aer's native MPS,
    not from SaveAmplitudes.
    """
    if IMPORT_ERROR:
        return {"ok": False, "unavailable": True, "engine": "aer-mps", "error": IMPORT_ERROR}

    gc.collect()

    t0 = time.perf_counter()
    circuit = make_audit_circuit(args.family, args.n, args.depth, args.seed)
    input_bits, output_bits = query_profile(args.profile, args.n, args.seed)

    qc = to_qiskit_base(circuit, input_bits)
    qc.save_matrix_product_state(label="mps")
    conversion = time.perf_counter() - t0

    sim = make_mps_sim(capped=False)

    t0 = time.perf_counter()
    tqc, transpile_mode = transpile_aer_no_target(qc, sim)
    planning = time.perf_counter() - t0

    def once():
        rr = sim.run(tqc, shots=None).result()
        if not rr.success:
            raise RuntimeError(str(rr.status))
        state = rr.data(0)["mps"]
        return native_mps_amplitude(state, output_bits)

    t0 = time.perf_counter()
    first_amp = once()
    first_kernel = time.perf_counter() - t0

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
        "engine": "aer-mps",
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
        "aer_method": "matrix_product_state",
        "aer_target_used": False,
        "aer_transpile_mode": transpile_mode,
        "mps_bond_cap": None,
        "mps_truncation_threshold": 0.0,
        "mps_query_route": "save_matrix_product_state+manual_single_amplitude",
        "mps_exactness_policy": "no bond truncation; zero coefficient threshold",
        "compatibility_patch": "v1.2.2",
    }


def bench_aer_mps_direct(*, capped):
    """
    Diagnostic-only direct SaveAmplitudes routes.
    """
    if IMPORT_ERROR:
        return {"ok": False, "unavailable": True, "engine": args.engine, "error": IMPORT_ERROR}

    gc.collect()

    t0 = time.perf_counter()
    circuit = make_audit_circuit(args.family, args.n, args.depth, args.seed)
    input_bits, output_bits = query_profile(args.profile, args.n, args.seed)

    qc = to_qiskit_base(circuit, input_bits)
    qc.save_amplitudes([qiskit_basis_index(output_bits)], label="amp")
    conversion = time.perf_counter() - t0

    sim = make_mps_sim(capped=capped)

    t0 = time.perf_counter()
    tqc, transpile_mode = transpile_aer_no_target(qc, sim)
    planning = time.perf_counter() - t0

    def once():
        rr = sim.run(tqc, shots=None).result()
        if not rr.success:
            raise RuntimeError(str(rr.status))
        return complex(np.asarray(rr.data(0)["amp"])[0])

    t0 = time.perf_counter()
    first_amp = once()
    first_kernel = time.perf_counter() - t0

    warm, amp, loops = repeated_warm(once, min(args.repeats, 3), first_kernel)

    if amp is None:
        amp = first_amp

    setup = conversion + planning

    return {
        "ok": True,
        "engine": args.engine,
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
        "aer_method": "matrix_product_state",
        "mps_bond_cap": int(args.bond) if capped else None,
        "mps_truncation_threshold": 0.0,
        "mps_query_route": "save_amplitudes",
        "diagnostic_only": True,
        "compatibility_patch": "v1.2.2",
    }


def bench_aer_mps_fullsv():
    """
    Diagnostic-only small-n check:
    MPS simulator -> full statevector -> requested amplitude.
    Never used in scored benchmark because it materializes 2^n amplitudes.
    """
    if IMPORT_ERROR:
        return {"ok": False, "unavailable": True, "engine": args.engine, "error": IMPORT_ERROR}

    gc.collect()

    t0 = time.perf_counter()
    circuit = make_audit_circuit(args.family, args.n, args.depth, args.seed)
    input_bits, output_bits = query_profile(args.profile, args.n, args.seed)

    qc = to_qiskit_base(circuit, input_bits)
    qc.save_statevector(label="sv")
    conversion = time.perf_counter() - t0

    sim = make_mps_sim(capped=False)

    t0 = time.perf_counter()
    tqc, transpile_mode = transpile_aer_no_target(qc, sim)
    planning = time.perf_counter() - t0

    def once():
        rr = sim.run(tqc, shots=None).result()
        if not rr.success:
            raise RuntimeError(str(rr.status))
        sv = np.asarray(rr.data(0)["sv"])
        return complex(sv[qiskit_basis_index(output_bits)])

    t0 = time.perf_counter()
    first_amp = once()
    first_kernel = time.perf_counter() - t0

    warm, amp, loops = repeated_warm(once, min(args.repeats, 3), first_kernel)

    if amp is None:
        amp = first_amp

    setup = conversion + planning

    return {
        "ok": True,
        "engine": args.engine,
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
        "aer_method": "matrix_product_state",
        "mps_bond_cap": None,
        "mps_truncation_threshold": 0.0,
        "mps_query_route": "save_statevector+index",
        "diagnostic_only": True,
        "compatibility_patch": "v1.2.2",
    }


def bench_aer_standard(method, label):
    if IMPORT_ERROR:
        return {"ok": False, "unavailable": True, "engine": label, "error": IMPORT_ERROR}

    AerSimulator = OPTIONAL["AerSimulator"]

    gc.collect()

    t0 = time.perf_counter()
    circuit = make_audit_circuit(args.family, args.n, args.depth, args.seed)
    input_bits, output_bits = query_profile(args.profile, args.n, args.seed)

    qc = to_qiskit_base(circuit, input_bits)
    qc.save_amplitudes([qiskit_basis_index(output_bits)], label="amp")
    conversion = time.perf_counter() - t0

    sim = AerSimulator(
        method=method,
        max_parallel_threads=1,
    )

    t0 = time.perf_counter()
    tqc, transpile_mode = transpile_aer_no_target(qc, sim)
    planning = time.perf_counter() - t0

    def once():
        rr = sim.run(tqc, shots=None).result()
        if not rr.success:
            raise RuntimeError(str(rr.status))
        return complex(np.asarray(rr.data(0)["amp"])[0])

    t0 = time.perf_counter()
    first_amp = once()
    first_kernel = time.perf_counter() - t0

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
        "compatibility_patch": "v1.2.2",
    }


neutral_numpy_warmup()

print("READY", flush=True)
if sys.stdin.readline().strip() != "GO":
    print(json.dumps({"ok": False, "engine": args.engine, "error": "missing GO"}), flush=True)
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
            "compatibility_patch": "v1.2.2",
        }

    elif args.engine == "cotatq":
        result = bench_cotatq()

    elif args.engine == "opt-greedy":
        result = bench_oe("greedy", "opt-greedy")

    elif args.engine == "opt-rg128":
        result = bench_oe("random-greedy-128", "opt-rg128")

    elif args.engine == "cotengra-rg128":
        result = bench_cotengra_rg128()

    elif args.engine == "cotengra-hyper2s":
        result = bench_cotengra_hyper2s()

    elif args.engine == "quimb-auto-hq":
        result = bench_quimb_hq_serial()

    elif args.engine == "aer-mps":
        result = bench_aer_mps_native_exact()

    elif args.engine == "aer-mps-direct-capped":
        result = bench_aer_mps_direct(capped=True)

    elif args.engine == "aer-mps-direct-uncapped":
        result = bench_aer_mps_direct(capped=False)

    elif args.engine == "aer-mps-fullsv":
        result = bench_aer_mps_fullsv()

    elif args.engine == "aer-auto":
        result = bench_aer_standard("automatic", "aer-auto")

    elif args.engine == "aer-statevector":
        result = bench_aer_standard("statevector", "aer-statevector")

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
        "compatibility_patch": "v1.2.2",
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
        "compatibility_patch": "v1.2.2",
    }), flush=True)
