#!/usr/bin/env python3
"""Same APK, GPU RGB packing in BOTH modes. Warmed, diagnostic-free paired timing.
Full photo/resolution/model/settings retained. Verification is a separate run.
"""
import json,re,traceback,statistics
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

def start(d,model,paired,verify=False):
    settings={'GGUF_VULKAN_IMAGE_PACK':'1','GGUF_DISABLE_IMAGE_EMBED_CACHE':'1'}
    if paired:settings['GGUF_PROJECTOR_BATCH2']='1'
    if verify:settings.update(GGUF_VERIFY_PROJECTOR_BATCH='1',GGUF_VERIFY_IMAGE_PACK='1')
    configure(d,settings);d.adb('logcat','-c')
    chat=d.new_chat(model,99,context_size=4096,threads=2);wait_ready(d)
    env=d.adb('exec-out','cat',f'/proc/{d.alive()}/environ',binary=True).split(b'\0')
    knobs={x.split(b'=',1)[0].decode():x.split(b'=',1)[1].decode() for x in env if x.startswith(b'GGUF_') and b'=' in x}
    for k,v in settings.items():assert knobs.get(k)==v
    for k in ('GGUF_PROJECTOR_BATCH2','GGUF_VERIFY_PROJECTOR_BATCH','GGUF_VERIFY_IMAGE_PACK','GGUF_VERIFY_IMAGE_EMBED_CACHE'):
        if k not in settings:assert k not in knobs
    load=d.adb('logcat','-d',f'--pid={d.alive()}')
    assert vulkan_offloaded(load) and 'GGUF_PROJECTOR_WEIGHTS backend=Vulkan' in load
    assert re.search(r'GGUF_MODEL_ALL_LAYERS loaded=(\d+) total=\1 tensor_cpu_fallback=blocked',load)
    attach(d,chat,['frame-a.jpg'])
    return chat

