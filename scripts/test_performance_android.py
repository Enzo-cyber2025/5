#!/usr/bin/env python3
"""Actual signed before/after CPU-auto and Vulkan inference; no phone-speed promise."""
import json,hashlib,re,statistics,traceback
from pathlib import Path
from test_latency_android import LatencyAndroid,wait_ready,latest_footer,FIRST,FOLLOW
from test_generation_stats_android import measured_reply,TEXT
from test_reply_notifications_android import init_ime,wake,sleep_after_start,stopped,check_notice
from android_checks import PACKAGE,completed_after_actual_sleep,vulkan_offloaded
from test_code_android import run as code_ui
E=Path('evidence')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def run_reply(d,chat,prompt,label,asleep,new):
    wait_ready(d)
    original=d.send
    if asleep:d.send=lambda text,clear_log=True:sleep_after_start(d,original,text,clear_log)
    try:r=measured_reply(d,chat,prompt,'perf-'+label,True)
    finally:d.send=original
    log=d.adb('logcat','-d',f'--pid={d.alive()}')
    if asleep:
        power=d.shell('dumpsys power')
        # PowerManagerService belongs to system_server, not the app PID.
        # Keep its real sleep event in the chronology used by this assertion.
        system_log=d.adb('logcat','-d')
        (E/f'physical-performance-{label}-power.txt').write_text(power)
        (E/f'physical-performance-{label}-sleep-log.txt').write_text('\n'.join(x for x in system_log.splitlines() if 'GGUF_' in x or 'PowerManagerService' in x))
        assert 'mWakefulness=Asleep' in power and completed_after_actual_sleep(system_log)
        if new:check_notice(d,chat,'perf-'+label)
    elif new:
        m=re.search(r'GGUF_UI_FIRST_TEXT send_to_first_ui_ns=(\d+)',log);assert m,'No actual Send->UI timing'
        r['send_to_first_ui_ns']=int(m[1]);assert r['send_to_first_ui_ns']>0
    if new:stopped(d)
    wake(d)
    # On a sleeping completion the old Activity missed DONE. Reopen normally,
    # without killing the process or discarding the native prefix cache.
    if asleep:
        d.shell('input keyevent 4');d.open_existing_chat(chat['title'])
    return r

