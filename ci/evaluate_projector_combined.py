#!/usr/bin/env python3
"""Small positive repeatable gains count; correctness and regressions still gate adoption."""
import hashlib,json,math,re,statistics,sys
from pathlib import Path
MODEL='650283ee95856be73ff45fa277ac6a4238b4d1bb52a670983c2e1690fd352a12'
def canonical_sha(s):return hashlib.sha256(json.dumps(s,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def positive(n):assert isinstance(n,(int,float)) and not isinstance(n,bool) and math.isfinite(n) and n>0

def row_check(r,after,stage,kind,verify=False):
    assert r['combined'] is after and r['diagnostic'] is verify
    m=r['metrics'];assert m['completed'] is True and m['version']==3 and m['timingScope']=='prefill_synchronized_before_decode'
    assert type(r['tokens']) is int and r['tokens']==m['tokens'] and 0<r['tokens']<=128
    cfg=r['settings'];assert cfg['nPredict']==128 and cfg['temperature']==0 and cfg['gpuLayers']==99
    assert cfg['contextSize']==4096 and cfg['nThreads']==2 and cfg['useMmap'] is True
    assert r['strict']['status']=='PASS' and r['strict']['tensor_cpu_fallback']=='blocked_by_native_policy'
    positive(r['strict']['submitted_graphs']);positive(r['strict']['submitted_math_nodes'])
    positive(m['decodeNs']);positive(m['firstTokenNs']);positive(r['native_decode_tokens_s'])
    assert abs(r['native_decode_tokens_s']-r['tokens']*1e9/m['decodeNs'])<1e-8
    history=r['raw_history'];assert len(history)==(2 if stage=='warmup' else 4)
    assert [x[0] for x in history]==['user','assistant']*(len(history)//2)
    assert all(isinstance(x[1],str) and x[1] for x in history)
    if kind=='text':
        assert r['tokens']==128
        assert (m['reusedPromptTokens']==0) if stage=='warmup' else (0<m['reusedPromptTokens']<m['promptTokens'])
        return
    images=r['image_records'];assert images and all(int(n)>0 and b=='Vulkan' for n,b in images)
    assert len(r['prepared_dimensions'])==1 and all(int(w)>0 and int(h)>0 for w,h,_ in r['prepared_dimensions'])
    assert r['realized_attention'] in ('enabled','disabled')
    st,p,q=r['stages'],r['pairing'],r['qkv']
    assert st['cache_disabled']==int(kind!='cache') and st['verification']==st['verified_hits']==0
    assert p['enabled']==q['requested']==int(after)
    assert p['verification']==q['verification']==int(verify)
    assert p['paired_images']==2*p['pair_calls']
    if kind=='cache' and stage=='sample':
        assert st['hits']==len(images) and st['encode_calls']==p['pair_calls']==0
        assert p['verified_images']==q['verified_images']==0
        assert r['upload_bytes']==0
    else:
        assert st['hits']==0
        if after:assert p['pair_calls']>0
        else:assert p['pair_calls']==0
        assert p['verified_images']==(p['paired_images'] if verify else 0)
        assert q['verified_images']==(len(images) if verify else 0)
        assert st['encode_calls']==len(images)-p['pair_calls']+p['verified_images']+q['verified_images']
        positive(st['encode_call_ns']);positive(r['upload_bytes'])

def load_check(obs,after,verify=False):
    load=obs['load'];positive(load['startup_ns']);positive(load['pss_kib']);positive(obs['pss_kib_after'])
    if not after:assert load['qkv']==[];return
    assert len(load['qkv'])==1
    layers,copied,extra,verified=map(int,load['qkv'][0])
    assert layers>0 and extra>=copied>0 and verified==int(verify)

def evaluate(s,proof=None):
    if not __debug__:raise RuntimeError('Optimized Python cannot validate evidence')
    assert s['status']!='FAIL' and not s.get('error')
    assert s['model_sha256']==MODEL
    b=s['build'];assert re.fullmatch('[0-9a-f]{64}',b['apk_sha256']) and b['default_combined'] is False
    assert s['code_and_copy']=={'stream':'PASS','history':'PASS'}
    kind=s['kind'];assert kind in ('verify','awake','asleep','cache','text')
    if kind=='verify':
        assert s['pairs']==[]
        v=s['verification'];load_check(v,True,True)
        assert list(v['states'])==['awake'] and list(v['states']['awake'])==['warmup']
        r=v['states']['awake']['warmup'];row_check(r,True,'warmup','verify',True)
        return dict(status='PASS_COMBINED_BYTE_REFERENCE',quality_passed=True,verified_images=len(r['image_records']),
                    realized_attention=r['realized_attention'],release_approved=False)
    assert proof and proof['kind']=='verify' and proof['status']=='PASS_COMBINED_BYTE_REFERENCE'
    assert proof['result']==evaluate(proof)
    assert s['byte_reference_sha256']==canonical_sha(proof) and proof['build']==b
    assert s['reference_attention']==proof['result']['realized_attention']
    pairs=s['pairs'];assert len(pairs)==3
    assert [list(p) for p in pairs]==[['before','after'],['after','before'],['before','after']]
    speed=[];encoder=[];extra=[];memory=[];startup=[];text={}
    states=('awake','asleep') if kind=='text' else (('asleep',) if kind=='asleep' else ('awake',))
    for pair in pairs:
        for phase in ('before','after'):load_check(pair[phase],phase=='after')
        extra.append(int(pair['after']['load']['qkv'][0][2]))
        memory.append({p:pair[p]['pss_kib_after'] for p in ('before','after')})
        startup.append({p:pair[p]['load']['startup_ns'] for p in ('before','after')})
        for state in states:
            aa,bb=pair['before']['states'][state],pair['after']['states'][state]
            for stage in ('warmup','sample'):
                a,c=aa[stage],bb[stage]
                row_check(a,False,stage,kind);row_check(c,True,stage,kind)
                assert a['raw_history']==c['raw_history'] and a['tokens']==c['tokens'] and a['settings']==c['settings']
                assert a['metrics']['promptTokens']==c['metrics']['promptTokens']
                if stage=='sample':assert a['raw_history'][:2]==aa['warmup']['raw_history']==bb['warmup']['raw_history']
                if state=='awake':positive(a['send_to_first_ui_ns']);positive(c['send_to_first_ui_ns'])
                if kind!='text':
                    assert a['image_records']==c['image_records'] and a['prepared_dimensions']==c['prepared_dimensions']
                    assert a['upload_bytes']==c['upload_bytes']
                    assert a['realized_attention']==c['realized_attention']==s['reference_attention'],'AUTO attention changed across modes'
            a,c=aa['sample'],bb['sample']
            if kind=='text':
                tr=text.setdefault(state,{'decode':[],'first_native':[],'first_ui':[]})
                tr['decode'].append(c['native_decode_tokens_s']/a['native_decode_tokens_s'])
                tr['first_native'].append(a['metrics']['firstTokenNs']/c['metrics']['firstTokenNs'])
                if state=='awake':tr['first_ui'].append(a['send_to_first_ui_ns']/c['send_to_first_ui_ns'])
            else:
                speed.append(a['send_to_first_ui_ns']/c['send_to_first_ui_ns'] if state=='awake' else a['metrics']['firstTokenNs']/c['metrics']['firstTokenNs'])
                if kind!='cache':encoder.append(a['stages']['encode_call_ns']/c['stages']['encode_call_ns'])
    if kind=='awake':passed=min(speed)>1 and min(encoder)>1  # no old 5% minimum
    elif kind=='text':
        passed=all(min(v)>=0.97 and statistics.median(v)>=1 for t in text.values() for k,v in t.items() if v)
    else:passed=min(speed)>=0.97 and statistics.median(speed)>=1 and (not encoder or (min(encoder)>=0.97 and statistics.median(encoder)>=1))
    return dict(status='PASS_COMBINED_SMALL_GAIN' if passed and kind=='awake' else ('PASS_COMBINED_REGRESSION_GUARDS' if passed else 'COMBINED_GAIN_OR_REGRESSION_NOT_MET'),
                kind=kind,passed=passed,speedup_ratios=speed,encoder_speedup_ratios=encoder,text=text,
                extra_qkv_device_bytes=extra,app_pss_kib=memory,chat_startup_ns=startup,release_approved=False,
                scope='Three paired warmed runs of the same APK and full workload. Any consistently positive awake image/encoder gain counts. Regression controls allow at most 3% per observation and require nonnegative medians. Byte reference and actual attention policy required. PSS is not peak/total GPU memory. Unsupported projectors and a generally safe activation policy still need separate review; not a release certificate.')

if __name__=='__main__':
    s=json.loads(Path(sys.argv[1]).read_text());proof=json.loads(Path(sys.argv[2]).read_text()) if len(sys.argv)>2 else None
    r=evaluate(s,proof);assert s['result']==r and s['status']==r['status']
    print(json.dumps(r,indent=2));raise SystemExit(0 if r.get('quality_passed') or r.get('passed') else 1)
