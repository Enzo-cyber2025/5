#!/usr/bin/env python3
"""New request: +200% means 3x, not 2x. Historical gates stay historical."""
import copy
import json
import re
import sys
from evaluate_gpu_rate import evaluate_pair, rate, HASHES, MODEL, SETTINGS

TARGET_MULTIPLIER = 3
ENV = {'GGML_VK_VISIBLE_DEVICES': '0'}
ON = {**ENV, 'GGUF_VK_ROW_TILE': '4'}
COMPLETE = 'COMPLETE_ROW_TILE_OBSERVATIONS'


def tile(factor):
    return dict(factor=factor, stdq=factor, q5_rows=2*factor, q8_rows=factor,
                fp16=0, int_dot=0, subgroup=8)


def validate_observation(r, state, build, factor):
    assert r['status'] == 'PASS_NATIVE_OBSERVER' and r['model_sha256'] == MODEL
    assert r['settings'] == SETTINGS and r['batch'] == 128 and r['ubatch'] == 32
    assert r['vulkan_positive_offload'] is True
    assert r['test_apk_sha256'] == build['payloads']['candidate']['test_sha256']
    assert r['vulkan_environment'] == (ON if factor == 4 else ENV)
    assert r['tile'] == tile(factor)
    assert r['tile_dispatch'] == {t: dict(rows=rows, activation='f32', quantize_y=0, columns=1)
                                  for t, rows in [('q5_0',2*factor), ('q8_0',factor)]}
    assert 'expansion' not in r, 'This is not a weight conversion experiment'
    for stage in ('warmup', 'sample'):
        rate(r[stage], 'after', state, stage)
    assert r['warmup']['response'] in r['sample']['prompt']


def evaluate(s):
    assert s['status'] == COMPLETE and s['state'] in ('awake', 'asleep')
    assert s['hardware'] == 'software_vulkan_emulator' and s['release_approved'] is False
    assert s['model_sha256'] == MODEL and len(s['pairs']) == 3
    build = s['build']; experiment = build['experiment']
    assert experiment['experimental_row_tile_build'] is True
    assert experiment['default_enabled'] is False and experiment['release_approved'] is False
    assert experiment['target_multiplier'] == TARGET_MULTIPLIER and experiment['row_factor'] == 4
    assert re.fullmatch('[0-9a-f]{40}', experiment['source_commit'])
    candidate = experiment['apk_sha256']; assert re.fullmatch('[0-9a-f]{64}', candidate)
    assert build['payloads']['candidate']['original_sha256'] == candidate
    assert not any(experiment.get(k, False) for k in ('experimental_expanded_weights_build', 'experimental_repacked_weights_build'))
    # SAME-APK OFF/ON correctness observations are never used for speed ratios.
    for mode, factor in [('off', 1), ('on', 4)]:
        validate_observation(s['correctness'][mode], s['state'], build, factor)
    reference = s['correctness']['off']
    for r in [s['correctness']['on'], *[p[phase] for p in s['pairs'] for phase in ('before', 'after', 'candidate')]]:
        for stage in ('warmup', 'sample'):
            for key in ('prompt', 'prompt_token_ids', 'response', 'chunks'):
                assert r[stage][key] == reference[stage][key], 'Complete output/prompt differs'
    for i, pair in enumerate(s['pairs']):
        assert pair['order'] == (['before', 'after', 'candidate'] if i % 2 == 0 else ['candidate', 'after', 'before'])
        validate_observation(pair['candidate'], s['state'], build, 4)
        for stage in ('warmup', 'sample'):
            assert pair['after'][stage]['strict']['status'] == 'PASS'

    comparisons = {}
    for label, control in [('historical', 'before'), ('delivered', 'after')]:
        projected = copy.deepcopy(s); projected['status'] = 'COMPLETE_OBSERVATIONS'
        expected = {'before': HASHES[control], 'after': candidate}
        projected['apk_sha256'] = expected.copy()
        projected['build']['payloads'] = {'before': build['payloads'][control], 'after': build['payloads']['candidate']}
        projected['pairs'] = [dict(order=['before', 'after'] if i % 2 == 0 else ['after', 'before'],
                                   before=p[control], after=p['candidate']) for i, p in enumerate(s['pairs'])]
        comparisons[label] = evaluate_pair(projected, expected, {'before': ENV, 'after': ON})
    reached = all(p['ratio'] >= TARGET_MULTIPLIER for p in comparisons['historical']['pairs'])
    no_regression = all(p['ratio'] >= 1 for p in comparisons['delivered']['pairs'])
    return dict(status='PASS_3X_THIS_TEXT_STATE_NOT_RELEASE' if reached and no_regression else 'THREE_TIMES_TARGET_NOT_MET',
                target_multiplier=TARGET_MULTIPLIER, target_gain_percent=200,
                target_3x_passed=reached and no_regression, comparisons=comparisons,
                same_apk_full_output_check_passed=True, physical_gpu_certified=False, release_approved=False,
                scope='One text fixture on software Vulkan; both screen states mandatory. Not pure kernel/UI timing, full tensor-result bit equivalence, image qualification, startup/memory qualification or signature-continuous release.')


if __name__ == '__main__':
    if not __debug__: raise RuntimeError('Assertions required')
    result = evaluate(json.load(open(sys.argv[1])))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['target_3x_passed'] else 1)
