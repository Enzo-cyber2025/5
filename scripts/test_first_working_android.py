#!/usr/bin/env python3
"""As-shipped first accepted mobile APK vs exact delivered APK; no resign/build.
Common device-clock Send-dispatch -> native completion (not decode-only speed).
"""
import hashlib,json,re,sys,traceback,shlex
from pathlib import Path
from test_latency_android import LatencyAndroid,wait_ready
from test_reply_notifications_android import init_ime,wake
from test_generation_stats_android import TEXT,stamp
from test_perceptible_text_android import PRIME,FOLLOW
from test_vulkan_profile_android import configure
from android_checks import PACKAGE,position,generation_completed,assistant_reply,vulkan_offloaded,completed_after_actual_sleep
from vulkan_strict_checks import strict_audit
sys.path.insert(0,str(Path('ci').resolve()))
from evaluate_first_working import evaluate,HASHES,MODEL
E=Path('evidence')
APKS={'before':Path('.cache/first-working.apk'),'after':Path('entrega/GGUF-Chat-acelerado.apk')}
FIELDS=('nPredict','temperature','topP','topK','minP','repeatPenalty','repeatLastN','contextSize','nThreads','gpuLayers','useMmap','thinking','webSearch','systemPrompt')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def reply(d,chat,prompt,label,asleep,after,backend):
    wake(d);wait_ready(d)
    d.tap(class_name='android.widget.EditText',package={PACKAGE});d.enter_text(prompt)
    point=position(d.ui(),text='Enviar',contains=True,package={PACKAGE},class_name='android.widget.Button');assert point
    d.adb('logcat','-c');pid=d.alive()
    # Both versions get the same external marker and single tap. No UI polling
    # during inference: the reported finish timestamp is native, not poll time.
    d.shell(f'log -t GGUF_COMPARE BEGIN; input tap {point[0]} {point[1]}')
    if asleep:d.shell('input keyevent 223')
    def done():
        assert d.alive()==pid,'App died/restarted; do not retry generation'
        log=d.adb('logcat','-d',f'--pid={pid}')
        assert 'Generation failed:' not in log,log[-4000:]
        if not generation_completed(log):return None
        saved=next(c for c in d.read_json('chats.json') if c['id']==chat['id'])
        try:answer=assistant_reply([saved],chat['id'],prompt)
        except AssertionError:return None
        m=re.findall(r'GGUF_NATIVE_COMPLETE tokens=(\d+) reason=(length|eog) projector=0',log);assert len(m)==1
        system=d.adb('logcat','-d')
        assert len(re.findall(r'GGUF_COMPARE.*BEGIN',system))==1
        elapsed=stamp(system,'GGUF_NATIVE_COMPLETE')-stamp(system,'GGUF_COMPARE.*BEGIN')
        if elapsed<0:elapsed+=86400
        assert 0<elapsed<1200
        r=dict(tokens=int(m[0][0]),reason=m[0][1],send_to_native_complete_s=elapsed,
               total_tokens_s=int(m[0][0])/elapsed,response=answer,
               raw_history=[(x['role'],x['content']) for x in saved['messages'] if x['role'] in ('user','assistant')],
               settings={k:saved.get(k) for k in FIELDS},backend=backend,
               sleep_confirmed=False,metric='device_log_dispatch_to_native_complete_including_prefill')
        if asleep:
            power=d.shell('dumpsys power');assert 'mWakefulness=Asleep' in power
            assert completed_after_actual_sleep(system)
            r['sleep_confirmed']=True
            (E/f'physical-first-{label}-power.txt').write_text(power)
        if after and backend=='vulkan':r['strict']=strict_audit(log)
        (E/f'physical-first-{label}-log.txt').write_text(system[-180000:])
        (E/f'physical-first-{label}.json').write_text(json.dumps(r,indent=2,ensure_ascii=False))
        return r
    r=d.wait(done,'actual native completion and persisted response',timeout=1200)
    wake(d)
    if asleep:
        d.shell('input keyevent 4');d.open_existing_chat(chat['title'])
    return r


