
import math
import time
from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple
import numpy as np

C128 = np.complex128
SQRT2_INV = 1.0 / np.sqrt(2.0)

H = np.array([
    [SQRT2_INV, SQRT2_INV],
    [SQRT2_INV, -SQRT2_INV]
], dtype=C128)

X = np.array([
    [0, 1],
    [1, 0]
], dtype=C128)

SWAP = np.array([
    [1,0,0,0],
    [0,0,1,0],
    [0,1,0,0],
    [0,0,0,1],
], dtype=C128)

CNOT_LR = np.array([
    [1,0,0,0],
    [0,1,0,0],
    [0,0,0,1],
    [0,0,1,0],
], dtype=C128)

CNOT_RL = np.array([
    [1,0,0,0],
    [0,0,0,1],
    [0,0,1,0],
    [0,1,0,0],
], dtype=C128)


def ry(theta: float) -> np.ndarray:
    c = math.cos(theta / 2.0)
    s = math.sin(theta / 2.0)
    return np.array([[c, -s], [s, c]], dtype=C128)


@dataclass(frozen=True)
class Gate:
    name: str
    a: int
    b: Optional[int] = None
    theta: Optional[float] = None


class Circuit:
    def __init__(self, n_qubits: int):
        if n_qubits < 1:
            raise ValueError("n_qubits debe ser >= 1")
        self.n = n_qubits
        self.gates: List[Gate] = []

    def _check(self, q):
        if not (0 <= q < self.n):
            raise ValueError(f"Qubit fuera de rango: {q}")

    def h(self, q):
        self._check(q)
        self.gates.append(Gate("H", q))
        return self

    def x(self, q):
        self._check(q)
        self.gates.append(Gate("X", q))
        return self

    def ry(self, q, theta):
        self._check(q)
        self.gates.append(Gate("RY", q, theta=float(theta)))
        return self

    def cnot(self, control, target):
        self._check(control)
        self._check(target)
        if control == target:
            raise ValueError("control y target no pueden ser iguales")
        self.gates.append(Gate("CNOT", control, target))
        return self

    def remap(self, old_to_new: Dict[int, int]):
        out = Circuit(self.n)
        for g in self.gates:
            if g.name == "H":
                out.h(old_to_new[g.a])
            elif g.name == "X":
                out.x(old_to_new[g.a])
            elif g.name == "RY":
                out.ry(old_to_new[g.a], g.theta)
            elif g.name == "CNOT":
                out.cnot(old_to_new[g.a], old_to_new[g.b])
        return out


def ghz_circuit(n: int) -> Circuit:
    c = Circuit(n).h(0)
    for q in range(n - 1):
        c.cnot(q, q + 1)
    return c


def pair_circuit(n: int) -> Circuit:
    c = Circuit(n)
    for q in range(0, n, 2):
        c.h(q)
        if q + 1 < n:
            c.cnot(q, q + 1)
    return c


def brickwork_circuit(n: int, depth: int, seed: int = 1234) -> Circuit:
    rng = np.random.default_rng(seed)
    c = Circuit(n)
    for d in range(depth):
        for q in range(n):
            c.ry(q, float(rng.uniform(-np.pi, np.pi)))
        start = d % 2
        for q in range(start, n - 1, 2):
            c.cnot(q, q + 1)
    return c


def sparse_long_range_circuit(n: int, depth: int, seed: int = 2026) -> Circuit:
    rng = np.random.default_rng(seed)
    c = Circuit(n)
    for d in range(depth):
        for q in range(n):
            c.ry(q, float(rng.uniform(-0.7, 0.7)))

        perm = rng.permutation(n)
        for i in range(0, n - 1, 2):
            a, b = int(perm[i]), int(perm[i+1])
            c.cnot(a, b)
    return c


