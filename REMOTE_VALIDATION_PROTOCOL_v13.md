# CotatQ v1.3 Remote Validation Protocol

## Frozen scientific subject

The scientific subject is CotatQ v1.2.2. v1.3 is orchestration only.

The original `PROTOCOL_LOCK.json`, `LOCKED_CASE_MANIFESTS.json`, `PATCH_LOCK_v122.json` and frozen source files are preserved.

## Remote environments

The STANDARD and FULL workflows use an OS matrix:

- GitHub-hosted Ubuntu (`ubuntu-latest`)
- GitHub-hosted Windows (`windows-latest`)
- Python 3.14
- exact pinned Python dependencies
- one-thread environment variables for numerical libraries

The runner image version and basic hardware characteristics are recorded with each run.

## STANDARD

Each OS independently executes:

- strict doctor;
- 72-case reproduction STANDARD;
- 36-case Strong-Rival STANDARD.

## FULL

Each OS independently executes:

- strict doctor;
- 270-case reproduction FULL;
- 90-case Strong-Rival FULL.

FULL is manual and requires an explicit checkbox in the GitHub UI.

## Scoring

No v1.3 scoring exists. Results are scored by the unchanged v1.2.2 runner and locked v1.2 protocol.

## Evidence preservation

Every job uploads:

- raw JSON;
- case CSV;
- row CSV;
- Markdown reports;
- environment manifests;
- doctor output;
- Aer MPS diagnostic;
- terminal logs;
- protocol/hash locks;
- a zipped evidence bundle.

## Claim boundary

Passing on hosted runners supports cross-environment reproducibility of this specialized classical single-amplitude benchmark. It does not establish a physical quantum computer, general simulator superiority, quantum advantage or peer-reviewed algorithmic novelty.
