
"""
CotatQ v0.7 — Swapless Graph Tensor Network

This backend targets SCALAR QUERIES such as:
    <000...0| U |000...0>

It does NOT materialize the full 2^n statevector.
That distinction is essential: v0.7 is a specialized backend, not a claim that
a full arbitrary quantum state can be compressed for free.

Main idea:
Represent the circuit itself as a tensor network.
Long-range CNOTs connect their two wires directly, so no SWAP routing is needed.

Contraction path:
CotatQ uses its own graph-aware greedy planner with limited 1-step lookahead.
This planner is experimental; tensor-network contraction ordering itself is a
known research field and is not claimed as a new principle.
"""

from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional
import math
import time
import numpy as np

from cotatq_v04 import Circuit, H, X, CNOT_LR, ry

C128 = np.complex128


@dataclass
class TensorNode:
    data: np.ndarray
    labels: Tuple[int, ...]


@dataclass
class GraphPlan:
    path: List[Tuple[int, int]]
    estimated_peak_rank: int
    estimated_peak_elements: int
    estimated_log2_flops: float
    steps: int
    planner_seconds: float


@dataclass
class GraphResult:
    amplitude: complex
    planner_seconds: float
    kernel_seconds: float
    total_seconds: float
    estimated_peak_rank: int
    estimated_peak_elements: int
    actual_peak_rank: int
    actual_peak_elements: int
    steps: int


def _cnot_tensor():
    # CNOT_LR is 4x4 with basis |control,target>.
    # Tensor index order: out_c, out_t, in_c, in_t.
    return np.asarray(CNOT_LR, dtype=C128).reshape(2, 2, 2, 2)


CNOT4 = _cnot_tensor()
ZERO_KET = np.array([1.0 + 0j, 0.0 + 0j], dtype=C128)
ZERO_BRA = np.array([1.0 + 0j, 0.0 + 0j], dtype=C128)


class CircuitTensorNetwork:
    """
    Builds the closed tensor network for one amplitude:
        <output_bits| U |input_bits>

    v0.7 currently defaults to all-zero input/output.
    """

    def __init__(self, circuit: Circuit, input_bits=None, output_bits=None):
        self.circuit = circuit
        n = circuit.n

        if input_bits is None:
            input_bits = [0] * n
        if output_bits is None:
            output_bits = [0] * n

        if len(input_bits) != n or len(output_bits) != n:
            raise ValueError("input_bits/output_bits must have n entries")

        self.input_bits = list(map(int, input_bits))
        self.output_bits = list(map(int, output_bits))
        if any(b not in (0,1) for b in self.input_bits + self.output_bits):
            raise ValueError("bits must be 0 or 1")

    def build(self) -> List[TensorNode]:
        c = self.circuit
        n = c.n
        nodes: List[TensorNode] = []

        next_label = 0
        current = [None] * n

        # Initial states.
        for q in range(n):
            lab = next_label
            next_label += 1
            current[q] = lab
            vec = ZERO_KET if self.input_bits[q] == 0 else np.array([0,1], dtype=C128)
            nodes.append(TensorNode(vec.copy(), (lab,)))

        # Gates.
        for g in c.gates:
            if g.name in ("H", "X", "RY"):
                inp = current[g.a]
                out = next_label
                next_label += 1

                if g.name == "H":
                    mat = H
                elif g.name == "X":
                    mat = X
                else:
                    mat = ry(g.theta)

                # U[out, in]
                nodes.append(TensorNode(np.asarray(mat, dtype=C128).copy(), (out, inp)))
                current[g.a] = out

            elif g.name == "CNOT":
                ic = current[g.a]
                it = current[g.b]
                oc = next_label
                ot = next_label + 1
                next_label += 2

                nodes.append(TensorNode(CNOT4.copy(), (oc, ot, ic, it)))
                current[g.a] = oc
                current[g.b] = ot

            else:
                raise ValueError(f"Unsupported gate {g.name}")

        # Final bra states.
        for q in range(n):
            lab = current[q]
            vec = ZERO_BRA if self.output_bits[q] == 0 else np.array([0,1], dtype=C128)
            nodes.append(TensorNode(vec.copy(), (lab,)))

        return nodes


def _merge_labels(a: Tuple[int, ...], b: Tuple[int, ...]):
    aset = set(a)
    bset = set(b)
    shared = aset & bset
    out = tuple([x for x in a if x not in shared] + [x for x in b if x not in shared])
    return out, shared


