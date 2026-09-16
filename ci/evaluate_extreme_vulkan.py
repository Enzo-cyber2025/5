#!/usr/bin/env python3
"""Separate measurement gate for +2000% throughput, 26x shorter first-token wait,
and awake >= asleep throughput. Functional PASS is NOT this gate. A sleeping
native-prefill timer cannot certify Send->first token; missing data fails closed.
"""
import argparse,json,math,statistics
from pathlib import Path
SCREENS=('awake','asleep')

def positive(value):
    return isinstance(value,(float,int)) and not isinstance(value,bool) and math.isfinite(value) and value>0

def assess(medians):
    throughput={};latency={}
    for screen in SCREENS:
        before,after=(medians[screen][phase] for phase in ('before','after'))
        assert positive(before['decode_tokens_s']) and positive(after['decode_tokens_s'])
        throughput[screen]=after['decode_tokens_s']/before['decode_tokens_s']
        # A displayed first-text arrival is conservative for the awake UI.
        key='send_to_first_ui_ns' if screen=='awake' else 'send_to_first_token_ns'
        b,a=before.get(key),after.get(key)
        latency[screen]=b/a if positive(b) and positive(a) else None
    awake=medians['awake']['after']['decode_tokens_s']
    asleep=medians['asleep']['after']['decode_tokens_s']
    checks=dict(throughput_21x_both_states=all(r>=21 for r in throughput.values()),
                first_token_wait_26x_both_states=all(r is not None and r>=26 for r in latency.values()),
                awake_at_least_as_fast_as_asleep=awake>=asleep,
                asleep_not_slowed=asleep>=medians['asleep']['before']['decode_tokens_s'])
    return dict(status='REQUESTED_MEASUREMENTS_MET_SOFTWARE_ONLY' if all(checks.values()) else 'REQUESTED_TARGETS_NOT_MET',
                required_throughput_multiplier=21,required_first_token_speedup=26,
                throughput_multipliers=throughput,end_to_end_first_token_speedups=latency,
                awake_asleep_throughput_ratio=awake/asleep,checks=checks,
                physical_gpu_certified=False,release_approved=False,
                note='Missing screen-off Send->first-token measurements cannot be replaced with native firstTokenNs. Equality here is of observed medians, not a universal timing guarantee.')

def recompute(summary):
    assert summary['status']=='PASS_UI_EXPERIMENT_ONLY'
    assert summary['build']['changed_payload_entries']==['classes.dex']
    assert summary['build']['baseline_sha256']=='323fd5a33667c6cab278699e97c89fe253e1bb7acead45b869729bf022eb9f5c'
    medians={};responses=set()
    for screen in SCREENS:
        medians[screen]={}
        for phase in ('before','after'):
            rows=summary['series'][phase][screen];assert len(rows)==3
            for r in rows:
                j=r['metrics'];assert r['tokens']==j['tokens']==128 and j['completed'] is True
                assert positive(j['decodeNs'])
                assert math.isclose(r['native_decode_tokens_s'],128e9/j['decodeNs'],rel_tol=1e-12)
                responses.add(r['response'])
            values={'decode_tokens_s':statistics.median(128e9/r['metrics']['decodeNs'] for r in rows)}
            # Only use real recorded end-to-end observations, never native prefill proxies.
            key='send_to_first_ui_ns' if screen=='awake' else 'send_to_first_token_ns'
            if all(positive(r.get(key)) for r in rows):values[key]=statistics.median(r[key] for r in rows)
            medians[screen][phase]=values
    assert len(responses)==1,'Changed deterministic output'
    return medians

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('summary',type=Path);args=parser.parse_args()
    result=assess(recompute(json.loads(args.summary.read_text())))
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if all(result['checks'].values()) else 1)
