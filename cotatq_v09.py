
"""
CotatQ v0.9 — Incremental Contraction Planner

v0.8 showed that GraphTN's numerical kernel was already fast, while planning
dominated end-to-end runtime.

v0.9 keeps the SAME greedy objective as the fast v0.7.1 family:
    1) minimize resulting intermediate rank
    2) prefer contracting more shared indices
    3) prefer lower combined input rank

But changes the implementation fundamentally:

OLD:
    after every contraction:
      rebuild label ownership
      rebuild every candidate pair
      rescore the entire graph

NEW:
    maintain label ownership incrementally
    maintain candidate contractions in a heap
    update only the neighborhood touched by the merge

The executor also uses stable tensor IDs in a dictionary instead of repeatedly
deleting and reindexing Python lists.

This is an implementation/algorithm-engineering improvement, not a claim that
greedy tensor contraction or priority queues are new scientific principles.
"""

from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional
import heapq
import hashlib
import json
import time
import numpy as np

from cotatq_v04 import Circuit
from cotatq_v07 import CircuitTensorNetwork, TensorNode

C128 = np.complex128


@dataclass
class IncrementalPlan:
    # Stable IDs: (left_id, right_id, new_id)
    steps: List[Tuple[int, int, int]]
    estimated_peak_rank: int
    estimated_peak_elements: int
    planner_seconds: float
    initial_node_count: int


@dataclass
class PreparedIncremental:
    nodes: List[TensorNode]
    plan: IncrementalPlan


@dataclass
class IncrementalResult:
    amplitude: complex
    planner_seconds: float
    kernel_seconds: float
    total_seconds: float
    estimated_peak_rank: int
    actual_peak_rank: int
    actual_peak_elements: int
    steps: int


def _merge_labels(a: Tuple[int, ...], b: Tuple[int, ...]):
    # Circuit TN labels are small tuples, so this is faster than heavyweight graph objects.
    bset = set(b)
    shared = [x for x in a if x in bset]
    shared_set = set(shared)
    out = tuple(
        [x for x in a if x not in shared_set] +
        [x for x in b if x not in shared_set]
    )
    return out, len(shared)


class IncrementalGraphPlanner:
    """
    Incremental min-intermediate-rank greedy contraction planner.

    Complexity improvement comes from not rescanning the entire tensor network
    after each merge. Only candidates adjacent to the newly-created tensor are
    inserted into the heap.
    """

    def plan(self, nodes: List[TensorNode]) -> IncrementalPlan:
        t0 = time.perf_counter()

        labels: Dict[int, Tuple[int, ...]] = {
            i: tuple(node.labels) for i, node in enumerate(nodes)
        }
        active = set(labels)
        version = {i: 0 for i in labels}

        # label -> active tensor IDs owning that index.
        owners: Dict[int, set] = {}
        for tid, labs in labels.items():
            for lab in labs:
                owners.setdefault(lab, set()).add(tid)

        heap = []

        def push_pair(i: int, j: int):
            if i == j or i not in active or j not in active:
                return
            if i > j:
                i, j = j, i

            out, shared = _merge_labels(labels[i], labels[j])
            if shared == 0:
                return

            # Same greedy objective used by v0.7.1.
            score = (
                len(out),
                -shared,
                len(labels[i]) + len(labels[j]),
                i,
                j,
                version[i],
                version[j],
            )
            heapq.heappush(heap, score)

        # Initial neighboring pairs.
        initial_pairs = set()
        for own in owners.values():
            ids = list(own)
            for x in range(len(ids)):
                for y in range(x + 1, len(ids)):
                    a, b = ids[x], ids[y]
                    initial_pairs.add((min(a, b), max(a, b)))

        for i, j in initial_pairs:
            push_pair(i, j)

        steps = []
        peak_rank = max((len(x) for x in labels.values()), default=0)
        next_id = len(nodes)

        while len(active) > 1:
            chosen = None

            # Lazy heap invalidation: stale candidates cost almost nothing to discard.
            while heap:
                out_rank, neg_shared, input_rank, i, j, vi, vj = heapq.heappop(heap)

                if i not in active or j not in active:
                    continue
                if version[i] != vi or version[j] != vj:
                    continue

                out, shared = _merge_labels(labels[i], labels[j])
                if shared == 0:
                    continue

                current_key = (
                    len(out),
                    -shared,
                    len(labels[i]) + len(labels[j]),
                )
                if current_key != (out_rank, neg_shared, input_rank):
                    continue

                chosen = (i, j, out)
                break

            if chosen is None:
                # Closed disconnected components can reduce to scalar tensors.
                active_ids = list(active)
                scalars = [i for i in active_ids if len(labels[i]) == 0]

                if len(scalars) >= 2:
                    i, j = scalars[0], scalars[1]
                    out = ()
                elif scalars:
                    i = scalars[0]
                    j = next(x for x in active_ids if x != i)
                    out = labels[j]
                else:
                    # Defensive fallback; ordinary circuit amplitude TNs should
                    # normally reach scalars rather than disconnected open tensors.
                    i, j = active_ids[0], active_ids[1]
                    out = tuple(labels[i] + labels[j])
            else:
                i, j, out = chosen

            new_id = next_id
            next_id += 1
            steps.append((i, j, new_id))
            peak_rank = max(peak_rank, len(out))

            # Remove old IDs only from labels they owned.
            for old in (i, j):
                for lab in labels[old]:
                    own = owners.get(lab)
                    if own is not None:
                        own.discard(old)
                        if not own:
                            owners.pop(lab, None)

                active.remove(old)
                version[old] += 1

            # Add merged tensor.
            labels[new_id] = out
            version[new_id] = 0
            active.add(new_id)

            # Only new neighbors can create new useful contraction candidates.
            neighbors = set()
            for lab in out:
                own = owners.setdefault(lab, set())
                neighbors.update(own)
                own.add(new_id)

            for other in neighbors:
                push_pair(other, new_id)

        planner_seconds = time.perf_counter() - t0

        return IncrementalPlan(
            steps=steps,
            estimated_peak_rank=peak_rank,
            estimated_peak_elements=1 << peak_rank,
            planner_seconds=planner_seconds,
            initial_node_count=len(nodes),
        )


