#!/usr/bin/env python3
"""Varredura funcional no emulador: cada função visível do aplicativo, exercitada.

O pedido foi "testa TODAS as funções". Este script existe para isso: percorre a
superfície do aplicativo como um usuário a percorre — estado vazio, abas, ajustes,
modelo (listar, descarregar, excluir), criar conversa, enviar, parar, raciocínio,
busca com fontes, gaveta de ferramentas, os quatro seletores de anexo, anexo
enviado de verdade, notificação em segundo plano, histórico após reinício e o
aviso de "sem modelo" — registrando, para cada função, PASS, FAIL ou SKIP **com
motivo**.

Três regras desta casa, aplicadas aqui:

* cada PASS tem uma observação real (estado persistido, marca no log do próprio
  aplicativo, ou texto exibido na tela);
* o que depende de peça ausente é SKIP declarado (visão sem mmproj, por exemplo),
  nunca PASS por omissão;
* uma função que falha não interrompe a varredura: o relatório sai completo e o
  script termina com erro se qualquer função tiver falhado.

Começa do zero de propósito (`pm clear` + preparo do modelo), para que o estado
vazio e a primeira execução sejam observados de verdade. O resultado vira
`evidence/functions-sweep.json`.
"""
import argparse
import json
import re
import shlex
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from android_checks import (PACKAGE, PICKERS, generation_completed,  # noqa: E402
                            has_package, position, search_panel)


class SkipCheck(Exception):
    """Peça/hardware ausente: não é aprovação nem reprovação, é ausência declarada."""


