# CotatQ v1.3 — GitHub Remote Reproduction Kit

This repository-ready kit runs the **unchanged CotatQ v1.2.2 scientific benchmark** on fresh GitHub-hosted runners.

It does **not** optimize CotatQ and does **not** change:

- frozen CotatQ source;
- circuit cases/seeds/profiles;
- numerical tolerance;
- timeouts;
- peak-element limit;
- verdict thresholds;
- best-valid-rival scoring.

The new code only automates installation, remote execution, evidence collection and comparison.

## What one STANDARD click does

GitHub starts two clean jobs in parallel:

1. `ubuntu-latest` + Python 3.14
2. `windows-latest` + Python 3.14

Each job:

1. checks the remote-kit hashes;
2. checks the original v1.2.2 frozen protocol;
3. records non-sensitive CPU/RAM/runner metadata;
4. installs exact pinned package versions;
5. runs the strict multi-topology Aer MPS doctor;
6. runs the locked 72-case reproduction STANDARD;
7. runs the locked 36-case Strong-Rival STANDARD;
8. writes JSON/CSV/Markdown/logs;
9. uploads everything as a GitHub Actions artifact.

## Exact dependency versions

The remote run pins the versions observed on the final local validation stack:

- numpy 2.4.6
- psutil 7.2.2
- opt_einsum 3.4.0
- qiskit 2.5.1
- qiskit-aer 0.17.2
- cotengra 0.8.2
- quimb 1.14.0

## Easiest upload method

1. Create a new empty GitHub repository.
2. Extract `CotatQ_v1.3_GITHUB_REMOTE_REPRODUCTION.zip`.
3. Open the extracted folder.
4. Upload **the contents of the folder**, including `.github`, to the repository root.
5. Commit the files.
6. Open the repository's **Actions** tab.
7. Select **CotatQ Remote STANDARD**.
8. Click **Run workflow**.

Do not run FULL first.

## After STANDARD finishes

Open the completed workflow run. At the bottom, download both artifacts:

- `cotatq-v13-standard-Linux-X64-...`
- `cotatq-v13-standard-Windows-X64-...`

Inside each artifact the quickest file to inspect is:

`remote_output/REMOTE_RESULT_SUMMARY_standard.md`

The raw scientific evidence is retained too.

If both environments are healthy and the result is worth escalating, run **CotatQ Remote FULL** and tick the confirmation checkbox.

## What FULL does

On both Ubuntu and Windows:

- locked 270-case reproduction FULL;
- locked 90-case Strong-Rival FULL;
- exact same scoring and thresholds;
- automatic comparison to the completed local v1.2.2 FULL reference.

## Interpreting a remote result

The strongest simple signal is still the predeclared one:

- zero accuracy failures;
- Cold win rate >= 70% against the fastest numerically-valid rival;
- Cold geometric mean >= 1.10x;
- lower bound of Cold bootstrap 95% CI > 1.00x;
- enough advanced-rival coverage.

A remote cloud-runner result is useful cross-environment reproduction. It is **not** peer review and is **not** proof of general quantum advantage.

## Why both Windows and Linux?

The local result came from Windows. Running the same locked code on two fresh hosted environments makes it much harder for one machine-specific cache, allocator, OS or library quirk to explain the whole result.

## Privacy

The hardware probe intentionally avoids username, hostname, IP address, GitHub token and hardware serials. It records only information useful for reproducibility, such as OS, CPU model/core count, RAM, Python and runner image metadata.
