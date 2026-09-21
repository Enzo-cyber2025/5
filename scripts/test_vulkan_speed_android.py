#!/usr/bin/env python3
"""Exact signed before/after Vulkan, BOTH screen states, same 128-token workload.
Software Vulkan validates functionality; it is not phone throughput certification.
"""
import hashlib
import json
import re
import statistics
import shlex
import traceback
from pathlib import Path

from test_latency_android import LatencyAndroid, wait_ready
from test_performance_android import run_reply
from test_reply_notifications_android import init_ime, wake
from test_generation_stats_android import TEXT
from test_code_android import run as code_ui
from test_image_android import pixels, inference
from android_checks import PACKAGE, position, vulkan_offloaded
from vulkan_strict_checks import strict_audit

E = Path('evidence')
PROMPT = 'Give three useful study tips.'
FOLLOW = 'Explain one more useful study tip.'


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def gpu_chat(d, model, label):
    d.adb('logcat', '-c')
    chat = d.new_chat(model, 99, context_size=2048, threads=0)
    wait_ready(d)
    log = d.adb('logcat', '-d', f'--pid={d.alive()}')
    (E/f'physical-vulkan-{label}-load.txt').write_text(log[-100000:])
    assert vulkan_offloaded(log), 'No actual Vulkan offload; see load log'
    assert chat['gpuLayers'] == 99 and chat['nThreads'] == 0
    return chat


def measured(d, chat, prompt, label, asleep, new, strict=False):
    # Both signed versions already have UI timing/completion notices.
    r = run_reply(d, chat, prompt, 'vulkan-'+label, asleep, True)
    log = d.adb('logcat', '-d', f'--pid={d.alive()}')
    assert r['metrics']['version'] == 3
    assert r['metrics']['timingScope'] == 'prefill_synchronized_before_decode'
    assert r['tokens'] > 0 and r['metrics']['completed']
    if new:
        hit = re.search(r'GGUF_VULKAN_DELIVERY token_only_export=1 overlap_submissions=(\d+) first_text_immediate=1', log)
        assert hit and 0 < int(hit[1]) < r['tokens']
        sampled = re.search(r'GGUF_GPU_SAMPLING_RESULT backend_selected=(\d+) emitted=(\d+)', log)
        assert sampled and int(sampled[2]) == r['tokens']
        if chat.get('temperature', 0) <= 0: assert int(sampled[1]) > 0
        # A non-greedy chain may be only partially supported on this driver.
        # Its original CPU fallback is valid and must not be relabelled all-GPU.
        r['overlap_submissions'] = int(hit[1])
        r['backend_selected'] = int(sampled[1])
    if strict:
        r['strict_tensor_routing'] = strict_audit(log)
    return r


