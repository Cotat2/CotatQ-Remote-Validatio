from __future__ import annotations
import argparse, time, zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
OUT=HERE/'remote_output'; OUT.mkdir(exist_ok=True)
parser=argparse.ArgumentParser(); parser.add_argument('--mode',choices=['doctor','standard','full'],required=True); args=parser.parse_args()
stamp=time.strftime('%Y%m%d_%H%M%S')
out=OUT/f'CotatQ_v13_REMOTE_{args.mode.upper()}_{stamp}.zip'
include_files=[
 'PROTOCOL_LOCK.json','LOCKED_CASE_MANIFESTS.json','FROZEN_SUBJECT_HASHES.json','PATCH_LOCK_v122.json',
 'REMOTE_PROTOCOL_LOCK_v13.json','REFERENCE_LOCAL_v122_FULL.json','README_GITHUB_REMOTE.md','CLAIMS_POLICY.md',
 'doctor_v122_latest.json','aer_mps_diagnostic_v122_latest.json'
]
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
    for name in include_files:
        p=HERE/name
        if p.exists(): z.write(p,arcname=name)
    for p in OUT.rglob('*'):
        if p.is_file() and p != out: z.write(p,arcname=str(p.relative_to(HERE)))
    for d in HERE.glob('results_v122_*'):
        if d.is_dir():
            for p in d.rglob('*'):
                if p.is_file(): z.write(p,arcname=str(p.relative_to(HERE)))
print('REMOTE BUNDLE:',out)
