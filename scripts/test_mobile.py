#!/usr/bin/env python3
"""Real SAF multi-selection, persisted pair, compact tools and native generation.
Requires a disposable emulator. No injected model database or simulated inference.
"""
import hashlib,json,shlex,time,traceback
from pathlib import Path
import xml.etree.ElementTree as ET
from test_android import Android
from android_checks import PACKAGE,PICKERS,position,has_package,fusion,assistant_reply,generation_completed

EVIDENCE=Path('evidence')
MODEL=Path('.cache/mobile-models/SmolVLM-256M-Instruct-Q8_0.gguf')
PROJ=Path('.cache/mobile-models/mmproj-SmolVLM-256M-Instruct-Q8_0.gguf')
APK=Path('.delivery/GGUF-Chat-mobile.apk')


class MobileAndroid(Android):
    def ui(self):
        # DocumentsUI sometimes returns success without producing a dump while
        # its window is transitioning. Retry collection, never a native crash,
        # never a send action, and never reuse a previous XML file.
        for attempt in range(3):
            try:return super().ui()
            except ET.ParseError:
                if attempt==2:raise
                self.alive()
                time.sleep(0.5)


def bounds(n):
    import re
    return list(map(int,re.findall(r'\d+',n.get('bounds',''))))


def select_pair(d):
    d.tap(text='Importar',contains=True,package={PACKAGE})
    d.tap(text='Importar .gguf',contains=True,package={PACKAGE})
    d.wait(lambda:has_package(d.ui(),PICKERS),'SAF aberto')
    # Navigate the actual document provider, never inject an import intent.
    for _ in range(6):
        xml=d.ui()
        if position(xml,text=MODEL.name,package=PICKERS) and not any(position(xml,text=t,package=PICKERS) for t in ('Open from','Abrir de')):break
        if not any(position(xml,text=t,package=PICKERS) for t in ('Open from','Abrir de')):
            d.tap(desc='Show roots',package=PICKERS,optional=True)
        d.select_downloads();time.sleep(1)
    xml=d.ui();p=position(xml,text=MODEL.name,package=PICKERS)
    assert p,'Modelo real não visível no seletor'
    d.shell(f'input touchscreen swipe {p[0]} {p[1]} {p[0]} {p[1]} 1000')
    d.tap(text=PROJ.name,package=PICKERS)
    assert d.confirm_picker(d.ui()),'Botão de confirmar seleção múltipla não encontrado'
    d.wait(lambda:not has_package(d.ui(),PICKERS),'retorno da seleção SAF')


