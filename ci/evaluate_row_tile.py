#!/usr/bin/env python3
"""+200% means 3x. Screening factors are predeclared; every pair must clear it."""
import copy
import json
import re
import sys
from pathlib import Path
from evaluate_gpu_rate import evaluate_pair, rate, HASHES, MODEL, SETTINGS

TARGET_MULTIPLIER = 3
PREDECLARED_FACTORS = (4, 8)
ACCEPTED_FACTORS = (1, 2, 4, 8, 16)
ENV = {'GGML_VK_VISIBLE_DEVICES': '0'}
COMPLETE = 'COMPLETE_ROW_TILE_OBSERVATIONS'
CONFIG = re.compile(r'GGUF_VK_ROW_TILE factor=(\d+) stdq=(\d+) kq=(\d+) stdq_int=(\d+) kq_int=(\d+) '
                    r'q5_rows=(\d+) q8_rows=(\d+) kq_rows=(\d+) fp16=(\d+) int_dot=(\d+) subgroup=(\d+)')
DISPATCH = re.compile(r'GGUF_VK_ROW_TILE_DISPATCH type=(\w+) rows=(\d+) activation=(\w+) quantize_y=(\d+) columns=(\d+)')
KEYS = ('factor', 'stdq', 'kq', 'stdq_int', 'kq_int', 'q5_rows', 'q8_rows', 'kq_rows', 'fp16', 'int_dot', 'subgroup')


def environment(factor):
    return ENV if factor == 1 else {**ENV, 'GGUF_VK_ROW_TILE': str(factor)}


def tile(factor):
    assert factor in ACCEPTED_FACTORS
    return dict(zip(KEYS, (factor, factor, 2*factor, factor, factor, 2*factor, factor, 2*factor, 0, 0, 8)))


def dispatch(factor):
    # Mirror of the pinned pipeline constants: stdq rows are 2*rm_stdq (Q8_0 1*rm_stdq),
    # k-quants use rm_kq directly.
    return {t: dict(rows=rows, activation='f32', quantize_y=0, columns=1)
            for t, rows in [('q5_0', 2*factor), ('q8_0', factor), ('q4_K', 2*factor), ('q6_K', 2*factor)]}


def parse_native(native):
    configurations = {tuple(int(v) for v in match) for match in CONFIG.findall(native)}
    matches = [dict(zip(KEYS, values)) for values in configurations]
    dispatches = {}
    for name, rows, activation, quantize_y, columns in DISPATCH.findall(native):
        entry = dict(rows=int(rows), activation=activation, quantize_y=int(quantize_y), columns=int(columns))
        assert dispatches.setdefault(name, entry) == entry, 'Conflicting dispatch audit entries'
    return matches, dispatches


def validate_observation(r, state, build, factor):
    assert r['status'] == 'PASS_NATIVE_OBSERVER' and r['model_sha256'] == MODEL
    assert r['settings'] == SETTINGS and r['batch'] == 128 and r['ubatch'] == 32
    assert r['vulkan_positive_offload'] is True
    assert r['test_apk_sha256'] == build['payloads']['candidate']['test_sha256']
    assert r['vulkan_environment'] == environment(factor)
    assert r['native_per_token_callbacks'] is True
    assert r['tile'] == tile(factor), (r['tile'], tile(factor))
    assert r['tile_dispatch'] == dispatch(factor), (r['tile_dispatch'], dispatch(factor))
    assert 'expansion' not in r, 'This is not a weight conversion experiment'
    for stage in ('warmup', 'sample'):
        rate(r[stage], 'after', state, stage)
    assert r['warmup']['response'] in r['sample']['prompt']


def evaluate(s):
    assert s['status'] == COMPLETE and s['state'] in ('awake', 'asleep')
    assert s['hardware'] == 'software_vulkan_emulator' and s['release_approved'] is False
    assert s['model_sha256'] == MODEL and len(s['pairs']) == 3
    factor = s['factor']
    assert int(factor) in PREDECLARED_FACTORS, 'Only predeclared screening factors may be measured'
    build = s['build']; experiment = build['experiment']
    assert experiment['experimental_row_tile_build'] is True
    assert experiment['default_enabled'] is False and experiment['release_approved'] is False
    assert experiment['target_multiplier'] == TARGET_MULTIPLIER
    assert list(experiment['predeclared_factors']) == list(PREDECLARED_FACTORS)
    assert experiment['per_token_callbacks'] is True
    assert re.fullmatch('[0-9a-f]{40}', experiment['source_commit'])
    candidate = experiment['apk_sha256']; assert re.fullmatch('[0-9a-f]{64}', candidate)
    assert build['payloads']['candidate']['original_sha256'] == candidate
    assert not any(experiment.get(k, False) for k in ('experimental_expanded_weights_build', 'experimental_repacked_weights_build'))
    # SAME-APK OFF/ON correctness observations are never used for speed ratios.
    for mode, mode_factor in [('off', 1), ('on', factor)]:
        validate_observation(s['correctness'][mode], s['state'], build, mode_factor)
    reference = s['correctness']['off']
    for r in [s['correctness']['on'], *[p[phase] for p in s['pairs'] for phase in ('before', 'after', 'candidate')]]:
        for stage in ('warmup', 'sample'):
            for key in ('prompt', 'prompt_token_ids', 'response', 'chunks'):
                assert r[stage][key] == reference[stage][key], 'Complete output/prompt differs'
    for i, pair in enumerate(s['pairs']):
        assert pair['order'] == (['before', 'after', 'candidate'] if i % 2 == 0 else ['candidate', 'after', 'before'])
        validate_observation(pair['candidate'], s['state'], build, factor)
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
        comparisons[label] = evaluate_pair(projected, expected, {'before': ENV, 'after': environment(factor)})
    reached = all(p['ratio'] >= TARGET_MULTIPLIER for p in comparisons['historical']['pairs'])
    no_regression = all(p['ratio'] >= 1 for p in comparisons['delivered']['pairs'])
    return dict(status='PASS_3X_THIS_TEXT_STATE_NOT_RELEASE' if reached and no_regression else 'THREE_TIMES_TARGET_NOT_MET',
                tested_factor=factor, target_multiplier=TARGET_MULTIPLIER, target_gain_percent=200,
                target_3x_passed=reached and no_regression, comparisons=comparisons,
                same_apk_full_output_check_passed=True, physical_gpu_certified=False, release_approved=False,
                scope='One text fixture on software Vulkan; both screen states and both predeclared factors must be reported. '
                      'Not pure kernel/UI timing, full tensor-result bit equivalence, image qualification, startup/memory qualification or signature-continuous release.')


if __name__ == '__main__':
    if not __debug__: raise RuntimeError('Assertions required')
    summary = json.load(open(sys.argv[1]))
    result = evaluate(summary)
    evidence = Path('evidence'); evidence.mkdir(exist_ok=True)
    (evidence/f"physical-row-tile-target-{summary['state']}-f{summary['factor']}.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['target_3x_passed'] else 1)
