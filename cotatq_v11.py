"""
CotatQ v1.1 — adversarial-audit circuit and tensor-network helpers.

This module does NOT optimize CotatQ's contraction planner or executor.
It expands the validation workload so the v1.0 result can be challenged by:
- genuinely complex-valued gates (RX, RZ, phase, S, T, CZ),
- non-zero input states,
- multiple output amplitudes,
- unseen interaction topologies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple
import math
import numpy as np

from cotatq_v04 import C128, Circuit, Gate, H, X, CNOT_LR, ry
from cotatq_v07 import TensorNode


def rx(theta: float) -> np.ndarray:
    c = math.cos(theta / 2.0)
    s = math.sin(theta / 2.0)
    return np.array([[c, -1j * s], [-1j * s, c]], dtype=C128)


def rz(theta: float) -> np.ndarray:
    return np.array(
        [[np.exp(-0.5j * theta), 0.0], [0.0, np.exp(0.5j * theta)]],
        dtype=C128,
    )


def phase(theta: float) -> np.ndarray:
    return np.array([[1.0, 0.0], [0.0, np.exp(1j * theta)]], dtype=C128)


S = phase(np.pi / 2.0)
T = phase(np.pi / 4.0)
CZ = np.diag([1.0, 1.0, 1.0, -1.0]).astype(C128)
CNOT4 = np.asarray(CNOT_LR, dtype=C128).reshape(2, 2, 2, 2)
CZ4 = CZ.reshape(2, 2, 2, 2)
ZERO = np.array([1.0 + 0j, 0.0 + 0j], dtype=C128)
ONE = np.array([0.0 + 0j, 1.0 + 0j], dtype=C128)


class ComplexCircuit(Circuit):
    def rx(self, q: int, theta: float):
        self._check(q)
        self.gates.append(Gate("RX", q, theta=float(theta)))
        return self

    def rz(self, q: int, theta: float):
        self._check(q)
        self.gates.append(Gate("RZ", q, theta=float(theta)))
        return self

    def p(self, q: int, theta: float):
        self._check(q)
        self.gates.append(Gate("P", q, theta=float(theta)))
        return self

    def s(self, q: int):
        self._check(q)
        self.gates.append(Gate("S", q))
        return self

    def t(self, q: int):
        self._check(q)
        self.gates.append(Gate("T", q))
        return self

    def cz(self, a: int, b: int):
        self._check(a)
        self._check(b)
        if a == b:
            raise ValueError("CZ qubits must differ")
        self.gates.append(Gate("CZ", a, b))
        return self


SINGLE_GATES = {
    "H": H,
    "X": X,
    "S": S,
    "T": T,
}


def gate_matrix(g: Gate) -> np.ndarray:
    if g.name in SINGLE_GATES:
        return SINGLE_GATES[g.name]
    if g.name == "RY":
        return ry(float(g.theta))
    if g.name == "RX":
        return rx(float(g.theta))
    if g.name == "RZ":
        return rz(float(g.theta))
    if g.name == "P":
        return phase(float(g.theta))
    raise ValueError(f"Unsupported single-qubit gate: {g.name}")


def two_gate_tensor(g: Gate) -> np.ndarray:
    if g.name == "CNOT":
        return CNOT4
    if g.name == "CZ":
        return CZ4
    raise ValueError(f"Unsupported two-qubit gate: {g.name}")


def _add_complex_single_layer(c: ComplexCircuit, rng: np.random.Generator, layer: int):
    """Dense complex single-qubit layer with deterministic gate variety."""
    for q in range(c.n):
        selector = (q + 3 * layer + int(rng.integers(0, 7))) % 7
        theta = float(rng.uniform(-np.pi, np.pi))
        if selector == 0:
            c.rx(q, theta)
        elif selector == 1:
            c.ry(q, theta)
        elif selector == 2:
            c.rz(q, theta)
        elif selector == 3:
            c.p(q, theta)
        elif selector == 4:
            c.h(q).rz(q, theta)
        elif selector == 5:
            c.s(q).rx(q, theta)
        else:
            c.t(q).ry(q, theta)


def _apply_edges(
    c: ComplexCircuit,
    edges: Iterable[Tuple[int, int]],
    rng: np.random.Generator,
):
    for a, b in edges:
        if a == b:
            continue
        if rng.random() < 0.55:
            c.cnot(int(a), int(b))
        else:
            c.cz(int(a), int(b))


def random_matching_complex(n: int, depth: int, seed: int) -> ComplexCircuit:
    rng = np.random.default_rng(seed)
    c = ComplexCircuit(n)
    for d in range(depth):
        _add_complex_single_layer(c, rng, d)
        perm = list(map(int, rng.permutation(n)))
        _apply_edges(c, [(perm[i], perm[i + 1]) for i in range(0, n - 1, 2)], rng)
    return c


def small_world_complex(n: int, depth: int, seed: int) -> ComplexCircuit:
    rng = np.random.default_rng(seed)
    c = ComplexCircuit(n)
    for d in range(depth):
        _add_complex_single_layer(c, rng, d)
        local = [(q, q + 1) for q in range(d % 2, n - 1, 2)]
        chords = []
        used = set()
        target = max(1, n // 8)
        while len(chords) < target:
            a, b = map(int, rng.choice(n, size=2, replace=False))
            if abs(a - b) < max(2, n // 5):
                continue
            key = (min(a, b), max(a, b))
            if key in used:
                continue
            used.add(key)
            chords.append((a, b))
        _apply_edges(c, local + chords, rng)
    return c


def hub_spoke_complex(n: int, depth: int, seed: int) -> ComplexCircuit:
    rng = np.random.default_rng(seed)
    c = ComplexCircuit(n)
    for d in range(depth):
        _add_complex_single_layer(c, rng, d)
        hubs = list(map(int, rng.choice(n, size=min(2, n), replace=False)))
        edges = []
        for hub in hubs:
            targets = [int(x) for x in rng.permutation(n) if int(x) != hub]
            for t in targets[: max(2, n // 6)]:
                edges.append((hub, t))
        _apply_edges(c, edges, rng)
    return c


def dense_longrange_complex(n: int, depth: int, seed: int) -> ComplexCircuit:
    rng = np.random.default_rng(seed)
    c = ComplexCircuit(n)
    for d in range(depth):
        _add_complex_single_layer(c, rng, d)
        for _ in range(2):
            perm = list(map(int, rng.permutation(n)))
            _apply_edges(c, [(perm[i], perm[i + 1]) for i in range(0, n - 1, 2)], rng)
    return c


def local_brickwork_complex(n: int, depth: int, seed: int) -> ComplexCircuit:
    rng = np.random.default_rng(seed)
    c = ComplexCircuit(n)
    for d in range(depth):
        _add_complex_single_layer(c, rng, d)
        _apply_edges(c, [(q, q + 1) for q in range(d % 2, n - 1, 2)], rng)
    return c


def grid2d_complex(n: int, depth: int, seed: int) -> ComplexCircuit:
    """Nearest-neighbor square-grid control topology, padded if n is not square."""
    rng = np.random.default_rng(seed)
    side = int(round(math.sqrt(n)))
    if side * side != n:
        raise ValueError("grid2d_complex requires a perfect-square number of qubits")
    c = ComplexCircuit(n)
    for d in range(depth):
        _add_complex_single_layer(c, rng, d)
        edges = []
        if d % 2 == 0:
            for r in range(side):
                for col in range((d // 2) % 2, side - 1, 2):
                    edges.append((r * side + col, r * side + col + 1))
        else:
            for r in range((d // 2) % 2, side - 1, 2):
                for col in range(side):
                    edges.append((r * side + col, (r + 1) * side + col))
        _apply_edges(c, edges, rng)
    return c


TARGET_FAMILIES = {
    "random_matching_complex",
    "small_world_complex",
    "hub_spoke_complex",
    "dense_longrange_complex",
}
CONTROL_FAMILIES = {"local_brickwork_complex", "grid2d_complex"}


def make_audit_circuit(family: str, n: int, depth: int, seed: int) -> ComplexCircuit:
    mapping = {
        "random_matching_complex": random_matching_complex,
        "small_world_complex": small_world_complex,
        "hub_spoke_complex": hub_spoke_complex,
        "dense_longrange_complex": dense_longrange_complex,
        "local_brickwork_complex": local_brickwork_complex,
        "grid2d_complex": grid2d_complex,
    }
    try:
        return mapping[family](n, depth, seed)
    except KeyError as e:
        raise ValueError(f"Unknown audit family: {family}") from e


def _deterministic_bits(n: int, salt: int) -> List[int]:
    rng = np.random.default_rng(salt)
    return list(map(int, rng.integers(0, 2, size=n)))


def query_profile(profile: str, n: int, seed: int) -> Tuple[List[int], List[int]]:
    if profile == "zero_to_zero":
        return [0] * n, [0] * n
    if profile == "random_to_random":
        return (
            _deterministic_bits(n, 1_000_003 + 7919 * seed + 13 * n),
            _deterministic_bits(n, 2_000_003 + 6151 * seed + 17 * n),
        )
    if profile == "checker_to_random":
        return (
            [q & 1 for q in range(n)],
            _deterministic_bits(n, 3_000_017 + 3571 * seed + 19 * n),
        )
    raise ValueError(f"Unknown query profile: {profile}")


def cotat_basis_index(bits: Sequence[int]) -> int:
    n = len(bits)
    return sum(int(bits[q]) << (n - 1 - q) for q in range(n))


def qiskit_basis_index(bits: Sequence[int]) -> int:
    return sum(int(bits[q]) << q for q in range(len(bits)))


class CircuitTensorNetworkV11:
    def __init__(
        self,
        circuit: Circuit,
        input_bits: Optional[Sequence[int]] = None,
        output_bits: Optional[Sequence[int]] = None,
    ):
        self.circuit = circuit
        self.input_bits = list(input_bits) if input_bits is not None else [0] * circuit.n
        self.output_bits = list(output_bits) if output_bits is not None else [0] * circuit.n
        if len(self.input_bits) != circuit.n or len(self.output_bits) != circuit.n:
            raise ValueError("input_bits/output_bits length must equal circuit.n")
        if any(int(b) not in (0, 1) for b in self.input_bits + self.output_bits):
            raise ValueError("input_bits/output_bits must contain only 0 or 1")

    def build(self) -> List[TensorNode]:
        c = self.circuit
        nodes: List[TensorNode] = []
        current = [0] * c.n
        next_label = 0

        for q in range(c.n):
            lab = next_label
            next_label += 1
            current[q] = lab
            nodes.append(TensorNode((ZERO if self.input_bits[q] == 0 else ONE).copy(), (lab,)))

        for g in c.gates:
            if g.name in {"H", "X", "RY", "RX", "RZ", "P", "S", "T"}:
                inp = current[g.a]
                out = next_label
                next_label += 1
                nodes.append(TensorNode(gate_matrix(g).copy(), (out, inp)))
                current[g.a] = out
            elif g.name in {"CNOT", "CZ"}:
                ia = current[g.a]
                ib = current[g.b]
                oa = next_label
                ob = next_label + 1
                next_label += 2
                nodes.append(TensorNode(two_gate_tensor(g).copy(), (oa, ob, ia, ib)))
                current[g.a] = oa
                current[g.b] = ob
            else:
                raise ValueError(f"Unsupported gate in tensor network: {g.name}")

        for q in range(c.n):
            vec = ZERO if self.output_bits[q] == 0 else ONE
            nodes.append(TensorNode(vec.copy(), (current[q],)))

        return nodes


class ExactEngineV11:
    def run(self, circuit: Circuit, input_bits: Optional[Sequence[int]] = None) -> np.ndarray:
        n = circuit.n
        bits = list(input_bits) if input_bits is not None else [0] * n
        state = np.zeros(1 << n, dtype=C128)
        state[cotat_basis_index(bits)] = 1.0 + 0j

        for g in circuit.gates:
            if g.name in {"H", "X", "RY", "RX", "RZ", "P", "S", "T"}:
                state = self._single(state, n, g.a, gate_matrix(g))
            elif g.name in {"CNOT", "CZ"}:
                state = self._two(state, n, g.a, g.b, two_gate_tensor(g))
            else:
                raise ValueError(g.name)
        return state

    @staticmethod
    def _single(state: np.ndarray, n: int, q: int, gate: np.ndarray) -> np.ndarray:
        t = state.reshape([2] * n)
        t = np.moveaxis(t, q, 0)
        t = np.tensordot(gate, t, axes=([1], [0]))
        t = np.moveaxis(t, 0, q)
        return np.ascontiguousarray(t).reshape(-1)

    @staticmethod
    def _two(
        state: np.ndarray,
        n: int,
        a: int,
        b: int,
        gate4: np.ndarray,
    ) -> np.ndarray:
        t = state.reshape([2] * n)
        t = np.moveaxis(t, [a, b], [0, 1])
        t = np.tensordot(gate4, t, axes=([2, 3], [0, 1]))
        t = np.moveaxis(t, [0, 1], [a, b])
        return np.ascontiguousarray(t).reshape(-1)


ALL_CONFIGS = [
    ("random_matching_complex", 20, 2),
    ("random_matching_complex", 40, 3),
    ("random_matching_complex", 80, 3),
    ("small_world_complex", 20, 2),
    ("small_world_complex", 40, 3),
    ("small_world_complex", 60, 3),
    ("hub_spoke_complex", 20, 2),
    ("hub_spoke_complex", 40, 2),
    ("hub_spoke_complex", 60, 3),
    ("dense_longrange_complex", 20, 2),
    ("dense_longrange_complex", 30, 2),
    ("dense_longrange_complex", 40, 2),
    ("local_brickwork_complex", 20, 4),
    ("local_brickwork_complex", 40, 6),
    ("local_brickwork_complex", 60, 8),
    ("grid2d_complex", 25, 4),
    ("grid2d_complex", 36, 5),
    ("grid2d_complex", 49, 6),
]


def audit_suite(mode: str):
    if mode == "quick":
        configs = [
            ("random_matching_complex", 20, 2),
            ("small_world_complex", 20, 2),
            ("hub_spoke_complex", 20, 2),
            ("dense_longrange_complex", 20, 2),
            ("local_brickwork_complex", 20, 4),
            ("grid2d_complex", 25, 4),
        ]
        seeds = [101]
        profiles = ["zero_to_zero", "random_to_random"]
        repeats = 5
    elif mode == "standard":
        configs = [cfg for i, cfg in enumerate(ALL_CONFIGS) if i % 3 != 2]
        seeds = [101, 202]
        profiles = ["zero_to_zero", "random_to_random", "checker_to_random"]
        repeats = 7
    elif mode == "full":
        configs = ALL_CONFIGS
        seeds = [101, 202, 303, 404, 505]
        profiles = ["zero_to_zero", "random_to_random", "checker_to_random"]
        repeats = 9
    else:
        raise ValueError("mode must be quick, standard, or full")

    cases = []
    for family, n, depth in configs:
        for seed in seeds:
            for profile in profiles:
                cases.append(
                    {
                        "family": family,
                        "n": n,
                        "depth": depth,
                        "seed": seed,
                        "profile": profile,
                        "target": family in TARGET_FAMILIES,
                    }
                )
    return cases, repeats