class ExactEngine:
    def run(self, circuit: Circuit) -> np.ndarray:
        n = circuit.n
        state = np.zeros(1 << n, dtype=C128)
        state[0] = 1.0 + 0j

        for g in circuit.gates:
            if g.name == "H":
                state = self._single(state, n, g.a, H)
            elif g.name == "X":
                state = self._single(state, n, g.a, X)
            elif g.name == "RY":
                state = self._single(state, n, g.a, ry(g.theta))
            elif g.name == "CNOT":
                state = self._cnot(state, n, g.a, g.b)
            else:
                raise ValueError(g.name)
        return state

    @staticmethod
    def _single(state, n, q, gate):
        t = state.reshape([2] * n)
        t = np.moveaxis(t, q, 0)
        t = np.tensordot(gate, t, axes=([1], [0]))
        t = np.moveaxis(t, 0, q)
        return np.ascontiguousarray(t).reshape(-1)

    @staticmethod
    def _cnot(state, n, control, target):
        idx = np.arange(state.size, dtype=np.uint64)
        c_mask = np.uint64(1 << (n - 1 - control))
        t_mask = np.uint64(1 << (n - 1 - target))
        select = ((idx & c_mask) != 0) & ((idx & t_mask) == 0)
        a = idx[select].astype(np.int64)
        b = (idx[select] | t_mask).astype(np.int64)
        out = state.copy()
        out[a] = state[b]
        out[b] = state[a]
        return out


class MPSResult:
    def __init__(self, tensors, total_discarded_weight, truncations, swap_count=0):
        self.tensors = tensors
        self.total_discarded_weight = float(total_discarded_weight)
        self.truncations = int(truncations)
        self.swap_count = int(swap_count)

    @property
    def n_qubits(self):
        return len(self.tensors)

    @property
    def max_bond_dimension(self):
        m = 1
        for a in self.tensors:
            m = max(m, a.shape[0], a.shape[2])
        return m

    @property
    def stored_complex_numbers(self):
        return int(sum(a.size for a in self.tensors))

    @property
    def memory_mib(self):
        return self.stored_complex_numbers * 16 / (1024 ** 2)

    def to_statevector(self, max_qubits=24):
        if self.n_qubits > max_qubits:
            raise ValueError("Demasiados qubits para reconstruir vector completo")
        psi = np.array([1.0 + 0j], dtype=C128)
        for a in self.tensors:
            psi = np.tensordot(psi, a, axes=([-1], [0]))
        psi = np.squeeze(psi, axis=-1)
        return np.ascontiguousarray(psi).reshape(-1)


class MPSEngine:
    """
    MPS con soporte para CNOT no vecinos mediante SWAP routing.
    """
    def __init__(self, max_bond=64, svd_cutoff=1e-12):
        self.max_bond = int(max_bond)
        self.svd_cutoff = float(svd_cutoff)

    def run(self, circuit: Circuit) -> MPSResult:
        tensors = []
        for _ in range(circuit.n):
            a = np.zeros((1, 2, 1), dtype=C128)
            a[0, 0, 0] = 1.0 + 0j
            tensors.append(a)

        discarded = 0.0
        truncations = 0
        swap_count = 0

        for g in circuit.gates:
            if g.name == "H":
                tensors[g.a] = self._single(tensors[g.a], H)
            elif g.name == "X":
                tensors[g.a] = self._single(tensors[g.a], X)
            elif g.name == "RY":
                tensors[g.a] = self._single(tensors[g.a], ry(g.theta))
            elif g.name == "CNOT":
                d, t, s = self._apply_nonlocal_cnot(tensors, g.a, g.b)
                discarded += d
                truncations += t
                swap_count += s
            else:
                raise ValueError(g.name)

        return MPSResult(tensors, discarded, truncations, swap_count)

    @staticmethod
    def _single(A, gate):
        return np.einsum("oi,lir->lor", gate, A, optimize=True)

    def _two_site(self, A, B, gate4):
        Dl, _, Dm = A.shape
        Dm2, _, Dr = B.shape
        if Dm != Dm2:
            raise RuntimeError("MPS incompatible")

        theta = np.einsum("aib,bjc->aijc", A, B, optimize=True)
        theta4 = theta.reshape(Dl, 4, Dr)
        theta4 = np.einsum("pq,aqc->apc", gate4, theta4, optimize=True)
        theta = theta4.reshape(Dl, 2, 2, Dr)

        matrix = theta.reshape(Dl * 2, 2 * Dr)
        U, S, Vh = np.linalg.svd(matrix, full_matrices=False)

        s2 = np.abs(S) ** 2
        total = float(np.sum(s2))
        keep_by_cutoff = int(np.count_nonzero(S > self.svd_cutoff))
        keep = max(1, min(self.max_bond, keep_by_cutoff))

        discarded = 0.0
        if total > 0 and keep < len(S):
            discarded = float(np.sum(s2[keep:]) / total)

        did_truncate = keep < len(S)

        U = U[:, :keep]
        S = S[:keep]
        Vh = Vh[:keep, :]

        kept_norm = float(np.linalg.norm(S))
        original_norm = math.sqrt(total) if total > 0 else 1.0
        if kept_norm > 0 and did_truncate:
            S = S * (original_norm / kept_norm)

        A2 = U.reshape(Dl, 2, keep)
        B2 = (S[:, None] * Vh).reshape(keep, 2, Dr)
        return A2, B2, discarded, int(did_truncate)

    def _apply_adjacent(self, tensors, left, gate4):
        A2, B2, d, t = self._two_site(tensors[left], tensors[left+1], gate4)
        tensors[left], tensors[left+1] = A2, B2
        return d, t

    def _apply_nonlocal_cnot(self, tensors, control, target):
        if control == target:
            return 0.0, 0, 0

        discarded = 0.0
        truncs = 0
        swaps = 0

        # Mover el qubit target junto al control, aplicar CNOT y deshacer SWAPs.
        if control < target:
            # target viaja a control+1
            for pos in range(target - 1, control, -1):
                d, t = self._apply_adjacent(tensors, pos, SWAP)
                discarded += d; truncs += t; swaps += 1

            d, t = self._apply_adjacent(tensors, control, CNOT_LR)
            discarded += d; truncs += t

            for pos in range(control + 1, target):
                d, t = self._apply_adjacent(tensors, pos, SWAP)
                discarded += d; truncs += t; swaps += 1

        else:
            # target está a la izquierda; moverlo a control-1
            for pos in range(target, control - 1):
                d, t = self._apply_adjacent(tensors, pos, SWAP)
                discarded += d; truncs += t; swaps += 1

            d, t = self._apply_adjacent(tensors, control - 1, CNOT_RL)
            discarded += d; truncs += t

            for pos in range(control - 2, target - 1, -1):
                d, t = self._apply_adjacent(tensors, pos, SWAP)
                discarded += d; truncs += t; swaps += 1

        return discarded, truncs, swaps


