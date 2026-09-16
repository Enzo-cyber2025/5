"""Real pixel decode + real unified-model inference with missing image metadata."""
import json,hashlib
from pathlib import Path
from test_mobile import MODEL,PROJ,select_pair
from test_inference_android import fixtures,attach,reply,F,item_state
from test_latency_android import wait_ready
from android_checks import PACKAGE,position
E=Path('evidence')
def pixels(d):
    pkg='com.ggufchat.codetest'
    start=d.shell('am start -W -n '+pkg+'/.ImageActivity');assert 'Status: ok' in start,start
    d.wait(lambda:position(d.ui(),text='Imagens OK:',contains=True,package={pkg}),'actual Android decoder cases')
    log=d.adb('logcat','-d');assert 'IMAGE_DECODER_PASS' in log
    (E/'physical-image-decoder-log.txt').write_text('\n'.join(x for x in log.splitlines() if 'GGUFImageTest' in x))
    d.capture('physical-image-decoder.png');d.shell('am force-stop '+pkg)
def inference(d):
    d.launch();d.shell('mkdir -p /sdcard/Download')
    for f in (MODEL,PROJ):d.adb('push',f,'/sdcard/Download/'+f.name,timeout=300)
    select_pair(d)
    # A fresh library has no models.json until the asynchronous import finishes.
    # Only absent storage is temporarily empty; malformed JSON/ADB errors still fail.
    model=d.wait(lambda:next((m for m in d.read_json('models.json',optional=True) if m.get('capability')=='VISION_SINGLE_GGUF'),None),'physical unified visual model',timeout=600)
    fixtures();source=F/'frame-a.jpg';alias=F/'foto-sem-extensao';alias.write_bytes(source.read_bytes())
    chat=d.new_chat(model,0,context_size=4096)
    # Simulate an existing chat missing its redundant mmprojPath; actual physical
    # encoder tensors remain in the real GGUF. No generated answer is injected.
    d.shell('am force-stop '+PACKAGE);chats=d.read_json('chats.json')
    for row in chats:
        if row['id']==chat['id']:row['mmprojPath']=None;chat=row
    d.write_private('files/chats.json',json.dumps(chats));d.launch();d.open_existing_chat(chat['title']);wait_ready(d)
    attach(d,chat,[alias.name]);items=item_state(d,chat)
    # Explicitly simulate a provider omitting MIME. The input bytes were really
    # copied through SAF and their hash verified by attach(). Only metadata changes.
    items['items'][0]['mime']='application/octet-stream'
    key=hashlib.sha256(chat['id'].encode()).hexdigest()
    d.write_private('files/attachments/'+key+'/index.json',json.dumps(items))
    answer=reply(d,chat,'Name the main animal in the image. Reply in English.','unknown-image-metadata',images=1)
    assert 'dog' in answer.lower(),answer
    log=d.adb('logcat','-d',f'--pid={d.alive()}');assert 'GGUF_IMAGE_PREPARED' in log and 'decoder=ImageDecoder' in log
    report=dict(status='PASS',source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),response=answer,scope='Real SAF bytes, explicit missing-MIME/legacy-chat metadata simulation, actual pixel encoding and model inference; no response/metric injection.')
    (E/'physical-image-metadata-inference.json').write_text(json.dumps(report,indent=2))
    return report
