#!/usr/bin/env python3
"""Actual SAF negative transactions on the exact APK; no model/index injection.
Run after physical acceptance. Preserve existing models/chats across every rejection.
"""
import hashlib,json,shlex,sys,traceback
from pathlib import Path
import test_mobile as mobile
from test_mobile import MobileAndroid,APK
from android_checks import PACKAGE,position

E=Path('evidence');F=Path('.cache/atomic-negative')

def main():
    d=MobileAndroid('emulator-5554',E);summary=json.loads((E/'summary.json').read_text());checks={};summary['atomic_checks']=checks
    try:
        assert d.shell('getprop ro.kernel.qemu')=='1'
        assert summary['status']=='PASS' and summary['apk_sha256']==hashlib.sha256(APK.read_bytes()).hexdigest()
        F.mkdir(parents=True,exist_ok=True)
        sys.path.insert(0,str(Path('tests').resolve()))
        from test_physical_gguf import fixture
        fake_language=F/'synthetic-language.gguf';fake_projector=F/'synthetic-projector.gguf'
        fixture(fake_language);fixture(fake_projector,'projector')
        broken=F/'truncated.gguf';broken.write_bytes(mobile.PROJ.read_bytes()[:128])
        actual_language=Path('.cache/mobile-models/SmolLM2-135M-Instruct-Q4_K_M.gguf')
        actual_projector=mobile.PROJ
        baseline=d.read_json('models.json');chats=d.read_json('chats.json')
        files=d.shell(f'find /data/user/0/{PACKAGE}/files/models -type f | sort')
        cases=[('two_real_language_models',actual_language,actual_language),
               ('two_real_projectors',actual_projector,actual_projector),
               ('truncated_second_input',actual_language,broken),
               ('native_loader_rejects_structurally_mergeable_fake_weights',fake_language,fake_projector)]
        for name,first,second in cases:
            d.launch();d.adb('logcat','-c')
            # Only disposable emulator Downloads fixtures; never user/provider originals.
            d.shell('rm -f /sdcard/Download/*.gguf')
            names=['strict-a.gguf','strict-b.gguf']
            for source,dest in zip((first,second),names):
                d.adb('push',source,'/sdcard/Download/'+dest,timeout=300)
                d.shell('am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d '+shlex.quote('file:///sdcard/Download/'+dest),check=False)
            mobile.MODEL=Path(names[0]);mobile.PROJ=Path(names[1]);mobile.select_pair(d)
            d.wait(lambda:position(d.ui(),text='Importação recusada',package={PACKAGE}),'rejeição explícita '+name,timeout=240)
            d.capture('physical-atomic-'+name+'.png')
            log=d.adb('logcat','-d');(E/('physical-atomic-'+name+'.txt')).write_text(log)
            assert 'GGUF_ATOMIC_IMPORT_REJECTED' in log and 'GGUF_ATOMIC_IMPORT_COMMITTED' not in log
            if name.startswith('native_loader'):
                assert 'Create failed:' in log or 'Failed to load model' in log,'A rejeição deve chegar ao motor real'
            d.tap(text='OK',package={PACKAGE})
            d.wait(lambda:d.shell(f'find /data/user/0/{PACKAGE}/files/pair-import-staging -mindepth 1').strip()=='','limpeza dos temporários')
            assert d.read_json('models.json')==baseline and d.read_json('chats.json')==chats
            assert d.shell(f'find /data/user/0/{PACKAGE}/files/models -type f | sort')==files
            for source,dest in zip((first,second),names):
                assert d.shell('sha256sum /sdcard/Download/'+dest).split()[0]==hashlib.sha256(source.read_bytes()).hexdigest()
            d.launch();assert d.read_json('models.json')==baseline
            checks[name]='PASS: no new records/files, previous library and chats unchanged, originals byte-identical, restart unchanged'
        summary['status']='PASS'
    except Exception as ex:
        summary['status']='FAIL';summary['error']='Atomic import: '+str(ex)
        (E/'physical-atomic-failure.txt').write_text(traceback.format_exc());traceback.print_exc()
    finally:
        (E/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False))
        try:d.capture('physical-atomic-final.png')
        except Exception:pass
    return 0 if summary['status']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
