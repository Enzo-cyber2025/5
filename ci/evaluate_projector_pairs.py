#!/usr/bin/env python3
"""Fail-closed check of warmed, diagnostic-free pairs. No physical GPU certificate."""
import json,sys,statistics
from pathlib import Path

def evaluate(path):
    s=json.loads(Path(path).read_text())
    if s.get('status')!='PASS_PAIRED_EXPERIMENT_ONLY':raise ValueError('No completed quality-passing experiment')
    rows=s['measurements'];assert len(rows)==2 and len(s['warmups'])==4
    assert [list(x) for x in rows]==[['serial','paired'],['paired','serial']]
    verification=s['verification'];assert verification['diagnostic']
    v=verification['pairs'];assert v['verification']==1 and v['verified_images']==v['paired_images']>0
    ratios=[];result=[]
    for block in rows:
        a,b=block['serial'],block['paired']
        assert a['raw_history']==b['raw_history']
        assert a['upload_bytes']==b['upload_bytes']>0
        assert a['tokens']==b['tokens']>0
        assert a['metrics']['promptTokens']==b['metrics']['promptTokens']
        assert a['stages']['encode_calls']==b['stages']['encode_calls']+b['pairs']['pair_calls']
        for r in (a,b):
            assert not r['diagnostic'] and r['pairs']['verification']==0 and r['pairs']['verified_images']==0
            assert r['stages']['verification']==0 and r['stages']['cache_disabled']==1 and r['stages']['hits']==0
            assert r['strict']['status']=='PASS' and r['metrics']['completed']
            assert r['metrics']['decodeNs']>0 and r['send_to_first_ui_ns']>0
            assert abs(r['native_decode_tokens_s']-r['tokens']*1e9/r['metrics']['decodeNs'])<1e-8
        ratio=a['send_to_first_ui_ns']/b['send_to_first_ui_ns'];ratios.append(ratio)
        result.append({'serial_send_to_first_ui_seconds':a['send_to_first_ui_ns']/1e9,
                       'paired_send_to_first_ui_seconds':b['send_to_first_ui_ns']/1e9,'ratio':ratio,
                       'serial_encode_calls':a['stages']['encode_calls'],'paired_encode_calls':b['stages']['encode_calls']})
    return {'status':'OBSERVED_GAIN_IN_BOTH_PAIRS' if all(x>1.05 for x in ratios) else 'NO_CONSISTENT_GAIN_OVER_5_PERCENT',
            'observations':result,'median_ratio':statistics.median(ratios),
            'quality_gate':'passed raw histories and separate bit verification',
            'scope':'Two warmed same-run pairs, AB/BA, full uncached photo. Not cold startup, screen-off, statistics, physical GPU or release approval.',
            'release_approved':False,'physical_gpu_certified':False}

if __name__=='__main__':print(json.dumps(evaluate(sys.argv[1]),indent=2))
