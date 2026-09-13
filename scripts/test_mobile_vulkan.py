#!/usr/bin/env python3
"""Exact shipped APK, real GGUFs, Vulkan generation. Provisioning is NOT SAF proof."""
import hashlib,json,re,shlex,traceback
from pathlib import Path
from test_mobile import MobileAndroid,APK,MODEL,PROJ
from android_checks import PACKAGE,generation_completed,assistant_reply,vulkan_offloaded,basic_response_quality

E=Path('evidence')

def main():
    d=MobileAndroid('emulator-5554',E)
    result={'status':'FAIL','scope':'real-models-vulkan-generation-NOT-SAF','cases':{},'apk_sha256':hashlib.sha256(APK.read_bytes()).hexdigest(),'environment':'Android 15 x86_64, Mesa software Vulkan; not physical GPU'}
    try:
        assert result['apk_sha256']=='409985de54388cbcb1429a8db4cd26139cc47a5764864c6cd4b408c75f07099f'
        assert d.shell('getprop ro.kernel.qemu')=='1'
        d.adb('root',check=False);d.adb('wait-for-device',timeout=60)
        assert d.shell('id -u')=='0'
        d.shell('wm size 720x1280');d.shell('wm density 240')
        d.shell('pm disable-user --user 0 com.google.android.apps.nexuslauncher',check=False)
        d.adb('logcat','-G','16M')
        d.shell('setprop debug.gguf.vulkan_device 0')
        (E/'vulkan-device.json').write_text(d.shell('cmd gpu vkjson',check=False))
        d.adb('install','-r','-g',APK,timeout=180)
        assert d.shell(f'pm clear {PACKAGE}')=='Success'
        d.grant_test_notifications();d.launch()
        for name,source,projector in [('smolvlm',MODEL,PROJ),('smollm2',Path('.cache/mobile-models/SmolLM2-135M-Instruct-Q4_K_M.gguf'),None)]:
            case={'status':'FAIL','setup':'rooted test provisioning of actual GGUF bytes, not SAF','model_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'requested_layers':99,'projector_backend':'CPU' if projector else None}
            result['cases'][name]=case
            model=d.provision_model(source)
            if projector:
                d.shell(f'am force-stop {PACKAGE}')
                dest=str(Path(model['path']).parent/projector.name)
                d.adb('push',projector,dest,timeout=300)
                uid=d.shell(f'stat -c %u /data/user/0/{PACKAGE}')
                d.shell(f'chown {uid}:{uid} {shlex.quote(dest)} && chmod 600 {shlex.quote(dest)} && restorecon {shlex.quote(dest)}')
                case['projector_sha256']=hashlib.sha256(projector.read_bytes()).hexdigest()
                assert d.shell('sha256sum '+shlex.quote(dest)).split()[0]==case['projector_sha256']
                model.update(mmprojPath=dest,multimodal=True)
                d.write_private('files/models.json',json.dumps([model]))
            d.adb('logcat','-c')
            chat=d.new_chat(model,99);pid=d.alive();case['pid']=pid
            def log():
                assert d.alive()==pid,'Application died or restarted'
                text=d.adb('logcat','-d',f'--pid={pid}')
                (E/f'{name}-logcat.txt').write_text(text)
                generation_completed(text) # also rejects native failures/crashes
                return text
            def loaded():
                text=log()
                if 'Create failed:' in text:raise AssertionError('Native load failed; CPU fallback is not Vulkan success')
                if 'model loaded:' not in text:return False
                assert vulkan_offloaded(text),'Latest successful model load did not offload layers to Vulkan'
                if projector:assert 'GGUF_PROJECTOR_LOADED vision=1' in text
                case['offload_records']=re.findall(r'offloaded\s+\d+(?:/\d+)?\s+layers?\s+to\s+GPU',text,re.I)
                return True
            d.wait(loaded,'actual Vulkan model load',timeout=300)
            replies=[]
            for i,prompt in enumerate(['Reply in English with a short greeting.','Reply in English: What is two plus two?'],1):
                baseline=log().count('GGUF_NATIVE_COMPLETE')
                d.send(prompt,clear_log=False)
                def completed():
                    text=log()
                    if text.count('GGUF_NATIVE_COMPLETE')<=baseline or not generation_completed(text):return None
                    assert vulkan_offloaded(text),'CPU fallback cannot pass this test'
                    assert re.search(r'GGUF_NATIVE_COMPLETE tokens=\d+ reason=\w+ projector='+('1' if projector else '0'),text)
                    chats=d.read_json('chats.json');(E/f'{name}-chats.json').write_text(json.dumps(chats,ensure_ascii=False))
                    try:return assistant_reply(chats,chat['id'],prompt)
                    except AssertionError:return None
                reply=d.wait(completed,'native completion and persisted reply with same PID',timeout=600)
                replies.append(reply);(E/f'{name}-{i}-reply.txt').write_text(reply);d.capture(f'{name}-{i}-reply.png')
            case['status']='PASS';case['native_generations']=2
            case['completions']=re.findall(r'GGUF_NATIVE_COMPLETE[^\n]+',log())
            try:basic_response_quality(*replies);case['basic_response_quality']='PASS'
            except AssertionError as e:case['basic_response_quality']='FAIL: '+str(e)
        result['status']='PASS'
    except Exception as e:
        result['error']=str(e);traceback.print_exc()
        commands=E/'commands.log'
        (E/'failure-context.txt').write_text(traceback.format_exc()+'\n'+(commands.read_text()[-12000:] if commands.exists() else ''))
    finally:
        try:
            full=d.adb('logcat','-d');(E/'final-logcat.txt').write_text(full)
            filtered='\n'.join(line for line in full.splitlines() if re.search(r'GGUF|[EFW] AndroidRuntime|Fatal signal|F DEBUG',line))
            (E/'vulkan-final-logcat.txt').write_text(filtered[-150000:]);d.capture('final-screen.png')
        except Exception:pass
        (E/'summary.json').write_text(json.dumps(result,indent=2,ensure_ascii=False))
    raise SystemExit(0 if result['status']=='PASS' else 1)

if __name__=='__main__':main()
