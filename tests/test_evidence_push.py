import os,subprocess
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
BRANCH='arena/test-evidence'


def run(tmp_path,mode):
    tools=tmp_path/'bin';tools.mkdir()
    git=tools/'git'
    git.write_text('''#!/usr/bin/env python3
import os,sys
from pathlib import Path
args=sys.argv[1:]
p=Path(os.environ['TEST_STATE']);p.mkdir(exist_ok=True)
with (p/'calls').open('a') as f:f.write(' '.join(args)+'\\n')
branch=os.environ['GITHUB_REF_NAME']
if args==['branch','--show-current']:
 print(branch);sys.exit(0)
if args[:1]==['pull']:
 sys.exit(1 if os.environ['TEST_MODE']=='conflict' else 0)
assert args==['push','origin',branch]
n=int((p/'count').read_text())+1 if (p/'count').exists() else 1
(p/'count').write_text(str(n));mode=os.environ['TEST_MODE']
if mode=='auth':print('Authentication failed',file=sys.stderr);sys.exit(1)
if mode=='forever' or (mode=='race' and n==1):
 print(f' ! [rejected] {branch} -> {branch} (fetch first)',file=sys.stderr);sys.exit(1)
sys.exit(0)
''');git.chmod(0o755)
    sleep=tools/'sleep';sleep.write_text('#!/bin/sh\nexit 0\n');sleep.chmod(0o755)
    state=tmp_path/'state'
    env=dict(os.environ,PATH=str(tools)+os.pathsep+os.environ['PATH'],
             GITHUB_REF=f'refs/heads/{BRANCH}',GITHUB_REF_NAME=BRANCH,
             TEST_STATE=str(state),TEST_MODE=mode)
    result=subprocess.run(['bash',str(ROOT/'ci/push_evidence.sh')],env=env,capture_output=True,text=True)
    return result,(state/'calls').read_text().splitlines()


def test_fast_forward_race_rebases_and_retries_only_session_branch(tmp_path):
    result,calls=run(tmp_path,'race');assert result.returncode==0
    assert calls.count(f'pull --rebase origin {BRANCH}')==2
    assert calls.count(f'push origin {BRANCH}')==2
    assert not any('--force' in c or 'checkout' in c for c in calls)


@pytest.mark.parametrize('mode,count',[('auth',1),('conflict',0),('forever',4)])
def test_auth_conflicts_and_repeated_races_fail_closed(tmp_path,mode,count):
    result,calls=run(tmp_path,mode);assert result.returncode!=0
    assert calls.count(f'push origin {BRANCH}')==count
