
"""
CotatQ v1.0 — Scientific Validation helpers.

This file deliberately expands beyond the exact random-matching LongRange family
used in v0.8/v0.9.

Target families:
  random_matching
  small_world
  hub_spoke
  dense_longrange

Negative/control family:
  local_brickwork

The point is to test whether CotatQ's scalar GraphTN advantage generalizes or
collapses when topology changes.
"""
import math
import numpy as np

from cotatq_v04 import (
    Circuit,
    brickwork_circuit,
    sparse_long_range_circuit,
)


TARGET_FAMILIES = {
    "random_matching",
    "small_world",
    "hub_spoke",
    "dense_longrange",
}

CONTROL_FAMILIES = {
    "local_brickwork",
}


def small_world_circuit(n: int, depth: int, seed: int):
    rng = np.random.default_rng(seed)
    c = Circuit(n)

    for d in range(depth):
        for q in range(n):
            c.ry(q, float(rng.uniform(-np.pi, np.pi)))

        # Local backbone.
        start = d % 2
        for q in range(start, n - 1, 2):
            c.cnot(q, q + 1)

        # A modest number of long-range chords.
        chords = max(1, n // 8)
        chosen = set()
        attempts = 0

        while len(chosen) < chords and attempts < 10000:
            a, b = map(int, rng.choice(n, size=2, replace=False))
            attempts += 1

            if abs(a - b) < max(2, n // 5):
                continue

            key = (min(a, b), max(a, b))
            if key in chosen:
                continue
            chosen.add(key)

        for a, b in chosen:
            # Randomize direction too.
            if rng.random() < 0.5:
                c.cnot(a, b)
            else:
                c.cnot(b, a)

    return c


def hub_spoke_circuit(n: int, depth: int, seed: int):
    rng = np.random.default_rng(seed)
    c = Circuit(n)

    for d in range(depth):
        for q in range(n):
            c.ry(q, float(rng.uniform(-np.pi, np.pi)))

        hubs = list(map(int, rng.choice(n, size=min(2, n), replace=False)))
        targets = list(map(int, rng.permutation(n)))

        for hub in hubs:
            count = 0
            for t in targets:
                if t == hub:
                    continue
                c.cnot(hub, t)
                count += 1
                if count >= max(2, n // 6):
                    break

    return c


def dense_longrange_circuit(n: int, depth: int, seed: int):
    """
    Harder/adversarial family:
    two independent random perfect-match CNOT layers per depth.

    Some cases intentionally exceed CotatQ's configured peak-rank safety limit.
    Those are counted honestly rather than silently removed.
    """
    rng = np.random.default_rng(seed)
    c = Circuit(n)

    for d in range(depth):
        for q in range(n):
            c.ry(q, float(rng.uniform(-np.pi, np.pi)))

        for _ in range(2):
            perm = list(map(int, rng.permutation(n)))
            for i in range(0, n - 1, 2):
                c.cnot(perm[i], perm[i + 1])

    return c


def make_circuit(family: str, n: int, depth: int, seed: int):
    if family == "random_matching":
        return sparse_long_range_circuit(n, depth, seed=seed)
    if family == "small_world":
        return small_world_circuit(n, depth, seed)
    if family == "hub_spoke":
        return hub_spoke_circuit(n, depth, seed)
    if family == "dense_longrange":
        return dense_longrange_circuit(n, depth, seed)
    if family == "local_brickwork":
        return brickwork_circuit(n, depth, seed=seed)
    raise ValueError(f"Unknown family: {family}")


def query_bits(query: str, n: int, seed: int):
    if query == "zero":
        return [0] * n

    if query == "checker":
        return [q & 1 for q in range(n)]

    if query == "random":
        # Separate deterministic stream from circuit generation.
        rng = np.random.default_rng(1_000_003 + 7919 * seed + 17 * n)
        return list(map(int, rng.integers(0, 2, size=n)))

    raise ValueError(f"Unknown query: {query}")


def cotat_basis_index(bits):
    """
    CotatQ ExactEngine basis order is |q0 q1 ... q(n-1)>,
    so q0 is the most significant bit in the flattened vector.
    """
    n = len(bits)
    return sum(int(bits[q]) << (n - 1 - q) for q in range(n))


def qiskit_basis_index(bits):
    """
    Qiskit basis integer uses q0 as the least significant bit.
    """
    return sum(int(bits[q]) << q for q in range(len(bits)))


CONFIGS = [
    # Original-like target family.
    ("random_matching", 20, 2),
    ("random_matching", 40, 3),
    ("random_matching", 80, 3),
    ("random_matching", 100, 2),

    # Mixed local/long-range topology.
    ("small_world", 20, 2),
    ("small_world", 40, 2),
    ("small_world", 60, 3),
    ("small_world", 80, 2),

    # High-degree long-range topology.
    ("hub_spoke", 20, 2),
    ("hub_spoke", 40, 2),
    ("hub_spoke", 60, 3),
    ("hub_spoke", 80, 2),

    # Deliberately harder/adversarial long-range topology.
    ("dense_longrange", 20, 2),
    ("dense_longrange", 30, 2),
    ("dense_longrange", 40, 2),
    ("dense_longrange", 60, 2),

    # Negative/control family: mostly local interactions.
    ("local_brickwork", 20, 4),
    ("local_brickwork", 40, 6),
    ("local_brickwork", 60, 8),
]


def suite(mode: str):
    if mode == "quick":
        configs = [
            ("random_matching", 20, 2),
            ("random_matching", 40, 3),
            ("small_world", 40, 2),
            ("hub_spoke", 40, 2),
            ("dense_longrange", 30, 2),
            ("local_brickwork", 40, 6),
        ]
        seeds = [11]
        queries = ["zero", "random"]
        repeats = 3

    elif mode == "standard":
        configs = CONFIGS
        seeds = [11, 22]
        queries = ["zero", "random"]
        repeats = 5

    elif mode == "full":
        configs = CONFIGS
        seeds = [11, 22, 33, 44, 55]
        queries = ["zero", "checker", "random"]
        repeats = 7

    else:
        raise ValueError("mode must be quick, standard or full")

    cases = []
    for family, n, depth in configs:
        for seed in seeds:
            for query in queries:
                cases.append({
                    "family": family,
                    "n": n,
                    "depth": depth,
                    "seed": seed,
                    "query": query,
                    "target": family in TARGET_FAMILIES,
                })

    return cases, repeats
