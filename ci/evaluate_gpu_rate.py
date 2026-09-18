#!/usr/bin/env python3
"""Pre-first-acceleration native callback intervals; NEVER end-to-end or UI t/s."""
import json,statistics,sys
HASHES={'before':'0c45fd2e6c318da3ebb961bbd461c56d7401161c31a1869157f509550e4b05d1',
        'after':'bd7c45d3c9b80ee583e0d4102595c5ed55242c37aa0394f0befe093c07fd88d2'}
MODEL='2e8040ceae7815abe0dcb3540b9995eaa1fa0d2ca9e797d0a635ae4433c68c2d'
METRIC='native_token_delivery_intervals_excluding_first_token_and_prefill'
SETTINGS=dict(context=2048,threads=2,gpu_layers=99,predict=128,temperature=0,top_p=.95,top_k=40,min_p=.05,repeat=1.1,last_n=64,seed=42,mmap=True)
PRIME='Explain ten practical ways to learn a language. Give a detailed example for each. Reply in English.'
FOLLOW='Give ten more practical recommendations, with detailed examples. Reply in English.'

def rate(r,phase,state,stage):
    assert r['metric']==METRIC and r['stage']==stage
    assert r['screen_asleep']==(state=='asleep') and r['native_success'] is True and r['done_success'] is True
    # Native emitted-token counter is independent of the observer's callback count.
    assert r['native_tokens']==r['callbacks']==128 and r['native_reason']=='length'
    t=r['callback_times_ns'];assert len(t)==128 and all(type(x) is int and x>0 for x in t)
    assert all(a<b for a,b in zip(t,t[1:]))
    assert r['interval_ns']==t[-1]-t[0]>0
    c=r['chunks'];assert len(c)==128 and all(isinstance(x,str) and x for x in c)
    assert ''.join(c)==r['response'] and len(r['response'].strip())>64 and '\ufffd' not in r['response']
    ids=r['prompt_token_ids'];assert ids and all(type(x) is int and x>=0 for x in ids) and len(ids)+128<=2048
    assert PRIME in r['prompt'] and ((FOLLOW in r['prompt'])==(stage=='sample'))
    if phase=='after':assert r['strict']['status']=='PASS' and r['strict']['tensor_cpu_fallback']=='blocked_by_native_policy'
    return 127e9/r['interval_ns']

def evaluate(s):
    assert s['status']=='COMPLETE_OBSERVATIONS' and s['state'] in ('awake','asleep')
    assert s['apk_sha256']==HASHES and s['model_sha256']==MODEL
    assert s['hardware']=='software_vulkan_emulator' and s['release_approved'] is False
    build=s['build'];assert build['release_approved'] is False
    for p in HASHES:
        assert build['payloads'][p]['original_sha256']==HASHES[p]
        assert build['payloads'][p]['non_signature_payload_identical'] is True
        assert build['payloads'][p]['native'] and len(build['payloads'][p]['test_sha256'])==64
    assert len(s['pairs'])==3
    values=[];reference={}
    for i,pair in enumerate(s['pairs']):
        assert pair['order']==(['before','after'] if i%2==0 else ['after','before'])
        v={}
        for phase in ('before','after'):
            r=pair[phase];assert r['status']=='PASS_NATIVE_OBSERVER' and r['model_sha256']==MODEL
            assert r['test_apk_sha256']==build['payloads'][phase]['test_sha256']
            assert r['settings']==SETTINGS and r['vulkan_environment']=={'GGML_VK_VISIBLE_DEVICES':'0'}
            assert r['vulkan_positive_offload'] is True
            assert r['batch']==128 and r['ubatch']==32
            for stage in ('warmup','sample'):
                speed=rate(r[stage],phase,s['state'],stage)
                # Preserve the complete history and the full per-token strings,
                # not a trimmed prefix or a text-length heuristic.
                key=(r[stage]['prompt'],r[stage]['prompt_token_ids'],r[stage]['response'],r[stage]['chunks'])
                if stage in reference:assert reference[stage]==key,'Different prompt/tokenization/output; no apples-to-apples speed claim'
                else:reference[stage]=key
            assert r['warmup']['response'] in r['sample']['prompt']
            v[phase]=speed # sample ONLY; warmup discarded
        values.append(dict(before_tps=v['before'],after_tps=v['after'],ratio=v['after']/v['before']))
    ratios=[r['ratio'] for r in values]
    return dict(comparison_valid=True,metric=METRIC,state=s['state'],pairs=values,
                before_median_tps=statistics.median(v['before_tps'] for v in values),
                after_median_tps=statistics.median(v['after_tps'] for v in values),
                median_paired_gain_percent=(statistics.median(ratios)-1)*100,
                all_pairs_faster=all(x>1 for x in ratios),physical_gpu_certified=False,release_approved=False,
                baseline_all_tensor_gpu_policy_proven=False,
                scope='Unchanged original DEX/native/resources in disposable test-signed copies; same native observer, 127 token-delivery intervals after first callback. Not app/UI/footer timing or pure GPU kernel time.')

if __name__=='__main__':
    if not __debug__:raise RuntimeError('Assertions required')
    print(json.dumps(evaluate(json.load(open(sys.argv[1]))),indent=2))
