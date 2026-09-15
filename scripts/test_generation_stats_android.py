#!/usr/bin/env python3
"""Before/after benchmark on the same emulator, weights, context and prompts.
No estimated tokens. Check native metrics, message JSON, footer geometry and restart.
"""
import hashlib,json,re,statistics,traceback,os,time
from pathlib import Path
import xml.etree.ElementTree as ET
from test_mobile import MobileAndroid,APK,MODEL,PROJ,select_pair,bounds
from android_checks import PACKAGE,position,assistant_reply,generation_completed,active_wake_locks,completed_after_actual_sleep
from test_inference_android import fixtures,attach,reply
E=Path('evidence');TEXT=Path('.cache/mobile-models/SmolLM2-135M-Instruct-Q4_K_M.gguf')
PROMPT='List ten useful tips for learning a new language. Explain each tip in two sentences.'

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def stamp(log,marker):
    m=re.search(r'(?m)^\d\d-\d\d (\d\d):(\d\d):(\d\d)\.(\d+) .*'+marker,log)
    assert m,'No timestamp: '+marker
    h,mi,s,ms=map(int,m.groups());return h*3600+mi*60+s+ms/1000

def measured_reply(d,chat,prompt,phase,stats):
    d.send(prompt);pid=d.alive()
    def done():
        assert d.alive()==pid,'App process changed'
        log=d.adb('logcat','-d',f'--pid={pid}')
        if 'Generation failed:' in log:raise AssertionError(log[-4000:])
        if not generation_completed(log):return None
        chats=d.read_json('chats.json')
        try:answer=assistant_reply(chats,chat['id'],prompt)
        except AssertionError:return None
        hit=re.search(r'GGUF_NATIVE_COMPLETE tokens=(\d+)',log);assert hit
        elapsed=stamp(log,'GGUF_NATIVE_COMPLETE')-stamp(log,'GGUF_CONTENT_PREPARED')
        if elapsed<0:elapsed+=86400
        assert 0<elapsed<600, 'Invalid benchmark clock interval'
        record=dict(tokens=int(hit[1]),prefill_and_generation_seconds=elapsed,prefill_and_generation_tokens_s=int(hit[1])/elapsed,response=answer)
        saved=next(c for c in chats if c['id']==chat['id'])
        message=next(m for m in reversed(saved['messages']) if m['role']=='assistant')
        if stats:
            m=re.search(r'GGUF_GENERATION_STATS tokens=(\d+) decode_ns=(\d+) prefill_ns=(\d+) callbacks=(\d+) success=1',log)
            if not m:return None
            n,ns,prefill,callbacks=map(int,m.groups());j=message['generationMetrics']
            assert j['tokens']==n==record['tokens'] and j['decodeNs']==ns>0 and j['prefillNs']==prefill and j['completed'] is True
            assert 0<callbacks<=n
            record.update(metrics=j,callbacks=callbacks,native_decode_tokens_s=n*1e9/ns)
        (E/f'physical-speed-{phase}.json').write_text(json.dumps(dict(record,chat=saved),indent=2,ensure_ascii=False))
        # Keep complete source logs in artifacts; bounded extracts in git.
        (E/f'physical-speed-{phase}-log.txt').write_text(log[-150000:])
        return record
    return d.wait(done,'native completion and per-message counters: '+phase,timeout=600)

def footer(d,record,stage):
    def ready():
        root=ET.fromstring(d.ui());nodes=list(root.iter('node'))
        captions=[n for n in nodes if n.get('content-desc')=='Velocidade da resposta']
        return (nodes,captions) if captions else None
    nodes,captions=d.wait(ready,'footer below the response')
    assert len(captions)==1
    label=captions[0].get('text','');rate=float(re.search(r'([\d.,]+) tokens/s',label)[1].replace(',','.'))
    expected=record['native_decode_tokens_s'];assert abs(rate-expected)<=0.051,(rate,expected)
    body=next(n for n in nodes if n.get('text')==record['response'])
    assert bounds(captions[0])[1]>=bounds(body)[3],(body.attrib,captions[0].attrib)
    d.capture('physical-speed-'+stage+'.png')