def observe(d,chat,label,paired,verify=False):
    pending=sum(item.get('message',-1)<0 for item in item_state(d,chat)['items'])
    r=run_reply(d,chat,PROMPT,'projector-speed-'+label,False,True,
                persisted_prompt=persisted_image_prompt(PROMPT,pending),timeout=1200)
    log=d.adb('logcat','-d',f'--pid={d.alive()}');r['strict']=strict_audit(log)
    images=image_prefill_records(log,1);assert images and all(b=='Vulkan' for _,b in images)
    m=re.search(r'GGUF_PROJECTOR_STAGES ([^\r\n]+)',log);assert m
    stages={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',m[1])}
    assert stages['cache_disabled']==1 and stages['hits']==0 and stages['verified_hits']==0
    m=re.search(r'GGUF_PROJECTOR_PAIRS ([^\r\n]+)',log);assert m
    pairs={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',m[1])}
    assert pairs['enabled']==int(paired) and pairs['verification']==int(verify)
    assert stages['encode_calls']==len(images)-pairs['pair_calls']+pairs['verified_images']
    if paired:assert pairs['pair_calls']>0 and pairs['paired_images']==2*pairs['pair_calls']
    else:assert pairs['pair_calls']==0 and pairs['verified_images']==0
    if verify:assert pairs['verified_images']==pairs['paired_images']>0
    else:
        assert pairs['verified_images']==0
        assert 'GGUF_IMAGE_PACK_BYTES_EQUAL' not in log and 'GGUF_IMAGE_PACK_EMBEDDING' not in log
    uploads=re.findall(r'GGUF_IMAGE_UPLOAD packing=(\w+) bytes=(\d+) host_planar_copy=(\d+)',log)
    assert uploads and all(kind=='Vulkan' and copied=='0' for kind,_,copied in uploads)
    saved=next(c for c in d.read_json('chats.json') if c['id']==chat['id'])
    r['raw_history']=[(m['role'],m['content']) for m in saved['messages'] if m['role'] in ('user','assistant')]
    r.update(stages=stages,pairs=pairs,upload_bytes=sum(int(n) for _,n,_ in uploads),diagnostic=verify)
    (E/f'physical-projector-speed-{label}.json').write_text(json.dumps(r,indent=2,ensure_ascii=False))
    return r

def main():
    E.mkdir(exist_ok=True);C.mkdir(parents=True,exist_ok=True)
    d=LatencyAndroid('emulator-5554',E)
    apk=Path('.cache/projector-candidate.apk');build=json.load(open(E/'physical-projector-build.json'))
    result=dict(status='FAIL',apk_sha256=sha(apk),build=build,measurements=[],warmups=[],checks={},release_approved=False,physical_gpu_certified=False)
    try:
        assert result['apk_sha256']==build['after_sha256']
        assert d.shell('getprop ro.kernel.qemu')=='1'
        d.adb('root',check=False);d.adb('wait-for-device');d.shell('wm size 720x1280');d.shell('wm density 240');d.adb('logcat','-G','32M')
        d.shell('pm disable-user --user 0 com.google.android.apps.nexuslauncher',check=False)
        d.shell('setprop debug.gguf.vulkan_device 0');init_ime(d);fixtures()
        external=independent_single();expected=tensor_hashes(MODEL);expected.update(tensor_hashes(PROJ));assert tensor_hashes(external)==expected
        result['gguf_sha256']=sha(external)
        d.adb('install','-g',apk,timeout=180);d.grant_test_notifications();model=d.import_model(external)
        for block in range(2):
            rows={}
            for mode in (('serial','paired') if block==0 else ('paired','serial')):
                chat=start(d,model,mode=='paired')
                warm=observe(d,chat,f'{block}-{mode}-warmup',mode=='paired')
                result['warmups'].append(dict(block=block,mode=mode,record=warm))
                row=observe(d,chat,f'{block}-{mode}',mode=='paired')
                rows[mode]=row
                latest_footer(d,row,f'projector-speed-{block}-{mode}')
            assert rows['serial']['raw_history']==rows['paired']['raw_history'],'Raw saved output/history differs'
            assert rows['serial']['tokens']==rows['paired']['tokens']
            assert rows['serial']['upload_bytes']==rows['paired']['upload_bytes'],'Pixel payload changed'
            result['measurements'].append(rows)
            (E/'summary.json').write_text(json.dumps(result,indent=2,ensure_ascii=False))
        # Separate correctness run: per-chunk batched output compared directly to
        # fresh individual GPU encodes. These slow measurements NEVER enter timing.
        chat=start(d,model,True,True)
        result['verification']=observe(d,chat,'byte-verification',True,True)
        result['checks']['exact_saved_histories_and_full_pixel_payload']='PASS'
        result['checks']['pair_embeddings_equal_individual_bytes']='PASS'
        ratios=[x['serial']['send_to_first_ui_ns']/x['paired']['send_to_first_ui_ns'] for x in result['measurements']]
        result['first_ui_speedup_ratios']=ratios
        result['median_first_ui_speedup']=statistics.median(ratios)
        result['observed_gain_over_5_percent_in_both_pairs']=all(r>1.05 for r in ratios)
        result['status']='PASS_PAIRED_EXPERIMENT_ONLY'
    except Exception as ex:
        result['error']=str(ex);(E/'physical-projector-speed-failure.txt').write_text(traceback.format_exc());traceback.print_exc()
    finally:
        try:d.shell('setprop wrap.'+PACKAGE+" ''")
        except Exception:pass
        result['scope']='One APK/model/photo/resolution/settings; full image inference on software Vulkan. RGB packing on in both modes. Two paired observations in AB/BA order, each preceded by a full warmup in its own Engine; warmups excluded. Image embedding cache disabled so no repeated-image shortcut masks encoder work. Timing observations have verification/readback disabled; per-chunk byte comparison is separate. Short exploratory sample, not statistical, screen-off, physical-device, first-cold-start, all-format or release certification. Decode/resize/crops/normalization still host-side. No 21x/26x promise.'
        (E/'summary.json').write_text(json.dumps(result,indent=2,ensure_ascii=False))
    return 0 if result['status']=='PASS_PAIRED_EXPERIMENT_ONLY' else 1
if __name__=='__main__':raise SystemExit(main())
