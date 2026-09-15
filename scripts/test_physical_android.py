#!/usr/bin/env python3
"""Disposable emulator: actual SAF merge, independent GGUF tensor audit,
independently written single-file import and real visual inference, system-role UI.
"""
import hashlib,json,os,shlex,sys,traceback,subprocess,shutil
from pathlib import Path
import xml.etree.ElementTree as ET
from test_mobile import MobileAndroid,select_pair,MODEL,PROJ,APK,bounds
from android_checks import PACKAGE,position
from test_inference_android import fixtures,attach,reply

E=Path('evidence');C=Path('.cache/physical-test')
sys.path.insert(0,str(Path('.cache/llama-mobile/gguf-py').resolve()))
from gguf import GGUFReader,GGUFWriter,GGUFValueType

def tensor_hashes(path):
    r=GGUFReader(str(path));return {t.name:{'shape':t.shape.tolist(),'type':int(t.tensor_type),'sha256':hashlib.sha256(t.data).hexdigest()} for t in r.tensors}

def independent_single():
    """Standard upstream writer, not the app merger; real pretrained weights.
    This is a generated external-format fixture, NOT a claimed public single-file model.
    """
    a,b=GGUFReader(str(MODEL)),GGUFReader(str(PROJ));path=C/'external-one.gguf'
    w=GGUFWriter(path,a.fields['general.architecture'].contents())
    for r in (a,b):
        for key,field in r.fields.items():
            if key.startswith('GGUF.') or key=='general.alignment':continue
            if r is b and key in a.fields:continue
            w.add_key_value(key,field.contents(),field.types[0],field.types[-1] if field.types[0]==GGUFValueType.ARRAY else None)
    w.add_name('Independent single-file vision fixture')
    for r in (a,b):
        for t in r.tensors:w.add_tensor(t.name,t.data,raw_dtype=t.tensor_type)
    w.write_header_to_file();w.write_kv_data_to_file();w.write_tensors_to_file();w.close()
    return path

def edit_prompt(d,text,global_prompt=False,reset=False):
    if global_prompt:
        d.launch();d.tap(desc='Prompt de sistema global',package={PACKAGE})
    else:
        d.tap(desc='Alternar ferramentas',package={PACKAGE});d.tap(desc='Prompt de sistema da conversa',package={PACKAGE})
    d.wait(lambda:position(d.ui(),desc='Texto do prompt de sistema',package={PACKAGE}),'editor de prompt')
    if not reset:
        d.tap(desc='Texto do prompt de sistema',package={PACKAGE})
        d.shell('input keycombination 113 29')
        d.shell('input text '+shlex.quote(text.replace(' ','%s')))
        d.adb('shell','input','keyevent','4')
    d.capture('system-global-editor.png' if global_prompt else 'system-chat-editor.png')
    d.tap(text=('Restaurar padrão' if global_prompt else 'Usar padrão global') if reset else 'Salvar',package={PACKAGE})
    d.wait(lambda:not position(d.ui(),desc='Texto do prompt de sistema',package={PACKAGE}),'editor fechado')
    if not global_prompt:d.tap(desc='Alternar ferramentas',package={PACKAGE})

