#!/usr/bin/env python3
"""Warmed before/after of two UI-only changes, keeping native binaries exact.
Debug-signed candidate on a disposable emulator, NOT release/update acceptance.
Neither functional PASS nor fewer drawn frames implies the requested 21x/26x.
"""
import hashlib,json,re,statistics,traceback
from pathlib import Path
from test_latency_android import LatencyAndroid,wait_ready,latest_footer
from test_performance_android import run_reply
from test_reply_notifications_android import init_ime,wake
from test_vulkan_speed_android import gpu_chat,PROMPT
from test_generation_stats_android import TEXT
from test_code_android import run as code_ui
from android_checks import PACKAGE,position
from vulkan_strict_checks import strict_audit
E=Path('evidence')

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    E.mkdir(exist_ok=True);d=LatencyAndroid('emulator-5554',E)
    build=json.loads((E/'physical-ui-build.json').read_text())
    s=dict(status='FAIL',build=build,series={},checks={},medians={})
    try:
        assert d.shell('getprop ro.kernel.qemu')=='1'
        d.adb('root',check=False);d.adb('wait-for-device')
        d.shell('wm size 720x1280');d.shell('wm density 240');d.adb('logcat','-G','32M')
        d.shell('pm disable-user --user 0 com.google.android.apps.nexuslauncher',check=False)
        d.shell('setprop debug.gguf.vulkan_device 0');init_ime(d)
        reference=None
        for phase,apk in [('before',Path('.delivery/GGUF-Chat-mobile.apk')),('after',Path('.cache/ui-experiment/candidate.apk'))]:
            assert sha(apk)==build['baseline_sha256' if phase=='before' else 'candidate_sha256']
            if phase=='after':
                # Not an update test. No user phone/data is connected; only this
                # positively identified disposable emulator can be uninstalled.
                assert d.shell('getprop ro.kernel.qemu')=='1'
                d.adb('uninstall',PACKAGE)
            d.adb('install','-g',apk,timeout=180);d.grant_test_notifications()
            model=d.import_model(TEXT);s['series'][phase]={'awake':[],'asleep':[]}
            assert d.shell('sha256sum '+model['path']).split()[0]==sha(TEXT)
            # One excluded warmup PER state, followed by 3 measured repetitions.
            # Interleave screen states and reverse order on alternate repetitions.
            for i in range(4):
                states=('awake','asleep') if i%2==0 else ('asleep','awake')
                for screen in states:
                    label=f'ui-{phase}-{screen}-{i}'
                    chat=gpu_chat(d,model,label);wait_ready(d)
                    d.shell('dumpsys gfxinfo '+PACKAGE+' reset')
                    r=run_reply(d,chat,PROMPT,label,screen=='asleep',True)
                    log=d.adb('logcat','-d',f'--pid={d.alive()}')
                    r['strict_tensor_routing']=strict_audit(log)
                    assert r['tokens']==128 and r['metrics']['completed']
                    assert abs(r['native_decode_tokens_s']-128e9/r['metrics']['decodeNs'])<1e-9
                    if reference is None:reference=r['response']
                    assert r['response']==reference,'Changed deterministic output'
                    notice=re.search(r'GGUF_NOTICE_STATS progress_updates=(\d+) skipped_screen_off=(\d+)',log)
                    assert notice,'Missing real completion counters'
                    r['notification_updates']=int(notice[1]);r['skipped_screen_off']=int(notice[2])
                    gfx=d.shell('dumpsys gfxinfo '+PACKAGE+' framestats')
                    (E/f'physical-{label}-frames.txt').write_text(gfx[-100000:])
                    hit=re.search(r'Total frames rendered:\s*(\d+)',gfx)
                    if hit:r['frames_rendered_including_harness_navigation']=int(hit[1])
                    if i:s['series'][phase][screen].append(r)
                    else:(E/f'physical-{label}-warmup.json').write_text(json.dumps(r,indent=2))
                    (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
                    if i==3:latest_footer(d,r,label)
            if phase=='after':
                s['checks']['code_stream_history_copy']=code_ui(d)
                d.shell('am start -W -n com.ggufchat.codetest/.TailActivity')
                d.wait(lambda:position(d.ui(),text='Rolagem direta OK',package={'com.ggufchat.codetest'}),'real post-layout direct scroll',timeout=30)
                d.capture('physical-ui-tail.png');s['checks']['direct_scroll_after_layout']='PASS'
                d.shell('am force-stop com.ggufchat.codetest')
        s['checks']['same_128_token_outputs_and_strict_routing']='PASS'
        s['checks']['real_sleep_notice_and_service_cleanup']='PASS'
        for screen in ('awake','asleep'):
            s['medians'][screen]={}
            for phase in ('before','after'):
                rows=s['series'][phase][screen]
                values=dict(decode_tokens_s=statistics.median(r['native_decode_tokens_s'] for r in rows),native_first_token_ns=statistics.median(r['metrics']['firstTokenNs'] for r in rows),notification_updates=statistics.median(r['notification_updates'] for r in rows))
                if screen=='awake':values['send_to_first_ui_ns']=statistics.median(r['send_to_first_ui_ns'] for r in rows)
                s['medians'][screen][phase]=values
        s['status']='PASS_UI_EXPERIMENT_ONLY'
        awake=s['medians']['awake'];asleep=s['medians']['asleep']
        s['requested_target_observations']=dict(
            required_throughput_multiplier=21,required_first_token_speedup=26,
            throughput_multipliers={screen:v['after']['decode_tokens_s']/v['before']['decode_tokens_s'] for screen,v in s['medians'].items()},
            awake_send_to_first_ui_speedup=awake['before']['send_to_first_ui_ns']/awake['after']['send_to_first_ui_ns'],
            awake_asleep_throughput_ratio=awake['after']['decode_tokens_s']/asleep['after']['decode_tokens_s'],
            end_to_end_sleep_latency_measured=False,
            all_requested_targets_certified=False)
    except Exception as ex:
        s['error']=str(ex);(E/'physical-ui-failure.txt').write_text(traceback.format_exc());traceback.print_exc()
    finally:
        s['scope']='Android35 x86_64 SOFTWARE Vulkan. SmolLM2-135M Q4_K_M, context2048/GPU99/auto threads/128 tokens. One excluded warmup +3 per state/version. Fixed version order can retain thermal/cache bias. Native first-token metric is NOT Send->first token with screen off. No release/update or phone speed certification.'
        (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
        try:
            log=d.adb('logcat','-d')
            (E/'physical-ui-final-log.txt').write_text('\n'.join(x for x in log.splitlines() if any(t in x for t in ('GGUF','AndroidRuntime','FATAL','ANR in')))[-150000:])
            wake(d);d.capture('physical-ui-final.png')
        except Exception:pass
    return 0 if s['status']=='PASS_UI_EXPERIMENT_ONLY' else 1

if __name__=='__main__':raise SystemExit(main())
