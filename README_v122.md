# CotatQ v1.2.2 — Exact Aer MPS Fix

v1.2.1 fixed cotengra and quimb, but its strict doctor discovered that the
configured Aer MPS result disagreed with the exact engines by about `4.5e-2`.

The benchmark correctly refused to run.

## What v1.2.2 changes

Only the Aer MPS competitor adapter.

The scored MPS rival now uses:

- `method="matrix_product_state"`
- **no maximum bond-dimension cap**
- `matrix_product_state_truncation_threshold=0.0`
- `save_matrix_product_state`
- direct contraction of the requested basis amplitude from the native MPS

It does not materialize the full statevector.

The original Aer MPS 128-bond command-line field is retained only for diagnostic
comparison with the old route.

## Why no bond cap?

Aer documents the default `None` bond dimension as no limit. A finite cap can
discard Schmidt coefficients and therefore turn MPS into an approximation.

For this scientific benchmark a rival must either:

1. return the correct amplitude, or
2. timeout/fail honestly.

Returning a faster approximate result is not acceptable.

## Why native MPS instead of save_amplitudes?

`save_amplitudes` is documented as MPS-compatible, but the tested v1.2.1 setup
produced a large disagreement on the doctor case.

v1.2.2 therefore asks Aer for its native MPS and evaluates the single requested
amplitude from the documented Gamma-lambda chain.

## Diagnostic

Before the benchmark, v1.2.2 compares on several topologies:

- Aer statevector reference
- old capped MPS + save_amplitudes
- uncapped MPS + save_amplitudes
- uncapped native MPS + manual amplitude
- uncapped MPS converted to full statevector (small doctor cases only)

Each variant runs in its own process.

The scored route and the full-statevector MPS cross-check MUST both pass.

## Run

First:

```bat
run_v122_doctor.bat
```

Only if it ends with:

```text
STRICT DOCTOR: PASS
```

run:

```bat
run_v122_strong_standard.bat
```

Do not run FULL yet.
