#!/usr/bin/env python3
"""Real public Gemma 4 pair -> one physical GGUF -> actual Android image inference.
Preserve old-signer update evidence and every real reply. Never inject a model index.
"""
import gc,hashlib,json,shlex,traceback,os
from pathlib import Path
import test_mobile as mobile
from test_mobile import MobileAndroid,APK
from android_checks import PACKAGE,position,vulkan_offloaded
from test_inference_android import fixtures,attach,reply
from inspect_gemma4 import hashes

E=Path('evidence');BASE=Path('.cache/gemma4-models')
mobile.MODEL=BASE/'gemma-4-E2B-it-Q3_K_S.gguf'
mobile.PROJ=BASE/'mmproj-F16.gguf'
OLD=Path('.cache/previous-physical.apk')
OLD_SHA=os.environ.get('GGUF_PREVIOUS_APK_SHA','4d1697c2ee9b80ba38a03ee78ab0241dc8aa3d5464c956707e2412be70b11ce6')
OLD_CERT=os.environ.get('GGUF_PREVIOUS_CERT_SHA','9a368c9a1e4f3b3b0b6ecfb86aa3768d633a925855afba27eab3b9189177955a')


def main():
    E.mkdir(exist_ok=True);d=MobileAndroid('emulator-5554',E)
    candidate=json.loads(Path(os.environ.get('GGUF_CANDIDATE','ci/gemma4-candidate.json')).read_text())
    s={'status':'FAIL','scope':'Gemma4-reference-pair-physical-merge-and-native-vision','checks':{},
       'apk_sha256':hashlib.sha256(APK.read_bytes()).hexdigest(),
       'environment':'Android emulator, Mesa software Vulkan, exact signed candidate; 12 GiB configured guest RAM (not physical hardware)',
       'model_reference':'unsloth/gemma-4-E2B-it-GGUF at 0314792d7f1f7e229411f620751375812bb9faf2, Q3_K_S + mmproj-F16',
       'response_quality':{}}
    checks=s['checks']
    def save():(E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
    try:
        assert s['apk_sha256']==candidate['apk_sha256']
        assert hashlib.sha256(OLD.read_bytes()).hexdigest()==OLD_SHA
        assert d.shell('getprop ro.kernel.qemu')=='1'
        d.adb('root',check=False);d.adb('wait-for-device',timeout=60)
        d.shell('pm disable-user --user 0 com.google.android.apps.nexuslauncher',check=False);d.shell('wm size 720x1280');d.shell('wm density 240')
        d.adb('logcat','-G','16M');d.shell('setprop debug.gguf.vulkan_device 0')
        # Real in-place update: same package and certificate, with private data retained.
        d.adb('install','-r','-g',OLD,timeout=180);assert d.shell('pm clear '+PACKAGE)=='Success'
        d.grant_test_notifications();d.launch()
        d.write_private('files/signature-update-probe.txt','Gemma4 in-place update probe')
        if candidate['signer_sha256']==OLD_CERT:
            d.adb('install','-r','-g',APK,timeout=180)
            assert d.shell('cat /data/user/0/'+PACKAGE+'/files/signature-update-probe.txt')=='Gemma4 in-place update probe'
            checks['same_signature_update_retains_private_data']='PASS'
        else:
            assert candidate.get('replacement_signature_authorized') is True
            result=d.adb('install','-r','-g',APK,timeout=180,check=False,with_status=True)
            detail=(result.stdout+result.stderr).decode(errors='replace')
            assert result.returncode!=0 and 'INSTALL_FAILED_UPDATE_INCOMPATIBLE' in detail,detail
            assert d.shell('cat /data/user/0/'+PACKAGE+'/files/signature-update-probe.txt')=='Gemma4 in-place update probe'
            checks['different_signature_update_blocked_without_losing_old_private_data']='PASS'
            # Explicitly disposable emulator only; NEVER advise blind uninstall on a user's phone.
            assert d.adb('uninstall',PACKAGE).strip()=='Success'
            d.adb('install','-g',APK,timeout=180)
        save()
        # Clear ONLY this disposable emulator for the actual fresh SAF import acceptance.
        assert d.shell('pm clear '+PACKAGE)=='Success';d.grant_test_notifications();d.launch()
        d.shell('mkdir -p /sdcard/Download')
        for path in (mobile.MODEL,mobile.PROJ):
            d.adb('push',path,'/sdcard/Download/'+path.name,timeout=600)
            d.shell('am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d '+shlex.quote('file:///sdcard/Download/'+path.name),check=False)
        observer=None
        if os.environ.get('GGUF_PROGRESS_REQUIRED')=='1':
            from import_progress_checks import ProgressObserver
            observer=ProgressObserver(d,'gemma4-pair')
        mobile.select_pair(d)
        def complete():
            if observer:observer.poll()
            rows=d.read_json('models.json',optional=True)
            return rows[0] if len(rows)==1 and rows[0].get('capability')=='VISION_SINGLE_GGUF' and rows[0]['path']==rows[0].get('mmprojPath') else None
        unit=d.wait(complete,'Gemma4 unificado fisicamente',timeout=1800)
        if observer:checks['measured_per_file_identification_merge_verify_progress']=observer.finish([mobile.MODEL.stat().st_size,mobile.PROJ.stat().st_size],pair=True)
        assert unit['architecture']=='gemma4'
        assert 'GGUF_PHYSICAL_UNIFICATION_OK' in d.adb('logcat','-d')
        if os.environ.get('GGUF_ATOMIC_REQUIRED')=='1':
            log=d.adb('logcat','-d')
            assert 'GGUF_ATOMIC_NATIVE_VALIDATED same_path=1 backend=CPU' in log and 'GGUF_ATOMIC_IMPORT_COMMITTED records_added=1 source_files_remaining=0' in log
            assert d.shell('find /data/user/0/'+PACKAGE+'/files/pair-import-staging -mindepth 1').strip()==''
            checks['atomic_native_validated_one_file_commit']='PASS'
        private=d.shell('find /data/user/0/'+PACKAGE+'/files/models -type f').splitlines()
        assert private==[unit['path']],private
        actual=BASE/'android-unified.gguf';d.adb('pull',unit['path'],actual,timeout=600)
        expected=hashes(mobile.MODEL);projector=hashes(mobile.PROJ);assert not set(expected)&set(projector);expected.update(projector)
        assert hashes(actual)==expected
        assert len(expected)==2012 and actual.stat().st_size==unit['size']==3431306464
        with actual.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
        assert digest=='cb17b173deb6b62c1b8a2e914ea9bbdde75ae8a9a41baef23aaff2d074056066'
        (E/'physical-gemma4-android-tensors.json').write_text(json.dumps({'status':'PASS','apk_sha256':s['apk_sha256'],'tensor_count':len(expected),'size':unit['size'],'unified_sha256':digest,'tensors':expected},indent=2))
        (E/'physical-gemma4-model.json').write_text(json.dumps(unit,indent=2,ensure_ascii=False))
        actual.unlink();del expected,projector;gc.collect()
        # No originals remain inside app or Downloads during inference.
        for path in (mobile.MODEL,mobile.PROJ):d.shell('rm -- '+shlex.quote('/sdcard/Download/'+path.name))
        assert d.shell("find /sdcard/Download -type f -name '*.gguf'")==''
        assert position(d.ui(),text='👁',contains=True,package={PACKAGE})
        d.capture('physical-gemma4-one-file.png')
        checks['real_SAF_pair_to_one_GGUF_all_2012_tensors']='PASS';save()
        d.launch();assert d.read_json('models.json')==[unit]
        checks['single_file_survives_restart']='PASS'
        fixtures()
        chat=d.new_chat(unit,99,context_size=1024);attach(d,chat,['frame-a.jpg'])
        load=d.adb('logcat','-d');(E/'physical-gemma4-load.txt').write_text(load)
        answer=reply(d,chat,'Name the main animal in the image. Reply in English with one word.','gemma4-image',images=1,timeout=1200)
        log=load+(E/'inference-gemma4-image-logcat.txt').read_text()
        assert 'GGUF_SINGLE_FILE_LOADED same_path=1' in log
        assert 'GGUF_PROJECTOR_LOADED vision=1' in log
        assert 'GGUF_PROJECTOR_WEIGHTS backend=Vulkan' in log and vulkan_offloaded(log)
        assert 'GGUF_JINJA_TEMPLATE_APPLIED' in log
        checks['native_Gemma4_same_file_vision_Vulkan_Jinja']='PASS'
        s['response_quality']['gemma4-image']={'status':'PASS' if 'dog' in answer.lower() else 'FAIL','response':answer}
        # Force-stop and reopen the persisted media conversation; no separate projector exists.
        d.launch();assert d.read_json('models.json')==[unit];d.open_existing_chat(chat['title'])
        answer=reply(d,chat,'Name the main animal in the attached image again. Reply in English with one word.','gemma4-restart',images=1,timeout=1200)
        checks['native_image_history_after_restart']='PASS'
        s['response_quality']['gemma4-restart']={'status':'PASS' if 'dog' in answer.lower() else 'FAIL','response':answer}
        assert d.shell('find /data/user/0/'+PACKAGE+'/files/models -type f').splitlines()==[unit['path']]
        checks['image_inference']='PASS';save()
        text_chat=d.new_chat(unit,99,context_size=1024)
        answer=reply(d,text_chat,'What is 2 + 2? Reply with only the number.','gemma4-text',timeout=1200)
        checks['native_Gemma4_text_only']='PASS'
        s['response_quality']['gemma4-text']={'status':'PASS' if answer.strip(' \n.!*`')=='4' else 'FAIL','response':answer}
        assert all(r['status']=='PASS' for r in s['response_quality'].values()),'Gemma4 reference image/text quality did not pass; preserve actual replies'
        s['status']='PASS'
        s['limits']='Vision/text tested; audio weights preserved, but no audio-input UI/transcription acceptance. Reference pair is not asserted to match user files. No physical GPU/RAM approval.'
    except Exception as ex:
        s['error']=str(ex);traceback.print_exc();(E/'physical-gemma4-failure.txt').write_text(traceback.format_exc())
    finally:
        save();print(json.dumps(s,indent=2,ensure_ascii=False))
        try:d.capture('physical-gemma4-final.png');(E/'physical-gemma4-final-logcat.txt').write_text(d.adb('logcat','-d'))
        except Exception:pass
    return 0 if s['status']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
