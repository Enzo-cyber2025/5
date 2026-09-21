#!/usr/bin/env python3
"""Any stable positive media-prefix gain counts; never a release certificate."""
import json,re,statistics,sys
from pathlib import Path
from evaluate_projector_combined import canonical_sha,positive,MODEL
VERIFY_STAGES=('warmup','sample','append_B','exclude_A','restore_A','system_edit')


def check_row(r,after,stage,text=False,verify=False):
    assert r['enabled'] is after and r['diagnostic'] is (verify and after)
    m=r['metrics'];assert m['completed'] is True and m['version']==3 and m['timingScope']=='prefill_synchronized_before_decode'
    assert type(r['tokens']) is int and r['tokens']==m['tokens'] and 0<r['tokens']<=128
    cfg=r['settings'];assert cfg['nPredict']==128 and cfg['temperature']==0 and cfg['gpuLayers']==99
    assert cfg['contextSize']==4096 and cfg['nThreads']==2 and cfg['useMmap'] is True
    assert r['strict']['status']=='PASS' and r['strict']['tensor_cpu_fallback']=='blocked_by_native_policy'
    positive(r['strict']['submitted_graphs']);positive(r['strict']['submitted_math_nodes'])
    assert m['promptTokens']+128<=cfg['contextSize']
    assert r['completion_reason']==('length' if r['tokens']==128 else 'eog')
    positive(m['decodeNs']);positive(m['firstTokenNs']);positive(r['native_decode_tokens_s'])
    assert abs(r['native_decode_tokens_s']-r['tokens']*1e9/m['decodeNs'])<1e-8
    hist=r['raw_history'];assert len(hist)%2==0 and len(hist)>=2
    assert [x[0] for x in hist]==['user','assistant']*(len(hist)//2)
    assert all(isinstance(x[1],str) and x[1] for x in hist)
    if text:
        assert 64<=r['tokens']<=128 and not verify
        assert m['reusedPromptTokens']==0 if stage=='warmup' else 0<m['reusedPromptTokens']<m['promptTokens']
        return
    p=r['prefix'];assert p['enabled']==p['eligible']==int(after) and p['verification']==int(verify and after)
    assert p['reused_tokens']==m['reusedPromptTokens'] and 0<=p['reused_tokens']<m['promptTokens']
    assert (p['reused_chunks']>0)==(p['reused_tokens']>0)
    if not after or stage in ('warmup','system_edit'):assert p['reused_tokens']==0
    if after and stage=='sample':assert p['reused_tokens']>0 and r['reused_image_chunks']>0
    if verify and after and p['reused_tokens']:positive(p['verified_bytes'])
    else:assert p['verified_bytes']==0
    images=r['image_records'];assert images and all(int(n)>0 and backend=='Vulkan' for n,backend in images)
    assert len(images)==r['reused_image_chunks']+r['evaluated_image_chunks']
    assert r['prepared_dimensions'] and all(int(w)>0 and int(h)>0 for w,h,_ in r['prepared_dimensions'])
    enc=r['encoder'];assert enc['cache_disabled']==enc['verification']==enc['verified_hits']==0
    if stage=='warmup':positive(enc['encode_calls'])
    if stage=='sample':assert enc['encode_calls']==0


def compare(a,b,stage,text=False,verify=False):
    check_row(a,False,stage,text,False);check_row(b,True,stage,text,verify)
    for key in ('raw_history','response','tokens','settings','completion_reason'):assert a[key]==b[key],key
    assert a['metrics']['promptTokens']==b['metrics']['promptTokens']
    if not text:
        assert a['prepared_dimensions']==b['prepared_dimensions']
        if not verify:assert a['image_records']==b['image_records']


def evaluate(s,proof=None):
    if not __debug__:raise RuntimeError('Optimized Python cannot validate evidence')
    assert s['status']!='FAIL' and not s.get('error')
    assert s['model_sha256']==MODEL and s['code_and_copy']=={'stream':'PASS','history':'PASS'}
    build=s['build'];assert re.fullmatch('[0-9a-f]{64}',build['apk_sha256'])
    assert build['default_media_prefix'] is False and build['experimental_media_prefix_build'] is True
    kind=s['kind'];assert kind in ('verify','awake','asleep','text')
    if kind=='verify':
        assert s['pairs']==[] and list(s['verification'])==['before','after']
        a,b=s['verification']['before'],s['verification']['after']
        assert tuple(a)==tuple(b)==VERIFY_STAGES
        verified=[]
        for index,stage in enumerate(VERIFY_STAGES):
            compare(a[stage],b[stage],stage,verify=True)
            assert len(a[stage]['raw_history'])==2*(index+1)
            if index:assert a[stage]['raw_history'][:-2]==a[VERIFY_STAGES[index-1]]['raw_history']
            verified.append(b[stage]['prefix']['verified_bytes'])
        assert verified[1]>0
        return dict(status='PASS_MEDIA_PREFIX_KV_REFERENCE',quality_passed=True,kv_reference_bytes=verified,release_approved=False)
    assert proof and proof['status']=='PASS_MEDIA_PREFIX_KV_REFERENCE' and proof['result']==evaluate(proof)
    assert proof['build']==build and s['byte_reference_sha256']==canonical_sha(proof)
    assert len(s['pairs'])==3 and [list(p) for p in s['pairs']]==[['before','after'],['after','before'],['before','after']]
    speeds=[];decode=[];cold=[];text_results={}
    states=('awake','asleep') if kind=='text' else (kind,)
    for pair in s['pairs']:
        for phase in ('before','after'):assert tuple(pair[phase])==states
        for state in states:
            a,b=pair['before'][state],pair['after'][state]
            assert tuple(a)==tuple(b)==('warmup','sample')
            for stage in ('warmup','sample'):
                compare(a[stage],b[stage],stage,text=kind=='text')
                assert len(a[stage]['raw_history'])==(2 if stage=='warmup' else 4)
                if state=='awake':positive(a[stage]['send_to_first_ui_ns']);positive(b[stage]['send_to_first_ui_ns'])
            assert a['sample']['raw_history'][:2]==a['warmup']['raw_history']
            ar,br=a['sample'],b['sample']
            ratios=dict(first_native=ar['metrics']['firstTokenNs']/br['metrics']['firstTokenNs'],decode=br['native_decode_tokens_s']/ar['native_decode_tokens_s'])
            if state=='awake':ratios['first_ui']=ar['send_to_first_ui_ns']/br['send_to_first_ui_ns']
            if kind=='text':
                for metric,value in ratios.items():text_results.setdefault(state+'_'+metric,[]).append(value)
            else:
                speeds.append(ratios['first_ui'] if state=='awake' else ratios['first_native']);decode.append(ratios['decode'])
                cold.append(a['warmup']['metrics']['firstTokenNs']/b['warmup']['metrics']['firstTokenNs'])
    nonreg=lambda v:min(v)>=0.97 and statistics.median(v)>=1
    passed=all(nonreg(v) for v in text_results.values()) if kind=='text' else min(speeds)>1 and nonreg(decode) and nonreg(cold)
    return dict(status='PASS_MEDIA_PREFIX_OBSERVED_GAIN' if passed else 'MEDIA_PREFIX_GAIN_OR_REGRESSION_NOT_MET',
                passed=passed,kind=kind,first_text_speedups=speeds,decode_ratios=decode,cold_native_ratios=cold,text=text_results,
                release_approved=False,scope='Three AB/BA/AB pairs. Any positive continuation gain in every image pair; decode/text controls at most 3% slower per observation and nonnegative medians. Cold native first-token ratios must also satisfy the regression guard. No all-model, physical GPU or final-delivered-APK comparison claim.')

if __name__=='__main__':
    s=json.loads(Path(sys.argv[1]).read_text());proof=json.loads(Path(sys.argv[2]).read_text()) if len(sys.argv)>2 else None
    result=evaluate(s,proof);assert s['result']==result and s['status']==result['status']
    print(json.dumps(result,indent=2));raise SystemExit(0 if result.get('quality_passed') or result.get('passed') else 1)
