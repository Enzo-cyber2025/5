#!/usr/bin/env python3
"""Post-check raw saved replies; never certify from trimmed display strings.
One paired observation is exploratory, not statistical/physical-GPU approval.
"""
import json,sys
from pathlib import Path

def evaluate(directory):
    d=Path(directory);s=json.loads((d/'summary.json').read_text())
    if s.get('status')!='PASS_PROJECTOR_CACHE_EXPERIMENT_ONLY':
        raise ValueError('Android experiment did not pass; no speed approval')
    result={'status':'PASS_RAW_REPLY_COMPARISON_ONLY','observations':{},'physical_gpu_certified':False,'release_approved':False}
    cases=['projector-{phase}-{screen}-0-'+stage for stage in ('cold_A','append_B','exclude_A','restore_A')]
    cases+=['whole-app-{phase}-{screen}']
    for screen in ('awake','asleep'):
        for template in cases:
            rows={}
            for phase in ('before','after'):
                label=template.format(phase=phase,screen=screen)
                r=json.loads((d/f'physical-speed-perf-{label}.json').read_text())
                history=[(m['role'],m['content']) for m in r['chat']['messages'] if m['role'] in ('user','assistant')]
                assert history and history[-1][0]=='assistant'
                assert r['tokens']==r['metrics']['tokens']>0
                assert r['metrics']['completed'] and r['metrics']['decodeNs']>0
                assert abs(r['native_decode_tokens_s']-r['tokens']*1e9/r['metrics']['decodeNs'])<1e-8
                rows[phase]=(r,history)
            before,bh=rows['before'];after,ah=rows['after']
            assert bh==ah,'Raw persisted history changed, including whitespace: '+template
            assert before['tokens']==after['tokens']
            name=template.format(phase='paired',screen=screen)
            result['observations'][name]={
                'before_first_token_ns':before['metrics']['firstTokenNs'],
                'after_first_token_ns':after['metrics']['firstTokenNs'],
                'before_decode_tokens_s':before['native_decode_tokens_s'],
                'after_decode_tokens_s':after['native_decode_tokens_s'],
                'raw_saved_history_equal':True,
            }
    return result

if __name__=='__main__':
    print(json.dumps(evaluate(sys.argv[1]),indent=2))
