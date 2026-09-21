#!/usr/bin/env python3
"""Real screen-OFF imports and native inference. No fake counter/sleep worker.
Emulator only. Records power, foreground service, locks, persisted output and UI.
"""
import hashlib,json,os,re,shlex,time,traceback
from pathlib import Path
import xml.etree.ElementTree as ET
import test_mobile as mobile
from test_mobile import MobileAndroid,APK
from android_checks import PACKAGE,position,generation_completed,assistant_reply,active_wake_locks,completed_after_actual_sleep
from test_single_import_ui_android import select,push
from test_physical_android import tensor_hashes
E=Path('evidence');GEMMA=os.environ.get('GGUF_COMPUTE_GEMMA')=='1'
if GEMMA:
    mobile.MODEL=Path('.cache/gemma4-models/gemma-4-E2B-it-Q3_K_S.gguf')
    mobile.PROJ=Path('.cache/gemma4-models/mmproj-F16.gguf')

def off(d):
    d.shell('input keyevent 223')
    d.wait(lambda:'mWakefulness=Asleep' in d.shell('dumpsys power'),'tela realmente apagada',timeout=20)

def on(d):
    d.shell('input keyevent 224');d.shell('wm dismiss-keyguard')

def no_emoji(d):
    xml=d.ui()
    for n in ET.fromstring(xml).iter('node'):
        if n.get('package')==PACKAGE:
            assert not re.search('[\U0001f000-\U0001faff]',n.get('text','')),n.attrib