def _local_score(a, b):
    out, shared = _merge_labels(a, b)
    # All dimensions are 2.
    out_rank = len(out)
    union_rank = len(set(a) | set(b))
    # Prioritize intermediate rank, then rough flop exponent.
    return (out_rank, union_rank, -len(shared))


class CotatGraphPlanner:
    """
    Graph-aware pairwise contraction planner.

    Instead of considering every pair, candidate pairs are tensors that share at
    least one index. Among the best local candidates, a one-step lookahead picks
    the choice with the lowest projected peak rank.

    The planner works only on labels, so it does not allocate giant tensors.
    """

    def __init__(self, lookahead_candidates=10):
        self.lookahead_candidates = int(lookahead_candidates)

    @staticmethod
    def _candidate_pairs(label_sets):
        label_to_nodes: Dict[int, List[int]] = {}
        for i, labs in enumerate(label_sets):
            for lab in labs:
                label_to_nodes.setdefault(lab, []).append(i)

        pairs = set()
        for owners in label_to_nodes.values():
            if len(owners) == 2:
                i, j = owners
                if i != j:
                    pairs.add((min(i,j), max(i,j)))
            elif len(owners) > 2:
                # This should not happen for the circuit TN we build, but handle safely.
                for x in range(len(owners)):
                    for y in range(x+1, len(owners)):
                        i, j = owners[x], owners[y]
                        pairs.add((min(i,j), max(i,j)))
        return list(pairs)

    @staticmethod
    def _simulate_merge(label_sets, i, j):
        out, _ = _merge_labels(label_sets[i], label_sets[j])
        new = []
        for k, labs in enumerate(label_sets):
            if k not in (i, j):
                new.append(labs)
        new.append(out)
        return new, out

    def _best_next_rank(self, label_sets):
        pairs = self._candidate_pairs(label_sets)
        if not pairs:
            return 0
        best = None
        for i, j in pairs:
            out, _ = _merge_labels(label_sets[i], label_sets[j])
            r = len(out)
            if best is None or r < best:
                best = r
        return best if best is not None else 0

    def plan(self, nodes: List[TensorNode]) -> GraphPlan:
        t0 = time.perf_counter()

        # We store the path using dynamic list positions, matching the executor.
        label_sets = [tuple(n.labels) for n in nodes]
        path = []
        peak_rank = max((len(x) for x in label_sets), default=0)
        log2_flops_terms = []

        while len(label_sets) > 1:
            pairs = self._candidate_pairs(label_sets)

            if not pairs:
                # Closed disconnected components may already be scalar.
                scalar_idxs = [i for i, labs in enumerate(label_sets) if len(labs) == 0]
                if len(scalar_idxs) >= 2:
                    i, j = scalar_idxs[0], scalar_idxs[1]
                    out = ()
                    projected = 0
                    flop_exp = 0
                elif scalar_idxs:
                    i = scalar_idxs[0]
                    j = 0 if i != 0 else 1
                    out, _ = _merge_labels(label_sets[i], label_sets[j])
                    projected = len(out)
                    flop_exp = len(set(label_sets[i]) | set(label_sets[j]))
                else:
                    raise RuntimeError("Tensor network disconnected with open indices")
            else:
                # First rank by cheap local score.
                ranked = sorted(
                    pairs,
                    key=lambda ij: _local_score(label_sets[ij[0]], label_sets[ij[1]])
                )
                shortlist = ranked[:max(1, self.lookahead_candidates)]

                best_key = None
                best = None
                for i, j in shortlist:
                    merged_sets, out = self._simulate_merge(label_sets, i, j)
                    out_rank = len(out)
                    next_rank = self._best_next_rank(merged_sets) if len(merged_sets) > 1 else 0
                    flop_exp = len(set(label_sets[i]) | set(label_sets[j]))
                    key = (max(out_rank, next_rank), out_rank, flop_exp)

                    if best_key is None or key < best_key:
                        best_key = key
                        best = (i, j, out, out_rank, flop_exp)

                i, j, out, projected, flop_exp = best

            peak_rank = max(peak_rank, projected)
            log2_flops_terms.append(float(flop_exp))
            path.append((i, j))

            # Apply same dynamic-list update rule as executor: remove high index first,
            # append merged tensor.
            for k in sorted((i, j), reverse=True):
                del label_sets[k]
            label_sets.append(tuple(out))

        # log2(sum 2^exp) stably
        if log2_flops_terms:
            m = max(log2_flops_terms)
            total_log2 = m + math.log2(sum(2 ** (x - m) for x in log2_flops_terms))
        else:
            total_log2 = 0.0

        dt = time.perf_counter() - t0
        return GraphPlan(
            path=path,
            estimated_peak_rank=peak_rank,
            estimated_peak_elements=1 << peak_rank,
            estimated_log2_flops=total_log2,
            steps=len(path),
            planner_seconds=dt,
        )


