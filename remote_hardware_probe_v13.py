from __future__ import annotations
import json, os, platform, subprocess, sys, time
from pathlib import Path
import psutil

HERE = Path(__file__).resolve().parent
OUT = HERE / "remote_output"
OUT.mkdir(exist_ok=True)


def cmd_text(cmd):
    try:
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=8, shell=False)
        if p.returncode == 0:
            return p.stdout.strip()[:12000]
    except Exception:
        pass
    return None

cpu_detail = platform.processor() or None
if platform.system() == 'Linux':
    text = cmd_text(['lscpu'])
    if text:
        for line in text.splitlines():
            if line.lower().startswith('model name:'):
                cpu_detail = line.split(':',1)[1].strip()
                break
elif platform.system() == 'Windows':
    text = cmd_text(['powershell','-NoProfile','-Command','(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name)'])
    if text:
        cpu_detail = text.splitlines()[0].strip()

# GitHub exposes image metadata as environment variables on hosted runners.
allowed_env = [
    'GITHUB_ACTIONS','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_WORKFLOW',
    'GITHUB_JOB','RUNNER_OS','RUNNER_ARCH','RUNNER_ENVIRONMENT',
    'ImageOS','ImageVersion','ImageLabel','AGENT_TOOLSDIRECTORY'
]

data = {
    'timestamp_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    'privacy': 'No username, hostname, IP address, repository token, or machine serial is intentionally collected.',
    'platform': platform.platform(),
    'system': platform.system(),
    'release': platform.release(),
    'machine': platform.machine(),
    'cpu_model': cpu_detail,
    'cpu_physical': psutil.cpu_count(logical=False),
    'cpu_logical': psutil.cpu_count(logical=True),
    'ram_gib': psutil.virtual_memory().total / (1024**3),
    'python': sys.version,
    'github_runner_metadata': {k: os.environ.get(k) for k in allowed_env if os.environ.get(k) is not None},
}

path = OUT / 'REMOTE_HARDWARE_v13.json'
path.write_text(json.dumps(data, indent=2), encoding='utf-8')
print(json.dumps(data, indent=2))
print('Saved:', path)
