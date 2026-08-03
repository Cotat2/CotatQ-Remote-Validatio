# Aer MPS v1.2.2 Fix Note

## Failure discovered

v1.2.1 doctor:

- CotatQ / opt / cotengra / quimb / Aer statevector / Aer automatic agreed.
- Aer MPS differed by approximately `4.542e-02`.

The benchmark was blocked.

## Correctness policy

The Aer MPS competitor is now configured for exactness:

- no bond-dimension cap;
- coefficient truncation threshold 0;
- native MPS extraction;
- single-amplitude contraction.

Timeouts are unchanged.

This can make Aer MPS slower or cause more timeouts. That is intentional: an
exact benchmark must not reward an approximation for speed.

## Native amplitude formula

Aer represents the state as:

`Gamma[0] lambda[0] Gamma[1] ... lambda[n-2] Gamma[n-1]`

For an output bit string `b0 ... b(n-1)`, v1.2.2 computes:

`Gamma[0][b0] @ diag(lambda[0]) @ Gamma[1][b1] @ ... @ Gamma[n-1][b(n-1)]`

The diagonal lambda matrices are applied by broadcasting rather than explicitly
materialized.

## Scientific locks unchanged

- CotatQ source hashes
- cases
- seeds
- profiles
- verdict thresholds
- timeouts
- peak limits
- scoring logic

Only the external Aer MPS adapter is corrected.
