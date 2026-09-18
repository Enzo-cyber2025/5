import copy,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'ci'),str(ROOT/'tests')]
from evaluate_projector_combined import evaluate,MODEL,canonical_sha

def row(after,stage,kind='awake',verify=False):
    cached=kind=='cache' and stage=='sample';pair=2 if after and not cached else 0
    pv=4 if verify else 0;qv=5 if verify else 0
    hist=[['user','same full photo'],['assistant',' exact ']]*(1 if stage=='warmup' else 2)
    return dict(settings=dict(nPredict=128,temperature=0,gpuLayers=99,contextSize=4096,nThreads=2,useMmap=True),tokens=2,combined=after,diagnostic=verify,raw_history=hist,
      metrics=dict(tokens=2,version=3,timingScope='prefill_synchronized_before_decode',completed=True,decodeNs=1e9,firstTokenNs=2e9,promptTokens=500),
      strict=dict(status='PASS',tensor_cpu_fallback='blocked_by_native_policy',submitted_graphs=5,submitted_math_nodes=100),
      native_decode_tokens_s=2,send_to_first_ui_ns=1e9 if after else 1.01e9,
      image_records=[['64','Vulkan']]*5,prepared_dimensions=[['1024','803','ImageDecoder']],realized_attention='enabled',
      upload_bytes=0 if cached else 100,
      stages=dict(cache_disabled=int(kind!='cache'),verification=0,verified_hits=0,hits=5 if cached else 0,
                  encode_calls=0 if cached else 5-pair+pv+qv,encode_call_ns=1e9 if after else 1.01e9),
      pairing=dict(enabled=int(after),verification=int(verify),pair_calls=pair,paired_images=2*pair,verified_images=pv),
      qkv=dict(requested=int(after),verification=int(verify),verified_images=qv))

def obs(after,kind='awake',verify=False):
    return dict(load=dict(startup_ns=1e9,pss_kib=100,qkv=[['12','100','128',str(int(verify))]] if after else []),
                pss_kib_after=120,states={'awake':{s:row(after,s,kind,verify) for s in (('warmup',) if verify else ('warmup','sample'))}})

def fixture(kind='awake'):
    base=dict(status='RUNNING',model_sha256=MODEL,build=dict(apk_sha256='a'*64,default_combined=False),code_and_copy={'stream':'PASS','history':'PASS'})
    proof=copy.deepcopy(base);proof.update(kind='verify',pairs=[],verification=obs(True,verify=True));proof['result']=evaluate(proof);proof['status']=proof['result']['status']
    s=copy.deepcopy(base);s.update(kind=kind,byte_reference_sha256=canonical_sha(proof),reference_attention='enabled',pairs=[])
    for order in (('before','after'),('after','before'),('before','after')):
        s['pairs'].append({p:obs(p=='after',kind) for p in order})
    return s,proof

def test_small_consistent_gains_count_without_old_five_percent_floor():
    s,p=fixture();assert evaluate(s,p)['passed']
    assert evaluate(s,p)['speedup_ratios']==[1.01]*3

def test_cache_keeps_real_hits_and_cannot_be_used_to_fake_encoder_gain():
    s,p=fixture('cache');assert evaluate(s,p)['passed']
    s,p=fixture();s['pairs'][0]['after']['states']['awake']['sample']['stages']['hits']=5
    with pytest.raises(AssertionError):evaluate(s,p)

@pytest.mark.parametrize('field,value',[('tokens',1),('diagnostic',True),('realized_attention','disabled'),('upload_bytes',50)])
def test_output_budget_diagnostics_attention_or_input_changes_rejected(field,value):
    s,p=fixture();s['pairs'][0]['after']['states']['awake']['sample'][field]=value
    with pytest.raises(AssertionError):evaluate(s,p)

def test_one_slow_pair_is_not_a_stable_gain():
    s,p=fixture();s['pairs'][1]['after']['states']['awake']['sample']['send_to_first_ui_ns']=2e9
    assert not evaluate(s,p)['passed']

def test_cannot_use_another_apk_or_incomplete_reference():
    s,p=fixture();p['verification']['states']['awake']['warmup']['qkv']['verified_images']=4
    s['byte_reference_sha256']=canonical_sha(p)
    with pytest.raises(AssertionError):evaluate(s,p)
    s,p=fixture();s['build']['apk_sha256']='b'*64
    with pytest.raises(AssertionError):evaluate(s,p)

def test_production_guard_and_exact_reference_stay_present():
    s=(ROOT/'apk-fix/native/mobile.cpp').read_text()
    assert 'if(combined && (!combo || std::strcmp(combo,"1")!=0))' in s
    assert 'std::memcmp(fused.data(),embd,count*sizeof(float))' in s
    assert '~RestoreQkv(){mtmd_gguf_qkv_reference(ctx,false);}' in s
    assert 'std::memcmp(embd,reference,count*sizeof(float))' in s
    harness=(ROOT/'scripts/test_projector_combined_android.py').read_text()
    assert "p=='CPU' and h=='1'" in harness
    assert "assert actual==settings" in harness
    assert "range(3)" in harness

def test_optimized_python_is_not_a_validation_bypass():
    import subprocess
    r=subprocess.run([sys.executable,'-O','-c',"import sys;sys.path.insert(0,'ci');from evaluate_projector_combined import evaluate;evaluate({})"],cwd=ROOT,capture_output=True,text=True)
    assert r.returncode!=0 and 'Optimized Python' in r.stderr
