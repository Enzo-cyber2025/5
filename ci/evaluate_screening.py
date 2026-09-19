#!/usr/bin/env python3
"""Validity checks for the A/B screening runs. Never approves anything."""
import json
import statistics
import sys
from evaluate_gpu_rate import rate, MODEL, SETTINGS
from evaluate_row_tile import ENV


def evaluate(s):
    assert s['status'] == 'COMPLETE_SCREENING' and s['screening_only'] is True
    assert s['release_approved'] is False and s['state'] in ('awake', 'asleep')
    assert s['model_sha256'] == MODEL and len(s['pairs']) == 2
    reference = {}
    values = []
    for i, pair in enumerate(s['pairs']):
        assert pair['order'] == (['before', 'candidate'] if i % 2 == 0 else ['candidate', 'before'])
        pair_values = {}
        for phase in ('before', 'candidate'):
            r = pair[phase]
            assert r['status'] == 'PASS_NATIVE_OBSERVER' and r['model_sha256'] == MODEL
            assert r['settings'] == SETTINGS and r['batch'] == 128 and r['ubatch'] == 32
            assert r['vulkan_positive_offload'] is True and r['test_apk_sha256'] == s['build']['payloads']['candidate']['test_sha256']
            assert r['vulkan_environment'] == (ENV if phase == 'before' else s['configuration'])
            for stage in ('warmup', 'sample'):
                pair_values[(phase, stage)] = rate(r[stage], 'after', s['state'], stage)
                key = tuple(r[stage][field] for field in ('prompt', 'prompt_token_ids', 'response', 'chunks'))
                assert reference.setdefault(stage, key) == key, 'Screening arms produced different output'
        values.append(dict(before_tps=pair_values[('before', 'sample')], after_tps=pair_values[('candidate', 'sample')],
                           ratio=pair_values[('candidate', 'sample')]/pair_values[('before', 'sample')]))
    ratios = [v['ratio'] for v in values]
    return dict(status='SCREENING_ONLY_NOT_ACCEPTANCE', state=s['state'], label=s['label'], configuration=s['configuration'],
                pairs=values, median_paired_ratio=statistics.median(ratios),
                median_paired_gain_percent=(statistics.median(ratios)-1)*100,
                both_pairs_faster=all(x > 1 for x in ratios),
                release_approved=False, physical_gpu_certified=False,
                scope='Within-build A/B of the same candidate APK on software Vulkan. Discovery only: it cannot '
                      'approve a release and the accepted protocol compares against the delivered and pre-acceleration APKs.')


if __name__ == '__main__':
    if not __debug__: raise RuntimeError('Assertions required')
    print(json.dumps(evaluate(json.load(open(sys.argv[1]))), indent=2))
