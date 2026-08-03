
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


expected = json.loads((HERE / "PROTOCOL_LOCK.json").read_text(encoding="utf-8"))
manifest = json.loads((HERE / "LOCKED_CASE_MANIFESTS.json").read_text(encoding="utf-8"))

errors = []

for name, wanted in expected["frozen_subject_hashes"].items():
    got = sha256_file(HERE / name)
    if got != wanted:
        errors.append(f"FROZEN SUBJECT CHANGED: {name}\n  expected {wanted}\n  got      {got}")

for key, entry in manifest.items():
    raw = json.dumps(entry["cases"], sort_keys=True, separators=(",", ":")).encode()
    got = hashlib.sha256(raw).hexdigest()
    wanted = expected["case_manifest_hashes"][key]
    if got != wanted:
        errors.append(f"CASE MANIFEST CHANGED: {key}\n  expected {wanted}\n  got      {got}")

print("=" * 94)
print("CotatQ v1.2 freeze verification")
print("Protocol:", expected["protocol_version"])
print("=" * 94)

if errors:
    for e in errors:
        print("ERROR:", e)
    print("\nFREEZE VERIFICATION FAILED.")
    raise SystemExit(1)

print("Frozen CotatQ source: OK")
print("Locked case manifests: OK")
print("Verdict thresholds: locked")
print("FREEZE VERIFICATION PASSED.")