def main():
    E.mkdir(exist_ok=True)
    d = LatencyAndroid('emulator-5554', E)
    c = json.load(open('ci/vulkan-candidate.json'))
    apk = Path('.delivery/GGUF-Chat-mobile.apk')
    base = Path('.cache/vulkan-baseline.apk')
    s = dict(status='FAIL', apk_sha256=sha(apk), baseline_sha256=sha(base), checks={}, series={})
    try:
        assert s['apk_sha256'] == c['apk_sha256'] and s['baseline_sha256'] == c['baseline_sha256']
        assert d.shell('getprop ro.kernel.qemu') == '1'
        d.adb('root', check=False); d.adb('wait-for-device')
        d.shell('wm size 720x1280'); d.shell('wm density 240'); d.adb('logcat', '-G', '16M')
        d.shell('pm disable-user --user 0 com.google.android.apps.nexuslauncher', check=False)
        d.shell('setprop debug.gguf.vulkan_device 0')
        assert d.shell('getprop debug.gguf.vulkan_device') == '0'
        init_ime(d)
        d.adb('install', '-g', base, timeout=180)
        d.grant_test_notifications()
        for phase in ('before', 'after'):
            new = phase == 'after'
            strict = new and c.get('strict_tensor_routing', False)
            if new:
                old_models, old_chats = d.read_json('models.json'), d.read_json('chats.json')
                assert c['signer_sha256'] == c['baseline_signer_sha256']
                d.adb('install', '-r', '-g', apk, timeout=180)
                assert d.read_json('models.json') == old_models and d.read_json('chats.json') == old_chats
                s['checks']['same_key_update_preserves_data'] = 'PASS'
                s['checks']['code_clipboard'] = code_ui(d)
                d.shell('am start -W -n com.ggufchat.codetest/.CodeActivity --es mode plain')
                d.wait(lambda: position(d.ui(), text='Texto simples OK', package={'com.ggufchat.codetest'}), 'exact plain text on original view')
                d.capture('physical-vulkan-plain-view.png')
                s['checks']['plain_original_view'] = 'PASS'
                pixels(d); s['checks']['android_image_decoder'] = 'PASS'
                s['checks']['actual_visual_inference'] = inference(d, gpu_layers=99 if strict else 0)
                if strict:
                    log = d.adb('logcat', '-d', f'--pid={d.alive()}')
                    s['checks']['visual_strict_tensor_routing'] = strict_audit(log)
            if new:
                # Reuse the model whose preservation was just verified. A second
                # asynchronous import could race the next force-stop or create a
                # duplicate filename, invalidating the before/after comparison.
                model = next(x for x in d.read_json('models.json') if x['id']==model['id'])
            else:
                model = d.import_model(TEXT)
            assert d.shell('sha256sum '+shlex.quote(model['path'])).split()[0] == sha(TEXT)
            s['series'][phase] = {}
            for screen in ('awake', 'asleep'):
                runs = []; s['series'][phase][screen] = runs
                for i in range(4):
                    label = f'{phase}-{screen}-{i}'
                    chat = gpu_chat(d, model, label)
                    r = measured(d, chat, PROMPT, label, screen=='asleep', new, strict)
                    if i: runs.append(r)  # one warm-up, three measured runs
                    if i == 3:
                        follow = measured(d, chat, FOLLOW, label+'-follow', screen=='asleep', new, strict)
                        assert follow['metrics']['reusedPromptTokens'] > 0
                        s['series'][phase][screen+'_follow'] = follow
                        d.capture('physical-vulkan-'+label+'-follow.png')
            # The released UI derives seed from nanoTime; Chat has NO seed field.
            # Exercise real non-greedy fallback, without pretending two random
            # runs have the same seed or requiring identical stochastic text.
            chat = gpu_chat(d, model, phase+'-non-greedy')
            d.shell('am force-stop '+PACKAGE)
            chats = d.read_json('chats.json')
            for row in chats:
                if row['id'] == chat['id']:
                    row.update(temperature=0.7); chat=row
            d.write_private('files/chats.json', json.dumps(chats))
            d.launch(); d.open_existing_chat(chat['title']); wait_ready(d)
            s['series'][phase]['non_greedy'] = measured(d, chat, PROMPT, phase+'-non-greedy', False, new, strict)
        for screen in ('awake', 'asleep'):
            before, after = s['series']['before'][screen], s['series']['after'][screen]
            assert len(before) == len(after) == 3
            for a, b in zip(before, after):
                assert a['response'] == b['response'] and a['tokens'] == b['tokens'], 'Changed output: '+screen
            a, b = s['series']['before'][screen+'_follow'], s['series']['after'][screen+'_follow']
            assert a['response'] == b['response'] and a['tokens'] == b['tokens'], 'Changed continuation'
        assert all(s['series'][phase]['non_greedy']['response'].strip() for phase in ('before','after'))
        s['checks']['non_greedy_completed_original_sampling'] = 'PASS (different runtime-generated seeds; not output-equality proof)'
        s['checks']['identical_greedy_outputs_both_screen_states'] = 'PASS'
        if c.get('strict_tensor_routing'):
            s['checks']['strict_tensor_routing_both_screen_states_and_non_greedy'] = 'PASS'
            s['checks']['host_orchestration'] = 'CPU: Android, files, tokenization, image preprocessing, RNG/state; NOT an all-application-on-GPU claim'
        s['checks']['actual_vulkan_sleep_notice_and_cleanup'] = 'PASS'
        s['medians'] = {screen: {phase: {
            'total_s': statistics.median(x['prefill_and_generation_seconds'] for x in s['series'][phase][screen]),
            'first_native_text_s': statistics.median(x['metrics']['firstTokenNs']/1e9 for x in s['series'][phase][screen]),
            'decode_tokens_s': statistics.median(x['native_decode_tokens_s'] for x in s['series'][phase][screen])
        } for phase in ('before','after')} for screen in ('awake','asleep')}
        s['status'] = 'PASS'
    except Exception as ex:
        s['error'] = str(ex)
        (E/'physical-vulkan-failure.txt').write_text(traceback.format_exc()); traceback.print_exc()
    finally:
        s['scope'] = 'Same Android 35 x86_64 emulator, software Vulkan, SmolLM2-135M Q4_K_M, context 2048, GPU 99, Auto threads, 128-token limit. 1 warmup+3 measured per screen state; follow and non-greedy are single observations with no fixed stochastic seed. No phone/physical-GPU 5-second or 20-T/s certification.'
        s['model_sha256'] = sha(TEXT)
        (E/'summary.json').write_text(json.dumps(s, indent=2, ensure_ascii=False))
        try:
            log=d.adb('logcat','-d',f'--pid={d.alive()}')
            (E/'physical-vulkan-final-log.txt').write_text(log[-150000:]);d.capture('physical-vulkan-final.png')
        except Exception: pass
    return 0 if s['status']=='PASS' else 1

if __name__ == '__main__': raise SystemExit(main())
