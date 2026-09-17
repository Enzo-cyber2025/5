#!/usr/bin/env python3
"""Actual APK/SAF/projector comparison. No injected replies or artificial delays.
Baseline is the delivered 323 payload, re-signed ONLY for disposable testing.
Candidate includes latest UI work too: native cache counters isolate avoided
encoder calls; end-to-end timing is not attributed solely to Vulkan kernels.
"""
import hashlib,json,re,shlex,statistics,traceback
from pathlib import Path
from test_latency_android import LatencyAndroid,wait_ready,latest_footer
from test_reply_notifications_android import init_ime
from test_performance_android import run_reply
from test_inference_android import fixtures,attach,item_state
from test_physical_android import independent_single,tensor_hashes,C,MODEL,PROJ
from test_vulkan_profile_android import configure
from vulkan_strict_checks import strict_audit
from android_checks import PACKAGE,vulkan_offloaded,image_prefill_records
E=Path('evidence')
PROMPT='Name the main animal or vehicle in the attached images. Reply in English.'
STAGES=('cold_A','append_B','exclude_A','restore_A')
REPETITIONS=1 # Full-size projector costs minutes per photo under software Vulkan.
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def exclude_first(d,chat,excluded):
    # Explicit replay of a persisted user exclusion, in BOTH versions. Original
    # SAF bytes remain untouched; no assistant message or native metric is edited.
    data=item_state(d,chat);assert len(data['items'])==2
    data['items'][0]['excluded']=excluded
    key=hashlib.sha256(chat['id'].encode()).hexdigest()
    d.write_private('files/attachments/'+key+'/index.json',json.dumps(data))
    assert item_state(d,chat)['items'][0]['excluded']==excluded

