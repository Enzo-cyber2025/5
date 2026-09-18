#!/usr/bin/env python3
"""Recompute wait-policy evidence. Functional PASS is never speed approval."""
import json,math,re,statistics,sys
from pathlib import Path
from perceptible_text_gate import evaluate as text_gate

def positive(n):
    assert isinstance(n,(int,float)) and not isinstance(n,bool) and math.isfinite(n) and n>0

def evaluate(s):
    if not __debug__:raise RuntimeError('Optimized Python cannot validate evidence')
    assert s['status']!='FAIL' and not s.get('error')
    b=s['build'];sha=b['apk_sha256'];assert re.fullmatch('[0-9a-f]{64}',sha)
    assert b['experimental_wait_build'] is True and b['default_blocking_wait'] is True
    kind=s['kind'];assert kind in ('text','images')
    pairs=s['pairs'];assert len(pairs)==(3 if kind=='text' else 2)
    assert [list(p) for p in pairs]==[['before','after'],['after','before'],['before','after']][:len(pairs)]
    assert s['code_and_copy']=={'stream':'PASS','history':'PASS'}
    cpu=[];image_ratios=[];encoder_ratios=[]
    for pair in pairs:
        for state in (('awake','asleep') if kind=='text' else ('awake',)):
            for stage in ('warmup','sample'):
                a,c=pair['before'][state][stage],pair['after'][state][stage]
                assert a['raw_history']==c['raw_history'] and a['raw_history']
                assert len(a['raw_history'])==(2 if stage=='warmup' else 4)
                assert a['tokens']==c['tokens']>0
                assert a['metrics']['promptTokens']==c['metrics']['promptTokens']
                assert a['blocking_wait'] is False and c['blocking_wait'] is True
                for r in (a,c):
                    assert r['metrics']['completed'] is True and r['strict']['status']=='PASS'
                    assert r['strict']['tensor_cpu_fallback']=='blocked_by_native_policy'
                    positive(r['worker_cpu_ns']);positive(r['metrics']['decodeNs'])
                    assert abs(r['native_decode_tokens_s']-r['tokens']*1e9/r['metrics']['decodeNs'])<1e-8
                for field in ('submitted_graphs','submitted_math_nodes'):
                    assert a['strict'][field]==c['strict'][field]>0
                if kind=='images':
                    assert a['image_records']==c['image_records'] and a['image_records']
                    assert all(int(n)>0 and backend=='Vulkan' for n,backend in a['image_records'])
                    assert a['prepared_dimensions']==c['prepared_dimensions'] and len(a['prepared_dimensions'])==1
                    assert all(int(w)>0 and int(h)>0 for w,h,_ in a['prepared_dimensions'])
                    for r in (a,c):
                        st=r['stages'];assert st['cache_disabled']==1 and st['hits']==st['verified_hits']==st['verification']==0
                        assert st['encode_calls']==len(r['image_records'])
                        positive(st['encode_call_ns']);positive(r['send_to_first_ui_ns'])
            a,c=pair['before'][state]['sample'],pair['after'][state]['sample']
            if state=='awake':cpu.append(a['worker_cpu_ns']/c['worker_cpu_ns'])
            if kind=='images':
                image_ratios.append(a['send_to_first_ui_ns']/c['send_to_first_ui_ns'])
                encoder_ratios.append(a['stages']['encode_call_ns']/c['stages']['encode_call_ns'])
    if kind=='text':
        adapted=dict(s,build=dict(b,baseline_original_sha256=sha,candidate_original_sha256=sha,resigning_payload_exact=True))
        performance=text_gate(adapted,baseline_sha=sha,candidate_sha=sha)
        speed_passed=performance['text_gain_passed']
    else:
        performance={'first_ui_speedup_ratios':image_ratios,'encoder_speedup_ratios':encoder_ratios}
        speed_passed=min(image_ratios)>=1.10 and min(encoder_ratios)>=1.10
    # A claim about eliminating CPU waste requires measured worker CPU reduction,
    # not only an incidental wall-time outlier. This is NOT total app energy.
    passed=speed_passed and min(cpu)>1
    return {'status':'PASS_WAIT_GAIN_EXPERIMENT' if passed else 'WAIT_GAIN_NOT_MET',
            'gain_passed':passed,'kind':kind,'performance':performance,
            'worker_cpu_speedup_ratios':cpu,'median_worker_cpu_ratio':statistics.median(cpu),
            'physical_gpu_certified':False,'release_approved':False,
            'scope':'Same APK polling versus default blocking; all model tensor math remains on selected Vulkan backend. Warmed full work, no precision/budget changes. Text: each awake >=10%, median >=15%, sleep/first-text regression guards. Images: encoder and first-UI >=10% in both pairs. Worker CPU time lower in each awake pair. Not release/all-model/physical-device certification.'}

if __name__=='__main__':
    s=json.loads(Path(sys.argv[1]).read_text());assert s['status'] in ('PASS_WAIT_GAIN_EXPERIMENT','WAIT_GAIN_NOT_MET')
    r=evaluate(s);assert s['result']==r
    print(json.dumps(r,indent=2));raise SystemExit(0 if r['gain_passed'] else 1)
