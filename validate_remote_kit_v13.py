from __future__ import annotations
import hashlib, json, subprocess, sys
from pathlib import Path
HERE=Path(__file__).resolve().parent

def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

lock=json.loads((HERE/'REMOTE_PROTOCOL_LOCK_v13.json').read_text(encoding='utf-8'))
errors=[]
for name,wanted in lock['remote_files'].items():
    p=HERE/name
    if not p.exists(): errors.append(f'MISSING REMOTE FILE: {name}'); continue
    got=sha(p)
    if got!=wanted: errors.append(f'REMOTE FILE CHANGED: {name}\n expected={wanted}\n got={got}')
if sha(HERE/'PROTOCOL_LOCK.json') != lock['parent_protocol_lock_sha256']:
    errors.append('PARENT PROTOCOL_LOCK CHANGED')
if sha(HERE/'PATCH_LOCK_v122.json') != lock['parent_patch_lock_v122_sha256']:
    errors.append('PARENT PATCH_LOCK_v122 CHANGED')
if sha(HERE/'LOCKED_CASE_MANIFESTS.json') != lock['parent_locked_cases_sha256']:
    errors.append('PARENT LOCKED CASES CHANGED')

print('='*100)
print('CotatQ v1.3 remote kit verification')
print('='*100)
if errors:
    for e in errors: print('ERROR:',e)
    raise SystemExit(1)
print('Remote orchestration files: OK')
print('Parent v1.2.2 protocol files: OK')
print('Scientific subject: CotatQ v1.2.2 unchanged')
print('REMOTE KIT VERIFICATION PASSED')
