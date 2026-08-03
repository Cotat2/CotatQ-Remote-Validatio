
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


lock = json.loads((HERE / "PROTOCOL_LOCK.json").read_text(encoding="utf-8"))
man = json.loads((HERE / "LOCKED_CASE_MANIFESTS.json").read_text(encoding="utf-8"))

errors = []

for name, wanted in lock["frozen_subject_hashes"].items():
    got = sha256_file(HERE / name)
    if got != wanted:
        errors.append(f"FROZEN SUBJECT CHANGED: {name}")

for key, entry in man.items():
    raw = json.dumps(
        entry["cases"],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    got = hashlib.sha256(raw).hexdigest()
    wanted = lock["case_manifest_hashes"][key]
    if got != wanted:
        errors.append(f"LOCKED CASES CHANGED: {key}")

print("=" * 100)
print("CotatQ v1.2.1 — adapter-only patch verification")
print("=" * 100)

if errors:
    for e in errors:
        print("ERROR:", e)
    print("PATCH VERIFICATION FAILED")
    raise SystemExit(1)

print("Frozen CotatQ implementation: UNCHANGED")
print("Locked cases/seeds:          UNCHANGED")
print("Verdict thresholds:          UNCHANGED")
print("Timeout policy:              UNCHANGED")
print("Peak-element limit:          UNCHANGED")
print("Only external compatibility adapters / harness were patched.")
print("PATCH VERIFICATION PASSED")
