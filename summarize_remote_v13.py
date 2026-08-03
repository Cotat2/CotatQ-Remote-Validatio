from __future__ import annotations
import argparse, json, math, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'remote_output'
OUT.mkdir(exist_ok=True)
parser = argparse.ArgumentParser()
parser.add_argument('--mode', choices=['standard','full'], required=True)
args = parser.parse_args()


def newest(pattern):
    xs = sorted(HERE.glob(pattern), key=lambda p:p.stat().st_mtime, reverse=True)
    return xs[0] if xs else None

strong = newest(f'results_v122_strong_{args.mode}/raw_v122_strong_{args.mode}_*.json')
repro = newest(f'results_v122_reproduction_{args.mode}/raw_v122_reproduction_{args.mode}_*.json')
hardware = OUT / 'REMOTE_HARDWARE_v13.json'
reference = HERE / 'REFERENCE_LOCAL_v122_FULL.json'

payload = {
    'timestamp_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    'mode': args.mode,
    'strong_raw': str(strong.relative_to(HERE)) if strong else None,
    'reproduction_raw': str(repro.relative_to(HERE)) if repro else None,
}

if hardware.exists():
    payload['hardware'] = json.loads(hardware.read_text(encoding='utf-8'))
if reference.exists():
    payload['local_reference_full'] = json.loads(reference.read_text(encoding='utf-8'))

if strong:
    data = json.loads(strong.read_text(encoding='utf-8'))
    payload['verdict'] = data.get('verdict')
    payload['strong_summary'] = data.get('strong_summary')
    payload['replication_summary_from_strong_suite'] = data.get('replication_summary')
    payload['advanced_types_available'] = data.get('advanced_types_available')
    payload['advanced_case_coverage'] = data.get('advanced_case_coverage')
    payload['environment'] = data.get('environment')

if repro:
    data = json.loads(repro.read_text(encoding='utf-8'))
    payload['reproduction_suite_summary'] = data.get('replication_summary')

out_json = OUT / f'REMOTE_RESULT_SUMMARY_{args.mode}.json'
out_json.write_text(json.dumps(payload, indent=2), encoding='utf-8')

# Also human-readable markdown.
s = payload.get('strong_summary') or {}
lines = [
    f'# CotatQ v1.3 Remote Reproduction — {args.mode.upper()}',
    '',
    f"**Verdict:** {payload.get('verdict','N/A')}",
    '',
    '## Best valid rival score',
    '',
    f"- Cases/scorable: {s.get('cases','N/A')}/{s.get('scorable','N/A')}",
    f"- Cold W/T/L: {s.get('cold_wins','N/A')}/{s.get('cold_ties','N/A')}/{s.get('cold_losses','N/A')}",
    f"- Cold win rate: {100*s['cold_win_rate']:.1f}%" if s.get('cold_win_rate') is not None else '- Cold win rate: N/A',
    f"- Cold geometric mean: {s.get('cold_geomean','N/A')}",
    f"- Cold 95% CI: {s.get('cold_ci95_low','N/A')} — {s.get('cold_ci95_high','N/A')}",
    f"- Warm W/T/L: {s.get('warm_wins','N/A')}/{s.get('warm_ties','N/A')}/{s.get('warm_losses','N/A')}",
    f"- Warm win rate: {100*s['warm_win_rate']:.1f}%" if s.get('warm_win_rate') is not None else '- Warm win rate: N/A',
    f"- Warm geometric mean: {s.get('warm_geomean','N/A')}",
    f"- Advanced case coverage: {100*payload.get('advanced_case_coverage',0):.1f}%",
    f"- Advanced rivals: {payload.get('advanced_types_available',[])}",
    '',
    '## Interpretation rule',
    '',
    'This is a remote cross-environment reproduction of the locked v1.2.2 benchmark. It is stronger than another run on the same PC, but it is not peer review or proof of general quantum advantage.',
]
out_md = OUT / f'REMOTE_RESULT_SUMMARY_{args.mode}.md'
out_md.write_text('\n'.join(lines), encoding='utf-8')
print(out_md.read_text(encoding='utf-8'))
print('Saved:', out_json)
print('Saved:', out_md)
