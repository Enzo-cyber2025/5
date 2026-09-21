#!/usr/bin/env python3
"""Delivery gate: material latency reduction on retained-image reuse, not fresh photos."""
import json,sys
from pathlib import Path
BASELINE='323fd5a33667c6cab278699e97c89fe253e1bb7acead45b869729bf022eb9f5c'
CANDIDATE='2b444a73090dff9bd6d4ce6d199349cafd5e9ae73b83cc34e05101e7f77727cc'

def evaluate(s):
    if not __debug__:raise RuntimeError("Optimized Python cannot validate release evidence")
    assert s.get("status")!="FAIL" and not s.get("error")
    assert s['build']['baseline_original_sha256']==BASELINE
    assert s['build']['candidate_original_sha256']==CANDIDATE
    assert s['build']['resigning_payload_exact'] is True
    assert len(s['pairs'])==2
    assert [list(p) for p in s['pairs']]==[['before','after'],['after','before']]
    obs=[]
    for pair in s['pairs']:
        for stage in ('prime','exclude','restore'):
            a,b=pair['before'][stage],pair['after'][stage]
            assert a['raw_history']==b['raw_history'],'Raw history changed'
            assert a['tokens']==b['tokens']>0
            assert a['metrics']['promptTokens']==b['metrics']['promptTokens']
            assert a['image_records']==b['image_records'] and a['image_records']
            assert all(int(n)>0 and backend=='Vulkan' for n,backend in a['image_records'])
            assert a['prepared_dimensions']==b['prepared_dimensions']
            assert len(a['prepared_dimensions'])==(1 if stage=='exclude' else 2)
            assert all(int(w)>0 and int(h)>0 for w,h,_ in a['prepared_dimensions'])
            for r in (a,b):
                assert r['strict']['status']=='PASS' and r['metrics']['completed']
                assert not r['diagnostic'] and r['send_to_first_ui_ns']>0
                assert r['metrics']['decodeNs']>0
                assert abs(r['native_decode_tokens_s']-r['tokens']*1e9/r['metrics']['decodeNs'])<1e-8
        a,b=pair['before']['restore'],pair['after']['restore']
        assert a['cache']['hits']==0 and a['cache']['misses']>0
        assert b['cache']['hits']==a['cache']['misses'] and b['cache']['misses']==0
        assert b['stages']['verification']==0 and b['stages']['verified_hits']==0 and b['stages']['cache_disabled']==0
        assert b['stages']['encode_calls']==0
        before=a['send_to_first_ui_ns']/1e9;after=b['send_to_first_ui_ns']/1e9
        obs.append({'before_seconds':before,'after_seconds':after,'speedup':before/after,'seconds_saved':before-after})
    checks=s['checks']
    assert checks['code_and_copy']=='PASS' and checks['android_decoder']=='PASS'
    assert checks['screen_off_completion']=='PASS'
    assert checks['same_signer_test_update_preserved_data']=='PASS'
    passed=all(r['speedup']>=2 and r['seconds_saved']>=10 for r in obs)
    return {'status':'PASS_GAIN_GATE_RETAINED_IMAGES_ONLY' if passed else 'GAIN_GATE_NOT_MET',
            'gain_gate_passed':passed,'observations':obs,'required_speedup_each_pair':2,
            'required_seconds_saved_each_pair':10,
            'scope':'Reactivating two previously processed photos after excluding one; same byte/model settings; software Vulkan; fresh Engine and complete prime/exclude sequence per observation. No promise for first image, physical device or text throughput.',
            'physical_gpu_certified':False,'fresh_image_speedup_certified':False}

if __name__=='__main__':
    summary=json.loads(Path(sys.argv[1]).read_text())
    assert summary.get('status')=='PASS_GAIN_GATE_RETAINED_IMAGES_ONLY','No completed passing run'
    result=evaluate(summary)
    print(json.dumps(result,indent=2));raise SystemExit(0 if result['gain_gate_passed'] else 1)
