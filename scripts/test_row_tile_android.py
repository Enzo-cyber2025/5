#!/usr/bin/env python3
"""Same-APK OFF/ON correctness, then pre-accel/delivered/candidate triples; no release."""
import json
import sys
import traceback
import test_expanded_weights_android as harness
from evaluate_row_tile import evaluate, parse_native, environment, tile, ENV, PREDECLARED_FACTORS, MODEL, COMPLETE


def candidate_metadata(native):
    assert 'llvmpipe' in native and 'fp16: 0' in native and 'int dot: 0' in native
    assert 'GGUF_EXPANDED_WEIGHTS enabled=1' not in native
    assert 'GGUF_REPACKED_WEIGHTS enabled=1' not in native
    configurations, dispatches = parse_native(native)
    assert len(configurations) == 1, f'Ambiguous or missing native row grouping: {configurations}'
    value = configurations[0]
    assert value['factor'] in (1, *PREDECLARED_FACTORS) and value == tile(value['factor'], bool(value['large']))
    counts = __import__('re').findall(r'GGUF_ROW_TILE_CALLBACKS per_token=1 emitted=(\d+) callbacks=(\d+)', native)
    assert counts == [('128', '128'), ('128', '128')], 'Both native stages must independently confirm real per-token callbacks'
    return {'tile': value, 'native_per_token_callbacks': True, 'tile_dispatch': dispatches}


def main(state, factor, large='0'):
    assert state in ('awake', 'asleep') and int(factor) in PREDECLARED_FACTORS
    factor = int(factor); large = large == '1'
    harness.NAME = 'row-tile'; harness.candidate_metadata = candidate_metadata
    harness.ON = environment(factor, large)
    d = harness.Android('emulator-5554', harness.E)
    s = dict(status='FAIL', state=state, factor=factor, large=large, hardware='software_vulkan_emulator', release_approved=False,
             model_sha256=harness.sha(harness.TEXT), pairs=[], correctness={},
             build=json.loads((harness.BUILD/'build.json').read_text()))
    def save():
        (harness.E/'summary.json').write_text(json.dumps(s, indent=2, ensure_ascii=False))
    try:
        assert s['model_sha256'] == MODEL and d.shell('getprop ro.kernel.qemu') == '1'
        d.adb('root', check=False); d.adb('wait-for-device'); d.adb('logcat', '-G', '32M')
        d.shell('settings put system screen_off_timeout 1800000'); d.shell('setprop debug.gguf.vulkan_device 0')
        d.adb('install', '-r', '-t', harness.BUILD/'observer.apk', timeout=180)
        d.adb('push', harness.TEXT, '/data/local/tmp/gpu-rate.gguf', timeout=180)
        assert d.shell('sha256sum /data/local/tmp/gpu-rate.gguf').split()[0] == MODEL
        for mode, env in [('off', ENV), ('on', harness.ON)]:
            s['correctness'][mode] = harness.observation(d, s, 'candidate', state, f'correctness-{mode}-{state}', env)
            save()
        for stage in ('warmup', 'sample'):
            for field in ('prompt', 'prompt_token_ids', 'response', 'chunks'):
                assert s['correctness']['off'][stage][field] == s['correctness']['on'][stage][field]
        # Do not borrow OFF/ON correctness timings, warmups or another runner's rates.
        for i in range(3):
            order = ['before', 'after', 'candidate'] if i % 2 == 0 else ['candidate', 'after', 'before']
            pair = {'order': order}; s['pairs'].append(pair)
            for phase in order:
                pair[phase] = harness.observation(d, s, phase, state, f'{i+1}-{phase}-{state}', harness.ON if phase == 'candidate' else ENV)
                save()
        s['status'] = COMPLETE; s['evaluation'] = evaluate(s)
        print(json.dumps(s['evaluation'], indent=2), flush=True)
    except Exception:
        s['status'] = 'FAIL'; (harness.E/'physical-row-tile-failure.txt').write_text(traceback.format_exc()); raise
    finally:
        d.shell('setprop wrap.'+harness.PACKAGE+" ''", check=False)
        d.shell('input keyevent 224', check=False)
        save()


if __name__ == '__main__':
    if not __debug__: raise RuntimeError('Assertions required')
    main(sys.argv[1], sys.argv[2], *(sys.argv[3:4] or ['0']))
