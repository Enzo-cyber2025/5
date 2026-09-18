#!/usr/bin/env python3
"""Explicit opt-in only: batch2+QKV vs stock serial/separate with stock RGB packing."""
import json,re,sys,time,traceback,hashlib
from pathlib import Path
from test_latency_android import LatencyAndroid,wait_ready,latest_footer
from test_reply_notifications_android import init_ime
from test_vulkan_profile_android import configure
from test_performance_android import run_reply
from test_perceptible_text_android import PRIME,FOLLOW
from test_inference_android import fixtures,attach,item_state
from test_physical_android import independent_single,tensor_hashes,C,MODEL,PROJ
from test_projector_cache_android import persisted_image_prompt
from test_image_upload_android import PROMPT
from test_code_android import run as code_ui
from android_checks import PACKAGE,vulkan_offloaded,image_prefill_records
from vulkan_strict_checks import strict_audit
sys.path.insert(0,str(Path('ci').resolve()))
from evaluate_projector_combined import evaluate,canonical_sha
E=Path('evidence');APK=Path('.cache/combined-import/candidate.apk')
COMBINED={'GGUF_PROJECTOR_BATCH2':'1','GGUF_VULKAN_QKV':'1','GGUF_PROJECTOR_COMBINATION':'1'}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def memory(d,label):
    log=d.shell('dumpsys meminfo '+PACKAGE)
    (E/f'physical-combined-{label}-memory.txt').write_text(log)
    m=re.search(r'TOTAL PSS:\s*(\d+)',log)
    if not m:m=re.search(r'^\s*TOTAL\s+(\d+)\s',log,re.M)
    assert m,'Missing real process PSS'
    return int(m[1])

