#!/usr/bin/env python3
"""Real SAF -> private bytes -> text extraction / mtmd embeddings -> model replies.
No fake JNI, no injected answer, no subject hint in the image filenames/questions.
"""
import base64,hashlib,json,re,shlex,subprocess,traceback,zipfile,zlib
from pathlib import Path
from test_mobile import MobileAndroid,APK,VULKAN
from test_attachment_android import item_state,wait_items,select_all
from android_checks import PACKAGE,PICKERS,position,has_package,generation_completed
E=Path('evidence')
F=Path('.cache/inference-fixtures')
SOURCES=[('frame-a.jpg','pytorch/hub','12f0e0dd1162b94a5b0919ce8b91821450965985','f3f87bb8ab3c26c7ecfd3ac60421d7f32b0503d1d6c5baf8bac42ed93d86351a'),('frame-b.jpg','ultralytics/yolov5','b43e311165c785f000eb7493ff8fb662d06a3f83','33b198a1d2839bb9ac4c65d61f9e852196793cae9a0781360859425f6022b69c')]

def pdf(path,text=None,image=None):
    # A valid PDF with xref offsets, a compressed content stream and real font/image objects.
    if image:
        from test_attachment_android import jpeg_size
        w,h=jpeg_size(image);data=b'q 500 0 0 650 40 60 cm /Img Do Q'
        resource=b'/XObject << /Img 5 0 R >>'
        fifth=f'<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length {len(image)} >>\nstream\n'.encode()+image+b'\nendstream'
    else:
        data=('BT /F1 16 Tf 50 730 Td ('+text+') Tj ET').encode()
        resource=b'/Font << /F1 5 0 R >>';fifth=b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'
    content=zlib.compress(data)
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Count 1 /Kids [3 0 R] >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << '+resource+b' >> /Contents 4 0 R >>',f'<< /Length {len(content)} /Filter /FlateDecode >>\nstream\n'.encode()+content+b'\nendstream',fifth]
    out=bytearray(b'%PDF-1.4\n');offsets=[0]
    for i,obj in enumerate(objects,1):offsets.append(len(out));out+=f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n'
    start=len(out);out+=b'xref\n0 6\n0000000000 65535 f \n'
    for off in offsets[1:]:out+=f'{off:010} 00000 n \n'.encode()
    out+=f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode();path.write_bytes(out)

def fixtures():
    F.mkdir(parents=True,exist_ok=True)
    for name,repo,blob,digest in SOURCES:
        p=F/name
        if not p.exists():
            result=json.loads(subprocess.check_output(['gh','api',f'repos/{repo}/git/blobs/{blob}']))
            p.write_bytes(base64.b64decode(result['content']))
        assert hashlib.sha256(p.read_bytes()).hexdigest()==digest
    (F/'record.txt').write_text('Verification code: TULIP-6419.\n',encoding='utf-8')
    pdf(F/'record.pdf','Verification code: MAPLE-7382.')
    pdf(F/'scan.pdf',image=(F/'frame-a.jpg').read_bytes())
    with zipfile.ZipFile(F/'record.docx','w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Verification code: SILVER-2857.</w:t></w:r></w:p></w:body></w:document>')
    (F/'oversize.txt').write_text('unrelated text '*12000)
    (F/'broken.jpg').write_bytes(b'Not a JPEG image')

def attach(d,chat,names):
    # Fresh real folder: deleting files with shell does not remove DownloadsProvider's MediaStore rows.
    folder=f'000-read-{999999-d.counter:06d}'
    d.shell('mkdir -p /sdcard/Download/'+folder)
    before=len(item_state(d,chat)['items'])
    for name in names:
        dest='/sdcard/Download/'+folder+'/'+name;d.adb('push',F/name,dest)
        d.shell('am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d '+shlex.quote('file://'+dest),check=False)
    d.tap(desc='Anexar arquivos',package={PACKAGE})
    d.wait(lambda:has_package(d.ui(),PICKERS),'SAF de anexos')
    d.tap(desc='Show roots',package=PICKERS);d.select_downloads()
    d.wait(lambda:position(d.ui(),text=folder,package=PICKERS),'pasta nova no gerenciador')
    d.tap(text=folder,package=PICKERS)
    d.wait(lambda:all(position(d.ui(),text=n,package=PICKERS) for n in names),'arquivos na pasta isolada')
    select_all(d,names)
    state=wait_items(d,chat,before+len(names))
    key=hashlib.sha256(chat['id'].encode()).hexdigest()
    for item in state['items'][before:]:
        actual=d.shell('sha256sum '+shlex.quote(f'/data/user/0/{PACKAGE}/files/attachments/{key}/{item["id"]}.data')).split()[0]
        assert actual==hashlib.sha256((F/item['name']).read_bytes()).hexdigest()

