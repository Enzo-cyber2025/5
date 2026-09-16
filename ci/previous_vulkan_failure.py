"""Bounded diagnostic relay when Actions log storage is unreachable to the client.
Only a completed failed job of this repository/session may be inspected.
"""
import json
from pathlib import Path
import subprocess

c=json.load(open('ci/vulkan-candidate.json'))
job=c.get('bootstrap_failure_job')
if job:
    assert isinstance(job,int) and job>0
    base='repos/Enzo-cyber2025/5/'
    j=json.loads(subprocess.check_output(['gh','api',base+f'actions/jobs/{job}']))
    assert j['status']=='completed' and j['conclusion']=='failure'
    r=json.loads(subprocess.check_output(['gh','api',base+f"actions/runs/{j['run_id']}"]))
    assert r['head_branch']=='arena/01a09b42-5' and r['path']=='.github/workflows/vulkan-speed.yml'
    p=subprocess.run(['gh','api',base+f'actions/jobs/{job}/logs'],capture_output=True,text=True)
    text=p.stdout if p.returncode==0 else 'Previous log could not be retrieved by runner either.'
    text='\n'.join(line for line in text.splitlines() if '::add-mask::' not in line)[-100000:]
    dest=Path('evidence');dest.mkdir(exist_ok=True)
    (dest/'physical-prior-bootstrap-log.txt').write_text(text)
    # Surface the failure and its context even while the new benchmark is running.
    lines=text.splitlines()
    hits=[i for i,line in enumerate(lines) if any(x in line for x in ('Traceback','Error:','Error ', 'error:', 'Exception','failed with','ModuleNotFoundError','FileNotFoundError'))]
    excerpt='\n'.join(lines[max(0,min(hits)-8):min(len(lines),max(hits)+8)]) if hits else text[-15000:]
    excerpt=excerpt[-20000:]
    for i in range(0,len(excerpt),2500):
        chunk=excerpt[i:i+2500].replace('%','%25').replace('\r','%0D').replace('\n','%0A')
        print(f'::notice title=Prior failed bootstrap {job}::{chunk}')
