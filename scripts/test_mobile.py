#!/usr/bin/env python3
"""Real SAF multi-selection, persisted pair, compact tools and native generation.
Requires a disposable emulator. No injected model database or simulated inference.
"""
import hashlib,json,os,re,shlex,time,traceback
from pathlib import Path
import xml.etree.ElementTree as ET
from test_android import Android
from android_checks import PACKAGE,PICKERS,position,has_package,fusion,assistant_reply,generation_completed,vulkan_offloaded,basic_response_quality

EVIDENCE=Path('evidence')
MODEL=Path('.cache/mobile-models/SmolVLM-256M-Instruct-Q8_0.gguf')
PROJ=Path('.cache/mobile-models/mmproj-SmolVLM-256M-Instruct-Q8_0.gguf')
APK=Path(os.environ.get('GGUF_TEST_APK','.delivery/GGUF-Chat-mobile.apk'))
VULKAN=os.environ.get('GGUF_MOBILE_VULKAN')=='1'


class MobileAndroid(Android):
    """Driver destes testes: o retry de dump vazio vive na classe base.

    DocumentsUI às vezes responde sucesso sem produzir dump enquanto a janela
    transiciona; `Android.ui` repete a coleta nesse caso (nunca reaproveita XML
    antigo, nunca trata como falha do aplicativo). Antes o retry existia só aqui,
    e um teste que usava a classe base — o de anexos — reprovou a rodada
    36026742459 com `ParseError: syntax error: line 1, column 0`.
    """


def unified_pair(models, vision_name, projector_name):
    assert len(models)==1,'A seleção ainda está armazenada como mais de um modelo'
    m=models[0]
    assert m.get('fileName')==vision_name and m.get('id') and m.get('path')
    assert m.get('multimodal') is True and m.get('mmprojPath')
    assert m['mmprojPath'].endswith(projector_name) and m['path']!=m['mmprojPath']
    assert m['size']==MODEL.stat().st_size+PROJ.stat().st_size,'Tamanho não soma os componentes'
    return m['id'],m['path'],m['mmprojPath']


def bounds(n):
    import re
    return list(map(int,re.findall(r'\d+',n.get('bounds',''))))


def select_pair(d):
    d.tap(text='Importar',package={PACKAGE})
    d.tap(text='Importar GGUF',contains=True,package={PACKAGE})
    d.wait(lambda:has_package(d.ui(),PICKERS),'SAF aberto')
    # Navigate the actual document provider, never inject an import intent.
    for _ in range(6):
        xml=d.ui()
        if position(xml,text=MODEL.name,package=PICKERS) and not any(position(xml,text=t,package=PICKERS) for t in ('Open from','Abrir de')):break
        if not any(position(xml,text=t,package=PICKERS) for t in ('Open from','Abrir de')):
            d.tap(desc='Show roots',package=PICKERS,optional=True)
        d.select_downloads();time.sleep(1)
    # Recent can include UI-dump XML, so select only the two actual GGUFs.
    from android_checks import select_exact_documents
    d.tap(desc='List view',package=PICKERS,optional=True)
    select_exact_documents(d,[MODEL.name,PROJ.name])
    d.capture('saf-two-selected.png')
    # Select is the toolbar action. Do not hit a row's accessibility Open icon.
    d.tap(text='Select',package=PICKERS)
    observer=getattr(d,'progress_observer',None)
    if observer:
        # Actual worker events prove the SAF result reached the app; do not block
        # the first screenshot on uiautomator's accessibility-idle wait.
        d.wait(lambda:observer.poll() or bool(observer.events),'progresso real após seleção SAF')
    else:d.wait(lambda:not has_package(d.ui(),PICKERS),'retorno da seleção SAF')


