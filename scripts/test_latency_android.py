#!/usr/bin/env python3
"""Real APK comparison: cold prompt, follow-up prefix reuse, changed system,
process restart, cancellation recovery and real image generation while asleep.
No injected assistant replies, no manufactured tokens or timing values.
"""
import hashlib,json,re,statistics,traceback,shlex,base64
from pathlib import Path
import xml.etree.ElementTree as ET
from test_mobile import MobileAndroid,APK,MODEL,PROJ,select_pair,bounds
from test_generation_stats_android import measured_reply,TEXT
from test_inference_android import fixtures,attach,reply
from android_checks import PACKAGE,position,active_wake_locks,completed_after_actual_sleep
E=Path('evidence')
BACKGROUND=('A student practices reading and writing every day. The teacher recommends short lessons, regular breaks, careful notes and useful examples. ')*12
FIRST=BACKGROUND+'Explain three useful ways to learn a language. Reply in English.'
FOLLOW='Give one more practical recommendation, with a short explanation in English.'

class LatencyAndroid(MobileAndroid):
    def send(self,prompt,clear_log=True):
        if clear_log:self.adb('logcat','-c')
        self.tap(class_name='android.widget.EditText',package={PACKAGE})
        self.enter_text(prompt)
        self.tap(text='Enviar',package={PACKAGE},contains=True)

    def enter_text(self,prompt):
        # Actual InputConnection, not slow/droppable synthetic key bursts.
        # The entire focused EditText is still independently verified below.
        dready=lambda: 'data="ready"' in self.shell('am broadcast -a com.ggufchat.testinput.READY -p com.ggufchat.testinput')
        self.wait(dready,'test IME bound to real app input',timeout=30)
        encoded=base64.b64encode(prompt.encode('utf-8')).decode('ascii')
        result=self.shell('am broadcast -a com.ggufchat.testinput.TEXT -p com.ggufchat.testinput --es text_b64 '+shlex.quote(encoded))
        assert 'data="committed"' in result,result
        def exact():
            fields=[n.get('text','') for n in ET.fromstring(self.ui()).iter('node') if n.get('class')=='android.widget.EditText' and n.get('package')==PACKAGE]
            return prompt in fields
        self.wait(exact,'entire input reached the EditText before sending',timeout=30)

def edit_system_prompt(d,text):
    # This test IME deliberately has no keyboard panel. Sending Back would
    # dismiss the dialog itself, not a keyboard. Edit the actual dialog field
    # through the same verified InputConnection and explicitly tap Save.
    d.tap(desc='Alternar ferramentas',package={PACKAGE})
    d.tap(desc='Prompt de sistema da conversa',package={PACKAGE})
    d.wait(lambda:position(d.ui(),desc='Texto do prompt de sistema',package={PACKAGE}),'system editor')
    d.tap(desc='Texto do prompt de sistema',package={PACKAGE});d.enter_text(text)
    d.capture('system-chat-editor.png');d.tap(text='Salvar',package={PACKAGE})
    d.wait(lambda:not position(d.ui(),desc='Texto do prompt de sistema',package={PACKAGE}),'saved system editor closed')
    d.tap(desc='Alternar ferramentas',package={PACKAGE})

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def wait_ready(d):
    def ready():
        return any(n.get('class')=='android.widget.Button' and 'Enviar' in n.get('text','') and n.get('enabled')=='true' for n in ET.fromstring(d.ui()).iter('node'))
    d.wait(ready,'send enabled after the actual completion broadcast')

def latest_footer(d,r,name):
    wait_ready(d)
    def find():
        nodes=list(ET.fromstring(d.ui()).iter('node'))
        captions=[n for n in nodes if n.get('content-desc')=='Velocidade da resposta']
        return (nodes,captions[-1]) if captions else None
    nodes,caption=d.wait(find,'latest measured footer')
    rate=float(re.search(r'([\d.,]+) tokens/s',caption.get('text',''))[1].replace(',','.'))
    assert abs(rate-r['native_decode_tokens_s'])<=0.051
    body=next(n for n in reversed(nodes) if n.get('text','').strip()==r['response'].strip())
    assert bounds(caption)[1]>=bounds(body)[3]
    d.capture('physical-latency-'+name+'.png')

