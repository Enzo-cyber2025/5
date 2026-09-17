#!/usr/bin/env python3
"""Gate delivery on retained-image speedup, exact outputs and real Android regressions."""
import hashlib,json,re,shlex,subprocess,sys,traceback,os
from pathlib import Path
from test_latency_android import LatencyAndroid,wait_ready,latest_footer
from test_reply_notifications_android import init_ime
from test_performance_android import run_reply
from test_inference_android import fixtures,attach,item_state
from test_physical_android import independent_single,tensor_hashes,C,MODEL,PROJ
from test_projector_cache_android import persisted_image_prompt,exclude_first,PROMPT
from test_vulkan_profile_android import configure
from test_generation_stats_android import TEXT
from android_checks import PACKAGE,vulkan_offloaded,image_prefill_records
from vulkan_strict_checks import strict_audit
sys.path.insert(0,str(Path('ci').resolve()))
from perceptible_image_gate import evaluate
E=Path('evidence')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def observation(d,model,label,after):
    configure(d,{})
    d.adb('logcat','-c');chat=d.new_chat(model,99,context_size=4096,threads=2);wait_ready(d);pid=d.alive()
    entries=d.adb('exec-out','cat',f'/proc/{pid}/environ',binary=True).split(b'\0')
    forbidden=(b'GGUF_VERIFY_',b'GGUF_DISABLE_IMAGE_EMBED_CACHE=',b'GGUF_PROJECTOR_BATCH2=',b'GGUF_VULKAN_QKV=',b'GGUF_VULKAN_IMAGE_PACK=')
    assert not any(x.startswith(forbidden) for x in entries),'Leaked experiment/diagnostic setting'
    log=d.adb('logcat','-d',f'--pid={pid}')
    assert vulkan_offloaded(log) and 'GGUF_PROJECTOR_WEIGHTS backend=Vulkan' in log
    (E/f'physical-gain-{label}-load.txt').write_text(log[-160000:])
    attach(d,chat,['frame-a.jpg','frame-b.jpg'])
    rows={}
    for stage in ('prime','exclude','restore'):
        if stage=='exclude':exclude_first(d,chat,True)
        elif stage=='restore':exclude_first(d,chat,False)
        pending=sum(x.get('message',-1)<0 for x in item_state(d,chat)['items'])
        r=run_reply(d,chat,PROMPT,'gain-'+label+'-'+stage,False,True,
                    persisted_prompt=persisted_image_prompt(PROMPT,pending),timeout=1200)
        assert d.alive()==pid,'Engine process must remain alive through the sequence'
        log=d.adb('logcat','-d',f'--pid={pid}');r['strict']=strict_audit(log)
        records=image_prefill_records(log,1 if stage=='exclude' else 2)
        assert records and all(backend=='Vulkan' for _,backend in records)
        m=re.search(r'GGUF_IMAGE_EMBED_CACHE hits=(\d+) misses=(\d+) bytes=(\d+)',log);assert m
        r['cache']=dict(zip(('hits','misses','bytes'),map(int,m.groups())))
        if after:
            m=re.search(r'GGUF_PROJECTOR_STAGES ([^\r\n]+)',log);assert m
            r['stages']={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',m[1])}
            assert r['stages']['verification']==0 and r['stages']['cache_disabled']==0
        saved=next(c for c in d.read_json('chats.json') if c['id']==chat['id'])
        r['raw_history']=[(m['role'],m['content']) for m in saved['messages'] if m['role'] in ('user','assistant')]
        r['image_records']=records
        r['prepared_dimensions']=re.findall(r'GGUF_IMAGE_PREPARED width=(\d+) height=(\d+) decoder=(\w+)',log)
        assert len(r['prepared_dimensions'])==(1 if stage=='exclude' else 2)
        r['diagnostic']=False;rows[stage]=r
        (E/f'physical-gain-{label}-{stage}.json').write_text(json.dumps(r,indent=2,ensure_ascii=False))
    latest_footer(d,rows['restore'],'gain-'+label)
    return rows

def main():
    E.mkdir(exist_ok=True);C.mkdir(parents=True,exist_ok=True)
    d=LatencyAndroid('emulator-5554',E)
    s=dict(status='RUNNING',build=json.load(open(E/'physical-gain-build.json')),pairs=[],checks={})
    try:
        assert d.shell('getprop ro.kernel.qemu')=='1'
        d.adb('root',check=False);d.adb('wait-for-device');d.shell('wm size 720x1280');d.shell('wm density 240');d.adb('logcat','-G','32M')
        d.shell('pm disable-user --user 0 com.google.android.apps.nexuslauncher',check=False)
        d.shell('setprop debug.gguf.vulkan_device 0');init_ime(d);fixtures()
        model_file=independent_single();expected=tensor_hashes(MODEL);expected.update(tensor_hashes(PROJ));assert tensor_hashes(model_file)==expected
        s['model_sha256']=sha(model_file);model=None
        for block in range(2):
            pair={}
            for phase in (('before','after') if block==0 else ('after','before')):
                apk=Path('.cache/gain-'+phase+'.apk');assert sha(apk)==s['build'][phase+'_sha256']
                old_models=d.read_json('models.json',optional=True) if model else None
                old_chats=d.read_json('chats.json',optional=True) if model else None
                d.adb('install','-r','-g',apk,timeout=180);d.grant_test_notifications()
                if model:
                    assert d.read_json('models.json')==old_models and d.read_json('chats.json')==old_chats
                else:
                    model=d.import_model(model_file)
                    assert d.shell('sha256sum '+shlex.quote(model['path'])).split()[0]==s['model_sha256']
                pair[phase]=observation(d,model,f'{block}-{phase}',phase=='after')
            s['pairs'].append(pair)
            (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
            # Bounded partial evidence is public; it is explicitly RUNNING, not a pass.
            if os.environ.get('GITHUB_ACTIONS')=='true':subprocess.run(['bash','ci/publish_evidence.sh'],check=True)
        d.adb('install','-r','-g','.cache/gain-after.apk',timeout=180)
        from test_code_android import run as code_ui
        from test_image_android import pixels
        code=code_ui(d);assert code['stream']=='PASS' and code['history']=='PASS'
        s['checks']['code_and_copy']='PASS';pixels(d);s['checks']['android_decoder']='PASS'
        normal=d.import_model(TEXT);chat=d.new_chat(normal,99,context_size=2048,threads=0);wait_ready(d)
        off=run_reply(d,chat,'Give three useful study tips.','gain-sleep',True,True)
        off['strict']=strict_audit(d.adb('logcat','-d',f'--pid={d.alive()}'))
        s['sleep_check']=off;s['checks']['screen_off_completion']='PASS'
        s['checks']['same_signer_test_update_preserved_data']='PASS'
        s['gain_result']=evaluate(s);s['status']=s['gain_result']['status']
    except Exception as ex:
        s['status']='FAIL';s['error']=str(ex);(E/'physical-gain-failure.txt').write_text(traceback.format_exc());traceback.print_exc()
    finally:
        try:d.shell('setprop wrap.'+PACKAGE+" ''")
        except Exception:pass
        s['scope']='Two same-run AB/BA pairs; identical compiled candidate payload from functional run 35252559185, compared to delivered 323. Same model/photo bytes and settings. Prime A+B, explicitly exclude A, restore A. Only restore latency gates delivery; no diagnostic readbacks/hashes, no disabled cache, no output injection. Candidate has no batch2/QKV/GPU-packing experiment enabled. Only emulator data were used. New release signature may differ from delivered 7295.'
        (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
    return 0 if s['status']=='PASS_GAIN_GATE_RETAINED_IMAGES_ONLY' else 1
if __name__=='__main__':raise SystemExit(main())
