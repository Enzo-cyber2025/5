#!/usr/bin/env python3
"""Isolated multimodal KV reuse: unchanged inputs, whole chunks, stock projector."""
import hashlib,json,re,sys,traceback
from pathlib import Path
from test_latency_android import LatencyAndroid,wait_ready,latest_footer,edit_system_prompt
from test_reply_notifications_android import init_ime
from test_vulkan_profile_android import configure
from test_performance_android import run_reply
from test_inference_android import fixtures,attach,item_state
from test_physical_android import independent_single,tensor_hashes,C,MODEL,PROJ
from test_projector_cache_android import PROMPT,persisted_image_prompt,exclude_first
from test_perceptible_text_android import PRIME,FOLLOW
from test_code_android import run as code_ui
from android_checks import PACKAGE,vulkan_offloaded
from vulkan_strict_checks import strict_audit
sys.path.insert(0,str(Path('ci').resolve()))
from evaluate_media_prefix import evaluate,canonical_sha
E=Path('evidence');APK=Path('.cache/media-prefix-import/candidate.apk')
FIELDS=('nPredict','temperature','topP','topK','minP','repeatPenalty','repeatLastN','contextSize','nThreads','gpuLayers','useMmap','thinking','webSearch','systemPrompt')

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def observation(d,model,label,after,kind,asleep=False,verify=False):
    settings={'GGUF_MEDIA_PREFIX':'1'} if after else {}
    if verify and after:settings['GGUF_VERIFY_MEDIA_PREFIX']='1'
    configure(d,settings);d.adb('logcat','-c')
    chat=d.new_chat(model,99,context_size=4096,threads=2);wait_ready(d);pid=d.alive()
    env=d.adb('exec-out','cat',f'/proc/{pid}/environ',binary=True).split(b'\0')
    actual={x.split(b'=',1)[0].decode():x.split(b'=',1)[1].decode() for x in env if x.startswith(b'GGUF_') and b'=' in x}
    assert actual==settings and not any(x.startswith((b'GGML_VK_',b'LLAMA_GRAPH_')) for x in env)
    load=d.adb('logcat','-d',f'--pid={pid}')
    assert vulkan_offloaded(load) and 'GGUF_PROJECTOR_WEIGHTS backend=Vulkan' in load
    assert re.search(r'GGUF_MODEL_ALL_LAYERS loaded=(\d+) total=\1 tensor_cpu_fallback=blocked',load)
    assert 'GGUF_QKV_READY' not in load
    (E/f'physical-media-prefix-{label}-load.txt').write_text(load[-160000:])
    if kind!='text':attach(d,chat,['frame-a.jpg'])
    stages=('warmup','sample','append_B','exclude_A','restore_A','system_edit') if verify else ('warmup','sample')
    rows={}
    for stage in stages:
        if stage=='append_B':attach(d,chat,['frame-b.jpg'])
        elif stage=='exclude_A':exclude_first(d,chat,True)
        elif stage=='restore_A':exclude_first(d,chat,False)
        elif stage=='system_edit':edit_system_prompt(d,'You are a careful visual assistant. Answer in English.')
        pending=sum(x.get('message',-1)<0 and not x.get('excluded',False) for x in item_state(d,chat)['items']) if kind!='text' else 0
        prompt=(PRIME if stage=='warmup' else FOLLOW) if kind=='text' else PROMPT
        r=run_reply(d,chat,prompt,f'media-prefix-{label}-{stage}',asleep,True,
                    persisted_prompt=persisted_image_prompt(prompt,pending) if kind!='text' else None,timeout=1200)
        assert d.alive()==pid,'No process restart may stand in for invalidation/reuse'
        log=d.adb('logcat','-d',f'--pid={pid}');r['strict']=strict_audit(log)
        saved=next(c for c in d.read_json('chats.json') if c['id']==chat['id'])
        r['raw_history']=[(m['role'],m['content']) for m in saved['messages'] if m['role'] in ('user','assistant')]
        r['settings']={k:saved[k] for k in FIELDS}
        r.update(enabled=after,diagnostic=verify and after)
        complete=re.findall(r'GGUF_NATIVE_COMPLETE tokens=(\d+) reason=(length|eog) projector=1',log)
        assert len(complete)==1 and int(complete[0][0])==r['tokens']
        r['completion_reason']=complete[0][1]
        if kind=='text':
            assert 64<=r['tokens']<=128 and 'GGUF_MEDIA_PREFIX ' not in log and 'GGUF_IMAGE_' not in log
        else:
            m=re.search(r'GGUF_MEDIA_PREFIX ([^\r\n]+)',log);assert m
            r['prefix']={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',m[1])}
            m=re.search(r'GGUF_PROJECTOR_STAGES ([^\r\n]+)',log);assert m
            r['encoder']={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',m[1])}
            r['image_records']=re.findall(r'GGUF_IMAGE_(?:KV_REUSED|EVALUATED) tokens=(\d+) backend=(\w+)',log)
            r['reused_image_chunks']=len(re.findall(r'GGUF_IMAGE_KV_REUSED tokens=',log))
            r['evaluated_image_chunks']=len(re.findall(r'GGUF_IMAGE_EVALUATED tokens=',log))
            r['prepared_dimensions']=re.findall(r'GGUF_IMAGE_PREPARED width=(\d+) height=(\d+) decoder=(\w+)',log)
            assert 'GGUF_PROJECTOR_PAIRS enabled=0' in log and 'GGUF_QKV_RESULT requested=0' in log
            uploads=re.findall(r'GGUF_IMAGE_UPLOAD packing=(\w+) bytes=(\d+) host_planar_copy=(\d+)',log)
            assert all(k=='CPU' and h=='1' for k,_,h in uploads)
        rows[stage]=r
        (E/f'physical-media-prefix-{label}.json').write_text(json.dumps(rows,indent=2,ensure_ascii=False))
    latest_footer(d,rows[stages[-1]],'media-prefix-'+label)
    return rows


def main(kind):
    assert kind in ('verify','awake','asleep','text');E.mkdir(exist_ok=True);C.mkdir(parents=True,exist_ok=True)
    d=LatencyAndroid('emulator-5554',E)
    s=dict(status='RUNNING',kind=kind,build=json.load(open('.cache/media-prefix-import/build.json')),pairs=[],release_approved=False)
    try:
        assert sha(APK)==s['build']['apk_sha256'] and d.shell('getprop ro.kernel.qemu')=='1'
        d.adb('root',check=False);d.adb('wait-for-device');d.shell('wm size 720x1280');d.shell('wm density 240');d.adb('logcat','-G','32M')
        d.shell('pm disable-user --user 0 com.google.android.apps.nexuslauncher',check=False)
        d.shell('setprop debug.gguf.vulkan_device 0');init_ime(d);fixtures()
        model_file=independent_single();expected=tensor_hashes(MODEL);expected.update(tensor_hashes(PROJ));assert tensor_hashes(model_file)==expected
        s['model_sha256']=sha(model_file)
        d.adb('install','-g',APK,timeout=180);d.grant_test_notifications();model=d.import_model(model_file)
        assert d.shell('sha256sum '+model['path']).split()[0]==s['model_sha256']
        proof=None
        if kind=='verify':
            s['verification']={}
            for phase in ('before','after'):
                s['verification'][phase]=observation(d,model,phase+'-verify',phase=='after',kind,verify=True)
                (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
        else:
            proof=json.load(open('.cache/media-prefix-proof/summary.json'))
            assert proof['result']==evaluate(proof) and proof['build']==s['build']
            s['byte_reference_sha256']=canonical_sha(proof)
            for i in range(3):
                pair={}
                for phase in (('before','after') if i%2==0 else ('after','before')):
                    states={}
                    for state in (('awake','asleep') if kind=='text' else (kind,)):
                        states[state]=observation(d,model,f'{kind}-{i}-{phase}-{state}',phase=='after',kind,state=='asleep')
                    pair[phase]=states
                s['pairs'].append(pair)
                (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
        s['code_and_copy']=code_ui(d);s['result']=evaluate(s,proof);s['status']=s['result']['status']
    except Exception as ex:
        s['status']='FAIL';s['error']=str(ex);(E/'physical-media-prefix-failure.txt').write_text(traceback.format_exc());traceback.print_exc()
    finally:
        try:d.shell('setprop wrap.'+PACKAGE+" ''")
        except Exception:pass
        s['scope']='Experimental same-APK runtime comparison. Stock RGB, no batch2/QKV, existing image-embedding cache in both modes. Exact whole-chunk causal KV reuse only. Full KV byte-reference readbacks confined to verification. Software Vulkan, not physical-device/all-model or release approval.'
        (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
    return 1 if s['status']=='FAIL' else 0
if __name__=='__main__':raise SystemExit(main(sys.argv[1]))
