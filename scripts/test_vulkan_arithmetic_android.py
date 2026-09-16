#!/usr/bin/env python3
"""Diagnostic ONLY: does emulated FP16 arithmetic cost more than FP32?
No lower precision, altered GGUF, alternate APK, batch, context or token budget.
Require identical deterministic outputs; never adopt a policy on this screen alone.
"""
import hashlib,json,re,statistics,traceback
from pathlib import Path
from test_latency_android import LatencyAndroid,wait_ready
from test_reply_notifications_android import init_ime
from test_performance_android import run_reply
from test_generation_stats_android import TEXT
from test_vulkan_speed_android import gpu_chat,PROMPT
from test_vulkan_profile_android import configure,environment
from vulkan_strict_checks import strict_audit
from android_checks import PACKAGE
E=Path('evidence')

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    E.mkdir(exist_ok=True);d=LatencyAndroid('emulator-5554',E)
    s=dict(status='FAIL',apk_sha256=sha('.delivery/GGUF-Chat-mobile.apk'),series={},medians={})
    try:
        assert s['apk_sha256']=='323fd5a33667c6cab278699e97c89fe253e1bb7acead45b869729bf022eb9f5c'
        assert d.shell('getprop ro.kernel.qemu')=='1'
        d.adb('root',check=False);d.adb('wait-for-device')
        d.shell('wm size 720x1280');d.shell('wm density 240');d.adb('logcat','-G','32M')
        d.shell('pm disable-user --user 0 com.google.android.apps.nexuslauncher',check=False)
        d.shell('setprop debug.gguf.vulkan_device 0');init_ime(d)
        d.adb('install','-g','.delivery/GGUF-Chat-mobile.apk',timeout=180);d.grant_test_notifications()
        model=d.import_model(TEXT)
        assert d.shell('sha256sum '+model['path']).split()[0]==sha(TEXT)
        reference=None
        for policy,settings in [('default',{}),('disable_f16',{'GGML_VK_DISABLE_F16':'1'})]:
            configure(d,settings);s['series'][policy]={'awake':[],'asleep':[]}
            for i in range(4):
                for screen in (('awake','asleep') if i%2==0 else ('asleep','awake')):
                    label=f'arithmetic-{policy}-{screen}-{i}'
                    chat=gpu_chat(d,model,label);wait_ready(d);env=environment(d,settings)
                    if policy=='default':assert 'GGML_VK_DISABLE_F16' not in env
                    full=d.adb('logcat','-d',f'--pid={d.alive()}')
                    caps=[line for line in full.splitlines() if re.search(r'ggml_vulkan:|fp16:|warp size:|VULKAN_SELECTED',line,re.I)]
                    (E/f'physical-{label}-caps.txt').write_text('\n'.join(caps))
                    # Device log confirms actual capability selection, not just setprop success.
                    if policy=='default' and any(re.search(r'fp16:\s*0\b',line) for line in caps):
                        s['status']='NOT_APPLICABLE_ALREADY_FP32';return 0
                    expected='0' if policy=='disable_f16' else '1'
                    assert any(re.search(r'fp16:\s*'+expected+r'\b',line) for line in caps),'No actual expected FP16 capability line'
                    r=run_reply(d,chat,PROMPT,label,screen=='asleep',True)
                    log=d.adb('logcat','-d',f'--pid={d.alive()}')
                    r['routing']=strict_audit(log);r['environment']=env
                    assert 'Vulkan Timings:' not in log,'No instrumented profiling in speed comparisons'
                    assert r['tokens']==128
                    if reference is None:reference=r['response']
                    r['equals_reference']=r['response']==reference
                    if i:s['series'][policy][screen].append(r)
                    (E/f'physical-{label}.json').write_text(json.dumps(r,indent=2,ensure_ascii=False))
                    (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
                    assert r['equals_reference'],'Different deterministic output: DO NOT ADOPT this policy'
        for screen in ('awake','asleep'):
            s['medians'][screen]={}
            for policy in ('default','disable_f16'):
                rows=s['series'][policy][screen]
                s['medians'][screen][policy]=dict(decode_tokens_s=statistics.median(r['native_decode_tokens_s'] for r in rows),native_first_token_ns=statistics.median(r['metrics']['firstTokenNs'] for r in rows))
        s['status']='PASS_EXPLORATORY_ONLY'
    except Exception as ex:
        s['error']=str(ex);(E/'physical-arithmetic-failure.txt').write_text(traceback.format_exc());traceback.print_exc()
    finally:
        s['scope']='Software Vulkan only; FP32 instead of optional FP16 arithmetic, unchanged weights/KV format/parameters. One excluded warmup +3 per state/policy. Fixed policy order remains a source of bias. No production default changed; not phone speed certification or a 21x/26x claim.'
        (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
        try:
            log=d.adb('logcat','-d')
            (E/'physical-arithmetic-final-log.txt').write_text('\n'.join(x for x in log.splitlines() if any(t in x for t in ('GGUF','AndroidRuntime','FATAL','ANR in')))[-150000:])
            d.shell('setprop wrap.'+PACKAGE+" ''")
        except Exception:pass
    return 0 if s['status']=='PASS_EXPLORATORY_ONLY' else 1

if __name__=='__main__':raise SystemExit(main())