def main(backend):
    assert backend in ('cpu','vulkan');E.mkdir(exist_ok=True);d=LatencyAndroid('emulator-5554',E)
    s=dict(status='RUNNING',backend=backend,apk_sha256={p:sha(a) for p,a in APKS.items()},model_sha256=sha(TEXT),pairs=[])
    try:
        assert s['apk_sha256']==HASHES and s['model_sha256']==MODEL
        assert d.shell('getprop ro.kernel.qemu')=='1'
        d.adb('root',check=False);d.adb('wait-for-device');d.shell('wm size 720x1280');d.shell('wm density 240');d.adb('logcat','-G','32M')
        d.shell('pm disable-user --user 0 com.google.android.apps.nexuslauncher',check=False);init_ime(d)
        d.shell('setprop debug.gguf.vulkan_device 0')
        for i in range(3):
            pair={}
            for phase in (('before','after') if i%2==0 else ('after','before')):
                # Exact incompatible certificates: clean DISPOSABLE emulator only.
                assert d.shell('getprop ro.kernel.qemu')=='1'
                d.shell('setprop wrap.'+PACKAGE+" ''")
                d.adb('uninstall',PACKAGE,check=False)
                d.adb('install','-g',APKS[phase],timeout=180);d.grant_test_notifications()
                model=d.import_model(TEXT)
                assert d.shell('sha256sum '+shlex.quote(model['path'])).split()[0]==MODEL
                states={}
                for state in ('awake','asleep'):
                    settings={'GGML_VK_VISIBLE_DEVICES':'0'} if backend=='vulkan' else {}
                    configure(d,settings);d.adb('logcat','-c')
                    chat=d.new_chat(model,99 if backend=='vulkan' else 0,context_size=2048,threads=2);wait_ready(d)
                    pid=d.alive();load=d.adb('logcat','-d',f'--pid={pid}')
                    # Send enabled alone is not proof loading finished.
                    load=d.wait(lambda:(v if 'model loaded: n_ctx=' in (v:=d.adb('logcat','-d',f'--pid={pid}')) else None),'actual model loaded',timeout=240)
                    if backend=='vulkan':assert vulkan_offloaded(load),'Vulkan unavailable or fallback: no GPU speed ratio may be reported'
                    else:assert not vulkan_offloaded(load)
                    env=d.adb('exec-out','cat',f'/proc/{pid}/environ',binary=True).split(b'\0')
                    knobs={x.split(b'=',1)[0].decode():x.split(b'=',1)[1].decode() for x in env if x.startswith((b'GGUF_',b'GGML_VK_',b'LLAMA_GRAPH_')) and b'=' in x}
                    assert knobs==settings,knobs
                    (E/f'physical-first-{backend}-{i}-{phase}-{state}-load.txt').write_text(load[-180000:])
                    states[state]={}
                    for stage,prompt in (('warmup',PRIME),('sample',FOLLOW)):
                        states[state][stage]=reply(d,chat,prompt,f'{backend}-{i}-{phase}-{state}-{stage}',state=='asleep',phase=='after',backend)
                pair[phase]=states
            s['pairs'].append(pair);(E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
        s['result']=evaluate(s);s['status']=s['result']['status']
    except Exception as ex:
        s['status']='FAIL';s['error']=str(ex);(E/'physical-first-failure.txt').write_text(traceback.format_exc());traceback.print_exc()
    finally:
        try:d.shell('setprop wrap.'+PACKAGE+" ''")
        except Exception:pass
        s['scope']='Exact first accepted mobile 409985de vs delivered bd7c45d, not experimental builds. Three AB/BA/AB pairs, same GGUF, prompts, public settings and 128-token budget. Common external device-clock total interval, NOT native decode-only tokens/s or first-visible-text. Shipped llama versions and internal ubatch differ (old 64, current 32); no APK modified to normalize internals. First APK had no image inference. Software Vulkan is not physical GPU certification; old Vulkan does not imply strict all-tensor routing.'
        (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
    return 1 if s['status']=='FAIL' else 0
if __name__=='__main__':raise SystemExit(main(sys.argv[1]))
