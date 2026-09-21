#!/usr/bin/env python3
"""Real DocumentsUI and external camera, after the signed APK's model/Vulkan suite."""
import base64,hashlib,json,re,shlex,struct,traceback,zipfile
from pathlib import Path
import xml.etree.ElementTree as ET
from test_mobile import MobileAndroid,APK
from android_checks import PACKAGE,PICKERS,position,has_package,generation_completed

E=Path('evidence')
CAMERAS={'com.android.camera2','com.android.camera','com.google.android.GoogleCamera'}


def item_state(d,chat):
    key=hashlib.sha256(chat['id'].encode()).hexdigest()
    state=d.read_json('attachments/'+key+'/index.json',optional=True)
    return state if isinstance(state,dict) else {'items':[],'error':''}


def wait_items(d,chat,count):
    def check():
        d.alive();state=item_state(d,chat)
        if state.get('error'):raise AssertionError(state['error'])
        return state if len(state['items'])==count else None
    return d.wait(check,'anexos copiados e persistidos: '+str(count),timeout=240)


def controls(d,multimodal):
    root=ET.fromstring(d.ui());nodes=list(root.iter('node'))
    camera=next(n for n in nodes if n.get('content-desc')=='Câmera')
    clip=next(n for n in nodes if n.get('content-desc')=='Anexar arquivos')
    text=next(n for n in nodes if n.get('class')=='android.widget.EditText')
    bounds=lambda n:list(map(int,re.findall(r'\d+',n.get('bounds',''))))
    a,b,c=map(bounds,(camera,clip,text))
    assert a[2]<=b[0]<b[2]<=c[0],'Ícones não estão à esquerda do campo'
    assert camera.get('enabled')==str(multimodal).lower()
    assert clip.get('enabled')=='true'
    return {'camera_bounds':a,'clip_bounds':b,'input_bounds':c,'camera_enabled':multimodal}


def select_all(d,names):
    d.wait(lambda:has_package(d.ui(),PICKERS),'gerenciador de arquivos aberto')
    for _ in range(5):
        xml=d.ui()
        if all(position(xml,text=name,package=PICKERS) for name in names):break
        if position(xml,text='attachment-tests',package=PICKERS):
            d.tap(text='attachment-tests',package=PICKERS)
        else:
            d.tap(desc='Show roots',package=PICKERS,optional=True)
            d.select_downloads()
    xml=d.ui()
    assert all(position(xml,text=name,package=PICKERS) for name in names),'Arquivos de teste não apareceram no seletor'
    d.tap(desc='List view',package=PICKERS,optional=True)
    from android_checks import select_exact_documents
    select_exact_documents(d,names)
    d.capture('attachments-saf-selected.png')
    d.tap(text='Select',package=PICKERS)
    d.wait(lambda:not has_package(d.ui(),PICKERS),'resultado de seleção múltipla')


def jpeg_size(data):
    assert data[:2]==b'\xff\xd8','Câmera não salvou JPEG'
    pos=2
    while pos<len(data):
        if data[pos]!=255:pos+=1;continue
        while data[pos]==255:pos+=1
        marker=data[pos];pos+=1
        if marker in (0xd8,0xd9) or 0xd0<=marker<=0xd7:continue
        size=struct.unpack_from('>H',data,pos)[0]
        if marker in (0xc0,0xc1,0xc2):
            h,w=struct.unpack_from('>HH',data,pos+3);return w,h
        pos+=size
    raise AssertionError('Dimensões JPEG ausentes')