def run_reply(d,chat,prompt,phase,new):
    wait_ready(d)
    r=measured_reply(d,chat,prompt,'latency-'+phase,True)
    j=r['metrics'];assert j['tokens']>0 and j['prefillNs']>0
    if new:
        assert j['firstTokenNs']>=j['prefillNs'] and j['promptTokens']>j['reusedPromptTokens']>=0
        log=d.adb('logcat','-d',f'--pid={d.alive()}')
        hit=re.search(r'GGUF_PROMPT_CACHE input_tokens=(\d+) reused_tokens=(\d+) evaluated_tokens=(\d+) media=(\d+)',log);assert hit
        total,reused,evaluated,media=map(int,hit.groups())
        assert total==j['promptTokens'] and reused==j['reusedPromptTokens'] and evaluated==total-reused and media==0
    return r

def main():
    E.mkdir(exist_ok=True);d=LatencyAndroid('emulator-5554',E)
    c=json.load(open('ci/latency-candidate.json'));s=dict(status='FAIL',apk_sha256=sha(APK),checks={},benchmark={});checks=s['checks']
    try:
        assert s['apk_sha256']==c['apk_sha256'] and d.shell('getprop ro.kernel.qemu')=='1'
        d.adb('root',check=False);d.adb('wait-for-device');d.shell('wm size 720x1280');d.shell('wm density 240')
        d.shell('pm disable-user --user 0 com.google.android.apps.nexuslauncher',check=False);d.adb('logcat','-G','16M')
        d.shell('input keyevent 224');d.shell('wm dismiss-keyguard')
        d.adb('install','-r',Path('.cache/test-input/input.apk'))
        # Package install and InputMethodManager's post-user-unlock scan are
        # asynchronous on a cold API-35 emulator. Use its actual published ID.
        def registered_ime():
            listing=d.shell('ime list -a -s')
            (E/'physical-latency-ime-registration.txt').write_text(listing)
            return next((x.strip() for x in listing.splitlines() if x.strip().startswith('com.ggufchat.testinput/')),None)
        ime=d.wait(registered_ime,'test IME registered after real user unlock',timeout=60)
        d.shell('ime enable '+shlex.quote(ime));d.shell('ime set '+shlex.quote(ime))
        baseline=Path('.cache/latency-baseline.apk');assert sha(baseline)==c['baseline_sha256']
        d.adb('install','-r','-g',baseline,timeout=180);assert d.shell('pm clear '+PACKAGE)=='Success'
        d.grant_test_notifications();model=d.import_model(TEXT)
        series={'before':[],'after':[]};changed={}
        for phase in ('before','after'):
            new=phase=='after'
            if new:
                models=d.read_json('models.json');chats=d.read_json('chats.json')
                if c['signer_sha256']=='3dd851d414caaa20d06ea22391e75b752aab0d26c749168b3353dd389b1332da':
                    d.adb('install','-r','-g',APK,timeout=180)
                    assert d.read_json('models.json')==models and d.read_json('chats.json')==chats
                    checks['same_key_update_preserves_data']='PASS'
                    s['installation_scope']='same-certificate in-place update'
                else:
                    # Test the real, unmodified baseline APK. A new certificate
                    # MUST be refused without destroying the installed app data.
                    result=d.adb('install','-r','-g',APK,timeout=180,check=False,with_status=True)
                    error=(result.stdout+result.stderr).decode(errors='replace')
                    assert result.returncode!=0 and 'INSTALL_FAILED_UPDATE_INCOMPATIBLE' in error,error
                    assert d.read_json('models.json')==models and d.read_json('chats.json')==chats
                    (E/'physical-latency-signature-incompatible.txt').write_text(error)
                    checks['signature_change_blocks_update_without_data_loss']='PASS'
                    # Destructive cleanup is ONLY on this disposable emulator,
                    # never a migration instruction for the user's phone.
                    assert d.shell('getprop ro.kernel.qemu')=='1'
                    d.adb('uninstall',PACKAGE)
                    d.adb('install','-g',APK,timeout=180)
                    d.grant_test_notifications();model=d.import_model(TEXT)
                    s['installation_scope']='different certificate: refused update; fresh install on disposable emulator ONLY, no data migration claim'
                checks['installation_policy_verified']='PASS'
            for i in range(4):
                chat=d.new_chat(model,0,context_size=2048);pid=d.alive()
                first=run_reply(d,chat,FIRST,f'{phase}-{i}-cold',new)
                follow=run_reply(d,chat,FOLLOW,f'{phase}-{i}-follow',new)
                assert d.alive()==pid,'The follow-up must reuse the same process/engine'
                if new:
                    assert first['metrics']['reusedPromptTokens']==0
                    assert follow['metrics']['reusedPromptTokens']>=first['metrics']['promptTokens']-8
                pair=dict(cold=first,follow=follow)
                if i:series[phase].append(pair)
            if new:latest_footer(d,follow,'follow-footer')
            wait_ready(d);edit_system_prompt(d,'Respond in English. Use concise sentences. The reference code is CEDAR-8624.')
            changed[phase]=run_reply(d,chat,'What is the reference code?',phase+'-changed-system',new)
            assert d.alive()==pid,'Editing system prompt must not hide cache bugs by restarting'
            if new:
                assert changed[phase]['metrics']['reusedPromptTokens']<32,'Changed system content incorrectly reused'
                latest_footer(d,changed[phase],'changed-system-footer')
                d.launch();d.open_existing_chat(chat['title']);latest_footer(d,changed[phase],'reopened-footer')
                cold=run_reply(d,chat,'Reply in English with a short greeting.','after-restart',True)
                assert cold['metrics']['reusedPromptTokens']==0
                checks['prefix_reuse_system_edit_restart_and_footer']='PASS'
        for i in range(3):
            for kind in ('cold','follow'):
                assert series['before'][i][kind]['response']==series['after'][i][kind]['response'],f'Deterministic output differs: {i}/{kind}'
        assert changed['before']['response']==changed['after']['response'],'System edit changed output'
        checks['identical_outputs_with_real_prefix_reuse']='PASS'
        bench=dict(model=TEXT.name,model_sha256=sha(TEXT),backend='CPU',threads=2,context=2048,warmup_pairs_excluded=1,repetitions=3,series=series,scope='Prefill and engine token generation are measured by native monotonic clock. firstTokenNs is engine-to-first-delivery, NOT tap-to-screen or model-loading time. No physical-phone speed certification.')
        for kind in ('cold','follow'):
            bench[kind]={}
            for phase in ('before','after'):
                runs=[x[kind] for x in series[phase]]
                bench[kind][phase]=dict(prefill_ms=statistics.median(r['metrics']['prefillNs']/1e6 for r in runs),decode_tokens_s=statistics.median(r['native_decode_tokens_s'] for r in runs),native_total_ms=statistics.median((r['metrics']['prefillNs']+r['metrics']['decodeNs'])/1e6 for r in runs))
        s['benchmark']=bench
        # Cancel actual decoding, then verify that no partial KV state is reused.
        wait_ready(d);d.send('Write a very long detailed numbered list of fifty useful study tips. Explain each tip.')
        d.wait(lambda:'GGUF_PROMPT_CACHE' in d.adb('logcat','-d',f'--pid={d.alive()}'),'native prefill before cancellation',timeout=180)
        d.tap(text='Parar',package={PACKAGE})
        d.wait(lambda:'GGUF_GENERATION_STATS' in d.adb('logcat','-d',f'--pid={d.alive()}'),'native cancellation cleanup',timeout=60)
        log=d.adb('logcat','-d',f'--pid={d.alive()}');assert re.search(r'GGUF_GENERATION_STATS .*success=0',log),'Test did not cancel before completion'
        (E/'physical-latency-cancel-log.txt').write_text(log[-150000:])
        recovery=run_reply(d,chat,'Reply in English with hello.','cancel-recovery',True)
        assert recovery['metrics']['reusedPromptTokens']==0
        checks['cancel_invalidates_partial_cache']='PASS'
        # Actual physical visual import and pixel inference. Text-prefix caching
        # must never mistake image embeddings for ordinary token KV.
        d.launch();d.shell('mkdir -p /sdcard/Download')
        for p in (MODEL,PROJ):d.adb('push',p,'/sdcard/Download/'+p.name,timeout=300)
        select_pair(d)
        vision=d.wait(lambda:next((m for m in d.read_json('models.json') if m.get('capability')=='VISION_SINGLE_GGUF'),None),'physical vision GGUF',timeout=600)
        fixtures();chat=d.new_chat(vision,0,context_size=4096);attach(d,chat,['frame-a.jpg'])
        original=d.send
        def asleep_send(prompt,clear_log=True):
            original(prompt,clear_log=clear_log)
            def acquired():
                power=d.shell('dumpsys power')
                return power if 'GGUFChat:LocalCompute' in active_wake_locks(power) else None
            power=d.wait(acquired,'actual generation CPU lease')
            (E/'physical-latency-active-power.txt').write_text(power)
            d.shell('input keyevent 223')
        d.send=asleep_send
        answer=reply(d,chat,'Name the main animal in the image. Reply in English.','latency-vision',images=1)
        d.send=original;assert 'dog' in answer.lower()
        power=d.shell('dumpsys power');log=d.adb('logcat','-d')
        assert 'mWakefulness=Asleep' in power and completed_after_actual_sleep(log)
        d.wait(lambda:'GGUFChat:LocalCompute' not in active_wake_locks(d.shell('dumpsys power')),'lease released before process restart')
        (E/'physical-latency-asleep-power.txt').write_text(d.shell('dumpsys power'))
        (E/'physical-latency-sleep-log.txt').write_text('\n'.join(x for x in log.splitlines() if 'GGUF_' in x or 'PowerManagerService' in x))
        msg=next(x for x in d.read_json('chats.json') if x['id']==chat['id'])['messages'][-1]
        assert msg['generationMetrics']['reusedPromptTokens']==0 and msg['generationMetrics']['tokens']>0
        d.shell('input keyevent 224');d.shell('wm dismiss-keyguard');d.launch();d.open_existing_chat(chat['title'])
        j=msg['generationMetrics'];latest_footer(d,dict(response=answer,native_decode_tokens_s=j['tokens']*1e9/j['decodeNs']),'vision-footer')
        checks['real_image_no_text_cache_screen_off_and_lease_release']='PASS'
        # Re-opening above deliberately discards all native state. Establish an
        # image cache in this process, then ask again without restarting it.
        warmup=reply(d,chat,'What animal is shown? Reply in English.','image-cache-fill',images=1)
        fill_log=d.adb('logcat','-d',f'--pid={d.alive()}')
        hit=re.search(r'GGUF_IMAGE_EMBED_CACHE hits=(\d+) misses=(\d+) bytes=(\d+)',fill_log);assert hit
        assert int(hit[1])==0 and int(hit[2])>0 and 0<int(hit[3])<=16*1024*1024
        fill=next(x for x in d.read_json('chats.json') if x['id']==chat['id'])['messages'][-1]['generationMetrics']
        wait_ready(d);pid=d.alive()
        warm=reply(d,chat,'Name that animal again. Reply in English.','image-cache-hit',images=1)
        assert d.alive()==pid and 'dog' in warmup.lower() and 'dog' in warm.lower()
        hit_log=d.adb('logcat','-d',f'--pid={pid}')
        hit=re.search(r'GGUF_IMAGE_EMBED_CACHE hits=(\d+) misses=(\d+) bytes=(\d+)',hit_log);assert hit
        assert int(hit[1])>0 and int(hit[2])==0 and 0<int(hit[3])<=16*1024*1024
        warm_stats=next(x for x in d.read_json('chats.json') if x['id']==chat['id'])['messages'][-1]['generationMetrics']
        s['image_prefill_ms']=dict(cold=fill['prefillNs']/1e6,warm=warm_stats['prefillNs']/1e6,scope='Same image and native process, different follow-up questions. One observation, not a statistical speed guarantee.')
        (E/'physical-latency-image-cache-fill-log.txt').write_text(fill_log[-150000:])
        (E/'physical-latency-image-cache-hit-log.txt').write_text(hit_log[-150000:])
        latest_footer(d,dict(response=warm,native_decode_tokens_s=warm_stats['tokens']*1e9/warm_stats['decodeNs']),'cached-image-footer')
        # A changed ordered set of real image bytes must not reuse the dog-only
        # cache. All pixels still reach the existing decoder/positioning helper.
        attach(d,chat,['frame-b.jpg']);wait_ready(d)
        changed_image=reply(d,chat,'What vehicle is shown in the second image? Reply in English.','image-cache-changed',images=2)
        assert 'bus' in changed_image.lower(),changed_image
        changed_log=d.adb('logcat','-d',f'--pid={d.alive()}')
        hit=re.search(r'GGUF_IMAGE_EMBED_CACHE hits=(\d+) misses=(\d+) bytes=(\d+)',changed_log);assert hit
        assert int(hit[1])==0 and int(hit[2])>0
        (E/'physical-latency-image-cache-changed-log.txt').write_text(changed_log[-150000:])
        checks['same_image_embeddings_reused_and_changed_images_reencoded']='PASS'
        s['status']='PASS'
    except Exception as ex:
        s['error']=str(ex);(E/'physical-latency-failure.txt').write_text(traceback.format_exc());traceback.print_exc()
    finally:
        (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
        try:d.capture('physical-latency-final.png');(E/'physical-latency-final-log.txt').write_text(d.adb('logcat','-d')[-150000:])
        except Exception:pass
        print(json.dumps(s,indent=2,ensure_ascii=False))
    return 0 if s['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