def observation(d,model,label,after,kind,verify=False):
    settings=dict(COMBINED) if after else {}
    if kind in ('awake','asleep','verify'):settings['GGUF_DISABLE_IMAGE_EMBED_CACHE']='1'
    if verify:settings.update(GGUF_VERIFY_QKV='1',GGUF_VERIFY_PROJECTOR_BATCH='1')
    configure(d,settings);d.adb('logcat','-c')
    started=time.monotonic_ns();chat=d.new_chat(model,99,context_size=4096,threads=2);wait_ready(d)
    startup_ns=time.monotonic_ns()-started;pid=d.alive()
    entries=d.adb('exec-out','cat',f'/proc/{pid}/environ',binary=True).split(b'\0')
    actual={x.split(b'=',1)[0].decode():x.split(b'=',1)[1].decode() for x in entries if x.startswith(b'GGUF_') and b'=' in x}
    assert actual==settings,(actual,settings)
    assert not any(x.startswith((b'GGML_VK_',b'LLAMA_GRAPH_')) for x in entries)
    load=d.adb('logcat','-d',f'--pid={pid}')
    assert vulkan_offloaded(load) and 'GGUF_PROJECTOR_WEIGHTS backend=Vulkan' in load
    assert re.search(r'GGUF_MODEL_ALL_LAYERS loaded=(\d+) total=\1 tensor_cpu_fallback=blocked',load)
    ready=re.findall(r'GGUF_QKV_READY layers=(\d+) copied_bytes=(\d+) extra_device_bytes=(\d+) weight_verification=(\d+) backend=Vulkan\w*',load)
    if after:assert len(ready)==1 and all(int(x)>0 for x in ready[0][:3]) and int(ready[0][3])==int(verify)
    else:assert not ready
    (E/f'physical-combined-{label}-load.txt').write_text(load[-160000:])
    rows={'load':dict(startup_ns=startup_ns,qkv=ready,pss_kib=memory(d,label+'-load')), 'states':{}}
    if kind!='text':attach(d,chat,['frame-a.jpg'])
    # A single Engine is retained for warmup + continuation/cache hit.
    for state in (('awake','asleep') if kind=='text' else (('asleep',) if kind=='asleep' else ('awake',))):
        if kind=='text' and state=='asleep':
            # Separate process/Engine and identical two-message history per state.
            return_with_sleep=observation_text_sleep(d,model,label,after)
            rows['states'][state]=return_with_sleep
            break
        stages={};attention=[]
        for stage,prompt in [('warmup',PRIME),('sample',FOLLOW)]:
            if verify and stage=='sample':break
            pending=sum(x.get('message',-1)<0 for x in item_state(d,chat)['items']) if kind!='text' else 0
            if kind!='text':prompt=PROMPT
            r=run_reply(d,chat,prompt,f'combined-{label}-{state}-{stage}',state=='asleep',True,
                        persisted_prompt=persisted_image_prompt(prompt,pending) if kind!='text' else None,timeout=1200)
            assert d.alive()==pid
            log=d.adb('logcat','-d',f'--pid={pid}');r['strict']=strict_audit(log)
            r.update(combined=after,diagnostic=verify)
            saved=next(c for c in d.read_json('chats.json') if c['id']==chat['id'])
            r['raw_history']=[(m['role'],m['content']) for m in saved['messages'] if m['role'] in ('user','assistant')]
            r['settings']={k:saved[k] for k in ('nPredict','temperature','topP','topK','minP','repeatPenalty','repeatLastN','contextSize','nThreads','gpuLayers','useMmap','thinking','webSearch','systemPrompt')}
            if kind=='text':assert r['tokens']==128 and 'GGUF_IMAGE_EVALUATED' not in log
            else:
                assert f'GGUF_PROJECTOR_COMBINATION enabled={int(after)} verification={int(verify)}' in log
                r['image_records']=image_prefill_records(log,1)
                r['prepared_dimensions']=re.findall(r'GGUF_IMAGE_PREPARED width=(\d+) height=(\d+) decoder=(\w+)',log)
                for field,tag in [('stages','GGUF_PROJECTOR_STAGES'),('pairing','GGUF_PROJECTOR_PAIRS'),('qkv','GGUF_QKV_RESULT')]:
                    m=re.search(tag+r' ([^\r\n]+)',log);assert m
                    r[field]={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',m[1])}
                uploads=re.findall(r'GGUF_IMAGE_UPLOAD packing=(\w+) bytes=(\d+) host_planar_copy=(\d+)',log)
                assert all(p=='CPU' and h=='1' for p,_,h in uploads),'RGB packing must stay stock in BOTH modes'
                r['upload_bytes']=sum(int(n) for _,n,_ in uploads)
                modes=re.findall(r'warmup: flash attention is (enabled|disabled)',log)
                if modes:attention.extend(modes)
                if stage=='warmup':assert len(modes)==1,'Missing/ambiguous realized attention policy'
                assert len(set(attention))==1
                r['realized_attention']=attention[0]
                assert 'GGUF_QKV_DIFF' not in log and 'GGUF_PROJECTOR_PAIR_DIFF' not in log
            stages[stage]=r
        rows['states'][state]=stages
        latest_footer(d,stages['warmup' if verify else 'sample'],f'combined-{label}-{state}')
    rows['pss_kib_after']=memory(d,label+'-after')
    return rows

def observation_text_sleep(d,model,label,after):
    settings=dict(COMBINED) if after else {};configure(d,settings);d.adb('logcat','-c')
    chat=d.new_chat(model,99,context_size=4096,threads=2);wait_ready(d);pid=d.alive()
    entries=d.adb('exec-out','cat',f'/proc/{pid}/environ',binary=True).split(b'\0')
    actual={x.split(b'=',1)[0].decode():x.split(b'=',1)[1].decode() for x in entries if x.startswith(b'GGUF_') and b'=' in x}
    assert actual==settings
    load=d.adb('logcat','-d',f'--pid={pid}');assert vulkan_offloaded(load)
    (E/f'physical-combined-{label}-asleep-load.txt').write_text(load[-160000:])
    rows={}
    for stage,prompt in [('warmup',PRIME),('sample',FOLLOW)]:
        r=run_reply(d,chat,prompt,f'combined-{label}-asleep-{stage}',True,True,timeout=1200)
        assert d.alive()==pid
        log=d.adb('logcat','-d',f'--pid={pid}');r['strict']=strict_audit(log)
        assert r['tokens']==128 and 'GGUF_IMAGE_EVALUATED' not in log
        r.update(combined=after,diagnostic=False)
        saved=next(c for c in d.read_json('chats.json') if c['id']==chat['id'])
        r['raw_history']=[(m['role'],m['content']) for m in saved['messages'] if m['role'] in ('user','assistant')]
        r['settings']={k:saved[k] for k in ('nPredict','temperature','topP','topK','minP','repeatPenalty','repeatLastN','contextSize','nThreads','gpuLayers','useMmap','thinking','webSearch','systemPrompt')}
        rows[stage]=r
    latest_footer(d,rows['sample'],f'combined-{label}-asleep')
    return rows

def main(kind):
    assert kind in ('verify','awake','asleep','text','cache');E.mkdir(exist_ok=True);C.mkdir(parents=True,exist_ok=True)
    d=LatencyAndroid('emulator-5554',E)
    s=dict(status='RUNNING',kind=kind,build=json.load(open('.cache/combined-import/build.json')),pairs=[],release_approved=False)
    try:
        assert sha(APK)==s['build']['apk_sha256'] and d.shell('getprop ro.kernel.qemu')=='1'
        d.adb('root',check=False);d.adb('wait-for-device');d.shell('wm size 720x1280');d.shell('wm density 240');d.adb('logcat','-G','32M')
        d.shell('pm disable-user --user 0 com.google.android.apps.nexuslauncher',check=False)
        d.shell('setprop debug.gguf.vulkan_device 0');init_ime(d);fixtures()
        model_file=independent_single();expected=tensor_hashes(MODEL);expected.update(tensor_hashes(PROJ));assert tensor_hashes(model_file)==expected
        s['model_sha256']=sha(model_file)
        d.adb('install','-g',APK,timeout=180);d.grant_test_notifications();model=d.import_model(model_file)
        assert d.shell('sha256sum '+model['path']).split()[0]==s['model_sha256']
        if kind=='verify':
            s['verification']=observation(d,model,'byte-reference',True,kind,True)
        else:
            proof=json.load(open('.cache/combined-proof/summary.json'))
            assert proof['status']=='PASS_COMBINED_BYTE_REFERENCE' and proof['build']==s['build'] and proof['model_sha256']==s['model_sha256']
            s['byte_reference_sha256']=canonical_sha(proof)
            s['reference_attention']=proof['verification']['states']['awake']['warmup']['realized_attention']
            for block in range(3):
                row={}
                for mode in (('before','after') if block%2==0 else ('after','before')):
                    row[mode]=observation(d,model,f'{kind}-{block}-{mode}',mode=='after',kind)
                s['pairs'].append(row)
                (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
        s['code_and_copy']=code_ui(d)
        s['result']=evaluate(s,None if kind=='verify' else proof);s['status']=s['result']['status']
    except Exception as ex:
        s['status']='FAIL';s['error']=str(ex);(E/'physical-combined-failure.txt').write_text(traceback.format_exc());traceback.print_exc()
    finally:
        try:d.shell('setprop wrap.'+PACKAGE+" ''")
        except Exception:pass
        s['scope']='Opt-in batch2+QKV, stock RGB packing, same APK/GGUF/settings. Dedicated full byte reference before any benchmarks. Three AB/BA/AB warmed pairs per workload. Cache disabled for encoder timing, enabled for cache regressions. Observed app PSS is not total device/peak GPU memory. Software Vulkan only; not general release approval.'
        (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
    return 1 if s['status']=='FAIL' else 0
if __name__=='__main__':raise SystemExit(main(sys.argv[1]))
