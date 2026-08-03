# CotatQ v1.2.1 — Compatibility-Fixed Strong Rival Audit

This is an **adapter-only patch** to CotatQ v1.2.

The CotatQ implementation and locked scientific protocol are unchanged.

## Do this now

You already completed the v1.2 72-case reproduction successfully.

So on the same PC you only need:

```bat
run_v121_doctor.bat
```

If every required engine is `OK`, run:

```bat
run_v121_strong_standard.bat
```

Do **not** run the FULL yet.

## Required doctor engines

The benchmark is blocked unless these tiny checks all run and agree numerically:

- CotatQ
- opt_einsum greedy
- opt_einsum random-greedy-128
- cotengra RandomGreedy 128
- cotengra Hyper 2s
- quimb serial HQ stack
- Aer MPS
- Aer Automatic
- Aer statevector

## What result matters

The 36-case Strong STANDARD still uses the original locked thresholds.

The headline result remains:

> CotatQ vs the fastest finished numerically-valid rival in each case.

The two previously broken rival adapters now get a real chance to win.

If CotatQ loses more cases after this fix, that is a valid scientific result and
must be kept.

## Full

Only after the fixed STANDARD is inspected:

```bat
run_v121_strong_full.bat
```

That executes the original locked 90-case strong-rival challenge.
