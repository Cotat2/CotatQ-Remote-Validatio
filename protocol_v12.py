
"""
CotatQ v1.2 — Locked Independent Validation Protocol.

IMPORTANT:
- This file defines the cases and verdict thresholds BEFORE any v1.2 benchmark.
- The CotatQ algorithm is frozen; v1.2 adds no planner/executor optimization.
- Reproduction suite replicates v1.1.1.
- Strong-rival suite adds harder external tensor-network competitors.
"""

from cotatq_v11 import audit_suite, ALL_CONFIGS, TARGET_FAMILIES

PROTOCOL_VERSION = "1.2-independent-validation-locked-2026-08-03"

ERROR_TOL = 1e-10
PEAK_LIMIT = 1 << 24

# Engine names are part of the locked protocol.
PRIMARY_BASELINE = "opt-greedy"

ADVANCED_TN_ENGINES = [
    "opt-rg128",
    "cotengra-rg128",
    "cotengra-hyper2s",
    "quimb-auto-hq",
]

SECONDARY_QUANTUM_ENGINES = [
    "aer-mps",
    "aer-auto",
    "aer-statevector",
]

ALL_RIVALS = [
    PRIMARY_BASELINE,
    *ADVANCED_TN_ENGINES,
    *SECONDARY_QUANTUM_ENGINES,
]

# Fixed fresh-process time budgets AFTER READY/GO.
TIMEOUTS = {
    "cotatq": 30.0,
    "opt-greedy": 30.0,
    "opt-rg128": 10.0,
    "cotengra-rg128": 10.0,
    "cotengra-hyper2s": 7.0,
    "quimb-auto-hq": 10.0,
    "aer-mps": 5.0,
    "aer-auto": 5.0,
    "aer-statevector": 5.0,
}

# Verdict is intentionally demanding and is fixed before seeing v1.2 results.
VERDICT_THRESHOLDS = {
    "accuracy_failures_max": 0,

    # Against the BEST finished numerically-valid rival on each strong-rival case:
    "cold_win_rate_min": 0.70,
    "cold_geomean_min": 1.10,
    "cold_ci95_low_min": 1.00,

    "warm_win_rate_min": 0.55,
    "warm_geomean_min": 1.00,

    # At least two independent advanced competitor implementations/policies
    # must actually be available, not simply timed out/missing.
    "advanced_engine_types_available_min": 2,

    # At least half the cases need an advanced TN rival to finish correctly.
    "advanced_case_coverage_min": 0.50,
}


def reproduction_suite(mode):
    """
    Exact v1.1.1 case definitions.
    """
    if mode not in ("standard", "full"):
        raise ValueError("mode must be standard or full")
    return audit_suite(mode)


def _small_config_per_family():
    out = []
    seen = set()
    for cfg in ALL_CONFIGS:
        fam = cfg[0]
        if fam not in seen:
            out.append(cfg)
            seen.add(fam)
    return out


def _medium_large_configs():
    # ALL_CONFIGS is grouped 3 sizes per family in cotatq_v11.
    return [cfg for i, cfg in enumerate(ALL_CONFIGS) if i % 3 != 0]


def strong_rival_suite(mode):
    """
    Locked challenge set.

    STANDARD = 36 cases:
      - 12 medium/large configs * seed101 * {zero, random} = 24
      - 6 smallest configs * seed202 * {zero, random} = 12

    FULL = 90 cases:
      - 12 medium/large configs * {101,303,505} * {zero,random} = 72
      - 6 smallest configs * seed202 * 3 profiles = 18
    """
    medium_large = _medium_large_configs()
    small = _small_config_per_family()

    cases = []

    if mode == "standard":
        for family, n, depth in medium_large:
            for profile in ("zero_to_zero", "random_to_random"):
                cases.append({
                    "family": family,
                    "n": n,
                    "depth": depth,
                    "seed": 101,
                    "profile": profile,
                    "target": family in TARGET_FAMILIES,
                })

        for family, n, depth in small:
            for profile in ("zero_to_zero", "random_to_random"):
                cases.append({
                    "family": family,
                    "n": n,
                    "depth": depth,
                    "seed": 202,
                    "profile": profile,
                    "target": family in TARGET_FAMILIES,
                })

        repeats = 7

    elif mode == "full":
        for family, n, depth in medium_large:
            for seed in (101, 303, 505):
                for profile in ("zero_to_zero", "random_to_random"):
                    cases.append({
                        "family": family,
                        "n": n,
                        "depth": depth,
                        "seed": seed,
                        "profile": profile,
                        "target": family in TARGET_FAMILIES,
                    })

        for family, n, depth in small:
            for profile in (
                "zero_to_zero",
                "random_to_random",
                "checker_to_random",
            ):
                cases.append({
                    "family": family,
                    "n": n,
                    "depth": depth,
                    "seed": 202,
                    "profile": profile,
                    "target": family in TARGET_FAMILIES,
                })

        repeats = 9

    else:
        raise ValueError("mode must be standard or full")

    return cases, repeats