def main():
    d=MobileAndroid('emulator-5554',EVIDENCE)
    summary={'status':'FAIL','scope':'single-stored-unit-SAF-eye-Vulkan-projector-text','checks':{},'apk_sha256':hashlib.sha256(APK.read_bytes()).hexdigest()}
    try:
        assert d.shell('getprop ro.kernel.qemu')=='1'
        d.adb('root',check=False);d.adb('wait-for-device',timeout=60)
        assert d.shell('id -u')=='0'
        d.shell('wm size 720x1280');d.shell('wm density 240')
        d.shell('pm disable-user --user 0 com.google.android.apps.nexuslauncher',check=False)
        d.adb('logcat','-G','16M')
        if VULKAN:
            d.shell('setprop debug.gguf.vulkan_device 0')
            for name,command in (('vulkan-device.json','cmd gpu vkjson'),('vulkan-features.txt','pm list features')):
                (EVIDENCE/name).write_text(d.shell(command,check=False))
            summary['backend_requested']='Vulkan, 99 language layers requested; projector weights also Vulkan'
            summary['environment']='Android Vulkan through Mesa software driver, not physical GPU'
            assert summary['apk_sha256']==json.loads(Path('.delivery/mobile-signed.json').read_text())['apk_sha256'],'APK differs from signed build provenance'

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
            try:return unified_pair(models,MODEL.name,PROJ.name)
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
        assert position(xml,text='Visão',contains=True,package={PACKAGE}),'Unidade multimodal sem olho'
        summary['checks']['single_stored_unit_and_eye']='PASS'
        d.capture('import.png');d.launch()
        assert linked()==pair
        summary['checks']['pair_survives_restart']='PASS'
        d.adb('logcat','-c')
        chat=d.new_chat(model,99 if VULKAN else 0);pid=d.alive()
        assert chat.get('mmprojPath')==model['mmprojPath'],'Conversa perdeu o projetor associado'
        def loaded():
            assert d.alive()==pid,'Processo substituído durante carregamento'
            log=d.adb('logcat','-d',f'--pid={pid}')
            (EVIDENCE/'mobile-logcat.txt').write_text(log)
            if 'Create failed:' in log or 'Fatal signal' in log:raise AssertionError('Falha no carregamento nativo: '+log[-5000:])
            return 'GGUF_PROJECTOR_LOADED vision=1' in log and 'projector=loaded' in log
        d.wait(loaded,'GGUF e mmproj carregados pelo mtmd real',timeout=300)
        summary['checks']['native_model_and_projector_load']='PASS'
        if VULKAN:
            log=(EVIDENCE/'mobile-logcat.txt').read_text()
            assert vulkan_offloaded(log),'Latest model load did not offload layers to Vulkan; CPU fallback is not success'
            assert re.search(r'GGUF_PROJECTOR_WEIGHTS backend=Vulkan\w* bytes=[1-9]\d* tensors=[1-9]\d*',log),'Pesos do projetor não carregados no Vulkan'
            assert 'GGUF_UNIT_LOADED language=Vulkan' in log and 'projector=Vulkan' in log
            summary['checks']['vulkan_language_and_projector_weights']='PASS'

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
        if VULKAN:
            log=(EVIDENCE/'mobile-logcat.txt').read_text()
            assert vulkan_offloaded(log),'Generation used a CPU fallback load'
            (EVIDENCE/'vulkan-backend.txt').write_text('\n'.join(line for line in log.splitlines() if re.search(r'vulkan|offload|GGUF_NATIVE_COMPLETE|GGUF_PROJECTOR',line,re.I)))
            summary['offload_records']=re.findall(r'offloaded\s+\d+(?:/\d+)?\s+layers?\s+to\s+GPU',log,re.I)
            # A second actual send must produce a NEW native completion and a
            # persisted response after its own exact prompt, not a stale marker.
            previous_completions=log.count('GGUF_NATIVE_COMPLETE')
            question='Reply in English: What is two plus two?'
            d.send(question,clear_log=False)
            def second_done():
                assert d.alive()==pid,'Process died or restarted during second generation'
                current=d.adb('logcat','-d',f'--pid={pid}')
                (EVIDENCE/'vulkan-final-logcat.txt').write_text(current)
                if not generation_completed(current) or current.count('GGUF_NATIVE_COMPLETE')<=previous_completions:return None
                assert vulkan_offloaded(current)
                chats=d.read_json('chats.json')
                (EVIDENCE/'vulkan-chats.json').write_text(json.dumps(chats,ensure_ascii=False))
                try:return assistant_reply(chats,chat['id'],question)
                except AssertionError:return None
            second=d.wait(second_done,'second Vulkan response persisted with new native completion',timeout=600)
            (EVIDENCE/'vulkan-reply.txt').write_text(second);d.capture('vulkan-reply.png')
            summary['checks']['second_vulkan_generation']='PASS'
            try:
                basic_response_quality(reply,second)
                summary['checks']['basic_response_quality']='PASS'
            except AssertionError as e:
                summary['checks']['basic_response_quality']='FAIL: '+str(e)

        # Reimport through SAF with older same-named records present. Only the
        # current selection may be associated; existing pairs must not change.
        previous={m['id']:m for m in d.read_json('models.json')}
        d.launch();select_pair(d)
        def relinked():
            models=d.read_json('models.json')
            fresh=[m for m in models if m['id'] not in previous]
            try: result=unified_pair(fresh,MODEL.name,PROJ.name)
            except AssertionError:return None
            for m in models:
                if m['id'] in previous:assert m==previous[m['id']],'Reimportação alterou um registro anterior'
            (EVIDENCE/'mobile-reimport-models.json').write_text(json.dumps(models,ensure_ascii=False))
            return result
        d.wait(relinked,'reimportação associa somente os dois novos arquivos',timeout=600)
        xml=d.ui();assert sum(n.get('text')=='Excluir' for n in ET.fromstring(xml).iter('node'))==2
        d.capture('reimport.png')
        summary['checks']['repeat_saf_import_keeps_pairs_separate']='PASS'
        # A standalone language import must remain a distinct normal model,
        # even if the GGUF metadata happens to mention a vision architecture.
        normal_source=Path('.cache/mobile-models/SmolLM2-135M-Instruct-Q4_K_M.gguf')
        normal=d.import_model(normal_source)
        assert not normal.get('mmprojPath') and not normal.get('multimodal')
        assert normal['size']==normal_source.stat().st_size
        xml=d.ui()
        labels=[n.get('text','') for n in ET.fromstring(xml).iter('node') if normal['name'] in n.get('text','')]
        assert labels and all('Visão' not in label for label in labels),'Modelo normal recebeu olho'
        d.capture('normal-no-eye.png')
        summary['checks']['normal_model_without_eye']='PASS'
        # Delete one unit through the actual dialog; both files disappear, while
        # the reimported unit and standalone model remain intact.
        before_delete=d.read_json('models.json')
        d.tap(text='Excluir',package={PACKAGE})
        d.tap(resource_id='android:id/button1',package={PACKAGE})
        remaining=d.wait(lambda: (lambda rows: rows if len(rows)==len(before_delete)-1 else None)(d.read_json('models.json')),'exclusão da unidade persistida')
        removed=next(m for m in before_delete if m['id'] not in {r['id'] for r in remaining})
        assert removed.get('mmprojPath'),'Excluiu modelo errado, não a unidade multimodal'
        for path in (removed['path'],removed['mmprojPath']):
            assert d.shell('test -e '+shlex.quote(path)+'; echo $?')=='1','Componente órfão após exclusão'
        for m in remaining:
            for path in (m['path'],m.get('mmprojPath')):
                if path:assert d.shell('test -f '+shlex.quote(path)+'; echo $?')=='0','Exclusão atingiu outro modelo'
        (EVIDENCE/'unified-after-delete.json').write_text(json.dumps(remaining,ensure_ascii=False))
        d.capture('unified-after-delete.png')
        summary['checks']['delete_unit_removes_both_preserves_others']='PASS'
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
