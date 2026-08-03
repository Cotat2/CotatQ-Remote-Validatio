# CotatQ v1.2.1 — Compatibility Patch

## Why this patch exists

The v1.2 STANDARD exposed two benchmark-adapter failures:

1. `cotengra-rg128`
   - installed package: cotengra 0.8.2
   - failure: `RandomGreedyOptimizer.__call__() takes 4 positional arguments but 5 were given`

2. `quimb-auto-hq`
   - installed package: quimb 1.14.0
   - failure: `BrokenProcessPool`

These are benchmark integration failures, not evidence that those libraries are slower than CotatQ.

## What changed

### cotengra RandomGreedy

v1.2 routed a `RandomGreedyOptimizer` through opt_einsum.

v1.2.1 builds:

- `inputs`
- `output`
- `size_dict`

from the exact tensor network and calls:

```python
path = optimizer(inputs, output, size_dict)
```

directly.

The explicit resulting path is then compiled into the same opt_einsum expression
used for repeated execution.

### quimb

v1.2 used the string preset:

```python
optimize="auto-hq"
```

which triggered a nested process-pool failure on the tested Windows/Python 3.14
environment.

v1.2.1 gives quimb an explicit:

```python
cotengra.ReusableHyperOptimizer(
    methods=["greedy"],
    minimize="combo",
    max_repeats=64,
    max_time=2.0,
    parallel=False,
    reconf_opts={},
    optlib="random",
)
```

Quimb then obtains a contraction tree and a reusable expression from that tree.

No nested process pool is allowed.

## What DID NOT change

- CotatQ planner
- CotatQ executor
- tensor representation
- circuit generator
- seeds
- profiles
- STANDARD/FULL case lists
- peak limit
- engine timeouts
- numerical tolerance
- scoring
- verdict thresholds

`verify_patch_v121.py` checks this before every run.

## Required workflow

Run:

```bat
run_v121_doctor.bat
```

The doctor must show all required adapters `OK` and numerical agreement.

Then run only:

```bat
run_v121_strong_standard.bat
```

The previous 72-case reproduction does not need to be repeated on the same PC.

Only after inspecting that 36-case result should the locked 90-case FULL be run.