def take_photo(d):
    def ready():
        xml=d.ui()
        if has_package(xml,CAMERAS):return xml
        for text in ('While using the app','Only this time','Allow','OK','Next','No thanks','No, thanks'):
            if position(xml,text=text):d.tap(text=text);return None
        return None
    d.wait(ready,'aplicativo real da câmera',timeout=90)
    for _ in range(8):
        xml=d.ui();point=None
        for rid in ('com.android.camera2:id/shutter_button','com.android.camera:id/shutter_button','com.google.android.GoogleCamera:id/shutter_button'):
            point=position(xml,resource_id=rid,package=CAMERAS)
            if point:break
        if not point:
            for desc in ('Shutter','Take photo','Capture','Capture photo'):
                point=position(xml,desc=desc,package=CAMERAS)
                if point:break
        if point:
            d.shell(f'input tap {point[0]} {point[1]}');break
        advanced=False
        for text in ('Next','OK','No thanks','No, thanks','Got it','Allow','While using the app','Only this time'):
            if position(xml,text=text):d.tap(text=text);advanced=True;break
        if not advanced:raise AssertionError('Obturador da câmera não encontrado')
    else:raise AssertionError('Câmera não ficou pronta')
    d.capture('attachments-camera-preview.png')
    def returned():
        xml=d.ui()
        if position(xml,text='Foto adicionada à fila',package={PACKAGE}):return True
        for desc in ('Done','Review done','Confirm','Save'):
            point=position(xml,desc=desc,package=CAMERAS)
            if point:d.shell(f'input tap {point[0]} {point[1]}');return None
        for rid in ('com.android.camera2:id/done_button','com.android.camera2:id/btn_done','com.android.camera:id/btn_done'):
            point=position(xml,resource_id=rid,package=CAMERAS)
            if point:d.shell(f'input tap {point[0]} {point[1]}');return None
        return None
    d.wait(returned,'foto completa confirmada pela câmera',timeout=90)


