#!/usr/bin/env python3
"""Exploratory same-byte APK Vulkan tuning, NOT release acceptance or +150% proof.
Rooted disposable emulator injects upstream environment knobs through wrap.*.
Profiler runs are separate: timestamp logging adds waits and is not speed data.
"""
import hashlib,json,re,shlex,traceback
from pathlib import Path
from test_latency_android import LatencyAndroid,wait_ready
from test_reply_notifications_android import init_ime
from test_performance_android import run_reply
from test_generation_stats_android import TEXT
from test_vulkan_speed_android import gpu_chat,PROMPT
from vulkan_strict_checks import strict_audit
from android_checks import PACKAGE

E=Path('evidence')
PROFILES={'default100':{},'submit32':{'GGML_VK_MAX_NODES_PER_SUBMIT':'32'},
          'submit512':{'GGML_VK_MAX_NODES_PER_SUBMIT':'512'},
          'timestamps':{'GGML_VK_PERF_LOGGER':'1','GGML_VK_PERF_LOGGER_CONCURRENT':'1','GGML_VK_PERF_LOGGER_FREQUENCY':'128'}}


def configure(d,settings):
    assert d.shell('getprop ro.kernel.qemu')=='1'
    d.shell('am force-stop '+PACKAGE)
    script='#!/system/bin/sh\n'+'\n'.join('export '+k+'='+shlex.quote(v) for k,v in settings.items())+'\nexec "$@"\n'
    d.write_private('files/vulkan-wrap.sh',script)
    d.shell('setprop wrap.'+PACKAGE+' '+shlex.quote('/system/bin/sh /data/user/0/'+PACKAGE+'/files/vulkan-wrap.sh'))


def environment(d,settings):
    raw=d.adb('exec-out','cat',f'/proc/{d.alive()}/environ',binary=True)
    entries=raw.split(b'\0')
    # Only publish tuning knobs, never the full process environment.
    selected={x.split(b'=',1)[0].decode():x.split(b'=',1)[1].decode() for x in entries if x.startswith(b'GGML_VK_') and b'=' in x}
    for k,v in settings.items():assert selected.get(k)==v,('Wrapper not applied',k,selected)
    for k in ('GGML_VK_PERF_LOGGER','GGML_VK_PERF_LOGGER_CONCURRENT','GGML_VK_MAX_NODES_PER_SUBMIT'):
        if k not in settings:assert k not in selected,('Leaked previous tuning',k)
    return selected


def main():
    E.mkdir(exist_ok=True);d=LatencyAndroid('emulator-5554',E)
    c=json.load(open('ci/vulkan-candidate.json'))
    s=dict(status='FAIL',apk_sha256=hashlib.sha256(Path('.delivery/GGUF-Chat-mobile.apk').read_bytes()).hexdigest(),series={})
    try:
        assert s['apk_sha256']==c['apk_sha256'] and c['strict_tensor_routing']
        assert d.shell('getprop ro.kernel.qemu')=='1'
        d.adb('root',check=False);d.adb('wait-for-device')
        d.shell('wm size 720x1280');d.shell('wm density 240');d.adb('logcat','-G','32M')
        d.shell('pm disable-user --user 0 com.google.android.apps.nexuslauncher',check=False)
        d.shell('setprop debug.gguf.vulkan_device 0');init_ime(d)
        d.adb('install','-g','.delivery/GGUF-Chat-mobile.apk',timeout=180);d.grant_test_notifications()
        model=d.import_model(TEXT)
        assert d.shell('sha256sum '+shlex.quote(model['path'])).split()[0]==hashlib.sha256(TEXT.read_bytes()).hexdigest()
        reference=None
        for label,settings in PROFILES.items():
            configure(d,settings);s['series'][label]={}
            states=('asleep',) if label=='timestamps' else ('awake','asleep')
            for state in states:
                chat=gpu_chat(d,model,'profile-'+label+'-'+state);wait_ready(d)
                env=environment(d,settings)
                r=run_reply(d,chat,PROMPT,'profile-'+label+'-'+state,state=='asleep',True)
                log=d.adb('logcat','-d',f'--pid={d.alive()}')
                r['routing']=strict_audit(log);r['environment']=env
                if reference is None:reference=r['response']
                assert r['response']==reference and r['tokens']==128,'Changed deterministic output'
                if label=='timestamps':
                    assert 'Vulkan Timings:' in log,'No actual GPU timestamp report'
                    lines=[line for line in log.splitlines() if 'Vulkan Timings:' in line or ' us' in line or 'GGUF_' in line]
                    (E/'physical-vulkan-kernel-timings.txt').write_text('\n'.join(lines)[-1000000:])
                    r['not_valid_as_unprofiled_speed']=True
                else:assert 'Vulkan Timings:' not in log,'Profiler must be OFF during speed screening'
                s['series'][label][state]=r
                (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
        s['status']='PASS_EXPLORATORY_ONLY'
    except Exception as ex:
        s['error']=str(ex);(E/'physical-profile-failure.txt').write_text(traceback.format_exc());traceback.print_exc()
    finally:
        s['scope']='Exact signed 323fd5 APK, one observation per policy/screen, no statistical speed acceptance. Same GGUF/128-token output, root wrapper changes only upstream submission policy. GPU timestamp run is separately instrumented and excluded from speed comparisons. Software Vulkan is not phone GPU certification.'
        s['gain_150_percent_certified']=False
        (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
        try:d.shell('setprop wrap.'+PACKAGE+" ''")
        except Exception:pass
    return 0 if s['status']=='PASS_EXPLORATORY_ONLY' else 1

if __name__=='__main__':raise SystemExit(main())