# ----------------------- ANÁLISIS / PLANIFICADOR -----------------------

class DSU:
    def __init__(self, n):
        self.p = list(range(n))
        self.sz = [1] * n

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.sz[ra] < self.sz[rb]:
            ra, rb = rb, ra
        self.p[rb] = ra
        self.sz[ra] += self.sz[rb]


@dataclass
class CircuitAnalysis:
    n_qubits: int
    n_gates: int
    n_two_qubit: int
    components: List[List[int]]
    max_component: int
    average_edge_span: float
    max_edge_span: int
    estimated_cutwidth: int


@dataclass
class Plan:
    engine: str
    reason: str
    order: List[int]
    max_bond: int
    svd_cutoff: float
    analysis: CircuitAnalysis


@dataclass
class PlannerResult:
    plan: Plan
    result: object
    seconds: float
    reordered_circuit: Circuit


def analyze_circuit(circuit: Circuit, order: Optional[List[int]] = None) -> CircuitAnalysis:
    n = circuit.n
    if order is None:
        order = list(range(n))

    pos = {q: i for i, q in enumerate(order)}
    dsu = DSU(n)
    edges = []

    for g in circuit.gates:
        if g.name == "CNOT":
            dsu.union(g.a, g.b)
            edges.append((g.a, g.b))

    groups: Dict[int, List[int]] = {}
    for q in range(n):
        groups.setdefault(dsu.find(q), []).append(q)
    components = list(groups.values())

    spans = [abs(pos[a] - pos[b]) for a, b in edges]
    avg_span = float(np.mean(spans)) if spans else 0.0
    max_span = max(spans) if spans else 0

    # Cutwidth: número máximo de edges que cruzan un corte lineal.
    max_cross = 0
    for cut in range(n - 1):
        cross = 0
        for a, b in edges:
            pa, pb = pos[a], pos[b]
            lo, hi = min(pa, pb), max(pa, pb)
            if lo <= cut < hi:
                cross += 1
        max_cross = max(max_cross, cross)

    return CircuitAnalysis(
        n_qubits=n,
        n_gates=len(circuit.gates),
        n_two_qubit=len(edges),
        components=components,
        max_component=max(len(c) for c in components),
        average_edge_span=avg_span,
        max_edge_span=max_span,
        estimated_cutwidth=max_cross,
    )


