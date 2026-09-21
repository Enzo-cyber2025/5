#!/usr/bin/env python3
"""Direct as-shipped comparison; never splice ratios from different runners."""
import json,math,statistics,sys
from pathlib import Path
HASHES={'before':'409985de54388cbcb1429a8db4cd26139cc47a5764864c6cd4b408c75f07099f',
        'after':'bd7c45d3c9b80ee583e0d4102595c5ed55242c37aa0394f0befe093c07fd88d2'}
MODEL='2e8040ceae7815abe0dcb3540b9995eaa1fa0d2ca9e797d0a635ae4433c68c2d'
PARAMS=('nPredict','temperature','topP','topK','minP','repeatPenalty','repeatLastN','contextSize','nThreads','gpuLayers','useMmap')

def evaluate(s):
    if not __debug__:raise RuntimeError('Optimized Python cannot validate evidence')
    assert s['status']!='FAIL' and not s.get('error')
    assert s['apk_sha256']==HASHES and s['model_sha256']==MODEL and s['backend'] in ('cpu','vulkan')
    assert len(s['pairs'])==3
    assert [list(p) for p in s['pairs']]==[['before','after'],['after','before'],['before','after']]
    same=True;out={}
    for state in ('awake','asleep'):
        ratios=[];before=[];after=[]
        for pair in s['pairs']:
            for stage in ('warmup','sample'):
                a,b=(pair[p][state][stage] for p in ('before','after'))
                for r in (a,b):
                    assert r['tokens']==128 and r['reason']=='length'
                    assert r['backend']==s['backend'] and r['sleep_confirmed'] is (state=='asleep')
                    assert r['metric']=='device_log_dispatch_to_native_complete_including_prefill'
                    t=r['send_to_native_complete_s'];assert not isinstance(t,bool) and math.isfinite(t) and 0<t<1200
                    assert abs(r['total_tokens_s']-128/t)<1e-8
                    cfg=r['settings'];assert cfg['nPredict']==128 and cfg['temperature']==0 and cfg['contextSize']==2048 and cfg['nThreads']==2
                    assert cfg['gpuLayers']==(99 if s['backend']=='vulkan' else 0) and cfg['useMmap'] is True
                    assert cfg.get('thinking') in (None,False) and cfg.get('webSearch') in (None,False)
                    assert cfg.get('systemPrompt') in (None,'')
                    hist=r['raw_history'];assert len(hist)==(2 if stage=='warmup' else 4)
                    assert [x[0] for x in hist]==['user','assistant']*(len(hist)//2)
                    assert all(isinstance(x[1],str) and x[1] for x in hist)
                assert {k:a['settings'][k] for k in PARAMS}=={k:b['settings'][k] for k in PARAMS}
                assert [x for x in a['raw_history'] if x[0]=='user']==[x for x in b['raw_history'] if x[0]=='user']
                same=same and a['raw_history']==b['raw_history'] and a['response']==b['response']
                if stage=='sample':
                    for p in ('before','after'):assert pair[p][state][stage]['raw_history'][:2]==pair[p][state]['warmup']['raw_history']
                if s['backend']=='vulkan':
                    assert b['strict']['status']=='PASS' and b['strict']['tensor_cpu_fallback']=='blocked_by_native_policy'
            a,b=pair['before'][state]['sample'],pair['after'][state]['sample']
            ratios.append(a['send_to_native_complete_s']/b['send_to_native_complete_s'])
            before.append(a['send_to_native_complete_s']);after.append(b['send_to_native_complete_s'])
        out[state]=dict(before_seconds=before,after_seconds=after,speedup_ratios=ratios,median_speedup=statistics.median(ratios),all_pairs_faster=min(ratios)>1)
    return dict(status='PASS_DIRECT_COMPARISON' if same else 'OUTPUT_CHANGED_NO_QUALITY_PRESERVING_SPEED_CLAIM',
                outputs_identical=same,observations=out,backend=s['backend'],release_approved=False,
                scope='Total Send-dispatch to native completion of 128 tokens, including prefill. Not decode-only throughput or first-visible-text. Same public controls, as-shipped engine versions/internal batching. No image comparison: first accepted mobile APK lacked image inference. Software Vulkan only; baseline offload is not strict all-tensor routing.')

if __name__=='__main__':
    s=json.loads(Path(sys.argv[1]).read_text());r=evaluate(s);assert s['result']==r and s['status']==r['status']
    print(json.dumps(r,indent=2));raise SystemExit(0 if r['outputs_identical'] else 1)