def main():
    d=MobileAndroid('emulator-5554',EVIDENCE)
    summary={'status':'FAIL','scope':'saf-pair-load-text-generation','checks':{},'apk_sha256':hashlib.sha256(APK.read_bytes()).hexdigest()}
    try:
        assert d.shell('getprop ro.kernel.qemu')=='1'
        d.adb('root',check=False);d.adb('wait-for-device',timeout=60)
        assert d.shell('id -u')=='0'
        d.shell('wm size 720x1280');d.shell('wm density 240')
        d.shell('pm disable-user --user 0 com.google.android.apps.nexuslauncher',check=False)
        d.adb('logcat','-G','16M')
        d.adb('install','-r','-g',APK,timeout=180)
        assert d.shell(f'pm clear {PACKAGE}')=='Success'
        d.grant_test_notifications();d.launch();d.capture('launch.png')
        d.shell('mkdir -p /sdcard/Download')
        for p in (MODEL,PROJ):
            d.adb('push',p,'/sdcard/Download/'+p.name,timeout=300)
            d.shell('am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d '+shlex.quote('file:///sdcard/Download/'+p.name),check=False)
        select_pair(d)
        def linked():
            d.alive()
            models=d.read_json('models.json',optional=True)
            (EVIDENCE/'mobile-models.json').write_text(json.dumps(models,ensure_ascii=False))
            try:return fusion(models,MODEL.name,PROJ.name)
            except AssertionError:return None
        pair=d.wait(linked,'par GGUF/mmproj associado após importação real',timeout=600)
        summary['checks']['saf_multiselect_pair']='PASS'
        models=d.read_json('models.json')
        model=next(m for m in models if m.get('fileName')==MODEL.name)
        for p,path in ((MODEL,model['path']),(PROJ,model['mmprojPath'])):
            assert d.shell('sha256sum '+shlex.quote(path)).split()[0]==hashlib.sha256(p.read_bytes()).hexdigest()
        summary['checks']['imported_sha256']='PASS'
        xml=d.ui()
        deletes=[n for n in ET.fromstring(xml).iter('node') if n.get('text')=='Excluir']
        assert len(deletes)==1,'Par associado ainda aparece como dois cartões'
        assert position(xml,text='GGUF + mmproj',contains=True,package={PACKAGE})
        summary['checks']['unified_model_card']='PASS'
        d.capture('import.png');d.launch()
        assert linked()==pair
        summary['checks']['pair_survives_restart']='PASS'
        d.adb('logcat','-c')
        chat=d.new_chat(model,0);pid=d.alive()
        assert chat.get('mmprojPath')==model['mmprojPath'],'Conversa perdeu o projetor associado'
        def loaded():
            assert d.alive()==pid,'Processo substituído durante carregamento'
            log=d.adb('logcat','-d',f'--pid={pid}')
            (EVIDENCE/'mobile-logcat.txt').write_text(log)
            if 'Create failed:' in log or 'Fatal signal' in log:raise AssertionError('Falha no carregamento nativo: '+log[-5000:])
            return 'GGUF_PROJECTOR_LOADED vision=1' in log and 'projector=loaded' in log
        d.wait(loaded,'GGUF e mmproj carregados pelo mtmd real',timeout=300)
        summary['checks']['native_model_and_projector_load']='PASS'
        xml=d.ui()
        assert position(xml,desc='Alternar ferramentas',package={PACKAGE})
        for label in ('Thinking','Foto','Vídeo','Áudio','Arquivo','Ferramentas'):
            assert not position(xml,text=label,package={PACKAGE}),label+' exposto antes do botão'
        d.capture('tools-collapsed.png')
        d.tap(desc='Alternar ferramentas',package={PACKAGE})
        xml=d.ui();root=ET.fromstring(xml)
        rows=[n for n in root.iter('node') if n.get('class')=='android.widget.HorizontalScrollView' and n.get('content-desc')=='Ferramentas da conversa']
        assert len(rows)==1,'Ferramentas não estão numa linha rolável'
        buttons=[n for n in rows[0].iter('node') if n.get('class')=='android.widget.Button' and len(bounds(n))==4]
        assert len(buttons)>=3
        ys={(bounds(n)[1],bounds(n)[3]) for n in buttons}
        assert len(ys)==1,'Ferramentas quebraram linha'
        for left,right in zip(buttons,buttons[1:]):
            a,b=bounds(left),bounds(right)
            if a[2]<700 and b[2]<700:assert b[0]-a[2]==10,(a,b)
        for n in buttons:assert bounds(n)[3]-bounds(n)[1]<=55,'Botão não foi reduzido'
        d.capture('tools-expanded.png')
        d.tap(desc='Alternar ferramentas',package={PACKAGE})
        assert not position(d.ui(),text='Foto',package={PACKAGE})
        summary['checks']['compact_single_row_10px_toggle']='PASS'
        prompt='Reply in English with a short greeting.'
        d.send(prompt,clear_log=False)
        def completed():
            assert d.alive()==pid,'Processo morreu durante geração'
            log=d.adb('logcat','-d',f'--pid={pid}')
            (EVIDENCE/'mobile-logcat.txt').write_text(log)
            chats=d.read_json('chats.json');(EVIDENCE/'mobile-chats.json').write_text(json.dumps(chats,ensure_ascii=False))
            if not generation_completed(log):return None
            assert 'GGUF_NATIVE_COMPLETE' in log and 'projector=1' in log
            try:return assistant_reply(chats,chat['id'],prompt)
            except AssertionError:return None
        reply=d.wait(completed,'resposta nativa concluída e salva',timeout=600)
        (EVIDENCE/'mobile-reply.txt').write_text(reply);d.capture('mobile-reply.png')
        summary['checks']['native_generation_and_persistence']='PASS'
        summary['generation_pid']=pid
        # Reimport through SAF with older same-named records present. Only the
        # current selection may be associated; existing pairs must not change.
        previous={m['id']:m for m in d.read_json('models.json')}
        d.launch();select_pair(d)
        def relinked():
            models=d.read_json('models.json')
            fresh=[m for m in models if m['id'] not in previous]
            try: result=fusion(fresh,MODEL.name,PROJ.name)
            except AssertionError:return None
            for m in models:
                if m['id'] in previous:assert m==previous[m['id']],'Reimportação alterou um registro anterior'
            (EVIDENCE/'mobile-reimport-models.json').write_text(json.dumps(models,ensure_ascii=False))
            return result
        d.wait(relinked,'reimportação associa somente os dois novos arquivos',timeout=600)
        xml=d.ui();assert sum(n.get('text')=='Excluir' for n in ET.fromstring(xml).iter('node'))==2
        d.capture('reimport.png')
        summary['checks']['repeat_saf_import_keeps_pairs_separate']='PASS'
        summary['checks']['physical_A55']='NOT_TESTED: emulator x86_64 is not Samsung ARM64 hardware'
        summary['checks']['image_inference']='NOT_TESTED: model/projector load and text message only'
        summary['status']='PASS'
    except Exception as e:
        summary['error']=str(e);traceback.print_exc()
        commands=EVIDENCE/'commands.log'
        (EVIDENCE/'failure-context.txt').write_text(traceback.format_exc()+'\n'+(commands.read_text()[-20000:] if commands.exists() else ''))
    finally:
        try:
            (EVIDENCE/'final-logcat.txt').write_text(d.adb('logcat','-d'))
            d.capture('final-screen.png')
        except Exception:pass
        (EVIDENCE/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False))
        print(json.dumps(summary,ensure_ascii=False))
    raise SystemExit(0 if summary['status']=='PASS' else 1)
if __name__=='__main__':main()
