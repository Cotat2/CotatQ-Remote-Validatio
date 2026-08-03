from __future__ import annotations
import argparse, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'remote_output'; OUT.mkdir(exist_ok=True)
parser = argparse.ArgumentParser()
parser.add_argument('remote_summary')
args = parser.parse_args()
remote = json.loads(Path(args.remote_summary).read_text(encoding='utf-8'))
local = json.loads((HERE/'REFERENCE_LOCAL_v122_FULL.json').read_text(encoding='utf-8'))
lines=[]
def emit(x=''):
    print(x); lines.append(str(x))

emit('='*90)
emit('CotatQ remote vs validated local reference')
emit('='*90)
emit(f"Remote verdict: {remote.get('verdict')}")
rs = remote.get('strong_summary') or {}
ls = local['best_valid_rival_score']
emit(f"Remote cold W/T/L: {rs.get('cold_wins')} {rs.get('cold_ties')} {rs.get('cold_losses')}")
emit(f"Local  cold W/T/L: {ls['cold']['wins']} {ls['cold']['ties']} {ls['cold']['losses']}")
emit(f"Remote cold geo: {rs.get('cold_geomean')}")
emit(f"Local  cold geo: {ls['cold']['geomean']}")
emit(f"Remote cold CI: {rs.get('cold_ci95_low')} {rs.get('cold_ci95_high')}")
emit(f"Local  cold CI: {ls['cold']['ci95_low']} {ls['cold']['ci95_high']}")
emit(f"Remote warm geo: {rs.get('warm_geomean')}")
emit(f"Local  warm geo: {ls['warm']['geomean']}")
emit(f"Remote environment: {(remote.get('environment') or {}).get('environment_signature')}")
emit(f"Local  environment: {local.get('environment_signature')}")
if rs.get('cold_ci95_low') is not None:
    if rs['cold_ci95_low'] > 1.0:
        emit('REMOTE SIGNAL: cold 95% CI remains fully above 1.0x')
    else:
        emit('REMOTE SIGNAL: cold 95% CI reaches/crosses 1.0x')

path=OUT/'COMPARE_TO_LOCAL_FULL.txt'
path.write_text('\n'.join(lines)+'\n', encoding='utf-8')
emit(f'Saved: {path}')