class GraphTensorEngine:
    def __init__(
        self,
        lookahead_candidates=10,
        max_peak_rank=24,
    ):
        self.planner = CotatGraphPlanner(lookahead_candidates=lookahead_candidates)
        self.max_peak_rank = int(max_peak_rank)

    @staticmethod
    def _contract_pair(a: TensorNode, b: TensorNode):
        shared = [x for x in a.labels if x in set(b.labels)]

        if shared:
            axes_a = [a.labels.index(x) for x in shared]
            axes_b = [b.labels.index(x) for x in shared]
            data = np.tensordot(a.data, b.data, axes=(axes_a, axes_b))

            out_labels = tuple(
                [x for x in a.labels if x not in shared] +
                [x for x in b.labels if x not in shared]
            )
        else:
            # Scalar multiplication or disconnected outer product fallback.
            data = np.tensordot(a.data, b.data, axes=0)
            out_labels = tuple(a.labels + b.labels)

        return TensorNode(np.asarray(data, dtype=C128), out_labels)

    def amplitude(
        self,
        circuit: Circuit,
        input_bits=None,
        output_bits=None,
    ) -> GraphResult:
        nodes = CircuitTensorNetwork(circuit, input_bits, output_bits).build()
        plan = self.planner.plan(nodes)

        if plan.estimated_peak_rank > self.max_peak_rank:
            raise MemoryError(
                f"GraphTN path estimates peak rank {plan.estimated_peak_rank} "
                f"(~2^{plan.estimated_peak_rank} complex values), above safety limit "
                f"{self.max_peak_rank}."
            )

        work = nodes
        actual_peak_rank = max((len(n.labels) for n in work), default=0)
        actual_peak_elements = max((n.data.size for n in work), default=1)

        t0 = time.perf_counter()

        for i, j in plan.path:
            a = work[i]
            b = work[j]
            merged = self._contract_pair(a, b)

            actual_peak_rank = max(actual_peak_rank, len(merged.labels))
            actual_peak_elements = max(actual_peak_elements, merged.data.size)

            for k in sorted((i, j), reverse=True):
                del work[k]
            work.append(merged)

        kernel = time.perf_counter() - t0

        if len(work) != 1 or work[0].labels:
            raise RuntimeError("Contraction did not finish to a scalar")

        amp = complex(np.asarray(work[0].data).reshape(()))

        return GraphResult(
            amplitude=amp,
            planner_seconds=plan.planner_seconds,
            kernel_seconds=kernel,
            total_seconds=plan.planner_seconds + kernel,
            estimated_peak_rank=plan.estimated_peak_rank,
            estimated_peak_elements=plan.estimated_peak_elements,
            actual_peak_rank=actual_peak_rank,
            actual_peak_elements=actual_peak_elements,
            steps=plan.steps,
        )


@dataclass
class AutoScalarPlan:
    engine: str
    graph_peak_rank: Optional[int]
    reason: str


class ScalarQueryPlanner:
    """
    Specialized v0.7 dispatcher for ONE amplitude query.

    If GraphTN predicts a manageable contraction width, use the swapless graph
    backend. Otherwise report that this scalar query should fall back to another
    backend (future versions can plug MPS / stabilizer / slicing here).
    """

    def __init__(self, graph_rank_limit=24):
        self.graph_rank_limit = int(graph_rank_limit)

    def make_plan(self, circuit: Circuit):
        nodes = CircuitTensorNetwork(circuit).build()
        gp = CotatGraphPlanner().plan(nodes)

        if gp.estimated_peak_rank <= self.graph_rank_limit:
            return AutoScalarPlan(
                engine="GRAPH_TN",
                graph_peak_rank=gp.estimated_peak_rank,
                reason=(
                    f"estimated graph contraction rank={gp.estimated_peak_rank} "
                    f"<= limit {self.graph_rank_limit}; no SWAP routing required"
                )
            )

        return AutoScalarPlan(
            engine="FALLBACK",
            graph_peak_rank=gp.estimated_peak_rank,
            reason=(
                f"estimated graph contraction rank={gp.estimated_peak_rank} "
                f"> limit {self.graph_rank_limit}; avoid unsafe contraction"
            )
        )