def series(d,model,label,asleep,after,verify=False):
    d.adb('logcat','-c');chat=d.new_chat(model,99,context_size=4096,threads=2);wait_ready(d);pid=d.alive()
    env=d.adb('exec-out','cat',f'/proc/{pid}/environ',binary=True).split(b'\0')
    assert (b'GGUF_VERIFY_IMAGE_EMBED_CACHE=1' in env)==verify
    assert not any(x.startswith(b'GGUF_DISABLE_IMAGE_EMBED_CACHE=') for x in env)
    load=d.adb('logcat','-d',f'--pid={pid}')
    assert vulkan_offloaded(load) and 'GGUF_PROJECTOR_WEIGHTS backend=Vulkan' in load
    (E/f'physical-projector-{label}-load.txt').write_text(load[-100000:])
    attach(d,chat,['frame-a.jpg']);rows={}
    stages=STAGES[:3] if verify else STAGES
    for stage in stages:
        if stage=='append_B':attach(d,chat,['frame-b.jpg'])
        elif stage=='exclude_A':exclude_first(d,chat,True)
        elif stage=='restore_A':exclude_first(d,chat,False)
        r=run_reply(d,chat,PROMPT,'projector-'+label+'-'+stage,asleep,True)
        assert d.alive()==pid,'Cache comparison must keep the same Engine process'
        log=d.adb('logcat','-d',f'--pid={pid}')
        r['strict']=strict_audit(log)
        image_count=1 if stage in ('cold_A','exclude_A') else 2
        records=image_prefill_records(log,image_count)
        assert records and all(backend=='Vulkan' for _,backend in records)
        m=re.search(r'GGUF_IMAGE_EMBED_CACHE hits=(\d+) misses=(\d+) bytes=(\d+)',log);assert m
        r['cache']=dict(zip(('hits','misses','bytes'),map(int,m.groups())))
        helper_ms=[int(v) for v in re.findall(r'image decoded \(batch \d+/\d+\) in (\d+) ms',log)]
        assert len(helper_ms)>=len(records),'Missing upstream embedding helper timings'
        r['embedding_helper_wall_ms']=sum(helper_ms) # submission/waits, not isolated GPU time
        r['embedding_helper_batches']=len(helper_ms)
        assert r['cache']['bytes']<=16*1024*1024
        if after:
            m=re.search(r'GGUF_PROJECTOR_STAGES ([^\r\n]+)',log);assert m
            r['stages']={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',m[1])}
            t=r['stages'];assert t['verification']==int(verify) and t['cache_disabled']==0
            assert t['hits']==r['cache']['hits'] and t['encode_calls']==r['cache']['misses']+t['verified_hits']
            assert t['verified_hits']==(t['hits'] if verify else 0)
            if stage=='append_B':assert t['hits']>0 and t['encode_calls']>0
            if stage in ('exclude_A','restore_A'):assert t['hits']>0 and t['encode_calls']==t['verified_hits']
        else:
            assert r['cache']['hits']==0 and r['cache']['misses']>0
        rows[stage]=r
        (E/f'physical-projector-{label}.json').write_text(json.dumps(rows,indent=2,ensure_ascii=False))
    if after:latest_footer(d,rows[stages[-1]],'projector-'+label)
    return rows

def main():
    E.mkdir(exist_ok=True);C.mkdir(parents=True,exist_ok=True)
    d=LatencyAndroid('emulator-5554',E)
    s=dict(status='FAIL',build=json.load(open(E/'physical-projector-build.json')),series={},checks={})
    try:
        assert d.shell('getprop ro.kernel.qemu')=='1'
        d.adb('root',check=False);d.adb('wait-for-device');d.shell('wm size 720x1280');d.shell('wm density 240');d.adb('logcat','-G','32M')
        d.shell('pm disable-user --user 0 com.google.android.apps.nexuslauncher',check=False)
        d.shell('setprop debug.gguf.vulkan_device 0');init_ime(d);fixtures()
        external=independent_single();expected=tensor_hashes(MODEL);expected.update(tensor_hashes(PROJ));assert tensor_hashes(external)==expected
        s['external_gguf_sha256']=sha(external)
        model=None
        # Fresh Engine for every four-stage series; first image starts uncached.
        # One series per state/version: exploratory, not statistical certification.
        for repetition in range(REPETITIONS):
            for phase in (('before','after') if repetition%2==0 else ('after','before')):
                apk=Path('.cache/projector-'+('baseline' if phase=='before' else 'candidate')+'.apk')
                assert sha(apk)==s['build'][phase+'_sha256']
                saved=d.read_json('models.json',optional=True) if model else None
                d.adb('install','-r','-g',apk,timeout=180);d.grant_test_notifications()
                if saved is not None:assert saved==d.read_json('models.json')
                if model is None:
                    model=d.import_model(external)
                    assert d.shell('sha256sum '+shlex.quote(model['path'])).split()[0]==s['external_gguf_sha256']
                configure(d,{})
                for screen in (('awake','asleep') if repetition%2==0 else ('asleep','awake')):
                    label=f'{phase}-{screen}-{repetition}'
                    rows=series(d,model,label,screen=='asleep',phase=='after')
                    s['series'][label]=rows
                    (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
        for rep in range(REPETITIONS):
            for screen in ('awake','asleep'):
                before=s['series'][f'before-{screen}-{rep}'];after=s['series'][f'after-{screen}-{rep}']
                for stage in STAGES:
                    assert before[stage]['response']==after[stage]['response'],('Changed deterministic visual output',screen,rep,stage)
                    assert before[stage]['tokens']==after[stage]['tokens']
        s['checks']['exact_responses_and_tokens']='PASS'
        # Separate, deliberately slower verification: recompute every cached
        # embedding on real Vulkan and memcmp ALL output bytes, not only text.
        d.adb('install','-r','-g','.cache/projector-candidate.apk',timeout=180)
        configure(d,{'GGUF_VERIFY_IMAGE_EMBED_CACHE':'1'})
        s['verification']=series(d,model,'byte-verification',False,True,True)
        assert sum(r['stages']['verified_hits'] for r in s['verification'].values())>0
        s['checks']['cached_embeddings_equal_real_vulkan_byte_for_byte']='PASS'
        s['checks']['awake_asleep_completion_notice_cleanup']='PASS'
        s['observations']={screen:{stage:{phase:{
            'native_first_token_ns':statistics.median(s['series'][f'{phase}-{screen}-{i}'][stage]['metrics']['firstTokenNs'] for i in range(REPETITIONS)),
            'embedding_helper_wall_ms':statistics.median(s['series'][f'{phase}-{screen}-{i}'][stage]['embedding_helper_wall_ms'] for i in range(REPETITIONS)),
            'prefill_ns':statistics.median(s['series'][f'{phase}-{screen}-{i}'][stage]['metrics']['prefillNs'] for i in range(REPETITIONS)),
            'encoder_calls':statistics.median(s['series'][f'{phase}-{screen}-{i}'][stage]['cache']['misses'] for i in range(REPETITIONS))
        } for phase in ('before','after')} for stage in STAGES} for screen in ('awake','asleep')}
        s['status']='PASS_PROJECTOR_CACHE_EXPERIMENT_ONLY'
    except Exception as ex:
        s['error']=str(ex);(E/'physical-projector-failure.txt').write_text(traceback.format_exc());traceback.print_exc()
    finally:
        try:d.shell('setprop wrap.'+PACKAGE+" ''")
        except Exception:pass
        s['scope']='Real APK, actual SAF image bytes, same GGUF/quantization/parameters, software Vulkan. Re-signed baseline retains every non-signature payload entry from delivered 323. Candidate also includes prior UI changes. One fresh-Engine sequence/state/version, fixed before/after and awake/asleep order; no independent warmup, statistical significance or repeatability claim. Long full-resolution software-projector runtime limits this exploratory sample, not image resolution or output budget. encode_call_ns is host wall time including device dependencies, NOT isolated GPU kernel time; verification samples excluded. Native image preparation/tokenization and submission are not full Android Send-to-first-text. No first-image, physical GPU, universal quality, ON/OFF parity or 21x/26x guarantee.'
        (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
    return 0 if s['status']=='PASS_PROJECTOR_CACHE_EXPERIMENT_ONLY' else 1
if __name__=='__main__':raise SystemExit(main())