def main():
    E.mkdir(exist_ok=True);d=LatencyAndroid('emulator-5554',E)
    c=json.load(open('ci/performance-candidate.json'));apk=Path('.delivery/GGUF-Chat-mobile.apk')
    result=dict(status='FAIL',apk_sha256=sha(apk),checks={},series={});checks=result['checks']
    try:
        assert result['apk_sha256']==c['apk_sha256'];assert d.shell('getprop ro.kernel.qemu')=='1'
        d.adb('root',check=False);d.adb('wait-for-device');d.shell('wm size 720x1280');d.shell('wm density 240');d.adb('logcat','-G','16M')
        d.shell('pm disable-user --user 0 com.google.android.apps.nexuslauncher',check=False)
        init_ime(d)
        # Test the installed candidate's actual code renderer/clipboard first,
        # so UI defects are not hidden behind a long inference benchmark.
        d.adb('install','-g',apk,timeout=180)
        checks['code_boxes_exact_android_clipboard']=code_ui(d)
        assert d.shell('getprop ro.kernel.qemu')=='1'
        d.adb('uninstall',PACKAGE) # fresh disposable emulator, no user data
        base=Path('.cache/performance-base.apk');assert sha(base)==c['baseline_sha256']
        d.adb('install','-r','-g',base,timeout=180);d.shell('pm clear '+PACKAGE);d.grant_test_notifications()
        for phase in ('before','after'):
            new=phase=='after'
            if new:
                old_models=d.read_json('models.json');old_chats=d.read_json('chats.json')
                install=d.adb('install','-r','-g',apk,timeout=180,check=False,with_status=True)
                if c['signer_sha256']==c['baseline_signer_sha256']:
                    assert install.returncode==0
                    assert d.read_json('models.json')==old_models and d.read_json('chats.json')==old_chats
                    checks['same_key_update']='PASS'
                else:
                    error=(install.stdout+install.stderr).decode(errors='replace')
                    assert install.returncode!=0 and 'INSTALL_FAILED_UPDATE_INCOMPATIBLE' in error
                    assert d.read_json('models.json')==old_models and d.read_json('chats.json')==old_chats
                    (E/'physical-performance-signature-refusal.txt').write_text(error)
                    assert d.shell('getprop ro.kernel.qemu')=='1' # disposable emulator only
                    d.adb('uninstall',PACKAGE);d.adb('install','-g',apk,timeout=180)
                    checks['different_key_refused_without_deleting_data']='PASS'
                d.grant_test_notifications()
            model=d.import_model(TEXT);series={};result['series'][phase]=series
            for screen in ('awake','asleep'):
                runs=[];series[screen]=runs
                for i in range(4): # 1 warmup, 3 measured repetitions
                    chat=d.new_chat(model,0,context_size=2048,threads=0);pid=d.alive();wait_ready(d)
                    load=d.adb('logcat','-d',f'--pid={pid}')
                    assert chat['nThreads']==0
                    if new:
                        t=re.search(r'GGUF_CPU_THREADS requested=0 available=(\d+) capacities=\d+ resolved=(\d+)',load);assert t
                        assert int(t[2])>1 if int(t[1])>1 else int(t[2])==1
                        assert 'GGUF_CPU_DISPATCH library=aijni' in load
                        (E/f'physical-performance-load-{screen}-{i}.txt').write_text(load[-100000:])
                    else:assert 'threads=1 ' in load,'Baseline auto must really resolve to one thread'
                    first=run_reply(d,chat,FIRST,f'{phase}-{screen}-{i}-cold',screen=='asleep',new)
                    follow=run_reply(d,chat,FOLLOW,f'{phase}-{screen}-{i}-follow',screen=='asleep',new)
                    assert d.alive()==pid and follow['metrics']['reusedPromptTokens']>0
                    if i:runs.append(dict(cold=first,follow=follow))
                if new and screen=='awake':latest_footer(d,follow,'performance-follow')
            # A manual CPU choice must remain unchanged.
            chat=d.new_chat(model,0,context_size=2048,threads=2);wait_ready(d)
            if new:
                assert re.search(r'GGUF_CPU_THREADS requested=2 .*resolved=2',d.adb('logcat','-d',f'--pid={d.alive()}'))
            series['manual']=run_reply(d,chat,FIRST,phase+'-manual',False,new)
            # Actual Vulkan backend under software emulation. Functional proof only,
            # never use these timings to claim physical GPU speed.
            chat=d.new_chat(model,99,context_size=2048,threads=0);wait_ready(d)
            load=d.adb('logcat','-d',f'--pid={d.alive()}');assert vulkan_offloaded(load)
            (E/f'physical-performance-{phase}-vulkan-load.txt').write_text(load[-100000:])
            series['gpu']=run_reply(d,chat,'Give three useful study tips.',phase+'-vulkan',True,new)
            if new:
                log=d.adb('logcat','-d',f'--pid={d.alive()}')
                assert 'GGUF_GPU_SAMPLING requested=1 attached=1' in log
                m=re.search(r'GGUF_GPU_SAMPLING_RESULT backend_selected=(\d+) emitted=(\d+)',log);assert m and int(m[1])>0
                # Preserve all stages/parameters for inspection, even if equality fails.
                (E/'physical-performance-gpu-sampling.txt').write_text(log[-150000:])
        before=result['series']['before'];after=result['series']['after']
        for screen in ('awake','asleep'):
            for i in range(3):
                for kind in ('cold','follow'):
                    assert before[screen][i][kind]['response']==after[screen][i][kind]['response'],f'Output changed: {screen}/{i}/{kind}'
        assert before['manual']['response']==after['manual']['response'],'Manual CPU output changed'
        assert before['gpu']['response']==after['gpu']['response'],'Vulkan sampling changed deterministic response'
        checks['identical_model_outputs_auto_manual_cpu_and_vulkan']='PASS'
        checks['actual_sleep_saved_notifications_and_service_cleanup']='PASS'
        checks['automatic_threads_and_manual_override']='PASS'
        checks['real_send_to_first_ui_timing']='PASS'
        result['medians']={screen:{phase:{kind:{'decode_tokens_s':statistics.median(x[kind]['native_decode_tokens_s'] for x in result['series'][phase][screen]),'prefill_ms':statistics.median(x[kind]['metrics']['prefillNs']/1e6 for x in result['series'][phase][screen]),'first_native_text_ms':statistics.median(x[kind]['metrics']['firstTokenNs']/1e6 for x in result['series'][phase][screen])} for kind in ('cold','follow')} for phase in ('before','after')} for screen in ('awake','asleep')}
        result['status']='PASS'
    except Exception as ex:
        result['error']=str(ex);(E/'physical-performance-failure.txt').write_text(traceback.format_exc());traceback.print_exc()
    finally:
        result['scope']='SmolLM2-135M Q4_K_M, same Android 35 x86_64 emulator, CPU auto, 1 warmup and 3 measured pairs per screen state; Vulkan is software, not a physical GPU. No 15/20 tokens/s phone certification.'
        result['model_sha256']=sha(TEXT)
        (E/'summary.json').write_text(json.dumps(result,indent=2,ensure_ascii=False))
        try:
            log=d.adb('logcat','-d')
            (E/'physical-performance-final-log.txt').write_text('\n'.join(x for x in log.splitlines() if any(t in x for t in ('GGUF','ggufchat','AndroidRuntime','FATAL','ANR in')))[-150000:])
            d.capture('physical-performance-final.png')
        except Exception:pass
    return 0 if result['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
