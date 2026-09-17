#!/usr/bin/env python3
"""Quality passing CI is not speed approval; verify warmed, non-diagnostic pairs."""
import json,sys,statistics
from pathlib import Path

def evaluate(path):
    s=json.loads(Path(path).read_text())
    if s.get('status')!='PASS_QKV_EXPERIMENT_ONLY':raise ValueError('QKV experiment did not pass quality and completion')
    assert s['verification']['diagnostic'] and s['verification']['verified_images']==s['verification']['image_chunks']>0
    loads=s['loads'];assert len(loads)==5 and loads[0]['mode']=='verification'
    assert int(loads[0]['report'][0][3])==1
    for x in loads[1:]:
        if x['mode']=='fused':assert int(x['report'][0][3])==0
        else:assert not x['report']
    rows=s['measurements'];assert len(rows)==2 and len(s['warmups'])==4
    assert [list(x) for x in rows]==[['separate','fused'],['fused','separate']]
    output=[]
    for block in rows:
        a,b=block['separate'],block['fused']
        assert a['raw_history']==b['raw_history'] and a['tokens']==b['tokens']>0
        assert a['metrics']['promptTokens']==b['metrics']['promptTokens']
        assert a['upload_bytes']==b['upload_bytes']>0
        assert a['image_chunks']==b['image_chunks']>0
        for r in (a,b):
            assert not r['diagnostic'] and r['verified_images']==0
            assert r['stages']['cache_disabled']==1 and r['stages']['hits']==0 and r['stages']['verification']==0
            assert r['stages']['encode_calls']==r['image_chunks']
            assert r['strict']['status']=='PASS' and r['metrics']['completed']
            assert r['metrics']['decodeNs']>0 and r['send_to_first_ui_ns']>0
            assert abs(r['native_decode_tokens_s']-r['tokens']*1e9/r['metrics']['decodeNs'])<1e-8
        output.append({'separate_first_ui_s':a['send_to_first_ui_ns']/1e9,'fused_first_ui_s':b['send_to_first_ui_ns']/1e9,
                       'ratio':a['send_to_first_ui_ns']/b['send_to_first_ui_ns'],
                       'separate_encode_call_s':a['stages']['encode_call_ns']/1e9,'fused_encode_call_s':b['stages']['encode_call_ns']/1e9})
    ratios=[x['ratio'] for x in output]
    return {'status':'OBSERVED_GAIN_IN_BOTH_PAIRS' if all(x>1.05 for x in ratios) else 'NO_CONSISTENT_GAIN_OVER_5_PERCENT',
            'observations':output,'median_ratio':statistics.median(ratios),
            'extra_device_bytes':[int(x['report'][0][2]) for x in loads if x['report']],
            'quality':'exact original weight-copy bytes, full projector output reference, raw saved histories',
            'scope':'Two AB/BA warmed observations per mode on one software-Vulkan runner; not physical GPU, statistics, cold startup or global speedup',
            'release_approved':False,'physical_gpu_certified':False}

if __name__=='__main__':print(json.dumps(evaluate(sys.argv[1]),indent=2))
