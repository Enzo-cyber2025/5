#!/usr/bin/env python3
"""Warmed paired text continuation throughput and first-text latency, ON and OFF."""
import json,traceback,sys,re,hashlib
from pathlib import Path
from test_latency_android import LatencyAndroid,wait_ready,latest_footer
from test_performance_android import run_reply
from test_reply_notifications_android import init_ime
from test_generation_stats_android import TEXT
from test_vulkan_profile_android import configure
from android_checks import PACKAGE,vulkan_offloaded
from vulkan_strict_checks import strict_audit
sys.path.insert(0,str(Path('ci').resolve()))
from perceptible_text_gate import evaluate
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
E=Path('evidence')
PRIME='Explain ten practical ways to learn a language. Give a detailed example for each. Reply in English.'
FOLLOW='Give ten more practical recommendations, with detailed examples. Reply in English.'

def run(d,model,label,state):
    configure(d,{})
    d.adb('logcat','-c');chat=d.new_chat(model,99,context_size=2048,threads=0);wait_ready(d)
    pid=d.alive();env=d.adb('exec-out','cat',f'/proc/{pid}/environ',binary=True).split(b'\0')
    assert not any(x.startswith((b'GGUF_VERIFY_',b'GGUF_VULKAN_QKV=',b'GGUF_PROJECTOR_BATCH2=')) for x in env)
    load=d.adb('logcat','-d',f'--pid={pid}');assert vulkan_offloaded(load)
    (E/f'physical-text-gain-{label}-{state}-load.txt').write_text(load[-100000:])
    rows={}
    for kind,prompt in [('warmup',PRIME),('sample',FOLLOW)]:
        r=run_reply(d,chat,prompt,f'text-gain-{label}-{state}-{kind}',state=='asleep',True)
        assert d.alive()==pid
        log=d.adb('logcat','-d',f'--pid={pid}');r['strict']=strict_audit(log)
        assert 'GGUF_IMAGE_EVALUATED' not in log and r['tokens']==128
        saved=next(c for c in d.read_json('chats.json') if c['id']==chat['id'])
        r['raw_history']=[(m['role'],m['content']) for m in saved['messages'] if m['role'] in ('user','assistant')]
        rows[kind]=r
    latest_footer(d,rows['sample'],f'text-gain-{label}-{state}')
    return rows

def main():
    E.mkdir(exist_ok=True);d=LatencyAndroid('emulator-5554',E)
    s=dict(status='RUNNING',build=json.load(open(E/'physical-gain-build.json')),pairs=[])
    try:
        assert d.shell('getprop ro.kernel.qemu')=='1'
        d.adb('root',check=False);d.adb('wait-for-device');d.shell('wm size 720x1280');d.shell('wm density 240');d.adb('logcat','-G','32M')
        d.shell('pm disable-user --user 0 com.google.android.apps.nexuslauncher',check=False)
        d.shell('setprop debug.gguf.vulkan_device 0');init_ime(d)
        model=None
        for block in range(3):
            pair={}
            for phase in (('before','after') if block%2==0 else ('after','before')):
                apk=Path('.cache/gain-'+phase+'.apk');assert sha(apk)==s['build'][phase+'_sha256']
                d.adb('install','-r','-g',apk,timeout=180);d.grant_test_notifications()
                if model is None:
                    model=d.import_model(TEXT);assert d.shell('sha256sum '+model['path']).split()[0]==sha(TEXT)
                states={}
                for state in (('awake','asleep') if block%2==0 else ('asleep','awake')):
                    states[state]=run(d,model,f'{block}-{phase}',state)
                pair[phase]=states
            s['pairs'].append(pair)
            (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
        s['result']=evaluate(s);s['status']=s['result']['status']
    except Exception as ex:
        s['status']='FAIL';s['error']=str(ex);(E/'physical-text-gain-failure.txt').write_text(traceback.format_exc());traceback.print_exc()
    finally:
        try:d.shell('setprop wrap.'+PACKAGE+" ''")
        except Exception:pass
        s['scope']='Original 323 vs exact image-gain-approved compiled candidate, only disposable signatures changed. Same SmolLM2-135M Q4_K_M, GPU99/all layers, context2048, threadsAuto, 128-token budget, greedy parameters. Three interleaved pairs, warmup and continuation per Engine/state. Warmups excluded. ON/OFF not equalized by slowing OFF. Image gains do not count as text gains.'
        (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
    return 0 if s['status'] in ('PASS_TEXT_GAIN_GATE','TEXT_GAIN_GATE_NOT_MET') else 1
if __name__=='__main__':raise SystemExit(main())