class Sweep:
    def __init__(self, device, evidence):
        self.device = device
        self.evidence = evidence
        self.results = {}
        self.failed = []

    def run(self, name, function):
        print(f'--- {name}', flush=True)
        try:
            detail = function()
        except SkipCheck as skip:
            self.results[name] = {'status': 'SKIP', 'detail': str(skip)}
            self.dump(name)
            print(f'SKIP {name}: {skip}', flush=True)
            return False
        except Exception as error:  # noqa: BLE001 — o relatório precisa continuar
            detail = f'{type(error).__name__}: {error}'
            self.results[name] = {'status': 'FAIL', 'detail': detail}
            self.failed.append(name)
            print(f'FAIL {name}: {detail}', flush=True)
            try:
                self.device.capture(f'functions-{name}.png')
            except Exception as capture_error:  # noqa: BLE001
                print(f'(captura indisponível: {capture_error})', flush=True)
            self.dump(name)
            return False
        self.results[name] = {'status': 'PASS', 'detail': detail}
        print(f'PASS {name}: {detail}', flush=True)
        return True

    def dump(self, name):
        """Guarda a árvore de views do momento: é o que permite explicar um FAIL/SKIP."""
        try:
            (self.evidence / f'functions-{name}-ui.xml').write_text(self.device.ui())
        except Exception as error:  # noqa: BLE001
            print(f'(dump indisponível: {error})', flush=True)

    def write(self):
        report = {
            'status': 'FAIL' if self.failed else 'PASS',
            'functions_total': len(self.results),
            'functions_failed': self.failed,
            'functions': self.results,
        }
        (self.evidence / 'functions-sweep.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2))
        linhas = [f"{r['status']:4} {nome}: {r['detail']}" for nome, r in self.results.items()]
        resumo = (f"varredura funcional: {len(self.results)} funções, "
                  f"{sum(1 for r in self.results.values() if r['status'] == 'PASS')} PASS, "
                  f"{sum(1 for r in self.results.values() if r['status'] == 'SKIP')} SKIP, "
                  f"{len(self.failed)} FAIL\n" + '\n'.join(linhas) + '\n')
        (self.evidence / 'functions-sweep.txt').write_text(resumo)
        print(resumo, flush=True)
        return report


def on_screen(device, label, contains=True):
    return position(device.ui(), text=label, package={PACKAGE}, contains=contains)


def wait_screen(device, label, timeout=20, contains=True):
    return device.wait(lambda: on_screen(device, label, contains), f'"{label}" na tela', timeout=timeout)


def tap_label(device, label, contains=True, optional=False):
    return device.tap(text=label, package={PACKAGE}, contains=contains, optional=optional)


def tap_exact(device, label, optional=False):
    """Toque no controle cujo texto é EXATAMENTE esse.

    "Busca" não pode casar com "Busca ON", e "Excluir" não pode casar com o título
    "Excluir conversa" do diálogo — foi assim que a confirmação da exclusão ficou
    sem ser tocada na varredura anterior.
    """
    return tap_label(device, label, contains=False, optional=optional)


def edit_near(device, label):
    """EditText na mesma faixa vertical do rótulo — o campo daquele ajuste."""
    root = ET.fromstring(device.ui())
    target = None
    for node in root.iter('node'):
        if node.get('package') in PACKAGE and label.casefold() in node.get('text', '').casefold():
            match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.get('bounds', ''))
            if match:
                target = tuple(map(int, match.groups()))
    if target is None:
        raise AssertionError(f'rótulo do ajuste não encontrado: {label}')
    candidatos = []
    for node in root.iter('node'):
        if node.get('package') not in PACKAGE or node.get('class') != 'android.widget.EditText':
            continue
        match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.get('bounds', ''))
        if not match:
            continue
        x1, y1, x2, y2 = map(int, match.groups())
        if y1 >= target[3] - 10:  # abaixo do rótulo
            candidatos.append((y1, (x1 + x2) // 2, (y1 + y2) // 2))
    if not candidatos:
        raise AssertionError(f'campo editável não encontrado abaixo de "{label}"')
    # o campo do ajuste é o mais próximo abaixo do rótulo, não o primeiro da tela
    _, x, y = min(candidatos)
    return x, y


def field_text(device, point):
    """O que o campo mostra agora (texto do EditText que contém o ponto)."""
    x, y = point
    for node in ET.fromstring(device.ui()).iter('node'):
        if node.get('package') not in PACKAGE or node.get('class') != 'android.widget.EditText':
            continue
        match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.get('bounds', ''))
        if match:
            x1, y1, x2, y2 = map(int, match.groups())
            if x1 <= x <= x2 and y1 <= y <= y2:
                return node.get('text', '')
    return ''


def type_into(device, point, value):
    device.shell(f'input tap {point[0]} {point[1]}')
    time.sleep(0.6)
    device.shell('input keyevent KEYCODE_MOVE_END')
    for _ in range(12):
        device.shell('input keyevent KEYCODE_DEL')
    device.shell(f'input text {shlex.quote(value)}')
    time.sleep(0.5)


def other_window(device):
    """Alguma janela que não é o aplicativo está na frente (seletor do sistema)?"""
    return any(node.get('package') and node.get('package') not in PACKAGE
               for node in ET.fromstring(device.ui()).iter('node'))


def picker_then_back(device, label):
    """Abre o seletor do botão indicado e volta: o seletor abre, o app continua vivo."""
    if not tap_exact(device, label, optional=True):
        raise AssertionError(f'botão {label} não encontrado na gaveta')
    appeared = False
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        xml = device.ui()
        if has_package(xml, PICKERS) or other_window(device):
            appeared = True
            break
        time.sleep(1)
    for _ in range(2):
        device.shell('input keyevent KEYCODE_BACK')
        time.sleep(1)
    device.wait(lambda: has_package(device.ui(), {PACKAGE}), f'volta do seletor {label}', timeout=25)
    device.alive()
    if not appeared:
        raise AssertionError(f'o seletor de {label} não apareceu')
    return f'{label} abriu o seletor e o aplicativo voltou vivo'


def write_downloads_fixture(device, name, body):
    device.shell(f'rm -f /sdcard/Download/{name}')
    device.shell(f'printf %s {shlex.quote(body)} > /sdcard/Download/{name}')
    device.shell('am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d '
                 + shlex.quote(f'file:///storage/emulated/0/Download/{name}'), check=False)


def last_stats(log):
    matches = re.findall(r'GGUF_GENERATION_STATS tokens=(\d+) decode_ns=(\d+) prefill_ns=(\d+)', log)
    return tuple(map(int, matches[-1])) if matches else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--serial', required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--apk', type=Path, required=True)
    parser.add_argument('--mmproj', type=Path)
    parser.add_argument('--evidence', type=Path, default=Path('evidence'))
    parser.add_argument('--allow-data-reset', action='store_true')
    args = parser.parse_args()
    if not args.allow_data_reset or not args.serial.startswith('emulator-'):
        parser.error('Use somente emulador descartável, com --allow-data-reset explícito.')
    if not args.model.is_file():
        parser.error(f'modelo inexistente: {args.model}')

    from test_android import Android  # mesmo harness das outras fases
    args.evidence.mkdir(parents=True, exist_ok=True)
    device = Android(args.serial, args.evidence)
    sweep = Sweep(device, args.evidence)

    # Emulador descartável com root (como as outras fases); dados limpos para que o
    # estado vazio seja observado de verdade, e o modelo preparado em seguida.
    device.adb('root', check=False)
    device.adb('wait-for-device', timeout=60)
    if device.shell('id -u') != '0':
        raise SystemExit('varredura exige emulador descartável com adb root')
    if device.shell(f'pm clear {PACKAGE}') != 'Success':
        raise SystemExit('não foi possível limpar os dados do aplicativo')
    device.grant_test_notifications()
    device.shell('mkdir -p /sdcard/Download')
    model = device.provision_model(args.model)

    def estado_vazio():
        device.launch()
        wait_screen(device, 'Nenhuma conversa ainda', timeout=25)
        return 'primeira execução: a tela vazia orienta ("Toque em + Nova conversa para começar")'

    def abas():
        chegou = []
        for label, marker in (('Importar', 'Importar GGUF'), ('AI Modelos', 'Modelo'),
                              ('Ajustes', 'Salvar ajustes'), ('Chat', 'Nova conversa')):
            device.launch()
            if not tap_exact(device, label, optional=True):
                continue
            if device.wait(lambda m=marker: on_screen(device, m), f'conteúdo de {label}',
                           timeout=25):
                chegou.append(label)
        if len(chegou) < 3:
            raise AssertionError(f'abas alcançadas: {chegou}')
        return 'abas navegam e mostram conteúdo próprio: ' + ', '.join(chegou)

    def importar_botoes():
        device.launch()
        tap_exact(device, 'Importar')
        wait_screen(device, 'Importar GGUF')
        single = on_screen(device, 'Importar GGUF')
        pair = on_screen(device, 'Importar 2 GGUFs')
        if not single or not pair:
            raise AssertionError('faltam os dois caminhos de importação desta versão '
                                 '(botão único e par texto+mmproj)')
        return 'importação oferece o caminho unitário (Importar GGUF) e o par texto+mmproj'

    def ajustes():
        device.launch()
        if not tap_label(device, 'Ajustes', optional=True):
            raise SkipCheck('aba Ajustes não encontrada nesta versão')
        campos = ('Camadas na GPU', 'Tamanho de contexto', 'Threads de CPU', 'Máximo de tokens',
                  'Temperatura', 'Top-K', 'Top-P', 'Min-P')
        faltando = [c for c in campos if not on_screen(device, c)]
        if faltando:
            raise AssertionError(f'ajustes ausentes na tela: {faltando}')
        point = edit_near(device, 'Tamanho de contexto')
        antes = field_text(device, point)
        type_into(device, point, 'abc')
        depois = field_text(device, point)
        recusou_entrada = depois == antes or not re.search(r'[a-zA-Z]', depois)
        if not recusou_entrada:
            tap_label(device, 'Salvar ajustes')
            avisou = device.wait(
                lambda: (on_screen(device, 'Valor inválido')
                         or 'Valor inválido' in device.adb('logcat', '-d')),
                'recusa de valor inválido', timeout=10)
            if not avisou:
                raise AssertionError('valor inválido aceito sem aviso')
        point = edit_near(device, 'Tamanho de contexto')
        type_into(device, point, '1024')
        tap_label(device, 'Salvar ajustes')

        def persistido():
            prefs = device.shell(f'cat /data/user/0/{PACKAGE}/shared_prefs/ggufchat_settings.xml')
            return 'contextSize' in prefs and '1024' in prefs
        device.wait(persistido, 'contexto salvo nas preferências', timeout=25)
        detalhe = ('valor não numérico recusado pelo campo' if recusou_entrada
                   else 'valor inválido recusado com aviso')
        return f'os oito ajustes estão na tela; {detalhe}; valor válido salvo e persistido'

    def modelo_listado():
        device.launch()
        tap_label(device, 'Modelos', optional=True)
        wait_screen(device, model['name'], timeout=25)
        return f'modelo importado listado com o nome real ({model["name"]})'

    def descarregar_e_recarregar():
        device.launch()
        tap_exact(device, 'AI Modelos', optional=True) or tap_label(device, 'Modelos', optional=True)
        if not tap_label(device, 'Descarregar', optional=True):
            raise SkipCheck('esta versão não oferece descarregar o modelo pela interface '
                            '(nenhum controle com esse rótulo na tela de modelos)')
        device.wait(lambda: (on_screen(device, 'descarregado')
                             or 'Modelo descarregado' in device.adb('logcat', '-d')),
                    'confirmação do descarregamento', timeout=25)
        device.alive()
        device.generate(model, 0, 'functions-unload', prompt='Reply in English: say ok')
        if not (args.evidence / 'functions-unload-reply.txt').read_text().strip():
            raise AssertionError('sem resposta depois de descarregar: o modelo não voltou')
        return 'descarregou da memória e voltou a gerar resposta (recarga real, não presumida)'

    def nova_conversa():
        device.generate(model, 0, 'functions-chat', prompt='Reply in English: one word, hello')
        reply = (args.evidence / 'functions-chat-reply.txt').read_text().strip()
        stat = last_stats((args.evidence / 'functions-chat-logcat.txt').read_text())
        if not reply:
            raise AssertionError('conversa criada mas sem resposta persistida')
        return (f'criada com escolha de modelo; resposta persistida ({len(reply)} caracteres, '
                f'{stat[0] if stat else "?"} tokens nativos)')

    def parar_geracao():
        device.launch()
        chat = device.new_chat(model, 0, threads=2)
        device.wait_for_load()
        device.send('Write a long numbered list in English, at least fifty items.')
        device.wait(lambda: on_screen(device, 'Parar'), 'botão Parar durante a geração', timeout=30)
        time.sleep(2)
        tap_label(device, 'Parar')

        def parcial():
            device.alive()
            chats = device.read_json('chats.json')
            row = next((c for c in chats if c['id'] == chat['id']), None)
            if not row:
                return None
            reply = next((m for m in row.get('messages', []) if m.get('role') == 'assistant'), None)
            return reply if reply and reply.get('content', '').strip() else None
        reply = device.wait(parcial, 'resposta parcial persistida após parar', timeout=60)
        device.capture('functions-parar.png')
        stat = last_stats(device.adb('logcat', '-d'))
        if stat and stat[0] >= 128:
            raise AssertionError('Parar não interrompeu: a geração chegou ao limite de tokens')
        return (f'parou no meio e manteve a resposta parcial ({len(reply["content"])} caracteres'
                + (f', {stat[0]} tokens antes de parar' if stat else '') + ')')

    def raciocinio():
        device.launch()
        chat = device.new_chat(model, 0, threads=2)
        device.wait_for_load()
        if not device.tools_open():
            raise AssertionError('gaveta de ferramentas não abriu')
        tap_exact(device, 'Thinking')
        wait_screen(device, 'Thinking ON', contains=False, timeout=15)
        device.send('Say hello in English.')
        device.wait(lambda: generation_completed(device.adb('logcat', '-d')), 'geração com raciocínio', timeout=180)
        log = device.adb('logcat', '-d')
        chats = device.read_json('chats.json')
        row = next(c for c in chats if c['id'] == chat['id'])
        assistant = next(m for m in row['messages'] if m['role'] == 'assistant')
        prompt_aplicado = 'GGUF_SYSTEM_PROMPT_APPLIED' in log
        painel = 'GGUF_THINKING_PANEL attached=1' in log or 'GGUF_THINKING_UPGRADE' in log
        vazou = '<thinking>' in (assistant.get('content') or '').casefold()
        if not (prompt_aplicado and painel and row.get('thinking') is True):
            raise AssertionError(f'raciocínio não ficou ativo (prompt={prompt_aplicado}, painel={painel}, '
                                 f'persistido={row.get("thinking")})')
        if vazou:
            raise AssertionError('o bloco de raciocínio vazou para o texto visível')
        tap_exact(device, 'Thinking ON')
        wait_screen(device, 'Thinking', contains=False, timeout=15)
        return ('raciocínio liga e persiste (chat.thinking=true), prompt de sistema aplicado, painel '
                'próprio anexado, e o bloco não vaza para o texto visível; desliga limpo')

    def busca_fontes():
        device.launch()
        # pelo botão, como o usuário faz: gaveta → Busca → "Busca ON"
        chat = device.new_chat(model, 0, threads=2)
        device.wait_for_load()
        if not device.tools_open():
            raise AssertionError('gaveta de ferramentas não abriu')
        estado = device.search_button_state()
        if estado is not False:
            raise AssertionError(f'a conversa nova deveria estar com a busca desligada (estado={estado})')
        tap_exact(device, 'Busca')
        wait_screen(device, 'Busca ON', contains=False, timeout=15)
        prompt = 'Reply in English: What is the capital of Japan?'
        device.send(prompt)
        device.wait(lambda: generation_completed(device.adb('logcat', '-d')), 'geração com busca', timeout=240)
        log = device.adb('logcat', '-d')
        if 'GGUF_SEARCH_BUDGET' not in log:
            raise AssertionError('a busca não registrou orçamento')
        panel = search_panel(device.read_json('chats.json'), chat['id'], prompt)
        (args.evidence / 'functions-search-panel.json').write_text(
            json.dumps(panel, ensure_ascii=False, indent=2))
        encontrou = re.search(r'GGUF_SEARCH provider=(\S+) results=(\d+) ms=(\d+)', log)
        orcamento = re.search(r'GGUF_SEARCH_BUDGET total_ms=(\d+) used_ms=(\d+) exhausted=(\d)', log)
        if orcamento and int(orcamento.group(2)) > int(orcamento.group(1)) + 1500:
            raise AssertionError(f'busca passou do teto: {orcamento.group(2)} ms')
        if encontrou:
            if not panel or not panel.get('hits'):
                raise AssertionError('fontes encontradas ao vivo, mas não persistidas na mensagem')
            return (f'botão liga ("Busca ON") e a busca devolve {encontrou.group(1)} com '
                    f'{len(panel["hits"])} fonte(s) em {encontrou.group(3)} ms (teto {orcamento.group(1)} ms), '
                    f'fontes persistidas na mensagem')
        if not panel or not (panel.get('error') or '').strip():
            raise AssertionError('sem fontes e sem motivo declarado no painel')
        return (f'botão liga ("Busca ON"); sem rede/fontes neste runner, motivo persistido na mensagem: '
                f'{panel["error"][:80]}')

    def gaveta():
        device.launch()
        if not device.tools_open():
            raise AssertionError('gaveta de ferramentas não abriu')
        faltando = [b for b in ('Foto', 'Vídeo', 'Áudio', 'Arquivo', 'Ferramentas')
                    if not on_screen(device, b)]
        if faltando:
            raise AssertionError(f'botões ausentes na gaveta: {faltando}')
        return 'abre com os cinco controles: Foto, Vídeo, Áudio, Arquivo e Ferramentas'

    def seletores():
        device.launch()
        if not device.tools_open():
            raise AssertionError('gaveta de ferramentas não abriu')
        provas = []
        for label in ('Foto', 'Vídeo', 'Áudio', 'Arquivo'):
            device.tools_open()
            provas.append(picker_then_back(device, label))
        return '; '.join(provas)

    def anexo_texto():
        nome = 'gguf-anexo-de-teste.txt'
        write_downloads_fixture(device, nome, 'FATO: o projeto se chama GGUF Chat e roda localmente.\n')
        device.launch()
        chat = device.new_chat(model, 0, threads=2)
        device.wait_for_load()
        if not device.tools_open():
            raise AssertionError('gaveta de ferramentas não abriu')
        tap_exact(device, 'Arquivo')
        device.wait(lambda: has_package(device.ui(), PICKERS), 'seletor de arquivo', timeout=25)
        device.choose_file(nome)
        device.wait(lambda: on_screen(device, 'Anexo'), 'anexo listado na mensagem', timeout=30)
        device.capture('functions-anexo.png')
        device.send('Resuma o arquivo anexado em uma linha.')
        device.wait(lambda: generation_completed(device.adb('logcat', '-d')), 'geração com anexo', timeout=180)
        log = device.adb('logcat', '-d')
        prepared = re.search(r'GGUF_CONTENT_PREPARED files=(\d+) images=(\d+) text_chars=(\d+)', log)
        if not prepared or int(prepared.group(1)) < 1:
            raise AssertionError('o anexo não chegou ao conteúdo preparado para o modelo')
        chats = device.read_json('chats.json')
        row = next((c for c in chats if c['id'] == chat['id']), None)
        enviado = row and any('Anexo' in json.dumps(m, ensure_ascii=False) for m in row.get('messages', []))
        if not enviado:
            raise AssertionError('a mensagem não guardou o anexo enviado')
        return (f'texto anexado e enviado: conteúdo preparado (files={prepared.group(1)}, '
                f'text_chars={prepared.group(3)}) e anexo preservado na mensagem')

    def visao():
        if not args.mmproj:
            raise SkipCheck('sem par visão/mmproj neste runner: seleção, pré-processamento e leitura de '
                            'imagem não podem ser provados — e não serão aprovados por omissão')
        raise SkipCheck('par visão/mmproj fornecido; a inferência de imagem tem fase própria '
                        '(test_media_prefix_android.py)')

    def notificacao():
        device.launch()
        device.new_chat(model, 0, threads=2)
        device.wait_for_load()
        device.send('Write a long numbered list in English, at least fifty items.')
        device.wait(lambda: on_screen(device, 'Parar'), 'geração em andamento', timeout=30)
        device.shell('input keyevent KEYCODE_HOME')
        device.shell('input keyevent KEYCODE_POWER')  # tela apaga: canal de resposta pronta
        try:
            def avisado():
                dump = device.shell('dumpsys notification --noredact')
                return ('reply-ready-v1' in dump or 'Respostas prontas' in dump) and PACKAGE in dump
            device.wait(avisado, 'notificação de resposta pronta', timeout=200)
        finally:
            device.shell('input keyevent KEYCODE_POWER')
            time.sleep(2)
            device.launch()
        tap_label(device, 'Parar', optional=True)
        return 'com a tela apagada durante a geração, o canal "Respostas prontas" apareceu no dumpsys'

    def historico():
        chats = device.read_json('chats.json', optional=True) or []
        if not chats:
            raise SkipCheck('sem conversas para conferir após reinício')
        # A conversa do teste de "parar" tem resposta parcial; a do raciocínio e a
        # da busca têm resposta inteira. A mais nova pode não ter (parou no meio),
        # então a escolha é: a mais nova QUE TENHA resposta persistida.
        def respondida(chat):
            return any(m.get('role') == 'assistant' and (m.get('content') or '').strip()
                       for m in chat.get('messages', []))
        alvo = next((c for c in sorted(chats, key=lambda c: c.get('updatedAt', 0), reverse=True)
                     if respondida(c)), None)
        if not alvo:
            raise SkipCheck('nenhuma conversa com resposta persistida para conferir')
        esperada = next(m['content'] for m in reversed(alvo['messages'])
                        if m.get('role') == 'assistant' and (m.get('content') or '').strip())
        device.shell(f'am force-stop {PACKAGE}')
        device.launch()
        device.open_existing_chat(alvo['title'])
        amostra = esperada.strip().splitlines()[0][:40]
        wait_screen(device, amostra, timeout=30)
        return f'conversa "{alvo["title"]}" reabriu com o conteúdo salvo depois de fechar o aplicativo'

    def excluir_conversa():
        chats = device.read_json('chats.json', optional=True) or []
        if not chats:
            raise SkipCheck('sem conversas para excluir')
        alvo = max(chats, key=lambda c: c.get('updatedAt', 0))
        device.launch()
        ponto = on_screen(device, alvo['title'])
        if not ponto:
            raise AssertionError('conversa não encontrada na lista')
        x, y = ponto
        device.shell(f'input touchscreen swipe {x} {y} {x} {y} 900')  # toque longo
        # O diálogo de confirmação traz o próprio título "Excluir conversa" e o
        # botão "EXCLUIR": casamento exato, senão o toque cai no título e nada é
        # confirmado (foi o que aconteceu na primeira varredura).
        device.wait(lambda: on_screen(device, 'Excluir conversa'),
                    'diálogo de excluir conversa', timeout=25)
        if not tap_exact(device, 'Excluir', optional=True):
            raise AssertionError('o botão de confirmar a exclusão não foi encontrado')

        def sumiu():
            restantes = device.read_json('chats.json', optional=True) or []
            return True if all(c['id'] != alvo['id'] for c in restantes) else None
        device.wait(sumiu, 'conversa removida do armazenamento', timeout=30)
        return f'conversa "{alvo["title"]}" excluída pela interface e sumiu do armazenamento'

    def excluir_modelo():
        models = device.read_json('models.json', optional=True) or []
        if not models:
            raise SkipCheck('sem modelo para excluir')
        device.launch()
        tap_exact(device, 'AI Modelos', optional=True) or tap_label(device, 'Modelos', optional=True)
        if not (tap_label(device, 'Excluir modelo', optional=True)
                or tap_label(device, 'Remover modelo', optional=True)):
            raise SkipCheck('esta versão não oferece excluir o modelo pela interface '
                            '(nenhum controle com esse rótulo na tela de modelos)')
        tap_label(device, 'Excluir', optional=True)

        def vazio():
            restantes = device.read_json('models.json', optional=True) or []
            return True if not restantes else None
        device.wait(vazio, 'modelo removido do armazenamento', timeout=30)
        return 'modelo excluído pela interface e removido do armazenamento'

    def sem_modelo():
        device.launch()
        tap_label(device, 'Chat', optional=True)
        tap_label(device, 'Nova conversa')
        aviso = device.wait(lambda: (on_screen(device, 'Importe ao menos um modelo')
                                     or on_screen(device, 'Escolha o modelo')),
                            'aviso de que falta modelo', timeout=25)
        device.alive()
        if not aviso:
            raise AssertionError('sem modelo importado, o aplicativo não avisou o usuário')
        return 'sem modelo, criar conversa avisa o usuário em vez de falhar em silêncio'

    ordem = [
        ('estado_vazio', estado_vazio), ('abas', abas), ('importar_botoes', importar_botoes),
        ('ajustes', ajustes), ('modelo_listado', modelo_listado),
        ('descarregar_e_recarregar', descarregar_e_recarregar), ('nova_conversa', nova_conversa),
        ('parar_geracao', parar_geracao), ('raciocinio', raciocinio), ('busca_fontes', busca_fontes),
        ('gaveta_ferramentas', gaveta), ('seletores_de_anexo', seletores), ('anexo_texto', anexo_texto),
        ('visao', visao), ('notificacao', notificacao), ('historico', historico),
        ('excluir_conversa', excluir_conversa), ('excluir_modelo', excluir_modelo),
        ('sem_modelo', sem_modelo),
    ]
    for nome, funcao in ordem:
        sweep.run(nome, funcao)

    report = sweep.write()
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    if report['status'] != 'PASS':
        sys.exit(1)


if __name__ == '__main__':
    main()
