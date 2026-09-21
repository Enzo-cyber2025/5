#!/usr/bin/env python3
"""Validity checks for the within-build A/B screening runs. Approves nothing."""
import json
import statistics
import sys
from evaluate_gpu_rate import rate, MODEL, SETTINGS
from evaluate_row_tile import ENV


def evaluate(s):
    assert s['status'] == 'COMPLETE_SCREENING' and s['screening_only'] is True
    assert s['release_approved'] is False and s['state'] in ('awake', 'asleep')
    assert s['model_sha256'] == MODEL and s['baseline_environment'] == ENV
    assert s['configuration'] != ENV and len(s['pairs']) == 2
    build = s['build']; assert build['experiment']['default_enabled'] is False and build['experiment']['release_approved'] is False
    expected_apk = build['payloads']['candidate']['test_sha256']
    reference = {}; values = []
    for i, pair in enumerate(s['pairs']):
        assert pair['order'] == (['off', 'on'] if i % 2 == 0 else ['on', 'off'])
        pair_values = {}
        for arm in ('off', 'on'):
            r = pair[arm]
            assert r['status'] == 'PASS_NATIVE_OBSERVER' and r['model_sha256'] == MODEL
            assert r['settings'] == SETTINGS and r['batch'] == 128 and r['ubatch'] == 32
            assert r['vulkan_positive_offload'] is True and r['test_apk_sha256'] == expected_apk
            assert r['vulkan_environment'] == (ENV if arm == 'off' else s['configuration'])
            assert r['native_per_token_callbacks'] is True
            for stage in ('warmup', 'sample'):
                pair_values[(arm, stage)] = rate(r[stage], 'after', s['state'], stage)
                key = tuple(r[stage][field] for field in ('prompt', 'prompt_token_ids', 'response', 'chunks'))
                assert reference.setdefault(stage, key) == key, 'Screening arms produced different output'
        values.append(dict(off_tps=pair_values[('off', 'sample')], on_tps=pair_values[('on', 'sample')],
                           ratio=pair_values[('on', 'sample')]/pair_values[('off', 'sample')]))
    ratios = [v['ratio'] for v in values]
    return dict(status='SCREENING_ONLY_NOT_ACCEPTANCE', state=s['state'], label=s['label'], configuration=s['configuration'],
                pairs=values, median_paired_ratio=statistics.median(ratios),
                median_paired_gain_percent=(statistics.median(ratios)-1)*100,
                both_pairs_faster=all(x > 1 for x in ratios),
                release_approved=False, physical_gpu_certified=False,
                scope='Within-build A/B of the same candidate APK on software Vulkan. Discovery only: it cannot '
                      'approve a release, and the accepted protocol compares against the delivered and '
                      'pre-acceleration APKs instead.')


if __name__ == '__main__':
    if not __debug__: raise RuntimeError('Assertions required')
    result = evaluate(json.load(open(sys.argv[1])))
    print(json.dumps(result, indent=2))
