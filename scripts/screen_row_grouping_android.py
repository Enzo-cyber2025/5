#!/usr/bin/env python3
"""Screening only: A/B the candidate APK's own configurations on one emulator.

This is discovery, not acceptance. It never approves a release and never
replaces the historical/delivered protocol in scripts/test_row_tile_android.py.
"""
import json
import os
import sys
import traceback
import test_expanded_weights_android as harness
from evaluate_row_tile import ENV, MODEL


def main(state, label):
    assert state in ('awake', 'asleep')
    config = json.loads(os.environ['SCREEN_ENV'])
    assert config != ENV, 'Screening baseline must leave the build at its own defaults'
    harness.NAME = 'screen'; harness.ON = config
    d = harness.Android('emulator-5554', harness.E)
    build = json.loads((harness.BUILD/'build.json').read_text())
    assert build['experiment']['default_enabled'] is False and build['experiment']['release_approved'] is False
    # Both arms are the same candidate APK: one with this build's defaults, one with the lever.
    build = dict(build); build['payloads'] = {name: dict(build['payloads']['candidate']) for name in ('before', 'candidate')}
    s = dict(status='FAIL', state=state, label=label, screening_only=True, release_approved=False,
             configuration=config, model_sha256=harness.sha(harness.TEXT), pairs=[], build=build)
    def save():
        (harness.E/'summary.json').write_text(json.dumps(s, indent=2, ensure_ascii=False))
    try:
        assert s['model_sha256'] == MODEL and d.shell('getprop ro.kernel.qemu') == '1'
        d.adb('root', check=False); d.adb('wait-for-device'); d.adb('logcat', '-G', '32M')
        d.shell('settings put system screen_off_timeout 1800000'); d.shell('setprop debug.gguf.vulkan_device 0')
        d.adb('install', '-r', '-t', harness.BUILD/'observer.apk', timeout=180)
        d.adb('push', harness.TEXT, '/data/local/tmp/gpu-rate.gguf', timeout=180)
        assert d.shell('sha256sum /data/local/tmp/gpu-rate.gguf').split()[0] == MODEL
        reference = {}
        for i in range(2):
            pair = {'order': ['before', 'candidate'] if i % 2 == 0 else ['candidate', 'before']}; s['pairs'].append(pair)
            for phase in pair['order']:
                env = ENV if phase == 'before' else config
                pair[phase] = harness.observation(d, s, phase, state, f'{i+1}-{phase}-{state}', env)
                save()
                for stage in ('warmup', 'sample'):
                    key = tuple(pair[phase][stage][field] for field in ('prompt', 'prompt_token_ids', 'response', 'chunks'))
                    if stage in reference:
                        assert reference[stage] == key, 'Screening arms produced different output'
                    else:
                        reference[stage] = key
        s['status'] = 'COMPLETE_SCREENING'
    except Exception:
        s['status'] = 'FAIL'; (harness.E/f'physical-screen-{label}-failure.txt').write_text(traceback.format_exc()); raise
    finally:
        d.shell('setprop wrap.'+harness.PACKAGE+" ''", check=False)
        d.shell('input keyevent 224', check=False)
        save()


if __name__ == '__main__':
    if not __debug__: raise RuntimeError('Assertions required')
    main(sys.argv[1], sys.argv[2])