class IncrementalGraphEngine:
    def __init__(self, max_peak_rank=24):
        self.max_peak_rank = int(max_peak_rank)
        self.planner = IncrementalGraphPlanner()

    def prepare(self, circuit: Circuit, input_bits=None, output_bits=None):
        nodes = CircuitTensorNetwork(circuit, input_bits, output_bits).build()
        plan = self.planner.plan(nodes)

        if plan.estimated_peak_rank > self.max_peak_rank:
            raise MemoryError(
                f"Estimated peak rank {plan.estimated_peak_rank} exceeds safety "
                f"limit {self.max_peak_rank}."
            )

        return PreparedIncremental(nodes=nodes, plan=plan)

    @staticmethod
    def _contract_pair(a: TensorNode, b: TensorNode):
        # Precompute label -> axis for b. Tensor ranks here are generally small.
        bpos = {lab: idx for idx, lab in enumerate(b.labels)}
        shared = [lab for lab in a.labels if lab in bpos]

        if shared:
            apos = {lab: idx for idx, lab in enumerate(a.labels)}
            axes_a = [apos[x] for x in shared]
            axes_b = [bpos[x] for x in shared]

            data = np.tensordot(a.data, b.data, axes=(axes_a, axes_b))

            shared_set = set(shared)
            out_labels = tuple(
                [x for x in a.labels if x not in shared_set] +
                [x for x in b.labels if x not in shared_set]
            )
        else:
            # Scalar multiplication / defensive disconnected fallback.
            data = np.tensordot(a.data, b.data, axes=0)
            out_labels = tuple(a.labels + b.labels)

        return TensorNode(np.asarray(data, dtype=C128), out_labels)

    def execute(self, prepared: PreparedIncremental) -> IncrementalResult:
        # Stable IDs eliminate O(N) list deletions/reindexing on every contraction.
        work = {i: node for i, node in enumerate(prepared.nodes)}

        actual_peak_rank = max((len(n.labels) for n in work.values()), default=0)
        actual_peak_elements = max((int(n.data.size) for n in work.values()), default=1)

        t0 = time.perf_counter()

        for i, j, new_id in prepared.plan.steps:
            a = work.pop(i)
            b = work.pop(j)

            merged = self._contract_pair(a, b)
            work[new_id] = merged

            actual_peak_rank = max(actual_peak_rank, len(merged.labels))
            actual_peak_elements = max(actual_peak_elements, int(merged.data.size))

        kernel_seconds = time.perf_counter() - t0

        if len(work) != 1:
            raise RuntimeError("Contraction did not reduce to one tensor")

        final = next(iter(work.values()))
        if final.labels:
            raise RuntimeError("Contraction did not reduce to a scalar")

        amp = complex(np.asarray(final.data).reshape(()))

        return IncrementalResult(
            amplitude=amp,
            planner_seconds=prepared.plan.planner_seconds,
            kernel_seconds=kernel_seconds,
            total_seconds=prepared.plan.planner_seconds + kernel_seconds,
            estimated_peak_rank=prepared.plan.estimated_peak_rank,
            actual_peak_rank=actual_peak_rank,
            actual_peak_elements=actual_peak_elements,
            steps=len(prepared.plan.steps),
        )

    def amplitude(self, circuit: Circuit, input_bits=None, output_bits=None):
        prepared = self.prepare(circuit, input_bits, output_bits)
        return self.execute(prepared)


# ---------------------------------------------------------------------------
# Optional topology cache for parameter sweeps.
# This is NOT used in the cold one-shot fire benchmark.
# ---------------------------------------------------------------------------

def topology_key(circuit: Circuit) -> str:
    """
    Hash circuit topology while ignoring continuous rotation angles.

    Reusing a plan is valid when the tensor-network label topology is identical;
    numerical tensor values may change.
    """
    payload = [("n", circuit.n)]
    for g in circuit.gates:
        payload.append((g.name, g.a, g.b))
    raw = repr(payload).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class InMemoryPlanCache:
    def __init__(self, engine: Optional[IncrementalGraphEngine] = None):
        self.engine = engine or IncrementalGraphEngine()
        self._plans = {}

    def prepare(self, circuit: Circuit, input_bits=None, output_bits=None):
        key = topology_key(circuit)

        # Tensor values are rebuilt because parameters may have changed.
        nodes = CircuitTensorNetwork(circuit, input_bits, output_bits).build()

        if key in self._plans:
            plan = self._plans[key]
        else:
            plan = self.engine.planner.plan(nodes)
            if plan.estimated_peak_rank > self.engine.max_peak_rank:
                raise MemoryError(
                    f"Estimated peak rank {plan.estimated_peak_rank} exceeds safety "
                    f"limit {self.engine.max_peak_rank}."
                )
            self._plans[key] = plan

        return PreparedIncremental(nodes=nodes, plan=plan)

    def clear(self):
        self._plans.clear()
