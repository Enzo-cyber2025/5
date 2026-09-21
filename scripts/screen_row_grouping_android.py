#!/usr/bin/env python3
"""Screening only: A/B the SAME candidate APK with itself, one lever at a time.

Both arms install the identical APK; only the environment differs. Discovery,
never acceptance: the accepted protocol in scripts/test_row_tile_android.py is
the one that compares against the pre-acceleration and delivered APKs.
"""
import json
import os
import sys
import traceback
import test_expanded_weights_android as harness
from test_row_tile_android import candidate_metadata
from evaluate_row_tile import ENV, MODEL


def main(state, label):
    assert state in ('awake', 'asleep')
    config = json.loads(os.environ['SCREEN_ENV'])
    assert config != ENV and 'GGUF_VK_ROW_TILE' in config or 'GGUF_VK_DMMV_LARGE' in config, config
    harness.NAME = 'screen'; harness.ON = config; harness.candidate_metadata = candidate_metadata
    d = harness.Android('emulator-5554', harness.E)
    build = json.loads((harness.BUILD/'build.json').read_text())
    assert build['experiment']['default_enabled'] is False and build['experiment']['release_approved'] is False
    s = dict(status='FAIL', state=state, label=label, screening_only=True, release_approved=False,
             configuration=config, baseline_environment=ENV, model_sha256=harness.sha(harness.TEXT), pairs=[], build=build)
    def save():
        (harness.E/'summary.json').write_text(json.dumps(s, indent=2, ensure_ascii=False))
    try:
        assert s['model_sha256'] == MODEL and d.shell('getprop ro.kernel.qemu') == '1'
        d.adb('root', check=False); d.adb('wait-for-device'); d.adb('logcat', '-G', '32M')
        d.shell('settings put system screen_off_timeout 1800000'); d.shell('setprop debug.gguf.vulkan_device 0')
        d.adb('install', '-r', '-t', harness.BUILD/'observer.apk', timeout=180)
        d.adb('push', harness.TEXT, '/data/local/tmp/gpu-rate.gguf', timeout=180)
        assert d.shell('sha256sum /data/local/tmp/gpu-rate.gguf').split()[0] == MODEL
        for i in range(2):
            order = ['off', 'on'] if i % 2 == 0 else ['on', 'off']
            pair = {'order': order}; s['pairs'].append(pair)
            for arm in order:
                env = ENV if arm == 'off' else config
                pair[arm] = harness.observation(d, s, 'candidate', state, f'{i+1}-{arm}-{state}', env)
                save()
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
