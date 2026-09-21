import copy,sys,subprocess
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'ci'))
from evaluate_media_prefix import evaluate,VERIFY_STAGES,canonical_sha,MODEL


def row(after,stage,index,verify=False,text=False):
    reuse=after and stage not in ('warmup','system_edit')
    count=103 if text else 2
    history=[]
    for i in range(index+1):history.extend([['user','full input '+str(i)],['assistant',' exact answer '+str(i)]])
    r=dict(enabled=after,diagnostic=verify and after,tokens=count,response='exact answer',completion_reason='eog',raw_history=history,
        settings=dict(nPredict=128,temperature=0,gpuLayers=99,contextSize=4096,nThreads=2,useMmap=True),
        metrics=dict(tokens=count,version=3,timingScope='prefill_synchronized_before_decode',completed=True,decodeNs=1e9,
                     firstTokenNs=1e9 if after else 1.01e9,promptTokens=500+index*20,reusedPromptTokens=(204 if stage!='warmup' else 0) if text else (320 if reuse else 0)),
        strict=dict(status='PASS',tensor_cpu_fallback='blocked_by_native_policy',submitted_graphs=5,submitted_math_nodes=100),
        native_decode_tokens_s=count,send_to_first_ui_ns=1.1e9 if after else 1.111e9)
    if not text:
        reused=5 if reuse else 0;decoded=5 if not reuse or verify else 0
        r.update(prefix=dict(enabled=int(after),eligible=int(after),verification=int(verify and after),reused_tokens=320 if reuse else 0,
                             reused_chunks=5 if reuse else 0,verified_bytes=999 if verify and reuse else 0),
                 image_records=[['64','Vulkan']]*(decoded+reused),prepared_dimensions=[['1024','803','ImageDecoder']],
                 reused_image_chunks=reused,evaluated_image_chunks=decoded,
                 encoder=dict(cache_disabled=0,verification=0,verified_hits=0,encode_calls=5 if stage=='warmup' else 0))
    return r


def fixture(kind='awake'):
    base=dict(status='RUNNING',build=dict(apk_sha256='a'*64,default_media_prefix=False,experimental_media_prefix_build=True),
              model_sha256=MODEL,code_and_copy={'stream':'PASS','history':'PASS'})
    proof=copy.deepcopy(base);proof.update(kind='verify',pairs=[],verification={})
    for phase in ('before','after'):
        proof['verification'][phase]={stage:row(phase=='after',stage,index,True) for index,stage in enumerate(VERIFY_STAGES)}
    proof['result']=evaluate(proof);proof['status']=proof['result']['status']
    s=copy.deepcopy(base);s.update(kind=kind,byte_reference_sha256=canonical_sha(proof),pairs=[])
    for order in (('before','after'),('after','before'),('before','after')):
        s['pairs'].append({phase:{state:{stage:row(phase=='after',stage,index,text=kind=='text') for index,stage in enumerate(('warmup','sample'))}
                                for state in (('awake','asleep') if kind=='text' else (kind,))} for phase in order})
    return s,proof


@pytest.mark.parametrize('kind',['awake','asleep','text'])
def test_small_gain_and_natural_eos_with_unchanged_budget(kind):
    s,p=fixture(kind);assert evaluate(s,p)['passed']
    assert not evaluate(s,p)['release_approved']


@pytest.mark.parametrize('field,value',[('tokens',1),('completion_reason','length'),('diagnostic',True)])
def test_budget_output_or_verification_changes_fail(field,value):
    s,p=fixture();s['pairs'][0]['after']['awake']['sample'][field]=value
    with pytest.raises(AssertionError):evaluate(s,p)


def test_shortening_budget_is_not_natural_eos():
    s,p=fixture('text')
    for pair in s['pairs']:
        for phase in pair.values():
            for state in phase.values():
                for r in state.values():r['settings']['nPredict']=103
    with pytest.raises(AssertionError):evaluate(s,p)


def test_one_slower_image_pair_or_cold_regression_blocks_acceptance():
    for stage in ('sample','warmup'):
        s,p=fixture();r=s['pairs'][0]['after']['awake'][stage]
        r['send_to_first_ui_ns']=2e9;r['metrics']['firstTokenNs']=2e9
        assert not evaluate(s,p)['passed']


def test_same_filename_is_not_proof_and_no_byte_readback_is_not_proof():
    s,p=fixture();p['verification']['after']['sample']['prefix']['verified_bytes']=0
    with pytest.raises(AssertionError):evaluate(p)


def test_apk_identity_and_stale_system_prompt_cannot_pass():
    s,p=fixture();s['build']['apk_sha256']='b'*64
    with pytest.raises(AssertionError):evaluate(s,p)
    s,p=fixture();r=p['verification']['after']['system_edit'];r['prefix']['reused_tokens']=1;r['metrics']['reusedPromptTokens']=1;r['prefix']['reused_chunks']=1
    with pytest.raises(AssertionError):evaluate(p)


def test_optimized_python_is_refused():
    r=subprocess.run([sys.executable,'-O','-c',"import sys;sys.path.insert(0,'ci');from evaluate_media_prefix import evaluate;evaluate({})"],cwd=ROOT,capture_output=True,text=True)
    assert r.returncode and 'Optimized Python' in r.stderr
