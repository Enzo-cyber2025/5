#!/usr/bin/env python3
"""QKV: same APK, full photo, warm AB/BA timing. Exact GPU reference check first."""
import json,re,statistics,traceback
from pathlib import Path
from test_image_upload_android import sha,PROMPT
from test_latency_android import LatencyAndroid,wait_ready,latest_footer
from test_reply_notifications_android import init_ime
from test_performance_android import run_reply
from test_inference_android import fixtures,attach,item_state
from test_physical_android import independent_single,tensor_hashes,C,MODEL,PROJ
from test_projector_cache_android import persisted_image_prompt
from test_vulkan_profile_android import configure
from android_checks import PACKAGE,image_prefill_records,vulkan_offloaded
from vulkan_strict_checks import strict_audit
E=Path('evidence')

def start(d,model,fused,verify=False):
    settings={'GGUF_VULKAN_IMAGE_PACK':'1','GGUF_DISABLE_IMAGE_EMBED_CACHE':'1'}
    if fused:settings['GGUF_VULKAN_QKV']='1'
    if verify:settings['GGUF_VERIFY_QKV']='1'
    configure(d,settings);d.adb('logcat','-c')
    chat=d.new_chat(model,99,context_size=4096,threads=2);wait_ready(d)
    env=d.adb('exec-out','cat',f'/proc/{d.alive()}/environ',binary=True).split(b'\0')
    knobs={x.split(b'=',1)[0].decode():x.split(b'=',1)[1].decode() for x in env if x.startswith(b'GGUF_') and b'=' in x}
    for k,v in settings.items():assert knobs.get(k)==v
    for k in ('GGUF_VULKAN_QKV','GGUF_VERIFY_QKV','GGUF_PROJECTOR_BATCH2','GGUF_VERIFY_PROJECTOR_BATCH','GGUF_VERIFY_IMAGE_PACK','GGUF_VERIFY_IMAGE_EMBED_CACHE'):
        if k not in settings:assert k not in knobs
    log=d.adb('logcat','-d',f'--pid={d.alive()}')
    assert vulkan_offloaded(log) and 'GGUF_PROJECTOR_WEIGHTS backend=Vulkan' in log
    assert re.search(r'GGUF_MODEL_ALL_LAYERS loaded=(\d+) total=\1 tensor_cpu_fallback=blocked',log)
    ready=re.findall(r'GGUF_QKV_READY layers=(\d+) copied_bytes=(\d+) extra_device_bytes=(\d+) weight_verification=(\d+) backend=Vulkan\w*',log)
    if fused:
        assert len(ready)==1 and int(ready[0][0])>0 and int(ready[0][1])>0 and int(ready[0][3])==int(verify)
    else:assert not ready
    label='fused' if fused else 'separate'
    (E/f'physical-qkv-{label}-verify{int(verify)}-load.txt').write_text(log[-160000:])
    attach(d,chat,['frame-a.jpg'])
    return chat,ready

