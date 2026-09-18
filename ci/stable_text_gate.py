#!/usr/bin/env python3
"""Explicit user-authorized policy; never rewrites the original 15% gate result.
'Consistent' means the observed paired tests, not statistical/all-device proof.
"""
from perceptible_text_gate import evaluate as original_gate
from perceptible_image_gate import CANDIDATE
POLICY='user-stable-observed-v1'
USER_REQUEST='qualquer ganho estavel e valido. e aplique tudo que nao atarpalha o desempenho'

def evaluate(report,authorization):
    if not __debug__:raise RuntimeError('Optimized Python cannot validate release evidence')
    assert authorization['policy']==POLICY
    assert authorization['user_request']==USER_REQUEST
    assert authorization['payload_source_sha256']==CANDIDATE
    assert authorization['preserve_original_gate_result'] is True
    assert report['status'] in ('PASS_TEXT_GAIN_GATE','TEXT_GAIN_GATE_NOT_MET')
    old=original_gate(report)  # Includes complete histories, budgets, warmup, routes and finite timings.
    on=old['observations']['awake'];off=old['observations']['asleep']
    passed=(min(on['decode_speedup_ratios'])>1.0
            and min(on['first_ui_speedup_ratios'])>=1.0
            and min(off['decode_speedup_ratios'])>=0.97
            and off['median_decode_speedup']>=1.0)
    return dict(status='PASS_USER_STABLE_OBSERVED_TEXT_GAIN' if passed else 'USER_STABLE_TEXT_GAIN_NOT_MET',
                text_gain_passed=passed,policy=POLICY,observations=old['observations'],
                original_gate_status=old['status'],original_gate_passed=old['text_gain_passed'],
                requirements='Every one of three warmed awake pairs faster; no first-text pair slower; asleep median not slower and no asleep pair >3% slower. Original quality/input/128-token/cache/routing checks unchanged.',
                scope='User explicitly accepts small consistent measured gains. Consistency in three observed paired runs, not statistical certainty or physical-device/all-model performance certification. Original 15% requirement remains failed if it failed; not retroactively relabeled.')