def greedy_qubit_order(circuit: Circuit) -> List[int]:
    """
    Heurística simple: coloca juntos los qubits con más interacción.
    No pretende ser óptima; es una base para medir si reordenar ayuda.
    """
    n = circuit.n
    weights = [[0] * n for _ in range(n)]
    degree = [0] * n

    for g in circuit.gates:
        if g.name == "CNOT":
            weights[g.a][g.b] += 1
            weights[g.b][g.a] += 1
            degree[g.a] += 1
            degree[g.b] += 1

    unplaced = set(range(n))
    if not unplaced:
        return []

    start = max(unplaced, key=lambda q: degree[q])
    order = [start]
    unplaced.remove(start)

    while unplaced:
        best_q = None
        best_score = None

        for q in unplaced:
            interaction = sum(weights[q][p] for p in order[-4:])
            score = (interaction, degree[q])
            if best_score is None or score > best_score:
                best_score = score
                best_q = q

        order.append(best_q)
        unplaced.remove(best_q)

    return order


class AdaptivePlanner:
    """
    v0.4:
    - Exact para circuitos pequeños.
    - MPS para grandes.
    - Reordena qubits para reducir distancias de puertas.
    - Elige bond aproximado a partir del cutwidth estimado.
    """
    def __init__(
        self,
        exact_qubit_limit=20,
        max_bond_cap=128,
        min_bond=8,
        svd_cutoff=1e-12,
        enable_reordering=True,
    ):
        self.exact_qubit_limit = int(exact_qubit_limit)
        self.max_bond_cap = int(max_bond_cap)
        self.min_bond = int(min_bond)
        self.svd_cutoff = float(svd_cutoff)
        self.enable_reordering = bool(enable_reordering)

    def make_plan(self, circuit: Circuit) -> Plan:
        base_analysis = analyze_circuit(circuit)

        if circuit.n <= self.exact_qubit_limit:
            return Plan(
                engine="EXACT",
                reason=f"{circuit.n} qubits <= límite exacto {self.exact_qubit_limit}",
                order=list(range(circuit.n)),
                max_bond=0,
                svd_cutoff=0.0,
                analysis=base_analysis,
            )

        order = greedy_qubit_order(circuit) if self.enable_reordering else list(range(circuit.n))
        analysis = analyze_circuit(circuit, order=order)

        # Heurística deliberadamente conservadora.
        # Más edges cruzando cortes -> potencialmente más entrelazamiento.
        estimate = 2 ** min(analysis.estimated_cutwidth, 7)
        bond = max(self.min_bond, min(self.max_bond_cap, estimate))

        reason = (
            f"circuito grande ({circuit.n}q); "
            f"cutwidth≈{analysis.estimated_cutwidth}, "
            f"span medio≈{analysis.average_edge_span:.2f}; "
            f"MPS bond={bond}"
        )

        return Plan(
            engine="MPS",
            reason=reason,
            order=order,
            max_bond=bond,
            svd_cutoff=self.svd_cutoff,
            analysis=analysis,
        )

    def run(self, circuit: Circuit) -> PlannerResult:
        plan = self.make_plan(circuit)

        if plan.engine == "EXACT":
            t0 = time.perf_counter()
            result = ExactEngine().run(circuit)
            dt = time.perf_counter() - t0
            return PlannerResult(plan, result, dt, circuit)

        old_to_new = {old: new for new, old in enumerate(plan.order)}
        reordered = circuit.remap(old_to_new)

        t0 = time.perf_counter()
        result = MPSEngine(
            max_bond=plan.max_bond,
            svd_cutoff=plan.svd_cutoff
        ).run(reordered)
        dt = time.perf_counter() - t0

        return PlannerResult(plan, result, dt, reordered)


def fidelity(a: np.ndarray, b: np.ndarray) -> float:
    na = np.vdot(a, a).real
    nb = np.vdot(b, b).real
    if na <= 0 or nb <= 0:
        return 0.0
    ov = np.vdot(a, b)
    return float(abs(ov)**2 / (na * nb))


def theoretical_exact_memory_gib(n: int) -> float:
    return ((1 << n) * 16) / (1024 ** 3)
