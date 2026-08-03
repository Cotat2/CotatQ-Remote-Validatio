
import json
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
stamp = time.strftime("%Y%m%d_%H%M%S")
out = HERE / f"CotatQ_v12_RESULT_BUNDLE_{stamp}.zip"

include_root = [
    "PROTOCOL_LOCK.json",
    "LOCKED_CASE_MANIFESTS.json",
    "FROZEN_SUBJECT_HASHES.json",
    "REFERENCE_v111_FULL.json",
    "doctor_v12_latest.json",
    "README.md",
    "CLAIMS_POLICY.md",
]

with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for name in include_root:
        p = HERE / name
        if p.exists():
            z.write(p, arcname=name)

    # Include exact frozen source so a reviewer can inspect what executed.
    for name in [
        "cotatq_v04.py",
        "cotatq_v07.py",
        "cotatq_v09.py",
        "cotatq_v10.py",
        "cotatq_v11.py",
        "protocol_v12.py",
        "external_worker_v12.py",
        "independent_validation_v12.py",
    ]:
        p = HERE / name
        if p.exists():
            z.write(p, arcname=f"source/{name}")

    for d in sorted(HERE.glob("results_v12_*")):
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if p.is_file():
                z.write(p, arcname=str(p.relative_to(HERE)))

print("RESULT BUNDLE:", out)
