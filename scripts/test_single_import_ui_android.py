#!/usr/bin/env python3
"""Real Android: last-release upgrade, empty-library shortcut, legacy restoration,
SAF pair -> one native-valid file and three-file sequential selection. No index injection.
"""
import hashlib,json,re,shlex,traceback
from pathlib import Path
import xml.etree.ElementTree as ET
from test_mobile import MobileAndroid,APK,MODEL,PROJ,bounds
from android_checks import PACKAGE,PICKERS,position,has_package
from test_physical_android import tensor_hashes
E=Path('evidence')

def one_button(d,name):
    xml=d.ui();labels=[n.get('text','') for n in ET.fromstring(xml).iter('node') if n.get('package')==PACKAGE]
    assert labels.count('Importar GGUF')==1,labels
    assert not any('Importar 2' in t or 'Importar modelo GGUF' in t for t in labels),labels
    d.capture('physical-import-ui-'+name+'.png')

def push(d,p,name=None):
    name=name or p.name;d.adb('push',p,'/sdcard/Download/'+name,timeout=300)
    d.shell('am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d '+shlex.quote('file:///sdcard/Download/'+name),check=False)

def select(d,names,label):
    d.tap(text='Importar GGUF',package={PACKAGE})
    d.wait(lambda:has_package(d.ui(),PICKERS),'seletor múltiplo real')
    d.tap(desc='Show roots',package=PICKERS,optional=True);d.select_downloads()
    d.tap(desc='List view',package=PICKERS,optional=True)
    for i,name in enumerate(names):
        # The icon is the selection hotspot; touching the filename can OPEN it.
        xml=d.ui();root=ET.fromstring(xml);parents={c:p for p in root.iter() for c in p}
        target=next(n for n in root.iter('node') if n.get('text')==name and n.get('package') in PICKERS)
        parent=parents[target];point=None
        while parent is not None:
            icons=[n for n in parent.iter('node') if n.get('resource-id','').endswith(('/icon_mime','/icon_check','/icon_thumb'))]
            for n in icons:
                b=bounds(n)
                if len(b)==4 and b[2]>b[0] and b[3]>b[1]:point=((b[0]+b[2])//2,(b[1]+b[3])//2);break
            if point:break
            parent=parents.get(parent)
        assert point,'No selection hotspot for '+name
        d.shell(f'input tap {point[0]} {point[1]}')
        d.wait(lambda:position(d.ui(),text=f'{i+1} selected',package=PICKERS),'seleção exata '+str(i+1))
    d.capture('physical-import-ui-'+label+'-selected.png')
    d.tap(text='Select',package=PICKERS)


def main():
    E.mkdir(exist_ok=True);d=MobileAndroid('emulator-5554',E)
    c=json.load(open('ci/import-ui-candidate.json'))
    s=dict(status='FAIL',apk_sha256=hashlib.sha256(APK.read_bytes()).hexdigest(),checks={},scope='targeted import-navigation and real multi-selection regression; unchanged native/helpers/resources compared with last approved release')
    checks=s['checks']
    try:
        assert s['apk_sha256']==c['apk_sha256'];assert d.shell('getprop ro.kernel.qemu')=='1'
        d.adb('root',check=False);d.adb('wait-for-device');d.shell('wm size 720x1280');d.shell('wm density 240')
        old=Path('.cache/import-ui-base.apk');assert hashlib.sha256(old.read_bytes()).hexdigest()==c['ui_base_apk_sha256']
        d.adb('install','-r','-g',old,timeout=180);assert d.shell('pm clear '+PACKAGE)=='Success'
        d.grant_test_notifications();d.launch();d.write_private('files/import-ui-upgrade.txt','preserve latest release data')
        d.adb('install','-r','-g',APK,timeout=180)
        assert d.shell(f'cat /data/user/0/{PACKAGE}/files/import-ui-upgrade.txt')=='preserve latest release data'
        d.launch();assert d.shell(f'cat /data/user/0/{PACKAGE}/files/import-ui-upgrade.txt')=='preserve latest release data'
        checks['same_signature_upgrade_and_launch_preserve_private_data']='PASS'
        d.tap(text='Nova conversa',contains=True,package={PACKAGE})
        d.wait(lambda:position(d.ui(),text='Nenhum modelo',package={PACKAGE}),'aviso de biblioteca vazia')
        d.capture('physical-import-ui-empty-message.png');d.tap(text='Importar',package={PACKAGE})
        d.wait(lambda:position(d.ui(),text='Importar GGUF',package={PACKAGE}),'uma opção de importação')
        one_button(d,'empty-library');checks['empty_library_one_import_button']='PASS'
        for cold in (False,True):
            if cold:d.shell('am force-stop '+PACKAGE)
            d.shell('am start -W -n '+PACKAGE+'/.ModelsActivity')
            d.wait(lambda:position(d.ui(),text='Importar GGUF',package={PACKAGE}),'redirecionamento da tela antiga')
            one_button(d,'legacy-cold' if cold else 'legacy-warm')
        checks['legacy_activity_cold_and_warm_use_same_screen']='PASS'
        d.shell('mkdir -p /sdcard/Download');d.adb('logcat','-G','16M');d.adb('logcat','-c')
        for p in (MODEL,PROJ):push(d,p)
        select(d,[MODEL.name,PROJ.name],'pair')
        def merged():
            rows=d.read_json('models.json',optional=True)
            return rows[0] if len(rows)==1 and rows[0].get('capability')=='VISION_SINGLE_GGUF' else None
        unit=d.wait(merged,'dois arquivos em um GGUF válido',timeout=600)
        assert unit['path']==unit['mmprojPath']
        log=d.adb('logcat','-d');assert 'GGUF_ATOMIC_NATIVE_VALIDATED same_path=1 backend=CPU' in log
        assert 'GGUF_ATOMIC_IMPORT_COMMITTED records_added=1' in log
        result=Path('.cache/import-ui-output.gguf');d.adb('pull',unit['path'],result,timeout=300)
        tensors=tensor_hashes(MODEL);tensors.update(tensor_hashes(PROJ));assert tensor_hashes(result)==tensors
        assert d.shell(f'find /data/user/0/{PACKAGE}/files/pair-import-staging -mindepth 1').strip()==''
        checks['real_multi_select_pair_one_file_native_validation_exact_tensors']='PASS'
        (E/'physical-import-ui-pair-proof.json').write_text(json.dumps(dict(tensor_count=len(tensors),size=result.stat().st_size,sha256=hashlib.sha256(result.read_bytes()).hexdigest(),model=unit),indent=2))
        d.launch();d.tap(text='📁 Importar',package={PACKAGE});one_button(d,'pair-imported')
        text=Path('.cache/mobile-models/SmolLM2-135M-Instruct-Q4_K_M.gguf');names=['batch-a.gguf','batch-b.gguf','batch-c.gguf']
        for name in names:push(d,text,name)
        select(d,names,'three')
        rows=d.wait(lambda:(x if len(x:=d.read_json('models.json',optional=True))==4 else None),'três arquivos importados sem limite de dois',timeout=600)
        for name in names:
            row=next(r for r in rows if r['fileName']==name);assert row['capability']=='TEXT_ONLY' and not row['multimodal']
            assert d.shell('sha256sum '+shlex.quote(row['path'])).split()[0]==hashlib.sha256(text.read_bytes()).hexdigest()
        d.launch();assert len(d.read_json('models.json'))==4
        d.tap(text='📁 Importar',package={PACKAGE});one_button(d,'three-imported')
        checks['three_file_selection_imports_all_and_survives_restart']='PASS'
        s['status']='PASS'
    except Exception as e:
        s['error']=str(e);(E/'physical-import-ui-failure.txt').write_text(traceback.format_exc());traceback.print_exc()
    finally:
        (E/'summary.json').write_text(json.dumps(s,indent=2,ensure_ascii=False))
        try:d.capture('physical-import-ui-final.png');(E/'physical-import-ui-log.txt').write_text(d.adb('logcat','-d'))
        except Exception:pass
        print(json.dumps(s,indent=2,ensure_ascii=False))
    return 0 if s['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
