#!/usr/bin/env python3
"""Independent text gate; image-cache improvements never count as text speedup."""
import json,statistics,sys
from pathlib import Path
from perceptible_image_gate import BASELINE,CANDIDATE

def evaluate(s):
    assert s.get('status')!='FAIL' and not s.get('error')
    assert s['build']['baseline_original_sha256']==BASELINE and s['build']['candidate_original_sha256']==CANDIDATE
    assert s['build']['resigning_payload_exact']
    pairs=s['pairs'];assert len(pairs)==3
    expected=[['before','after'],['after','before'],['before','after']]
    assert [list(p) for p in pairs]==expected
    result={}
    for state in ('awake','asleep'):
        ratios=[];latencies=[]
        for pair in pairs:
            a,b=pair['before'][state]['sample'],pair['after'][state]['sample']
            assert a['raw_history']==b['raw_history'] and a['tokens']==b['tokens']==128
            assert a['metrics']['promptTokens']==b['metrics']['promptTokens']
            for phase in ('before','after'):
                for kind in ('warmup','sample'):
                    r=pair[phase][state][kind]
                    assert r['tokens']==128 and r['metrics']['completed']
                    assert r['strict']['status']=='PASS'
                    assert r['metrics']['decodeNs']>0 and r['metrics']['reusedPromptTokens']>=0
                    assert abs(r['native_decode_tokens_s']-128e9/r['metrics']['decodeNs'])<1e-8
            ratios.append(b['native_decode_tokens_s']/a['native_decode_tokens_s'])
            if state=='awake':
                assert a['send_to_first_ui_ns']>0 and b['send_to_first_ui_ns']>0
                latencies.append(a['send_to_first_ui_ns']/b['send_to_first_ui_ns'])
        result[state]={'decode_speedup_ratios':ratios,'median_decode_speedup':statistics.median(ratios)}
        if latencies:result[state].update(first_ui_speedup_ratios=latencies,median_first_ui_speedup=statistics.median(latencies))
    # Require consistent ON throughput improvement, not a cold-first-token outlier.
    awake=result['awake'];asleep=result['asleep']
    passed=(min(awake['decode_speedup_ratios'])>=1.10 and awake['median_decode_speedup']>=1.15
            and min(asleep['decode_speedup_ratios'])>=0.97
            and min(awake['first_ui_speedup_ratios'])>=0.95)
    return {'status':'PASS_TEXT_GAIN_GATE' if passed else 'TEXT_GAIN_GATE_NOT_MET','text_gain_passed':passed,'observations':result,
            'requirements':'Each awake pair >=10% faster decode; awake median >=15%; no asleep pair >3% slower; no awake first-UI pair >5.3% slower.',
            'scope':'Three paired warmed text continuations, same model/prompt/context/128-token budget, software Vulkan. Not cold startup or physical-device certification.'}

if __name__=='__main__':
    s=json.loads(Path(sys.argv[1]).read_text());assert s.get('status') in ('PASS_TEXT_GAIN_GATE','TEXT_GAIN_GATE_NOT_MET')
    r=evaluate(s);print(json.dumps(r,indent=2));raise SystemExit(0 if r['text_gain_passed'] else 1)
