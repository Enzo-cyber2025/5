"""Real image upload and per-image detach through the production UI.

The attachment is copied through SAF, the private bytes are hash-verified, the
strip with one detach control per image must be visible, and detaching must
really delete the private copy and the message link (no hidden duplicate). The
model is never asked to describe an image that was detached.
"""
import hashlib
import json
import os
from pathlib import Path

from android_checks import PACKAGE, position
from test_attachment_android import item_state
from test_inference_android import F, attach, fixtures
from test_mobile import MODEL, PROJ, select_pair

E = Path('evidence')


def failure_evidence(d,error):
    try:
        Path('evidence/attachments-detach-failure-ui.txt').write_text(d.ui())
    except Exception as dump_error:
        Path('evidence/attachments-detach-failure-ui.txt').write_text(f'dump falhou: {dump_error}\n')
    Path('evidence/attachments-detach-failure.txt').write_text(f'{type(error).__name__}: {error}\n')
    try:
        Path('evidence/attachments-detach-failure-logcat.txt').write_text(d.adb('logcat','-d')[-200000:])
    except Exception:pass


def run(d):
    try:
        return _run(d)
    except Exception as error:
        failure_evidence(d,error)
        raise


def _run(d):
    E.mkdir(exist_ok=True)
    checks = {}
    d.adb('root', check=False)
    d.adb('wait-for-device', timeout=60)
    # Este teste é sobre anexos, não sobre backend: o dispositivo Vulkan por
    # software do emulador descartável é evitado, como nos outros testes de anexo.
    d.shell('setprop debug.gguf.vulkan_device 0')
    d.launch()
    d.shell('mkdir -p /sdcard/Download')
    for f in (MODEL, PROJ):
        d.adb('push', f, '/sdcard/Download/' + f.name, timeout=300)
    select_pair(d)
    model = d.wait(lambda: next((m for m in d.read_json('models.json', optional=True)
                                 if m.get('capability') == 'VISION_SINGLE_GGUF'), None),
                   'modelo unificado de visão importado por SAF', timeout=600)
    fixtures()
    name = 'imagem-para-desanexar.jpg'
    (F / name).write_bytes((F / 'frame-a.jpg').read_bytes())
    chat = d.new_chat(model, 0, context_size=4096)

    # 1. Upload that really takes effect: real SAF bytes, hash-verified copy.
    attach(d, chat, [name])
    state = item_state(d, chat)
    assert len(state['items']) == 1, state
    item = state['items'][0]
    assert item['name'] == name
    checks['upload_copiado_e_verificado'] = 'PASS'

    # 2. The strip shows one detach control per image, not just a summary.
    def strip():
        return position(d.ui(), desc='Desanexar imagem 1', package={PACKAGE})
    visible_immediately = bool(strip())
    if not visible_immediately:
        # Reabrir a conversa é ação real de usuário: se a tira só aparecer assim,
        # isso é registrado como está, não como sucesso silencioso.
        d.shell('input keyevent 4')
        d.open_existing_chat(chat['title'])
        d.wait(strip, 'controle de desanexar por imagem depois de reabrir a conversa', timeout=90)
    xml = d.ui()
    assert position(xml, desc='Imagens anexadas', package={PACKAGE}), 'resumo dos anexos ausente'
    assert position(xml, desc='Desanexar todas as imagens', package={PACKAGE}), 'ação de desanexar todas ausente'
    assert position(xml, text='toque no ✕ para desanexar', contains=True, package={PACKAGE}), \
        'tira de imagens não explica o ✕'
    d.capture('attachments-strip.png')
    checks['botao_por_imagem'] = 'PASS'

    # 3. Detach: explicit confirmation, then real removal.
    d.tap(desc='Desanexar imagem 1', package={PACKAGE})
    d.wait(lambda: position(d.ui(), text='Desanexar esta imagem desta conversa?', contains=True,
                            package={PACKAGE}), 'confirmação de desanexar', timeout=20)
    d.capture('attachments-detach-confirm.png')
    d.tap(text='Desanexar', package={PACKAGE})
    key = hashlib.sha256(chat['id'].encode()).hexdigest()
    data = f"/data/user/0/{PACKAGE}/files/attachments/{key}/{item['id']}.data"
    d.wait(lambda: item_state(d, chat)['items'] == [], 'vínculo removido do estado privado', timeout=30)
    assert d.shell(f'[ -e {data} ] && echo present || echo absent', check=False).strip() == 'absent', \
        'cópia privada sobreviveu ao desanexar'
    pid = d.alive()
    log = d.adb('logcat', '-d', f'--pid={pid}')
    (E / 'attachments-detach-logcat.txt').write_text(log)
    assert 'GGUF_IMAGE_DETACHED' in log, 'desanexar não passou pelo código de produção'
    assert 'GGUF_IMAGE_STRIP shown=1' in log, 'tira de imagens nunca foi mostrada'
    assert 'FATAL EXCEPTION' not in log and 'Fatal signal' not in log
    d.wait(lambda: not position(d.ui(), desc='Imagens anexadas', package={PACKAGE}),
           'tira de imagens recolhida após remover a única imagem', timeout=30)
    d.capture('attachments-detached.png')
    checks['desanexar_remove_bytes_e_vinculo'] = 'PASS'

    (E / 'attachments-detach.json').write_text(json.dumps({
        'status': 'PASS', 'checks': checks, 'attachment': {'id': item['id'], 'name': item['name'],
                                                           'sha256': hashlib.sha256((F / name).read_bytes()).hexdigest()},
        'detach_visible_on_first_render': visible_immediately,
        'scope': 'Upload real via SAF com bytes verificados, controle por imagem e remoção efetiva da '
                 'cópia privada e do vínculo; backend Vulkan desativado de propósito; nenhuma resposta '
                 'de modelo foi injetada.'},
        ensure_ascii=False, indent=2))
    return checks


if __name__ == '__main__':
    import sys
    sys.path.insert(0, 'scripts')
    from test_android import Android
    print(json.dumps(run(Android(os.environ.get('ANDROID_SERIAL', 'emulator-5554'), Path('evidence'))),
                     ensure_ascii=False, indent=2))
