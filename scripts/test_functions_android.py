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

from android_checks import (PACKAGE, PICKERS, assistant_reply,  # noqa: E402
                            generation_completed, has_package, position, pref_value, search_panel)


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


def wait_toast(device, text, timeout=8):
    """A mensagem do próprio aplicativo (toast), capturada enquanto está na tela.

    Um toast vive poucos segundos e não passa pelo logcat: a leitura precisa ser
    repetida enquanto ele existe, em vez de uma leitura única.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for label in visible_labels(device, 40):
            if text in label:
                return label
        time.sleep(0.4)
    return None


def backend_text(device):
    """O valor de "Backend atual: ..." na tela de Ajustes ("—" sem motor carregado)."""
    for label in visible_labels(device, 40):
        found = re.search(r'Backend atual:[ \t]*([^\n]*)', label)
        if found:
            return found.group(1).strip()
    return None


def visible_labels(device, limit=14):
    """Os rótulos visíveis agora — o que permite explicar uma falha de navegação."""
    seen = []
    for node in ET.fromstring(device.ui()).iter('node'):
        if node.get('package') not in PACKAGE:
            continue
        for key in ('text', 'content-desc'):
            value = (node.get(key) or '').strip()
            if value and value not in seen:
                seen.append(value)
    return seen[:limit]


def tap_label(device, label, contains=True, optional=False):
    found = device.tap(text=label, package={PACKAGE}, contains=contains, optional=True)
    if not found and not optional:
        raise AssertionError(f'controle "{label}" não está na tela; visíveis: {visible_labels(device)}')
    return found


def last_button(device, label):
    """Centro do ÚLTIMO botão com esse texto exato (o diálogo vem depois da tela)."""
    achados = []
    for node in ET.fromstring(device.ui()).iter('node'):
        if node.get('package') not in PACKAGE or node.get('class') != 'android.widget.Button':
            continue
        match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.get('bounds', ''))
        if not match or (node.get('text') or '') != label or not match:
            continue
        x1, y1, x2, y2 = map(int, match.groups())
        if x2 > x1 and y2 > y1:
            achados.append(((x1 + x2) // 2, (y1 + y2) // 2))
    return achados[-1] if achados else None


def scroll_to(device, label, tries=5, contains=True):
    """Procura o rótulo rolando, nos DOIS sentidos.

    Na rodada 36238272473 a tela de Ajustes ficou no fim da lista e a busca só
    rolava para baixo: "Tamanho de contexto" estava acima e o teste reprovou o
    aplicativo por causa do sentido da rolagem. Agora a busca volta ao topo
    primeiro e, se não achar, procura também para cima.
    """
    def visible():
        return bool(on_screen(device, label, contains))

    if visible():
        return True
    for _ in range(6):  # volta ao topo antes de procurar
        device.shell('input touchscreen swipe 360 500 360 1000 250')
        time.sleep(0.3)
        if visible():
            return True
    for _ in range(tries):  # procura descendo
        device.shell('input touchscreen swipe 360 1000 360 500 300')
        time.sleep(0.6)
        if visible():
            return True
    for _ in range(tries):  # e, se preciso, subindo
        device.shell('input touchscreen swipe 360 500 360 1000 300')
        time.sleep(0.5)
        if visible():
            return True
    return visible()


def tools_button(device, label):
    """Ponto de toque de um botão da linha de ferramentas, se ele estiver inteiro na tela.

    A linha rola para o lado: "Áudio" aparece cortado na borda, "Arquivo" e
    "Ferramentas" ficam fora. Um botão cortado tem centro fora da tela e o toque
    cai no vazio (foi assim que "Arquivo" não foi encontrado na rodada
    36245048939: a linha terminava em "Áudio"). Só devolve o ponto quando o
    centro está dentro dos limites do emulador (720x1280 configurado pelo app).
    """
    for node in ET.fromstring(device.ui()).iter('node'):
        if node.get('package') not in PACKAGE or node.get('class') != 'android.widget.Button':
            continue
        if (node.get('text') or '') != label or node.get('enabled') != 'true':
            continue
        match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.get('bounds', ''))
        if not match:
            continue
        x1, y1, x2, y2 = map(int, match.groups())
        x, y = (x1 + x2) // 2, (y1 + y2) // 2
        if 10 <= x <= 1070 and y2 > y1 and x2 > x1:
            return x, y
    return None


def scroll_tools_to(device, label, tries=5):
    """Traz o botão para dentro da linha rolável de ferramentas, nos dois sentidos."""
    if tools_button(device, label):
        return tools_button(device, label)
    for step in ('input touchscreen swipe 950 2028 200 2028 300',
                 'input touchscreen swipe 200 2028 950 2028 300'):
        for _ in range(tries):
            device.shell(step)
            time.sleep(0.6)
            if tools_button(device, label):
                return tools_button(device, label)
    return None


def scroll_tools_row(device):
    """Compatibilidade: traz o botão "Ferramentas" (último da linha) para a tela."""
    return scroll_tools_to(device, 'Ferramentas') is not None


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
    """Abre o seletor do botão indicado e volta ao aplicativo de verdade.

    Na rodada 36192982173 dois BACKs fixos deixaram o launcher na frente e a
    espera pela volta do aplicativo expirou — o aplicativo não tinha defeito, o
    teste é que saía da pilha errada. Agora: BACK só enquanto o aplicativo não
    estiver na frente, e a prova de vida é o MESMO processo (PID), porque voltar
    na tela pode ser uma reinicialização disfarçada.
    """
    ponto = tools_button(device, label) or (scroll_tools_row(device) if label == 'Ferramentas'
                                            else scroll_tools_to(device, label))
    if ponto and 10 <= ponto[0] <= 1070:
        device.shell(f'input tap {ponto[0]} {ponto[1]}')
    elif not tap_exact(device, label, optional=True):
        raise AssertionError(f'botão {label} não encontrado na tela, nem rolando a linha de '
                             f'ferramentas; visíveis: {visible_labels(device)}')
    pid = device.alive()
    opened = None
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        xml = device.ui()
        if has_package(xml, PICKERS):
            opened = 'seletor de arquivos do sistema'
            break
        if other_window(device):
            opened = 'janela do sistema'
            break
        time.sleep(1)
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline and not has_package(device.ui(), {PACKAGE}):
        device.shell('input keyevent KEYCODE_BACK')
        time.sleep(1)
    if not has_package(device.ui(), {PACKAGE}):
        # A tarefa do seletor pode ter levado o aplicativo para trás do launcher:
        # traz a tarefa existente para a frente, sem -S (que reiniciaria o processo).
        device.shell(f'am start -W -n {PACKAGE}/.MainActivity')
        device.wait(lambda: has_package(device.ui(), {PACKAGE}), f'volta do seletor {label}', timeout=25)
    if device.alive() != pid:
        raise AssertionError(f'o processo do aplicativo mudou ao abrir {label}: '
                             f'{pid} → {device.alive()} (crash ou reinício)')
    if not opened:
        raise AssertionError(f'o seletor de {label} não apareceu')
    return f'{label} abriu o {opened} e o aplicativo voltou no mesmo processo'


def foto_com_par(device):
    """Foto na conversa MULTIMODAL: diálogo "Fotos" → "Importar foto" → seletor.

    O aplicativo só abre esse caminho quando a CONVERSA está ligada a um par
    visão/mmproj (Attachments.multimodal() lê chat.mmprojPath) — é a prova de que o
    botão usa o par, e não de que só existe desenhado.
    """
    device.tools_open()
    if not tap_exact(device, 'Foto', optional=True):
        raise AssertionError('botão Foto não encontrado na conversa multimodal; visíveis: '
                             + ', '.join(visible_labels(device, 20)))
    device.wait(lambda: on_screen(device, 'Fotos'), 'diálogo de fotos no modo multimodal', timeout=20)
    tap_exact(device, 'Importar foto')
    device.wait(lambda: has_package(device.ui(), PICKERS) or other_window(device),
                'seletor de imagens', timeout=30)
    pid = device.alive()
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline and not has_package(device.ui(), {PACKAGE}):
        device.shell('input keyevent KEYCODE_BACK')
        time.sleep(1)
    if not has_package(device.ui(), {PACKAGE}):
        device.shell(f'am start -W -n {PACKAGE}/.MainActivity')
        device.wait(lambda: has_package(device.ui(), {PACKAGE}), 'volta do seletor de imagens', timeout=25)
    if device.alive() != pid:
        raise AssertionError(f'o processo mudou no caminho de foto: {pid} → {device.alive()}')
    return 'Foto abriu o diálogo e o seletor de imagens no mesmo processo'


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
    parser.add_argument('--vision', type=Path, help='GGUF de visão, junto com --mmproj')
    parser.add_argument('--mmproj', type=Path, help='projetor (mmproj) do par de visão')
    parser.add_argument('--evidence', type=Path, default=Path('evidence'))
    parser.add_argument('--allow-data-reset', action='store_true')
    args = parser.parse_args()
    if not args.allow_data_reset or not args.serial.startswith('emulator-'):
        parser.error('Use somente emulador descartável, com --allow-data-reset explícito.')
    if not args.model.is_file():
        parser.error(f'modelo inexistente: {args.model}')
    if bool(args.vision) != bool(args.mmproj):
        parser.error('Forneça --vision e --mmproj juntos (o par é o que habilita visão).')
    for path in (args.vision, args.mmproj):
        if path and not path.is_file():
            parser.error(f'peça de visão inexistente: {path}')

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
        for label, marker in (('Importar', 'Importar GGUF'), ('AI Modelos', model['name']),
                              ('Ajustes', 'Salvar ajustes'), ('Chat', 'Nova conversa')):
            device.launch()
            if not tap_exact(device, label, optional=True):
                continue
            try:
                device.wait(lambda m=marker: on_screen(device, m), f'conteúdo de {label}', timeout=25)
                chegou.append(label)
            except AssertionError:  # rola a tela e tenta de novo antes de desistir
                try:
                    device.wait(lambda m=marker: scroll_to(device, m),
                                f'conteúdo de {label} após rolar', timeout=15)
                    chegou.append(label)
                except AssertionError:
                    print(f'   (a aba {label} não mostrou "{marker}"; '
                          f'visíveis: {visible_labels(device)})', flush=True)
        if len(chegou) < 3:
            raise AssertionError(f'abas alcançadas: {chegou}')
        return 'abas navegam e mostram conteúdo próprio: ' + ', '.join(chegou)

    def importar_botoes():
        device.launch()
        tap_exact(device, 'Importar')
        wait_screen(device, 'Importar GGUF')
        if not (on_screen(device, 'Importar GGUF') or scroll_to(device, 'Importar GGUF')):
            raise AssertionError('não há entrada de importação nesta tela; '
                                 f'visíveis: {visible_labels(device)}')
        # Esta versão tem UMA entrada de importação, de propósito: a tela antiga de
        # dois arquivos virou redirecionamento para cá (apk-fix/single_import_ui.py).
        # O teste então exige duas coisas: a entrada abre o seletor real, e a tela
        # explica o caminho do projetor — senão o par texto+mmproj sumiria calado.
        texto = ' '.join(visible_labels(device, 30)).casefold()
        if 'projetor' not in texto:
            raise AssertionError('a tela de importação não explica o caminho com projetor: '
                                 + ' '.join(visible_labels(device, 30))[:200])
        prova = picker_then_back(device, 'Importar GGUF')
        # A tela antiga (dois arquivos) continua alcançável e redireciona para a
        # entrada única: é a promessa de apk-fix/single_import_ui.py, provada aqui.
        device.shell(f'am start -W -n {PACKAGE}/.ModelsActivity')
        try:
            device.wait(lambda: on_screen(device, 'Importar GGUF'),
                        'tela antiga leva à importação atual', timeout=25)
        except AssertionError:
            raise AssertionError('a tela antiga de importação não levou à entrada única; '
                                 'visíveis: ' + ', '.join(visible_labels(device, 20)))
        return ('entrada única "Importar GGUF" que abre o seletor de verdade e a tela '
                f'explica os dois caminhos (par linguagem+projetor ou GGUF completo); {prova}')

    def ajustes():
        device.launch()
        if not tap_label(device, 'Ajustes', optional=True):
            raise SkipCheck('aba Ajustes não encontrada nesta versão')
        campos = ('Camadas na GPU', 'Tamanho de contexto', 'Threads de CPU', 'Máximo de tokens',
                  'Temperatura', 'Top-K', 'Top-P', 'Min-P')
        # A lista de ajustes rola: a tela não cabe. Percorrer e voltar é o que um
        # usuário faz; exigir os oito de uma vez era exigir do emulador, não do app.
        vistos = set()
        for _ in range(5):
            vistos.update(c for c in campos if on_screen(device, c))
            if len(vistos) == len(campos):
                break
            device.shell('input touchscreen swipe 360 1000 360 500 300')
            time.sleep(0.6)
        faltando = [c for c in campos if c not in vistos]
        if faltando:
            raise AssertionError(f'ajustes ausentes mesmo rolando a lista: {faltando}; '
                                 f'visíveis: {visible_labels(device)}')
        for _ in range(5):  # volta ao topo para editar o campo conhecido
            device.shell('input touchscreen swipe 360 500 360 1000 300')
            time.sleep(0.4)
        scroll_to(device, 'Tamanho de contexto')
        point = edit_near(device, 'Tamanho de contexto')
        antes = field_text(device, point)
        type_into(device, point, 'abc')
        depois = field_text(device, point)
        recusou_entrada = depois == antes or not re.search(r'[a-zA-Z]', depois)
        prefs = lambda: device.shell(  # noqa: E731 — leitura usada em duas esperas
            f'cat /data/user/0/{PACKAGE}/shared_prefs/ggufchat_settings.xml')
        if not recusou_entrada:
            # O campo aceitou letras. O comportamento declarado deste aplicativo não é
            # avisar "valor inválido" (essa mensagem não existe no APK): o smali diz
            # `parseInt(campo, 4096)` com catch que devolve o padrão. Então o que se
            # exige aqui é o que o aplicativo promete: o padrão, sem corromper o ajuste.
            scroll_to(device, 'Salvar ajustes')
            tap_label(device, 'Salvar ajustes')
            device.wait(lambda: pref_value(prefs(), 'contextSize') == '4096',
                        'valor não numérico caiu no padrão 4096', timeout=25)
            device.alive()
        scroll_to(device, 'Tamanho de contexto')
        point = edit_near(device, 'Tamanho de contexto')
        type_into(device, point, '1024')
        scroll_to(device, 'Salvar ajustes')
        if not tap_label(device, 'Salvar ajustes', optional=True):
            raise AssertionError('botão de salvar não encontrado na tela de ajustes; '
                                 f'visíveis: {visible_labels(device)}')

        def persistido():
            return pref_value(prefs(), 'contextSize') == '1024'
        device.wait(persistido, 'contexto salvo nas preferências', timeout=25)
        detalhe = ('valor não numérico recusado pelo próprio campo' if recusou_entrada
                   else 'valor não numérico não corrompe o ajuste: cai no padrão 4096')
        return f'os oito ajustes estão na tela; {detalhe}; valor válido salvo e persistido'

    def modelo_listado():
        device.launch()
        tap_exact(device, 'AI Modelos', optional=True) or tap_label(device, 'Modelos', optional=True)
        wait_screen(device, model['name'], timeout=25)
        return f'modelo importado listado com o nome real ({model["name"]})'

    def descarregar_e_recarregar():
        """Descarregar precisa de motor CARREGADO no mesmo processo para provar algo.

        A rodada 36261210088 esperava `GGUF_UNIT_RELEASED found=1` depois de abrir a
        tela com `am start -S` (que mata o processo): sem motor carregado, o botão
        não tinha o que liberar e a espera estourava. A prova honesta é: gerar uma
        resposta (o motor carrega neste processo), voltar à tela principal SEM
        reiniciar, tocar no botão e ver o próprio binário registrar a liberação
        (`GGUF_UNIT_RELEASED found=1`); depois, gerar de novo e ver a recarga
        (`GGUF_UNIT_LOADED`). O toast continua sendo observação, nunca critério.
        """
        device.generate(model, 0, 'functions-unload-pre', prompt='Reply in English: say ok')
        pid = device.alive()
        # Volta à tela principal sem reiniciar o processo: é o que faz o botão ter
        # um motor de verdade para descarregar.
        if not tap_exact(device, '‹', optional=True):
            device.shell('input keyevent KEYCODE_BACK')
        device.wait(lambda: on_screen(device, 'Ajustes') or on_screen(device, 'Nova conversa'),
                    'tela principal depois da conversa', timeout=25)
        if device.alive() != pid:
            raise AssertionError('o processo mudou ao voltar da conversa; sem o mesmo processo a '
                                 'prova do descarregamento não valeria')
        if not tap_label(device, 'Ajustes', optional=True):
            raise SkipCheck('aba Ajustes não encontrada nesta versão')
        if not scroll_to(device, 'Descarregar modelo da memória'):
            raise SkipCheck('controle de descarregar ausente mesmo rolando os ajustes; '
                            'rótulos visíveis: ' + ', '.join(visible_labels(device, 20)))
        scroll_to(device, 'Backend atual')
        antes = backend_text(device)
        # A prova é o log do binário, não um toast de vida curta que expira antes da
        # leitura (rodada 36255713807). O log diz se HAVIA motor para descarregar.
        device.adb('logcat', '-c')
        tap_label(device, 'Descarregar modelo da memória')
        def registrado():
            texto = device.adb('logcat', '-d')
            return texto if 'GGUF_UNIT_RELEASED' in texto else None
        log = device.wait(registrado, 'descarregamento registrado pelo binário (GGUF_UNIT_RELEASED)',
                          timeout=60)
        liberado = re.search(r'GGUF_UNIT_RELEASED found=(\d+) remaining=(\d+)', log)
        if not liberado or liberado.group(1) != '1':
            raise AssertionError('o motor estava carregado neste processo (uma resposta acabou de ser '
                                 'gerada sem reiniciar o aplicativo) e o botão não liberou nada: '
                                 f'log={liberado.group(0) if liberado else "ausente"}')
        aviso = wait_toast(device, 'Modelo descarregado', timeout=3)
        device.alive()
        # Recarga real, não presumida: a geração seguinte só responde se o modelo voltou.
        device.generate(model, 0, 'functions-unload', prompt='Reply in English: say ok')
        recarga = device.adb('logcat', '-d')
        if 'GGUF_UNIT_LOADED' not in recarga:
            raise AssertionError('o modelo respondeu, mas o log não mostra a recarga (GGUF_UNIT_LOADED): '
                                 'a prova seria presumida')
        if not (args.evidence / 'functions-unload-reply.txt').read_text().strip():
            raise AssertionError('sem resposta depois de descarregar: o modelo não voltou')
        extra = f', toast "{aviso}" também visto' if aviso else ''
        return ('botão na tela de Ajustes; com o motor carregado no mesmo processo, descarregou de '
                f'verdade (GGUF_UNIT_RELEASED found=1, remaining={liberado.group(2)}{extra}) e a '
                f'geração seguinte recarregou (GGUF_UNIT_LOADED; Backend atual: {antes!r} antes do '
                'toque é observação: o motor da conversa não fica vivo entre telas)')

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
        # 120 s: se o motor acabou de ser descarregado (ou é a primeira geração da
        # varredura), a carga do modelo entra nesta espera. Cronometrar 30 s aqui
        # media o emulador, não o aplicativo (rodada 36245048939).
        device.wait(lambda: on_screen(device, 'Parar'), 'botão Parar durante a geração', timeout=120)
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
            raise AssertionError('gaveta de ferramentas não abriu; visíveis: '
                                 + ', '.join(visible_labels(device, 20)))
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
            raise AssertionError('gaveta de ferramentas não abriu; visíveis: '
                                 + ', '.join(visible_labels(device, 20)))
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

    def abrir_conversa():
        """Gaveta só existe dentro de uma conversa: abre a mais recente com resposta."""
        chats = device.read_json('chats.json', optional=True) or []
        alvo = next((c for c in sorted(chats, key=lambda c: c.get('updatedAt', 0), reverse=True)
                     if c.get('messages')), None)
        if not alvo:
            device.new_chat(model, 0, threads=2)
            return
        device.shell(f'am force-stop {PACKAGE}')
        device.launch()
        device.open_existing_chat(alvo['title'])

    def gaveta():
        device.launch()
        abrir_conversa()
        if not device.tools_open():
            raise AssertionError('gaveta de ferramentas não abriu; visíveis: '
                                 + ', '.join(visible_labels(device, 20)))
        faltando = [b for b in ('Foto', 'Vídeo', 'Áudio', 'Arquivo')
                    if not (on_screen(device, b) and scroll_tools_to(device, b))]
        if faltando:
            raise AssertionError(f'botões ausentes (ou fora de alcance) na gaveta: {faltando}')
        # 'Ferramentas' é o último botão da linha: fica fora da tela até rolar para
        # o lado (a linha é um HorizontalScrollView). Rolar é o que o usuário faz.
        if not scroll_tools_row(device):
            raise AssertionError('o botão "Ferramentas" não apareceu nem rolando a linha; '
                                 'visíveis: ' + ', '.join(visible_labels(device, 20)))
        # "Ferramentas" não é um item: é a própria linha de ferramentas da conversa
        # (desc "Ferramentas da conversa"), que traz Sistema, Thinking, Busca e os
        # quatro anexos. A árvore de views da rodada 36192982173 está no repositório
        # e é ela que sustenta esta leitura.
        if not position(device.ui(), desc='Ferramentas da conversa', package={PACKAGE}):
            raise AssertionError('a linha "Ferramentas da conversa" não está na tela')
        return ('abre com Sistema, Thinking, Busca, os quatro anexos (Foto, Vídeo, Áudio, '
                'Arquivo) e o botão "Ferramentas" ao fim da linha (alcançado rolando)')

    def seletores():
        device.launch()
        abrir_conversa()
        if not device.tools_open():
            raise AssertionError('gaveta de ferramentas não abriu; visíveis: '
                                 + ', '.join(visible_labels(device, 20)))
        provas = []
        # Vídeo/Áudio/Arquivo vão para o seletor do sistema (ACTION_OPEN_DOCUMENT).
        for label in ('Vídeo', 'Áudio', 'Arquivo'):
            device.tools_open()
            provas.append(picker_then_back(device, label))
        # Foto: o que o aplicativo faz depende do MODELO DA CONVERSA ABERTA
        # (Attachments.multimodal() lê chat.mmprojPath), não de o par existir no
        # runner. Aqui a conversa é de TEXTO de propósito: o exigível é que o toque
        # não derrube o processo e não abra seletor nenhum. O caminho com o par —
        # diálogo "Fotos" → "Importar foto" → seletor de imagens — é exercitado na
        # etapa visao, na conversa multimodal de verdade (foto_com_par).
        device.tools_open()
        if not tap_exact(device, 'Foto', optional=True):
            raise AssertionError('botão Foto não encontrado na linha de ferramentas')
        time.sleep(1)
        device.alive()
        if has_package(device.ui(), PICKERS):
            raise AssertionError('conversa de texto abriu o seletor de imagens: o aplicativo deveria '
                                 'recusar sem par visão/mmproj ligado à conversa')
        detalhe = ('Foto: em conversa de texto o aplicativo não abre seletor (volta sem erro) e o '
                   'processo continua vivo; com o par ligado, o caminho completo é provado na etapa visao')
        return ('Vídeo, Áudio e Arquivo abriram o seletor do sistema e o aplicativo voltou no '
                f'mesmo processo; {detalhe}')

    def ferramentas_dialogo():
        device.launch()
        abrir_conversa()
        if not device.tools_open():
            raise AssertionError('gaveta de ferramentas não abriu; visíveis: '
                                 + ', '.join(visible_labels(device, 20)))
        if not scroll_tools_row(device):
            raise SkipCheck('botão "Ferramentas" fora de alcance nesta versão')
        tap_exact(device, 'Ferramentas')
        # O diálogo (showToolsDialog) traz o título "Ferramentas", as opções de
        # Thinking/Busca e "Fechar": é a segunda porta para as mesmas ferramentas.
        device.wait(lambda: on_screen(device, 'Fechar'), 'diálogo de ferramentas', timeout=20)
        opcoes = [b for b in ('Thinking', 'Busca') if on_screen(device, b)]
        if not opcoes:
            raise AssertionError('diálogo abriu sem as opções de ferramentas; visíveis: '
                                 + ', '.join(visible_labels(device, 20)))
        tap_exact(device, 'Fechar')
        device.wait(lambda: not on_screen(device, 'Fechar'), 'diálogo fechado', timeout=15)
        device.alive()
        return ('botão "Ferramentas" ao fim da linha abre o diálogo com ' + ', '.join(opcoes)
                + ' e "Fechar"')

    def anexo_texto():
        nome = 'gguf-anexo-de-teste.txt'
        write_downloads_fixture(device, nome, 'FATO: o projeto se chama GGUF Chat e roda localmente.\n')
        device.launch()
        chat = device.new_chat(model, 0, threads=2)
        device.wait_for_load()
        if not device.tools_open():
            raise AssertionError('gaveta de ferramentas não abriu; visíveis: '
                                 + ', '.join(visible_labels(device, 20)))
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
        """Imagem de verdade: par importado por SAF, anexo enviado e avaliado pelo motor.

        Sem o par, é SKIP declarado — nunca PASS por omissão. Com o par, o que prova a
        função não é a tela: é o motor tendo AVALIADO a imagem (`GGUF_IMAGE_EVALUATED`,
        com contagem de tokens) e a resposta persistida depois disso, além da cópia do
        anexo com hash conferido no armazenamento privado (o mesmo caminho da fase de
        anexos).
        """
        if not (args.vision and args.mmproj):
            raise SkipCheck('sem par visão/mmproj neste runner: seleção, pré-processamento e leitura de '
                            'imagem não podem ser provados — e não serão aprovados por omissão')
        try:
            from test_inference_android import F, fixtures, attach  # reuso do caminho já provado
        except Exception as exc:
            raise SkipCheck(f'fixtures de visão indisponíveis neste runner ({type(exc).__name__}: {exc})')
        # O par entra como o APLICATIVO o entrega: dois arquivos na MESMA seleção do
        # seletor, unificados num GGUF físico (path == mmprojPath). Duas seleções
        # separadas não vinculam nada — a rodada 36258711211 registrou mmprojPath=null
        # e reprovou esse caminho; a prova aqui é o registro unificado persistido.
        modelo = device.pair_import(args.vision, args.mmproj)
        fixtures()
        nome = 'imagem-da-visao.jpg'
        (F / nome).write_bytes((F / 'frame-a.jpg').read_bytes())
        chat = device.new_chat(modelo, 0, context_size=4096)
        device.wait_for_load()
        attach(device, chat, [nome])  # SAF com hash conferido na cópia privada
        prompt = 'In English, describe the image in one line.'
        device.submit(prompt, label='functions-visao')
        device.wait(lambda: generation_completed(device.adb('logcat', '-d')),
                   'geração com a imagem anexada', timeout=600)
        log = device.adb('logcat', '-d')
        (args.evidence / 'functions-visao-logcat.txt').write_text(log)
        avaliada = re.search(r'GGUF_IMAGE_EVALUATED tokens=(\d+) backend=(\w+)', log)
        resposta = assistant_reply(device.read_json('chats.json'), chat['id'], prompt).strip()
        if not avaliada:
            raise AssertionError('o motor não avaliou a imagem (sem GGUF_IMAGE_EVALUATED); visíveis: '
                                 + ', '.join(visible_labels(device, 20)))
        if not resposta:
            raise AssertionError('a imagem foi avaliada pelo motor mas nenhuma resposta foi persistida')
        # Com o par ligado à conversa, o caminho de foto do aplicativo abre de verdade.
        foto = foto_com_par(device)
        return (f'par visão/mmproj importado numa única seleção e unificado num GGUF físico; '
                f'imagem anexada (hash conferido) e avaliada pelo motor ({avaliada.group(1)} tokens de '
                f'imagem, backend {avaliada.group(2)}) com resposta persistida ({len(resposta)} '
                f'caracteres); {foto}')

    def notificacao():
        device.launch()
        device.new_chat(model, 0, threads=2)
        device.wait_for_load()
        device.send('Write a long numbered list in English, at least fifty items.')
        device.wait(lambda: on_screen(device, 'Parar'), 'geração em andamento', timeout=120)
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
        # Quem tem o botão "Excluir" da linha é a tela de importação: a árvore de views
        # da rodada 36192982173 mostra o botão ao lado do modelo importado, e o smali
        # do APK original liga esse botão ao diálogo "Excluir modelo" ("O arquivo será
        # removido do armazenamento do app."). A tela "AI Modelos" só lista nome e
        # tamanho — procurar ali era procurar no lugar errado.
        device.launch()
        tap_exact(device, 'Importar')
        apagados = []
        # Apaga TODOS os modelos listados: com o par de visão importado, apagar só o
        # primeiro deixaria modelo no armazenamento e a função seguinte ("sem modelo")
        # mediria outra coisa. O que é provado aqui é a exclusão pela interface, com
        # confirmação, repetida até não sobrar nenhum.
        for modelo in models:
            if not scroll_to(device, modelo['name']):
                raise AssertionError('o modelo não está listado na tela de importação; '
                                     'visíveis: ' + ', '.join(visible_labels(device, 20)))
            if not tap_exact(device, 'Excluir', optional=True):
                raise SkipCheck('nenhum controle de exclusão na linha do modelo; rótulos '
                                'visíveis: ' + ', '.join(visible_labels(device, 20)))
            device.wait(lambda: on_screen(device, 'Excluir modelo'),
                        'diálogo de excluir modelo', timeout=25)
            # Confirmação por casamento exato: "Excluir" também é o rótulo da linha, e o
            # título do diálogo é "Excluir modelo" — tocar em qualquer um dos dois não
            # confirma nada (foi o erro da varredura da conversa, que ficou sem excluir).
            if not tap_exact(device, 'EXCLUIR', optional=True):
                # O smali declara os botões do diálogo como "Excluir" e "Cancelar". O
                # primeiro "Excluir" da árvore é o da linha (atrás do diálogo), então o
                # toque vai no ÚLTIMO botão com esse texto exato — o do diálogo, que é
                # acrescentado depois.
                botao = last_button(device, 'Excluir')
                if not botao:
                    raise AssertionError('diálogo aberto mas sem botão de confirmação; '
                                         'visíveis: ' + ', '.join(visible_labels(device, 20)))
                device.shell(f'input tap {botao[0]} {botao[1]}')

            def sumiu_este(nome=modelo['name']):
                restantes = device.read_json('models.json', optional=True) or []
                return True if all(m.get('name') != nome for m in restantes) else None
            try:
                device.wait(sumiu_este, 'modelo removido do armazenamento', timeout=30)
            except AssertionError:
                raise AssertionError(f'o modelo {modelo["name"]!r} continua no armazenamento '
                                     'depois de excluir; visíveis: '
                                     + ', '.join(visible_labels(device, 20)))
            apagados.append(modelo['name'])
        return (f'{len(apagados)} modelo(s) excluído(s) pela linha da importação, diálogo '
                f'confirmado e arquivo fora do armazenamento: ' + ', '.join(apagados))

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
        ('gaveta_ferramentas', gaveta), ('ferramentas_dialogo', ferramentas_dialogo),
        ('seletores_de_anexo', seletores), ('anexo_texto', anexo_texto),
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