def main():
    E.mkdir(exist_ok=True);d=MobileAndroid('emulator-5554',E)
    s=dict(status='FAIL',apk_sha256=hashlib.sha256(APK.read_bytes()).hexdigest(),checks={},scope='screen-off real import, native load and persisted text response; emulator, not physical device or forced-stop immunity')
    c=s['checks']
    try:
        candidate=json.load(open('ci/compute-candidate.json'));assert s['apk_sha256']==candidate['apk_sha256']
        assert d.shell('getprop ro.kernel.qemu')=='1';d.adb('root',check=False);d.adb('wait-for-device')
        # Disposable emulator fixture: Pixel Launcher can ANR over another app.
        d.shell('pm disable-user --user 0 com.google.android.apps.nexuslauncher',check=False)
        d.shell('am force-stop com.google.android.apps.nexuslauncher',check=False)
        d.shell('wm size 720x1280');d.shell('wm density 240');d.adb('logcat','-G','16M')
        d.adb('install','-r','-g',APK,timeout=180);assert d.shell('pm clear '+PACKAGE)=='Success'
        d.grant_test_notifications();d.launch();d.shell('mkdir -p /sdcard/Download');no_emoji(d)
        d.tap(text='Nova conversa',contains=True,package={PACKAGE});d.tap(text='Importar',package={PACKAGE})
        no_emoji(d);d.capture('physical-compute-empty-library.png')
        for p in (mobile.MODEL,mobile.PROJ):push(d,p)
        d.adb('logcat','-c');select(d,[mobile.MODEL.name,mobile.PROJ.name],'screen-off-pair')
        d.wait(lambda:'GGUF_COMPUTE_STARTED foreground=1' in d.adb('logcat','-d'),'foreground antes de bloquear')
        pid=d.alive();off(d)
        before=d.adb('logcat','-d');assert 'GGUF_ATOMIC_IMPORT_COMMITTED' not in before,'Import finished before screen-off: not screen-off evidence'
        services=d.shell('dumpsys activity services '+PACKAGE)
        power=d.shell('dumpsys power')
        assert 'ComputeService' in services and 'isForeground=true' in services
        assert 'GGUFChat:LocalCompute' in active_wake_locks(power)
        (E/'physical-compute-screen-off-start.txt').write_text(services+'\n'+power)
        def done():
            assert d.alive()==pid
            rows=d.read_json('models.json',optional=True)
            return rows[0] if len(rows)==1 and rows[0].get('capability')=='VISION_SINGLE_GGUF' else None
        time.sleep(12) # No ADB polling: real work proceeds with the display off.
        model=d.wait(done,'unificação persistida enquanto tela permanece apagada',timeout=1800)
        power=d.shell('dumpsys power');assert 'mWakefulness=Asleep' in power
        log=d.adb('logcat','-d');assert 'GGUF_ATOMIC_NATIVE_VALIDATED same_path=1' in log
        assert 'GGUF_MEMORY_TELEMETRY' in log and 'policy=actual_allocator' in log
        events=re.findall(r'GGUF_IMPORT_PROGRESS stage=(\w+) percent=(-?\d+)',log[len(before):])
        assert events,'Nenhum progresso novo durante bloqueio'
        (E/'physical-compute-screen-off-complete.txt').write_text(power+'\n'+log[-150000:])
        c['real_pair_import_and_native_validation_screen_off']='PASS'
        d.wait(lambda:'GGUFChat:LocalCompute' not in active_wake_locks(d.shell('dumpsys power')),'wakelock liberado após importar')
        (E/'physical-compute-import-released.txt').write_text(d.shell('dumpsys power')+'\n'+d.shell('dumpsys activity services '+PACKAGE))
        d.wait(lambda:'isForeground=true' not in d.shell('dumpsys activity services '+PACKAGE),'serviço encerrado após importar')
        c['real_pair_import_and_native_validation_screen_off']='PASS'
        if GEMMA:
            size,available=map(int,re.findall(r'file_bytes=(\d+) available=(\d+)',log)[-1])
            assert size>0 and available>0
            estimate=size+size//2+512*262144+268435456
            assert estimate>available*7//10,(estimate,available)
            (E/'physical-compute-memory.json').write_text(json.dumps(dict(file_bytes=size,available_bytes=available,old_estimate=estimate,old_limit=available*7//10,old_would_reject=True,actual_native_load='PASS'),indent=2))
            c['real_gemma_load_succeeds_where_old_memory_formula_rejected']='PASS'
        output=Path('.cache/compute-unified.gguf');d.adb('pull',model['path'],output,timeout=600)
        expected=tensor_hashes(mobile.MODEL);expected.update(tensor_hashes(mobile.PROJ));assert tensor_hashes(output)==expected
        (E/'physical-compute-tensors.json').write_text(json.dumps(dict(apk_sha256=s['apk_sha256'],tensor_count=len(expected),size=output.stat().st_size,tensors=expected),indent=2))
        assert model['path']==model['mmprojPath'];c['independent_tensor_and_same_file_audit']='PASS'
        on(d);d.launch();d.tap(text='Importar',package={PACKAGE});no_emoji(d);d.capture('physical-compute-library.png')
        chat=d.new_chat(model,0,context_size=1024)
        no_emoji(d);d.capture('physical-compute-chat.png')
        d.tap(desc='Alternar ferramentas',package={PACKAGE});no_emoji(d);d.capture('physical-compute-tools.png');d.tap(desc='Alternar ferramentas',package={PACKAGE})
        prompt='Write a detailed explanation of how rain forms, in English.'
        d.send(prompt);pid=d.alive()
        power=d.shell('dumpsys power');services=d.shell('dumpsys activity services '+PACKAGE)
        before=d.adb('logcat','-d')
        assert 'GenerationService' in services and 'isForeground=true' in services and 'GGUFChat:LocalCompute' in active_wake_locks(power)
        (E/'physical-compute-generation-start.txt').write_text(power+'\n'+services+'\n'+before[-150000:])
        off(d)
        def reply():
            assert d.alive()==pid
            if not generation_completed(d.adb('logcat','-d')):return None
            try:return assistant_reply(d.read_json('chats.json'),chat['id'],prompt)
            except AssertionError:return None
        time.sleep(12) # No synthetic worker or fabricated progress.
        answer=d.wait(reply,'resposta real gravada com tela apagada',timeout=1200)
        power=d.shell('dumpsys power');assert 'mWakefulness=Asleep' in power
        log=d.adb('logcat','-d');assert completed_after_actual_sleep(log),'Native completion did not occur after actual system sleep'
        (E/'physical-compute-response.txt').write_text(answer)
        (E/'physical-compute-generation-complete.txt').write_text(power+'\n'+d.adb('logcat','-d')[-150000:])
        d.wait(lambda:'GGUFChat:LocalCompute' not in active_wake_locks(d.shell('dumpsys power')),'wakelock liberado após geração')
        c['real_native_generation_and_saved_response_screen_off']='PASS'
        on(d);d.launch();d.open_existing_chat(chat['title']);d.capture('physical-compute-reopened-response.png')
        assert assistant_reply(d.read_json('chats.json'),chat['id'],prompt)==answer
        c['reply_survives_reopen']='PASS';s['status']='PASS'
    except Exception as e:
        s['error']=str(e);(E/'physical-compute-failure.txt').write_text(traceback.format_exc());traceback.print_exc()
    finally:
        (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
        try:(E/'physical-compute-power-final.txt').write_text(d.shell('dumpsys power')+'\n'+d.shell('dumpsys activity services '+PACKAGE));on(d);d.capture('physical-compute-final.png');(E/'physical-compute-final-log.txt').write_text(d.adb('logcat','-d')[-150000:])
        except Exception:pass
        print(json.dumps(s,indent=2,ensure_ascii=False))
    return 0 if s['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
