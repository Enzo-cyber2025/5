import copy,sys,subprocess
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'ci'))
from evaluate_first_working import evaluate,HASHES,MODEL


def fixture():
    s=dict(status='RUNNING',backend='cpu',apk_sha256=HASHES.copy(),model_sha256=MODEL,pairs=[])
    for order in (('before','after'),('after','before'),('before','after')):
        pair={}
        for phase in order:
            pair[phase]={}
            for state in ('awake','asleep'):
                pair[phase][state]={}
                for stage in ('warmup','sample'):
                    t=20 if phase=='before' else 10
                    row=dict(tokens=128,reason='length',backend='cpu',sleep_confirmed=state=='asleep',
                             metric='device_log_dispatch_to_native_complete_including_prefill',send_to_native_complete_s=t,total_tokens_s=128/t,
                             settings=dict(nPredict=128,temperature=0,topP=.95,topK=40,minP=.05,repeatPenalty=1.1,repeatLastN=64,contextSize=2048,nThreads=2,gpuLayers=0,useMmap=True),
                             raw_history=[list(x) for x in ([['user','unchanged prompt'],['assistant','whole answer']]*(1 if stage=='warmup' else 2))],response='whole answer')
                    pair[phase][state][stage]=row
        s['pairs'].append(pair)
    return s


def test_direct_total_latency_comparison_not_decode_rate():
    r=evaluate(fixture());assert r['outputs_identical'] and r['observations']['awake']['median_speedup']==2
    assert not r['release_approved'] and 'Not decode-only' in r['scope']


def test_changed_outputs_cannot_be_a_quality_preserving_gain():
    s=fixture();s['pairs'][0]['after']['awake']['sample']['raw_history'][-1][1]='different'
    r=evaluate(s);assert not r['outputs_identical'] and r['status']=='OUTPUT_CHANGED_NO_QUALITY_PRESERVING_SPEED_CLAIM'


@pytest.mark.parametrize('mutation',['hash','budget','clock','sleep','tokens','rate'])
def test_invalid_comparisons_rejected(mutation):
    s=fixture();r=s['pairs'][0]['after']['awake']['sample']
    if mutation=='hash':s['apk_sha256']['before']='a'*64
    elif mutation=='budget':r['settings']['nPredict']=64
    elif mutation=='clock':r['send_to_native_complete_s']=-1
    elif mutation=='sleep':r['sleep_confirmed']=True
    elif mutation=='tokens':r['tokens']=64
    else:r['total_tokens_s']=999
    with pytest.raises(AssertionError):evaluate(s)


def test_exact_apks_and_external_common_clock():
    s=(ROOT/'scripts/test_first_working_android.py').read_text()
    assert 'log -t GGUF_COMPARE BEGIN; input tap' in s
    assert s.index("assert d.shell('getprop ro.kernel.qemu')=='1'",s.index('# Exact incompatible'))<s.index("d.adb('uninstall',PACKAGE")
    assert 'first-working.apk' in s and 'entrega/GGUF-Chat-acelerado.apk' in s
    assert 'sign --' not in s and '128' in s


def test_python_optimized_not_allowed():
    r=subprocess.run([sys.executable,'-O','-c',"import sys;sys.path.insert(0,'ci');from evaluate_first_working import evaluate;evaluate({})"],cwd=ROOT,capture_output=True,text=True)
    assert r.returncode and 'Optimized Python' in r.stderr
