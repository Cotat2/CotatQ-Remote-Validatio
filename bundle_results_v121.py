
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
stamp = time.strftime("%Y%m%d_%H%M%S")
out = HERE / f"CotatQ_v121_RESULT_BUNDLE_{stamp}.zip"

root_files = [
    "PROTOCOL_LOCK.json",
    "LOCKED_CASE_MANIFESTS.json",
    "FROZEN_SUBJECT_HASHES.json",
    "REFERENCE_v111_FULL.json",
    "PATCH_LOCK_v121.json",
    "doctor_v121_latest.json",
    "README_v121.md",
    "COMPATIBILITY_PATCH_v121.md",
    "CLAIMS_POLICY.md",
]

source_files = [
    "cotatq_v04.py",
    "cotatq_v07.py",
    "cotatq_v09.py",
    "cotatq_v10.py",
    "cotatq_v11.py",
    "protocol_v12.py",
    "external_worker_v121.py",
    "independent_validation_v121.py",
    "doctor_v121.py",
    "verify_patch_v121.py",
]

with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for name in root_files:
        p = HERE / name
        if p.exists():
            z.write(p, arcname=name)

    for name in source_files:
        p = HERE / name
        if p.exists():
            z.write(p, arcname=f"source/{name}")

    for d in sorted(HERE.glob("results_v121_*")):
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if p.is_file():
                z.write(p, arcname=str(p.relative_to(HERE)))

print("RESULT BUNDLE:", out)
