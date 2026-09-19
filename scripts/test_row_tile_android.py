#!/usr/bin/env python3
"""Separate OFF/ON correctness, then pre-accel/delivered/tiled triples; no release."""
import json
import re
import sys
import traceback
import test_expanded_weights_android as harness
from evaluate_row_tile import evaluate, tile, ENV, ON, MODEL, COMPLETE


def candidate_metadata(native):
    assert 'llvmpipe' in native and 'fp16: 0' in native and 'int dot: 0' in native
    assert 'GGUF_EXPANDED_WEIGHTS enabled=1' not in native
    assert 'GGUF_REPACKED_WEIGHTS enabled=1' not in native
    matches = re.findall(r'GGUF_VK_ROW_TILE factor=(\d+) stdq=(\d+) q5_rows=(\d+) q8_rows=(\d+) fp16=(\d+) int_dot=(\d+) subgroup=(\d+)', native)
    assert len(matches) == 1, 'Missing/ambiguous native row-tile configuration'
    value = dict(zip(('factor', 'stdq', 'q5_rows', 'q8_rows', 'fp16', 'int_dot', 'subgroup'), map(int, matches[0])))
    assert value['factor'] in (1, 4) and value == tile(value['factor'])
    dispatches = re.findall(r'GGUF_VK_ROW_TILE_DISPATCH type=(q5_0|q8_0) rows=(\d+) activation=(\w+) quantize_y=(\d+) columns=(\d+)', native)
    expected = [('q5_0', str(value['q5_rows']), 'f32', '0', '1'), ('q8_0', str(value['q8_rows']), 'f32', '0', '1')]
    assert sorted(dispatches) == sorted(expected), 'Missing actual FP32 single-column pipeline dispatch'
    counts = re.findall(r'GGUF_ROW_TILE_CALLBACKS per_token=1 emitted=(\d+) callbacks=(\d+)', native)
    assert counts == [('128','128'), ('128','128')], 'Both native stages must independently confirm real per-token callbacks'
    return {'tile': value, 'native_per_token_callbacks': True, 'tile_dispatch': {t: dict(rows=int(r), activation=a, quantize_y=int(q), columns=int(c)) for t,r,a,q,c in dispatches}}


def main(state):
    assert state in ('awake', 'asleep')
    harness.NAME = 'row-tile'; harness.candidate_metadata = candidate_metadata
    d = harness.Android('emulator-5554', harness.E)
    s = dict(status='FAIL', state=state, hardware='software_vulkan_emulator', release_approved=False,
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
        for mode, environment in [('off', ENV), ('on', ON)]:
            s['correctness'][mode] = harness.observation(d, s, 'candidate', state, 'correctness-'+mode+'-'+state, environment)
            save()
        for stage in ('warmup', 'sample'):
            for field in ('prompt', 'prompt_token_ids', 'response', 'chunks'):
                assert s['correctness']['off'][stage][field] == s['correctness']['on'][stage][field]
        # Do not borrow OFF/ON correctness timings, warmups or another runner's rates.
        for i in range(3):
            order = ['before', 'after', 'candidate'] if i % 2 == 0 else ['candidate', 'after', 'before']
            pair = {'order': order}; s['pairs'].append(pair)
            for phase in order:
                pair[phase] = harness.observation(d, s, phase, state, f'{i+1}-{phase}-{state}', ON if phase == 'candidate' else ENV)
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
    main(sys.argv[1])