def observe(d,chat,label,fused,verify=False):
    pending=sum(item.get('message',-1)<0 for item in item_state(d,chat)['items'])
    r=run_reply(d,chat,PROMPT,'qkv-'+label,False,True,persisted_prompt=persisted_image_prompt(PROMPT,pending),timeout=1200)
    log=d.adb('logcat','-d',f'--pid={d.alive()}');r['strict']=strict_audit(log)
    images=image_prefill_records(log,1);assert images and all(b=='Vulkan' for _,b in images)
    m=re.search(r'GGUF_PROJECTOR_STAGES ([^\r\n]+)',log);assert m
    stages={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',m[1])}
    assert stages['cache_disabled']==1 and stages['hits']==0 and stages['verified_hits']==0
    m=re.search(r'GGUF_QKV_RESULT requested=(\d+) verification=(\d+) verified_images=(\d+)',log);assert m
    requested,diagnostic,verified=map(int,m.groups())
    assert requested==int(fused) and diagnostic==int(verify) and verified==(len(images) if verify else 0)
    assert stages['encode_calls']==len(images)+verified
    assert 'GGUF_PROJECTOR_PAIRS enabled=0 pair_calls=0' in log and 'GGUF_QKV_DIFF' not in log
    if not verify:
        assert 'GGUF_IMAGE_PACK_BYTES_EQUAL' not in log and 'GGUF_IMAGE_PACK_EMBEDDING' not in log
    uploads=re.findall(r'GGUF_IMAGE_UPLOAD packing=(\w+) bytes=(\d+) host_planar_copy=(\d+)',log)
    assert len(uploads)==len(images)+verified and all(kind=='Vulkan' and copied=='0' for kind,_,copied in uploads)
    saved=next(c for c in d.read_json('chats.json') if c['id']==chat['id'])
    r['raw_history']=[(m['role'],m['content']) for m in saved['messages'] if m['role'] in ('user','assistant')]
    r.update(stages=stages,verified_images=verified,image_chunks=len(images),upload_bytes=sum(int(n) for _,n,_ in uploads),diagnostic=verify)
    (E/f'physical-qkv-{label}.json').write_text(json.dumps(r,indent=2,ensure_ascii=False))
    return r

def main():
    E.mkdir(exist_ok=True);C.mkdir(parents=True,exist_ok=True)
    d=LatencyAndroid('emulator-5554',E)
    apk=Path('.cache/projector-candidate.apk');build=json.load(open(E/'physical-projector-build.json'))
    s=dict(status='FAIL',apk_sha256=sha(apk),build=build,measurements=[],warmups=[],loads=[],checks={},default_enabled=False,release_approved=False,physical_gpu_certified=False)
    try:
        assert s['apk_sha256']==build['after_sha256'] and d.shell('getprop ro.kernel.qemu')=='1'
        d.adb('root',check=False);d.adb('wait-for-device');d.shell('wm size 720x1280');d.shell('wm density 240');d.adb('logcat','-G','32M')
        d.shell('pm disable-user --user 0 com.google.android.apps.nexuslauncher',check=False)
        d.shell('setprop debug.gguf.vulkan_device 0');init_ime(d);fixtures()
        external=independent_single();expected=tensor_hashes(MODEL);expected.update(tensor_hashes(PROJ));assert tensor_hashes(external)==expected
        s['gguf_sha256']=sha(external)
        d.adb('install','-g',apk,timeout=180);d.grant_test_notifications();model=d.import_model(external)
        # Fail fast on wrong weights/outputs before spending time on benchmarks.
        chat,load=start(d,model,True,True);s['loads'].append(dict(mode='verification',report=load))
        s['verification']=observe(d,chat,'byte-verification',True,True)
        s['checks']['weights_and_embeddings_exact']='PASS'
        (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
        for block in range(2):
            rows={}
            for mode in (('separate','fused') if block==0 else ('fused','separate')):
                chat,load=start(d,model,mode=='fused');s['loads'].append(dict(block=block,mode=mode,report=load))
                warm=observe(d,chat,f'{block}-{mode}-warmup',mode=='fused')
                s['warmups'].append(dict(block=block,mode=mode,record=warm))
                row=observe(d,chat,f'{block}-{mode}',mode=='fused');rows[mode]=row
                latest_footer(d,row,f'qkv-{block}-{mode}')
            assert rows['separate']['raw_history']==rows['fused']['raw_history'],'Raw saved output/history changed'
            assert rows['separate']['tokens']==rows['fused']['tokens']
            assert rows['separate']['upload_bytes']==rows['fused']['upload_bytes']
            s['measurements'].append(rows)
            (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
        s['checks']['raw_histories_pixels_parameters_and_strict_route']='PASS'
        ratios=[x['separate']['send_to_first_ui_ns']/x['fused']['send_to_first_ui_ns'] for x in s['measurements']]
        s['ratios']=ratios;s['median_ratio']=statistics.median(ratios)
        s['gain_over_5_percent_both_pairs']=all(r>1.05 for r in ratios)
        s['status']='PASS_QKV_EXPERIMENT_ONLY'
    except Exception as ex:
        s['error']=str(ex);(E/'physical-qkv-failure.txt').write_text(traceback.format_exc());traceback.print_exc()
    finally:
        try:d.shell('setprop wrap.'+PACKAGE+" ''")
        except Exception:pass
        s['scope']='Same APK, full photo, GGUF and quantization; no batch2; RGB packing GPU in both modes; embedding cache disabled. One separate diagnostic verifies copied weights and full projector embeddings against original separate projections on the same Vulkan device. Timing: two AB/BA pairs, full excluded warmup per Engine, no verification readbacks/hashes in timed runs. QKV duplicates weights on device in this prototype; extra memory reported. Not physical GPU, statistics, screen-off, cold-start, all-model, speed or release certification.'
        (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
    return 0 if s['status']=='PASS_QKV_EXPERIMENT_ONLY' else 1
if __name__=='__main__':raise SystemExit(main())
