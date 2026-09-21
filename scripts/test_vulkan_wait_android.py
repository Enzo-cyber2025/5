#!/usr/bin/env python3
"""One compiled APK: original polling vs default blocking completion, no math changes."""
import hashlib,json,re,sys,traceback
from pathlib import Path
from test_perceptible_text_android import PRIME,FOLLOW,TEXT
from test_latency_android import LatencyAndroid,wait_ready,latest_footer
from test_reply_notifications_android import init_ime
from test_performance_android import run_reply
from test_vulkan_profile_android import configure
from android_checks import PACKAGE,vulkan_offloaded,image_prefill_records
from vulkan_strict_checks import strict_audit
from test_code_android import run as code_ui
sys.path.insert(0,str(Path('ci').resolve()))
from evaluate_vulkan_wait import evaluate
E=Path('evidence');APK=Path('.cache/wait-import/candidate.apk')
IMAGE_PROMPT='Name the main animal in the image. Reply in English.'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def observation(d,model,mode,state,label,kind):
    settings={'GGUF_VULKAN_BLOCKING_WAIT':'0'} if mode=='before' else {}
    if kind=='images':settings['GGUF_DISABLE_IMAGE_EMBED_CACHE']='1'
    configure(d,settings);d.adb('logcat','-c')
    chat=d.new_chat(model,99,context_size=2048 if kind=='text' else 4096,threads=0 if kind=='text' else 2);wait_ready(d);pid=d.alive()
    entries=d.adb('exec-out','cat',f'/proc/{pid}/environ',binary=True).split(b'\0')
    flag=[x for x in entries if x.startswith(b'GGUF_VULKAN_BLOCKING_WAIT=')]
    assert flag==([b'GGUF_VULKAN_BLOCKING_WAIT=0'] if mode=='before' else [])
    forbidden=(b'GGUF_VERIFY_',b'GGML_VK_',b'GGUF_PROJECTOR_BATCH2=',b'GGUF_VULKAN_QKV=',b'GGUF_VULKAN_IMAGE_PACK=',b'GGUF_LOCAL_STREAM=')
    assert not any(x.startswith(forbidden) for x in entries)
    assert (b'GGUF_DISABLE_IMAGE_EMBED_CACHE=1' in entries)==(kind=='images')
    load=d.adb('logcat','-d',f'--pid={pid}');assert vulkan_offloaded(load)
    assert re.search(r'GGUF_MODEL_ALL_LAYERS loaded=(\d+) total=\1 tensor_cpu_fallback=blocked',load)
    (E/f'physical-wait-{label}-{state}-load.txt').write_text(load[-160000:])
    if kind=='images':
        from test_inference_android import attach
        assert 'GGUF_PROJECTOR_WEIGHTS backend=Vulkan' in load
        attach(d,chat,['frame-a.jpg'])
    rows={}
    for stage,prompt in [('warmup',PRIME),('sample',FOLLOW)]:
        if kind=='images':
            from test_inference_android import item_state
            from test_projector_cache_android import persisted_image_prompt
            prompt=IMAGE_PROMPT
            pending=sum(x.get('message',-1)<0 for x in item_state(d,chat)['items'])
            persisted=persisted_image_prompt(prompt,pending)
        else:persisted=None
        r=run_reply(d,chat,prompt,'wait-'+label+'-'+state+'-'+stage,state=='asleep',True,persisted_prompt=persisted,timeout=1200 if kind=='images' else 600)
        assert d.alive()==pid
        log=d.adb('logcat','-d',f'--pid={pid}');r['strict']=strict_audit(log)
        policy=int(mode=='after')
        if stage=='warmup':assert f'GGUF_VULKAN_WAIT_POLICY blocking={policy} same_completion_fence=1' in load+log
        cpu=re.search(r'GGUF_HOST_WORKER_CPU available=1 thread_cpu_ns=(\d+)',log);assert cpu
        r['worker_cpu_ns']=int(cpu[1]);r['blocking_wait']=bool(policy)
        saved=next(c for c in d.read_json('chats.json') if c['id']==chat['id'])
        r['raw_history']=[(m['role'],m['content']) for m in saved['messages'] if m['role'] in ('user','assistant')]
        if kind=='text':assert 'GGUF_IMAGE_EVALUATED' not in log and r['tokens']==128
        else:
            r['image_records']=image_prefill_records(log,1)
            r['prepared_dimensions']=re.findall(r'GGUF_IMAGE_PREPARED width=(\d+) height=(\d+) decoder=(\w+)',log)
            m=re.search(r'GGUF_PROJECTOR_STAGES ([^\r\n]+)',log);assert m
            r['stages']={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',m[1])}
            assert 'GGUF_PROJECTOR_PAIRS enabled=0 pair_calls=0' in log
            assert 'GGUF_QKV_RESULT requested=0 verification=0' in log
        rows[stage]=r
    latest_footer(d,rows['sample'],'wait-'+label+'-'+state)
    return rows

def main(kind):
    assert kind in ('text','images');E.mkdir(exist_ok=True)
    d=LatencyAndroid('emulator-5554',E)
    s=dict(status='RUNNING',kind=kind,build=json.load(open('.cache/wait-import/build.json')),pairs=[],release_approved=False)
    try:
        assert sha(APK)==s['build']['apk_sha256'] and s['build']['experimental_wait_build'] is True
        assert d.shell('getprop ro.kernel.qemu')=='1'
        d.adb('root',check=False);d.adb('wait-for-device');d.shell('wm size 720x1280');d.shell('wm density 240');d.adb('logcat','-G','32M')
        d.shell('pm disable-user --user 0 com.google.android.apps.nexuslauncher',check=False)
        d.shell('setprop debug.gguf.vulkan_device 0');init_ime(d)
        d.adb('install','-g',APK,timeout=180);d.grant_test_notifications()
        if kind=='text':model_file=TEXT
        else:
            from test_inference_android import fixtures
            from test_physical_android import independent_single,tensor_hashes,MODEL,PROJ,C
            C.mkdir(parents=True,exist_ok=True);fixtures();model_file=independent_single()
            expected=tensor_hashes(MODEL);expected.update(tensor_hashes(PROJ));assert tensor_hashes(model_file)==expected
        model=d.import_model(model_file);s['model_sha256']=sha(model_file)
        assert d.shell('sha256sum '+model['path']).split()[0]==s['model_sha256']
        for block in range(3 if kind=='text' else 2):
            rows={}
            for mode in (('before','after') if block%2==0 else ('after','before')):
                states={}
                for state in (('awake','asleep') if kind=='text' else ('awake',)):
                    states[state]=observation(d,model,mode,state,f'{kind}-{block}-{mode}',kind)
                rows[mode]=states
            s['pairs'].append(rows)
            (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
        s['code_and_copy']=code_ui(d)
        s['result']=evaluate(s);s['status']=s['result']['status']
    except Exception as ex:
        s['status']='FAIL';s['error']=str(ex);(E/'physical-wait-failure.txt').write_text(traceback.format_exc());traceback.print_exc()
    finally:
        try:d.shell('setprop wrap.'+PACKAGE+" ''")
        except Exception:pass
        s['scope']='Same APK/GGUF/sampling/context/full input/budget. Polling control env=0; candidate uses its default blocking wait with flag absent. Warmups excluded. Same GPU completion fence, no artificial timing delay or shader/precision changes. Text: three paired ON/OFF runs; images: two paired warmed full encodes with cache disabled in BOTH modes. Software Vulkan only; not physical GPU or general release approval.'
        (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
    return 1 if s['status']=='FAIL' else 0
if __name__=='__main__':raise SystemExit(main(sys.argv[1]))
