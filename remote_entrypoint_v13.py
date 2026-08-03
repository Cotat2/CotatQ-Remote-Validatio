from __future__ import annotations
import argparse, json, os, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'remote_output'
OUT.mkdir(exist_ok=True)

parser = argparse.ArgumentParser()
parser.add_argument('--mode', choices=['doctor','standard','full'], required=True)
parser.add_argument('--runner-label', default='remote')
args = parser.parse_args()


def run_logged(name, argv, required=True):
    log = OUT / f'{name}.log'
    print('\n' + '=' * 110)
    print('RUN:', ' '.join(argv))
    print('LOG:', log)
    print('=' * 110)
    start = time.perf_counter()
    with log.open('w', encoding='utf-8', errors='replace') as f:
        p = subprocess.Popen(argv, cwd=HERE, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1)
        assert p.stdout is not None
        for line in p.stdout:
            print(line, end='')
            f.write(line)
        rc = p.wait()
    elapsed = time.perf_counter() - start
    print(f'[{name}] returncode={rc} elapsed={elapsed:.1f}s')
    if required and rc != 0:
        raise SystemExit(rc)
    return {'name':name,'returncode':rc,'elapsed_seconds':elapsed,'log':str(log.name)}

summary = {
    'mode': args.mode,
    'runner_label': args.runner_label,
    'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    'steps': [],
}

# Remote-kit lock, then original scientific patch lock.
summary['steps'].append(run_logged('00_remote_kit_verify', [sys.executable, 'validate_remote_kit_v13.py']))
summary['steps'].append(run_logged('01_frozen_protocol_verify', [sys.executable, 'verify_patch_v122.py']))
summary['steps'].append(run_logged('02_hardware_probe', [sys.executable, 'remote_hardware_probe_v13.py']))
summary['steps'].append(run_logged('03_strict_doctor', [sys.executable, 'doctor_v122.py']))

if args.mode in ('standard','full'):
    summary['steps'].append(run_logged(
        f'10_reproduction_{args.mode}',
        [sys.executable, 'independent_validation_v122.py', '--suite', 'reproduction', '--mode', args.mode, '--runner-label', args.runner_label]
    ))
    summary['steps'].append(run_logged(
        f'20_strong_{args.mode}',
        [sys.executable, 'independent_validation_v122.py', '--suite', 'strong', '--mode', args.mode, '--runner-label', args.runner_label]
    ))

summary['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
summary_path = OUT / f'REMOTE_ENTRYPOINT_SUMMARY_{args.mode}.json'
summary_path.write_text(json.dumps(summary, indent=2), encoding='utf-8')
print('\nSaved:', summary_path)
