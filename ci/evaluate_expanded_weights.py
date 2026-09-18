#!/usr/bin/env python3
"""2x target against PRE-acceleration APK; current APK remains a separate control."""
import copy,json,sys
from evaluate_gpu_rate import evaluate_pair,HASHES,MODEL
ENV={'GGML_VK_VISIBLE_DEVICES':'0'}
ON={**ENV,'GGUF_EXPAND_WEIGHTS':'1'}
VERIFY={**ON,'GGUF_VERIFY_EXPANDED_WEIGHTS':'1'}

def evaluate(s):
    assert s['status']=='COMPLETE_EXPANDED_OBSERVATIONS' and s['release_approved'] is False
    build=s['build'];experiment=build['experiment'];candidate=experiment['apk_sha256']
    assert experiment['experimental_expanded_weights_build'] is True and experiment['default_enabled'] is False
    assert experiment['release_approved'] is False and len(experiment['source_commit'])==40
    assert build['payloads']['candidate']['original_sha256']==candidate
    proof=s['proof'];assert proof['vulkan_environment']==VERIFY
    assert proof['model_sha256']==MODEL and proof['status']=='PASS_NATIVE_OBSERVER'
    assert proof['test_apk_sha256']==build['payloads']['candidate']['test_sha256']
    x=proof['expansion'];assert x['verification']==1 and x['verified_bytes']>0 and x['tensors']>0
    assert x['extra_device_bytes']>=x['verified_bytes'] and x['precision']=='F32' and x['conversion']=='Vulkan'
    assert len(s['pairs'])==3
    for i,p in enumerate(s['pairs']):
        assert p['order']==(['before','after','candidate'] if i%2==0 else ['candidate','after','before'])
        for phase in ('before','after','candidate'):
            for stage in ('warmup','sample'):
                assert p[phase][stage]['response']==proof[stage]['response']
                assert p[phase][stage]['chunks']==proof[stage]['chunks']
                assert p[phase][stage]['prompt_token_ids']==proof[stage]['prompt_token_ids']
                if phase!='before':assert p[phase][stage]['strict']['status']=='PASS'
        e=p['candidate']['expansion'];assert e['verification']==e['verified_bytes']==0
        assert e['tensors']==x['tensors'] and e['extra_device_bytes']==x['extra_device_bytes']
        assert e['precision']=='F32' and e['conversion']=='Vulkan'
        assert e['prepare_ns']>0
    results={}
    for label,control in [('historical','before'),('delivered','after')]:
        projected=copy.deepcopy(s);projected['status']='COMPLETE_OBSERVATIONS'
        expected={'before':HASHES[control],'after':candidate};projected['apk_sha256']=expected.copy()
        projected['build']['payloads']={'before':build['payloads'][control],'after':build['payloads']['candidate']}
        projected['pairs']=[dict(order=['before','after'] if i%2==0 else ['after','before'],before=p[control],after=p['candidate']) for i,p in enumerate(s['pairs'])]
        results[label]=evaluate_pair(projected,expected,{'before':ENV,'after':ON})
    # Paired threshold, not an absolute rate borrowed from another runner.
    reached=all(p['ratio']>=2 for p in results['historical']['pairs'])
    no_regression=all(p['ratio']>=1 for p in results['delivered']['pairs'])
    return dict(status='PASS_2X_THIS_TEXT_STATE_NOT_RELEASE' if reached and no_regression else 'TWO_TIMES_TARGET_NOT_MET',
                target_2x_passed=reached and no_regression,comparisons=results,
                extra_device_bytes=x['extra_device_bytes'],verified_weight_bytes=x['verified_bytes'],
                physical_gpu_certified=False,release_approved=False,
                scope='One small-model text fixture; both screen jobs, images, startup/memory and broader quality remain required. Independent reference/readbacks excluded from timed observations. No signature-continuous release key available.')
if __name__=='__main__':
    if not __debug__:raise RuntimeError('Assertions required')
    r=evaluate(json.load(open(sys.argv[1])));print(json.dumps(r,indent=2))
    raise SystemExit(0 if r['target_2x_passed'] else 1)
