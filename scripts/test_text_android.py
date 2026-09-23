"""Real Android UI test of the text renderer that ships in the APK.

The fixture loads the production DEX, applies the real MarkdownText/CodeBlocks/
ThinkingView/SearchTool code to explicit synthetic UI fixtures and reports the
result on screen; this script reads that report from the device, exercises the
collapsible reasoning panel and the source panel through real taps, and requires
the production log markers. Nothing here is presented as a model answer.
"""
import json
from pathlib import Path

from android_checks import position

PKG = 'com.ggufchat.texttest'
APP = 'com.ggufchat.app'
REPORT = 'Ok: inline=ok;codigo=python;raciocinio=ok;fontes=ok;parsers=ok'


def run(d):
    d.adb('install', '-r', '.cache/text-test/test.apk')
    d.shell('am force-stop ' + PKG)
    started = d.shell('am start -W -n ' + PKG + '/.TextActivity')
    Path('evidence/physical-text-start.txt').write_text(started)
    assert 'Status: ok' in started, started
    pid = d.shell('pidof ' + PKG).split()[0]

    # 1. The fixture's own assertions (spans, code panel language, parsers).
    def rendered():
        xml = d.ui()
        return position(xml, text=REPORT, package={PKG})
    d.wait(rendered, 'renderizador de texto sem falhas', timeout=60)
    xml = d.ui()
    checks = {}

    # 2. Inline formatting really applied: visible text has no markdown markers.
    assert position(xml, text='Resposta com negrito', contains=True, package={PKG}), \
        'negrito não chegou ao balão renderizado'
    assert position(xml, text='itálico e código inline', contains=True, package={PKG}), \
        'texto formatado incompleto na tela'
    assert not position(xml, text='**', contains=True, package={PKG}), 'marcador ** visível ao usuário'
    assert not position(xml, text='`', contains=True, package={PKG}), 'marcador de código visível ao usuário'
    checks['negrito_italico_codigo_inline'] = 'PASS'

    # 3. Code block the model decided, labelled from its content.
    assert position(xml, text='python', package={PKG}), 'painel de código sem linguagem detectada'
    assert position(xml, text='Copiar', contains=True, package={PKG}), 'painel de código sem botão de cópia'
    assert position(xml, text='return a + b', contains=True, package={PKG}), 'corpo do código ausente'
    checks['bloco_de_codigo_detectado'] = 'PASS'

    # 4. Reasoning apart from the answer, collapsed by default and toggleable.
    assert position(xml, text='A resposta final é 4.', contains=True, package={PKG}), 'resposta ausente'
    assert not position(xml, text='passo 1: somar', contains=True, package={PKG}), \
        'raciocínio apareceu antes de expandir: não está separado'
    d.tap(desc='Alternar raciocínio', package={PKG})
    d.wait(lambda: position(d.ui(), text='passo 1: somar', contains=True, package={PKG}),
           'raciocínio visível após expandir', timeout=20)
    xml = d.ui()
    assert position(xml, text='Ocultar', contains=True, package={PKG}), 'alternador não mudou de estado'
    assert not position(xml, text='Raciocínio:', contains=True, package={PKG}), \
        'raciocínio ainda no balão da resposta'
    checks['raciocinio_separado_recolhivel'] = 'PASS'

    # 5. Search provenance: what was searched, provider, numbered sources, failure.
    assert position(xml, desc='O que foi pesquisado', package={PKG}), 'painel de fontes ausente'
    assert position(xml, text='Consulta: capital do Brasil', contains=True, package={PKG}), \
        'consulta pesquisada não exibida'
    assert position(xml, text='Wikipédia', contains=True, package={PKG}), 'provedor não exibido'
    assert position(xml, text='2 fonte(s)', contains=True, package={PKG}), 'contagem de fontes ausente'
    assert position(xml, desc='Fonte 1', package={PKG}) and position(xml, desc='Fonte 2', package={PKG}), \
        'fontes numeradas ausentes'
    assert position(xml, text='https://pt.wikipedia.org/wiki/Bras', contains=True, package={PKG}) or \
        position(xml, text='Brasília', contains=True, package={PKG}), 'títulos das fontes ausentes'
    assert position(xml, desc='Falha na busca', package={PKG}), 'falha de busca não foi mostrada'
    checks['fontes_e_consulta_visiveis'] = 'PASS'

    # 6. Production code paths actually ran inside this process.
    log = d.adb('logcat', '-d', f'--pid={pid}')
    Path('evidence/physical-text-logcat.txt').write_text(log)
    for marker in ('GGUF_THINKING_PANEL attached=1', 'GGUF_THINKING_UPGRADE', 'GGUF_THINKING_TOGGLED expanded=1',
                   'GGUF_SEARCH_PANEL shown=1'):
        assert marker in log, f'sem marca real de execução: {marker}'
    assert 'FATAL EXCEPTION' not in log and 'Fatal signal' not in log, 'falha durante o teste de texto'
    checks['codigo_de_producao_executado'] = 'PASS'

    d.capture('physical-text.png')
    Path('evidence/physical-text-ui.json').write_text(json.dumps(dict(
        status='PASS', checks=checks, fixture_report=REPORT, package=APP,
        scope='DEX de produção (MarkdownText/CodeBlocks/ThinkingView/SearchTool) em fixtures sintéticas '
              'explícitas; não é inferência de modelo.'), ensure_ascii=False, indent=2))
    d.shell('am force-stop ' + PKG)
    return checks


if __name__ == '__main__':
    import sys
    sys.path.insert(0, 'scripts')
    from test_android import Android
    d = Android('emulator-5554', Path('evidence'))
    print(json.dumps(run(d), ensure_ascii=False, indent=2))