def reply(d,chat,prompt,stage,images=0):
    d.send(prompt);pid=d.alive()
    def check():
        assert d.alive()==pid,'Native process died'
        log=d.adb('logcat','-d',f'--pid={pid}');(E/f'inference-{stage}-logcat.txt').write_text(log)
        if 'Generation failed:' in log:raise AssertionError(log[-8000:])
        error=item_state(d,chat).get('error','')
        if error and not stage.endswith('-recovery'):raise AssertionError(error)
        if not generation_completed(log):return None
        saved=next(c for c in d.read_json('chats.json') if c['id']==chat['id'])
        (E/f'inference-{stage}-chat.json').write_text(json.dumps(saved,ensure_ascii=False))
        users=[i for i,m in enumerate(saved['messages']) if m['role']=='user' and prompt in m['content']]
        if not users:return None
        answers=[m['content'] for m in saved['messages'][users[-1]+1:] if m['role']=='assistant' and m['content'].strip()]
        if not answers:return None
        if images:
            records=re.findall(r'GGUF_IMAGE_EVALUATED tokens=([1-9]\d*) backend=(\w+)',log)
            assert len(records)==images,records
            assert f'GGUF_MEDIA_PREFILL images={images} ' in log
            if VULKAN:assert all(backend=='Vulkan' for _,backend in records)
        else:assert 'GGUF_IMAGE_EVALUATED' not in log
        return answers[-1]
    text=d.wait(check,'resposta baseada no conteúdo real: '+stage,timeout=600)
    (E/f'inference-{stage}-reply.txt').write_text(text);d.capture(f'inference-{stage}.png')
    assert not d.shell(f'find /data/user/0/{PACKAGE}/cache/attachment-inference -type f 2>/dev/null',check=False),'Prepared images leaked'
    return text

def error_case(d,model,name,expected,stage):
    chat=d.new_chat(model,0);attach(d,chat,[name]);d.send('Describe the attached file.');pid=d.alive()
    def failed():
        assert d.alive()==pid
        state=item_state(d,chat)
        return state if expected in state.get('error','') else None
    state=d.wait(failed,'erro explícito sem fingir leitura: '+stage,timeout=180)
    log=d.adb('logcat','-d',f'--pid={pid}');assert 'GGUF_NATIVE_COMPLETE' not in log
    (E/f'inference-{stage}-error.json').write_text(json.dumps(state,ensure_ascii=False));d.capture(f'inference-{stage}.png')
    assert len(state['items'])==1 and state['items'][0]['size']==(F/name).stat().st_size
    # Recovery is a real UI action, including already-bound attachments.
    d.tap(desc='Lista de anexos',package={PACKAGE});d.tap(text=name,contains=True,package={PACKAGE});d.tap(text='Desativar leitura',package={PACKAGE})
    assert item_state(d,chat)['items'][0]['excluded'] is True
    text=reply(d,chat,'Reply in English with hello.',stage+'-recovery')
    assert re.search(r'\b(hello|hi|hey)\b',text,re.I),text
    return 'PASS'

def main():
    d=MobileAndroid('emulator-5554',E);summary=json.loads((E/'summary.json').read_text());summary['status']='FAIL';checks={};summary['content_checks']=checks
    try:
        fixtures();assert hashlib.sha256(APK.read_bytes()).hexdigest()==summary['apk_sha256']
        models=d.read_json('models.json');pair=next(m for m in models if m.get('mmprojPath'));normal=next(m for m in models if not m.get('mmprojPath'))
        layers=99 if VULKAN else 0
        for name,word in [('record.txt','6419'),('record.pdf','7382'),('record.docx','2857')]:
            chat=d.new_chat(normal,0);attach(d,chat,[name]);text=reply(d,chat,'What is the verification code in the attached document? Reply with the code.',name.replace('.','-'))
            assert word in text,(name,text);checks[name]='PASS: '+text
        prompt='Name the main animal or vehicle shown in the image. Reply in English.'
        for name,expected in [('frame-a.jpg',r'\b(dog|samoyed|puppy)\b'),('frame-b.jpg',r'\b(bus|buses)\b')]:
            chat=d.new_chat(pair,layers,context_size=4096);attach(d,chat,[name]);text=reply(d,chat,prompt,name,images=1)
            assert re.search(expected,text,re.I),(name,text);checks[name]='PASS: '+text
            if name=='frame-a.jpg':
                d.launch();d.open_existing_chat(chat['title'])
                second=reply(d,chat,'What animal was in the attached image? Reply in English.','image-after-restart',images=1)
                assert re.search(expected,second,re.I),second;checks['image_history_after_restart']='PASS: '+second
        chat=d.new_chat(pair,layers,context_size=4096);attach(d,chat,['frame-a.jpg','frame-b.jpg'])
        text=reply(d,chat,'Describe the first image and then the second image. Reply in English.','two-images',images=2)
        assert re.search(r'\b(dog|samoyed|puppy)\b',text,re.I) and re.search(r'\bbus\b',text,re.I),text
        checks['two_images']='PASS: '+text
        chat=d.new_chat(pair,layers,context_size=4096);attach(d,chat,['scan.pdf'])
        text=reply(d,chat,prompt,'scanned-pdf',images=1);assert re.search(r'\b(dog|samoyed|puppy)\b',text,re.I),text
        checks['scanned_pdf_visual']='PASS: '+text
        checks['oversize_explicit_no_truncation']=error_case(d,normal,'oversize.txt','orçamento de leitura','oversize')
        checks['invalid_image_explicit']=error_case(d,pair,'broken.jpg','Imagem inválida','broken-image')
        checks['normal_model_image_rejected']=error_case(d,normal,'frame-a.jpg','precisa de modelo','normal-image')
        summary['status']='PASS';summary['content_scope']='Actual TXT/PDF/DOCX contents and actual images evaluated; software Vulkan, not physical GPU. No audio/video transcription.'
    except Exception as ex:
        summary['error']='Content inference: '+str(ex);traceback.print_exc();(E/'inference-failure.txt').write_text(traceback.format_exc()+'\n'+(E/'commands.log').read_text()[-16000:])
    finally:
        (E/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
        try:d.capture('inference-final.png');(E/'inference-final-logcat.txt').write_text(d.adb('logcat','-d'))
        except Exception:pass
    raise SystemExit(0 if summary['status']=='PASS' else 1)
if __name__=='__main__':main()