def main():
    E.mkdir(exist_ok=True);d=MobileAndroid('emulator-5554',E)
    c=json.load(open('ci/speed-candidate.json'));s=dict(status='FAIL',apk_sha256=digest(APK),checks={},benchmark={})
    checks=s['checks']
    try:
        assert s['apk_sha256']==c['apk_sha256'];assert d.shell('getprop ro.kernel.qemu')=='1'
        d.adb('root',check=False);d.adb('wait-for-device');d.shell('wm size 720x1280');d.shell('wm density 240')
        d.shell('pm disable-user --user 0 com.google.android.apps.nexuslauncher',check=False)
        d.adb('logcat','-G','16M')
        baseline=Path('.cache/speed-baseline.apk');assert digest(baseline)==c['baseline_sha256']
        d.adb('install','-r','-g',baseline,timeout=180);assert d.shell('pm clear '+PACKAGE)=='Success';d.grant_test_notifications();d.launch()
        model=d.import_model(TEXT);d.write_private('files/speed-update-probe','preserve')
        baseline_runs=[];new_runs=[]
        for phase,runs in [('before',baseline_runs),('after',new_runs)]:
            if phase=='after':
                old_models=d.read_json('models.json');old_chats=d.read_json('chats.json')
                d.adb('install','-r','-g',APK,timeout=180)
                assert d.read_json('models.json')==old_models and d.read_json('chats.json')==old_chats
                assert d.shell('cat /data/user/0/'+PACKAGE+'/files/speed-update-probe')=='preserve'
                checks['same_certificate_update_preserves_models_chats']='PASS'
            # One excluded warm-up, three timed repetitions. New chat = no history difference.
            for i in range(4):
                chat=d.new_chat(model,0,context_size=1024)
                r=measured_reply(d,chat,PROMPT,phase+'-'+str(i),phase=='after')
                assert r['tokens']>=8,'Too few actual tokens to benchmark'
                if i:runs.append(r)
                if phase=='after' and i==3:
                    footer(d,r,'footer');d.launch();d.open_existing_chat(chat['title']);footer(d,r,'reopened-footer')
                    saved=d.read_json('chats.json');m=next(x for x in saved if x['id']==chat['id'])['messages'][-1]
                    assert m['generationMetrics']==r['metrics']
        assert len({r['response'] for r in baseline_runs+new_runs})==1,'Optimization changed deterministic output'
        before=statistics.median(r['prefill_and_generation_tokens_s'] for r in baseline_runs)
        after=statistics.median(r['prefill_and_generation_tokens_s'] for r in new_runs)
        s['benchmark']=dict(model=TEXT.name,backend='CPU',threads=2,context=1024,warmup_excluded=1,repetitions=3,before=baseline_runs,after=new_runs,median_before=before,median_after=after,relative_change_percent=(after/before-1)*100,scope='Native interval from content-ready to native completion, includes prefill; not the decode-only footer. Same disposable x86_64 emulator, not physical phone performance.')
        assert sum(r['callbacks'] for r in new_runs)<sum(r['tokens'] for r in new_runs),'No reduction in token delivery callbacks'
        checks['real_before_after_benchmark_identical_outputs']='PASS'
        checks['native_counters_persistence_footer_geometry']='PASS'
        # Old responses get no invented metric.
        old=next(x for x in reversed(d.read_json('chats.json')) if x['messages'] and any(m['role']=='assistant' and 'generationMetrics' not in m for m in x['messages']))
        d.launch();d.open_existing_chat(old['title']);d.wait(lambda:position(d.ui(),text='sem medição',contains=True,package={PACKAGE}),'old answer explicitly unmeasured')
        d.capture('physical-speed-old-response.png');checks['old_messages_not_fabricated']='PASS'
        # Real vision path uses the same counter and optimized stream.
        d.launch();d.shell('mkdir -p /sdcard/Download')
        for p in (MODEL,PROJ):d.adb('push',p,'/sdcard/Download/'+p.name,timeout=300)
        select_pair(d)
        vision=d.wait(lambda:next((m for m in d.read_json('models.json') if m.get('capability')=='VISION_SINGLE_GGUF'),None),'valid physical vision GGUF',timeout=600)
        fixtures();chat=d.new_chat(vision,0,context_size=4096);attach(d,chat,['frame-a.jpg'])
        original_send=d.send
        def screen_off_send(prompt,clear_log=True):
            original_send(prompt,clear_log=clear_log)
            # input tap returns before Android dispatches startForegroundService.
            # Wait for the CURRENT lease, never historical Wake Lock Log entries.
            def acquired():
                power=d.shell('dumpsys power')
                log=d.adb('logcat','-d',f'--pid={d.alive()}')
                assert not generation_completed(log), 'Generation ended before screen-off test could start'
                return power if 'GGUFChat:LocalCompute' in active_wake_locks(power) else None
            power=d.wait(acquired,'generation service acquired CPU lease',timeout=30)
            (E/'physical-speed-vision-active-power.txt').write_text(power)
            (E/'physical-speed-vision-active-services.txt').write_text(d.shell('dumpsys activity services '+PACKAGE))
            assert 'GGUFChat:LocalCompute' in active_wake_locks(power)
            d.shell('input keyevent 223')
        d.send=screen_off_send
        answer=reply(d,chat,'Name the main animal in the image. Reply in English.','speed-vision',images=1)
        d.send=original_send
        power=d.shell('dumpsys power');log=d.adb('logcat','-d')
        (E/'physical-speed-vision-asleep-power.txt').write_text(power)
        (E/'physical-speed-vision-sleep-log.txt').write_text('\n'.join(line for line in log.splitlines() if any(x in line for x in ('GGUF_', 'PowerManagerService'))))
        assert 'mWakefulness=Asleep' in power
        assert completed_after_actual_sleep(log)
        checks['metrics_and_real_vision_generation_screen_off']='PASS'
        d.shell('input keyevent 224');d.shell('wm dismiss-keyguard');d.launch();d.open_existing_chat(chat['title'])
        assert 'dog' in answer.lower(),answer
        msg=next(x for x in d.read_json('chats.json') if x['id']==chat['id'])['messages'][-1]
        assert msg['generationMetrics']['tokens']>0 and msg['generationMetrics']['decodeNs']>0
        d.capture('physical-speed-vision-footer.png');checks['real_image_inference_metrics']='PASS'
        d.wait(lambda:'GGUFChat:LocalCompute' not in active_wake_locks(d.shell('dumpsys power')),'CPU lease released')
        s['status']='PASS'
    except Exception as ex:
        s['error']=str(ex);(E/'physical-speed-failure.txt').write_text(traceback.format_exc());traceback.print_exc()
    finally:
        (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
        try:d.capture('physical-speed-final.png');(E/'physical-speed-final-log.txt').write_text(d.adb('logcat','-d')[-150000:])
        except Exception:pass
        print(json.dumps(s,indent=2,ensure_ascii=False))
    return 0 if s['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
