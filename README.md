# CotatQ v1.2 — Independent Validation Kit

CotatQ v1.1.1 survived 270 complex cases on the reference machine.

v1.2 does **not** optimize CotatQ.

Its job is to answer a harder question:

> Does the measured advantage survive stronger tensor-network competitors and a different machine/environment?

## Frozen subject

The validated implementation is frozen by SHA-256.

Run:

```bat
python verify_freeze_v12.py
```

If any frozen CotatQ source file or locked case manifest changes, the run is rejected.

## Two separate experiments

### 1. Reproduction

Same basic comparison as v1.1.1:

- frozen CotatQ;
- precompiled opt_einsum greedy;
- same complex circuit generator;
- fresh process per engine;
- neutral NumPy warmup;
- same-query amplitude validation.

This tests whether the previous result reproduces.

### 2. Strong-rival challenge

CotatQ is compared with:

- opt_einsum greedy;
- opt_einsum random-greedy-128;
- cotengra RandomGreedyOptimizer(128 trials);
- cotengra HyperOptimizer with a locked 2-second planning budget;
- quimb auto-hq using a reusable contraction tree/expression;
- Aer MPS;
- Aer Automatic;
- Aer statevector when size permits.

A rival is allowed to beat CotatQ only if its returned amplitude agrees numerically.

The headline score is against the **fastest finished numerically-valid rival** on
each case.

That is intentionally much harder than v1.1.1.

## Why cotengra and quimb?

They are dedicated tensor-network tools rather than generic statevector-only
baselines.

The protocol intentionally includes both:

- quick/high-quality path search;
- repeated prepared contraction.

## Locked case counts

### STANDARD

- reproduction: 72 cases;
- strong-rival challenge: 36 cases.

Use this first on any machine.

### FULL

- reproduction: 270 cases;
- strong-rival challenge: 90 locked cases.

The 90 strong cases include all six circuit families, small cases where Aer can
compete, and medium/large cases where tensor-network path quality matters.

## Installation

Core dependencies:

```bat
pip install -r requirements_core.txt
```

External competitors:

```bat
install_external_rivals.bat
```

Then:

```bat
run_v12_standard.bat
```

If that works:

```bat
run_v12_full.bat
```

## True independent validation

Running v1.2 again on the same PC is useful as an integration/replication check.

It is **not independent validation**.

For that, send the untouched ZIP to another person or machine and ask them to:

```bat
install_external_rivals.bat
run_v12_standard.bat
```

then, if successful:

```bat
run_v12_full.bat
```

Finally they send back the generated:

```text
CotatQ_v12_RESULT_BUNDLE_*.zip
```

No username, hostname, serial number or IP address is intentionally recorded.

## Compare two machines

Extract the two result bundles and run:

```bat
python compare_two_runs_v12.py raw_machine_A.json raw_machine_B.json
```

The tool reports:

- geometric speedup on each machine;
- common scorable cases;
- speedup correlation;
- whether the anonymous environment signatures differ.

## Locked strong-rival verdict

The threshold was fixed before running v1.2.

`STRONG-RIVAL VALIDATION SURVIVED` requires:

- 0 CotatQ accuracy failures;
- >=70% cold wins against the best valid rival;
- cold geometric mean >=1.10x;
- cold bootstrap 95% lower bound >1.00x;
- >=55% warm wins;
- warm geometric mean >1.00x;
- at least 2 advanced TN rival types available;
- an advanced TN rival finishing correctly on >=50% of challenge cases.

If advanced competitors are not installed or mostly fail, the benchmark says:

`INSUFFICIENT ADVANCED RIVAL COVERAGE`

It does not silently promote CotatQ.

## Scientific scope

CotatQ remains a classical specialized evaluator for single amplitudes of
quantum circuits represented as tensor networks.

Do not describe it as:

- a physical quantum computer;
- quantum advantage;
- the fastest quantum simulator in general;
- proof of a novel contraction algorithm.

See `CLAIMS_POLICY.md`.