def main():
    d=MobileAndroid('emulator-5554',E)
    summary=json.loads((E/'summary.json').read_text())
    summary['status']='FAIL';summary['attachment_checks']={};checks=summary['attachment_checks']
    summary['attachment_scope']='real SAF multi-file/photo selection, external camera, persistence, removal and message binding; storage regression plus explicit unsupported-format failure; content inference tested separately'
    try:
        assert hashlib.sha256(APK.read_bytes()).hexdigest()==summary['apk_sha256']
        models=d.read_json('models.json');paired=next(m for m in models if m.get('mmprojPath'));normal=next(m for m in models if not m.get('mmprojPath'))
        fixture=E/'attachment-fixtures';fixture.mkdir(exist_ok=True)
        png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=')
        for name in ('photo-a.png','photo-b.png'):(fixture/name).write_bytes(png)
        (fixture/'note.txt').write_text('attachment contents are stored, not injected into the model\n')
        (fixture/'zero.custom').write_bytes(b'')
        with zipfile.ZipFile(fixture/'archive.zip','w') as archive:archive.writestr('note.txt','Real ZIP fixture')
        with (fixture/'large.unknown').open('wb') as out:
            for _ in range(128):out.write(bytes(range(256))*256) # 8 MiB; not a size ceiling
        d.shell('mkdir -p /sdcard/Download/attachment-tests')
        hashes={}
        for file in fixture.iterdir():
            hashes[file.name]=hashlib.sha256(file.read_bytes()).hexdigest()
            dest='/sdcard/Download/attachment-tests/'+file.name
            d.adb('push',file,dest)
            d.shell('am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d '+shlex.quote('file://'+dest),check=False)
        chat=d.new_chat(paired,0) # UI/storage suite; preceding suite already tested the same APK via Vulkan.
        checks['multimodal_controls']=controls(d,True);d.capture('attachments-multimodal.png')
        d.tap(desc='Câmera',package={PACKAGE});xml=d.ui()
        assert position(xml,text='Importar foto',package={PACKAGE}) and position(xml,text='Tirar foto',package={PACKAGE})
        d.capture('attachments-camera-menu.png');d.tap(text='Importar foto',package={PACKAGE})
        select_all(d,['photo-a.png','photo-b.png']);wait_items(d,chat,2)
        checks['multiple_photos_from_files']='PASS'
        d.tap(desc='Anexar arquivos',package={PACKAGE});select_all(d,sorted(hashes));state=wait_items(d,chat,8)
        key=hashlib.sha256(chat['id'].encode()).hexdigest()
        for item in state['items']:
            path=f'/data/user/0/{PACKAGE}/files/attachments/{key}/{item["id"]}.data'
            assert d.shell('sha256sum '+shlex.quote(path)).split()[0]==hashes[item['name']]
            assert item['size']==(fixture/item['name']).stat().st_size
        checks['mixed_types_empty_large_and_exact_bytes']='PASS'
        d.capture('attachments-multiple.png');(E/'attachments-draft.json').write_text(json.dumps(state,ensure_ascii=False))
        d.launch();d.open_existing_chat(chat['title']);assert item_state(d,chat)==state
        checks['draft_survives_restart']='PASS'
        # Actual external camera, twice. No injected bitmap/result intent or fake camera.
        d.tap(desc='Câmera',package={PACKAGE});d.tap(text='Tirar foto',package={PACKAGE})
        take_photo(d);d.tap(text='Tirar outra foto',package={PACKAGE});take_photo(d);d.tap(text='Concluir',package={PACKAGE})
        state=wait_items(d,chat,10);photos=[m for m in state['items'] if m['name'].startswith('Foto-')]
        assert len(photos)==2
        dimensions=[]
        for photo in photos:
            path=f'/data/user/0/{PACKAGE}/files/attachments/{key}/{photo["id"]}.data'
            data=d.adb('exec-out','cat',path,binary=True);w,h=jpeg_size(data)
            assert min(w,h)>=480 and max(w,h)>=640,'Câmera retornou apenas miniatura'
            dimensions.append({'width':w,'height':h,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()})
        checks['two_real_camera_photos']=dimensions
        d.capture('attachments-camera-added.png')
        d.tap(desc='Lista de anexos',package={PACKAGE});d.capture('attachments-list.png')
        d.tap(text='zero.custom',contains=True,package={PACKAGE});d.tap(text='Remover',package={PACKAGE})
        state=wait_items(d,chat,9);assert not any(m['name']=='zero.custom' for m in state['items'])
        checks['remove_one_preserves_others']='PASS'
        d.send('Reply with hello.',clear_log=True);pid=d.alive()
        def sent():
            assert d.alive()==pid
            log=d.adb('logcat','-d',f'--pid={pid}');(E/'attachments-logcat.txt').write_text(log)
            error=item_state(d,chat).get('error','')
            if not error:return None
            assert 'não tem leitor' in error,error
            assert 'GGUF_NATIVE_COMPLETE' not in log,'Unsupported archive was silently treated as read'
            rows=item_state(d,chat)['items'];chats=d.read_json('chats.json');saved=next(c for c in chats if c['id']==chat['id'])
            (E/'attachments-sent.json').write_text(json.dumps({'items':rows,'chat':saved},ensure_ascii=False))
            if not rows or any(m['message']<0 for m in rows):return None
            for row in rows:
                msg=saved['messages'][row['message']];assert msg['role']=='user' and 'Reply with hello.' in msg['content']
                assert 'para leitura' in msg['content']
            return {'items':rows,'chat':saved}
        sent_state=d.wait(sent,'nove anexos vinculados à mensagem persistida',timeout=300)
        (E/'attachments-sent.json').write_text(json.dumps(sent_state,ensure_ascii=False));d.capture('attachments-sent.png')
        checks['multiple_attachments_bound_to_message']='PASS'
        checks['unsupported_archive_explicit_error']='PASS'
        # Normal model still offers *all* file formats through the paperclip.
        normal_chat=d.new_chat(normal,0);checks['normal_controls']=controls(d,False);d.capture('attachments-normal.png')
        d.tap(desc='Anexar arquivos',package={PACKAGE});select_all(d,sorted(hashes));normal_state=wait_items(d,normal_chat,6)
        assert len(item_state(d,chat)['items'])==9,'Anexos vazaram entre conversas'
        (E/'attachments-normal.json').write_text(json.dumps(normal_state,ensure_ascii=False))
        d.capture('attachments-normal-files.png');checks['normal_model_multi_file_import']='PASS'
        d.launch()
        point=position(d.ui(),text=normal_chat['title'],package={PACKAGE});assert point
        x,y=point;d.shell(f'input touchscreen swipe {x} {y} {x} {y} 1000')
        d.tap(resource_id='android:id/button1',package={PACKAGE})
        deleted_key=hashlib.sha256(normal_chat['id'].encode()).hexdigest()
        directory=f'/data/user/0/{PACKAGE}/files/attachments/{deleted_key}'
        d.wait(lambda:d.shell('test -e '+shlex.quote(directory)+'; echo $?')=='1','arquivos removidos ao excluir a conversa')
        assert not any(c['id']==normal_chat['id'] for c in d.read_json('chats.json'))
        assert len(item_state(d,chat)['items'])==9
        checks['delete_conversation_cleans_only_its_files']='PASS'
        summary['status']='PASS'
    except Exception as e:
        summary['error']='Attachment test: '+str(e);traceback.print_exc()
        (E/'failure-context.txt').write_text(traceback.format_exc()+'\n'+(E/'commands.log').read_text()[-20000:])
    finally:
        (E/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
        try:d.capture('final-screen.png');(E/'final-logcat.txt').write_text(d.adb('logcat','-d'))
        except Exception:pass
    raise SystemExit(0 if summary['status']=='PASS' else 1)

if __name__=='__main__':main()