def main():
    E.mkdir(exist_ok=True);C.mkdir(parents=True,exist_ok=True);d=MobileAndroid('emulator-5554',E)
    summary={'status':'FAIL','scope':'physical-GGUF-parameters-system-prompts','apk_sha256':hashlib.sha256(APK.read_bytes()).hexdigest(),'checks':{},'physical_checks':{},'environment':'Android emulator, Mesa software Vulkan; '+os.environ.get('GGUF_SIGNATURE_SCOPE','test-only ephemeral signature')};checks=summary['physical_checks']
    try:
        assert d.shell('getprop ro.kernel.qemu')=='1';d.adb('root',check=False);d.adb('wait-for-device',timeout=60)
        d.shell('pm disable-user --user 0 com.google.android.apps.nexuslauncher',check=False);d.shell('wm size 720x1280');d.shell('wm density 240');d.adb('logcat','-G','16M');d.shell('setprop debug.gguf.vulkan_device 0')
        d.adb('install','-r','-g',APK,timeout=180);assert d.shell('pm clear '+PACKAGE)=='Success'
        d.grant_test_notifications();d.launch()
        if os.environ.get('GGUF_PROGRESS_REQUIRED')=='1':
            d.tap(text='Nova conversa',contains=True,package={PACKAGE})
            d.wait(lambda:position(d.ui(),text='Nenhum modelo',package={PACKAGE}),'atalho com biblioteca vazia')
            d.tap(text='Importar',package={PACKAGE})
            d.wait(lambda:position(d.ui(),text='Importar .gguf',contains=True,package={PACKAGE}),'mesma tela de importação com progresso')
            d.capture('physical-progress-empty-library-shortcut.png')
            checks['empty_library_shortcut_uses_canonical_import']='PASS'
        d.shell('mkdir -p /sdcard/Download')
        for f in (MODEL,PROJ):
            d.adb('push',f,'/sdcard/Download/'+f.name,timeout=300)
            d.shell('am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d '+shlex.quote('file:///sdcard/Download/'+f.name),check=False)
        observer=None
        if os.environ.get('GGUF_PROGRESS_REQUIRED')=='1':
            from import_progress_checks import ProgressObserver
            observer=ProgressObserver(d,'small-pair')
        d.progress_observer=observer
        select_pair(d)
        def merged():
            if observer:observer.poll()
            rows=d.read_json('models.json',optional=True)
            return rows[0] if len(rows)==1 and rows[0].get('capability')=='VISION_SINGLE_GGUF' and rows[0]['path']==rows[0].get('mmprojPath') else None
        unit=d.wait(merged,'unificação física persistida',timeout=600)
        if observer:checks['measured_pair_progress']=observer.finish([MODEL.stat().st_size,PROJ.stat().st_size],pair=True);d.progress_observer=None
        assert 'GGUF_PHYSICAL_UNIFICATION_OK' in d.adb('logcat','-d')
        if os.environ.get('GGUF_ATOMIC_REQUIRED')=='1':
            log=d.adb('logcat','-d')
            assert 'GGUF_ATOMIC_NATIVE_VALIDATED same_path=1 backend=CPU' in log and 'GGUF_ATOMIC_IMPORT_COMMITTED records_added=1 source_files_remaining=0' in log
            assert d.shell('find /data/user/0/'+PACKAGE+'/files/pair-import-staging -mindepth 1').strip()==''
            checks['atomic_native_validated_one_file_commit']='PASS'
        actual=C/'app-unified.gguf';d.adb('pull',unit['path'],actual,timeout=300)
        expected=tensor_hashes(MODEL);projector=tensor_hashes(PROJ);assert not set(expected)&set(projector);expected.update(projector)
        assert tensor_hashes(actual)==expected
        assert actual.stat().st_size==unit['size']
        private=d.shell('find /data/user/0/'+PACKAGE+'/files/models -type f').splitlines();assert private==[unit['path']],private
        d.capture('physical-one-file.png');(E/'physical-tensor-proof.json').write_text(json.dumps({'status':'PASS','tensor_count':len(expected),'apk_sha256':summary['apk_sha256'],'unified_sha256':hashlib.sha256(actual.read_bytes()).hexdigest(),'size':unit['size'],'tensors':expected},indent=2))
        checks['one_physical_file_and_all_tensor_hashes']='PASS'
        d.launch();assert d.read_json('models.json')==[unit];checks['restart_persistence']='PASS'
        d.tap(text='Importar',contains=True,package={PACKAGE});assert position(d.ui(),text='👁',contains=True,package={PACKAGE})
        fixtures();chat=d.new_chat(unit,99,context_size=4096);attach(d,chat,['frame-a.jpg'])
        before_load=d.adb('logcat','-d')
        answer=reply(d,chat,'Name the main animal in the image. Reply in English.','physical-one-file',images=1)
        assert 'dog' in answer.lower(),answer
        log=before_load+(E/'inference-physical-one-file-logcat.txt').read_text();(E/'physical-native-load.txt').write_text(log);assert 'GGUF_SINGLE_FILE_LOADED same_path=1' in log and 'GGUF_PROJECTOR_WEIGHTS backend=Vulkan' in log
        checks['same_file_language_projector_visual_inference_vulkan']='PASS'
        external=independent_single();assert tensor_hashes(external)==expected
        if observer:d.progress_observer=ProgressObserver(d,'single-vision')
        foreign=d.import_model(external);assert foreign['path']==foreign.get('mmprojPath') and foreign['multimodal'] and foreign['capability']=='VISION_SINGLE_GGUF'
        if observer:checks['measured_single_vision_progress']=d.progress_observer.finish([external.stat().st_size],vision=True);d.progress_observer=None
        assert d.shell('sha256sum '+shlex.quote(foreign['path'])).split()[0]==hashlib.sha256(external.read_bytes()).hexdigest()
        chat=d.new_chat(foreign,99,context_size=4096);attach(d,chat,['frame-b.jpg'])
        answer=reply(d,chat,'Name the main vehicle in the image. Reply in English.','external-single-file',images=1);assert 'bus' in answer.lower(),answer
        checks['independent_external_format_single_file_import_and_inference']='PASS'
        # Actual language weights under a misleading filename do not acquire an eye.
        normal_file=C/'mmproj-fake-vision-name.gguf';shutil.copyfile('.cache/mobile-models/SmolLM2-135M-Instruct-Q4_K_M.gguf',normal_file)
        if observer:d.progress_observer=ProgressObserver(d,'single-text')
        normal=d.import_model(normal_file);assert not normal.get('mmprojPath') and not normal['multimodal'] and normal['capability']=='TEXT_ONLY'
        if observer:checks['measured_single_text_progress']=d.progress_observer.finish([normal_file.stat().st_size]);d.progress_observer=None
        d.capture('physical-normal-no-eye.png');checks['parameter_detection_not_filename']='PASS'
        global_text='You are a helpful assistant. Reply in English. Reference code: ORCHID-5291.'
        custom='You are a helpful assistant. Reply in English. Reference code: CEDAR-8624.'
        edit_prompt(d,global_text,global_prompt=True)
        chat=d.new_chat(normal,0);reply(d,chat,'What is the reference code?','system-global')
        log=(E/'inference-system-global-logcat.txt').read_text();assert 'scope=global' in log and hashlib.sha256(global_text.encode()).hexdigest() in log
        edit_prompt(d,custom)
        saved=next(c for c in d.read_json('chats.json') if c['id']==chat['id']);assert saved['systemPrompt']==custom
        d.launch();d.open_existing_chat(chat['title']);saved=next(c for c in d.read_json('chats.json') if c['id']==chat['id']);assert saved['systemPrompt']==custom
        reply(d,chat,'What is the reference code now?','system-chat')
        log=(E/'inference-system-chat-logcat.txt').read_text();assert 'scope=chat' in log and hashlib.sha256(custom.encode()).hexdigest() in log
        checks['system_global_override_json_restart_and_generation']='PASS'
        # Preserve the actual semantic result independently from plumbing assertions.
        quality={}
        for stage,code in [('system-global','ORCHID-5291'),('system-chat','CEDAR-8624')]:
            text=(E/f'inference-{stage}-reply.txt').read_text();quality[stage]={'status':'PASS' if code in text else 'FAIL','response':text}
        (E/'system-response-quality.json').write_text(json.dumps(quality,ensure_ascii=False,indent=2));summary['system_response_quality']=quality
        edit_prompt(d,'',reset=True);assert next(c for c in d.read_json('chats.json') if c['id']==chat['id']).get('systemPrompt') is None
        edit_prompt(d,'',global_prompt=True,reset=True);checks['system_reset_to_global_and_default']='PASS'
        # Delete first unit via real UI; preserve independent import and normal file.
        d.launch();d.tap(text='Importar',contains=True,package={PACKAGE});before=d.read_json('models.json');d.tap(text='Excluir',package={PACKAGE});d.tap(resource_id='android:id/button1',package={PACKAGE})
        after=d.wait(lambda:(lambda r:r if len(r)==len(before)-1 else None)(d.read_json('models.json')),'exclusão de arquivo único')
        removed=next(m for m in before if m['id'] not in {r['id'] for r in after});assert d.shell('test -e '+shlex.quote(removed['path'])+'; echo $?')=='1'
        for m in after:assert d.shell('test -f '+shlex.quote(m['path'])+'; echo $?')=='0'
        checks['single_file_scoped_delete']='PASS';summary['status']='PASS'
        (E/'physical-models.json').write_text(json.dumps(after,ensure_ascii=False,indent=2))
    except Exception as ex:
        summary['error']=str(ex);traceback.print_exc();(E/'physical-failure.txt').write_text(traceback.format_exc()+'\n'+(E/'commands.log').read_text()[-18000:])
    finally:
        (E/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False))
        try:d.capture('physical-final.png');(E/'physical-final-logcat.txt').write_text(d.adb('logcat','-d'))
        except Exception:pass
    raise SystemExit(0 if summary['status']=='PASS' else 1)
if __name__=='__main__':main()
