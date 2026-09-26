"""Os ajudantes do harness também rodam no host — antes de gastar um emulador.

Motivo direto: a rodada 36192982173 perdeu as fases de desempenho e de funções
porque `prefill_metric` chamava `re.findall` sem o módulo importado. Nada disso
precisava de um aparelho para ser descoberto: as funções são puras (ou quase) e
podem ser exercitadas aqui, com um aparelho de mentira.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# Os módulos do harness importam uns aos outros pelo nome (android_checks vive em
# scripts/), então o caminho entra antes de qualquer import deles.
sys.path.insert(0, str(ROOT / 'scripts'))

from android_checks import select_exact_documents  # noqa: E402


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


harness = load('harness_under_test', 'scripts/test_android.py')


def perf_entry(tokens_s, ui_first, first_token, prompt=800, reused=40, prefill_ns=800_000_000):
    return {'tokens_s': tokens_s, 'ui_first_text_s': ui_first, 'first_token_s': first_token,
            'prefill': {'prompt_tokens': prompt, 'reused_tokens': reused,
                        'fresh_tokens': prompt - reused, 'prefill_s': prefill_ns / 1e9,
                        'prefill_ms_per_token': round(prefill_ns / 1e6 / (prompt - reused), 3)}}


Android = harness.Android


class SubmitDevice:
    """Aparelho de mentira para exercitar o envio: o campo e o botão como eu quiser."""

    def __init__(self, field_text, persist_after=1, ready_after=0):
        self.field = field_text
        self.persist_after = persist_after
        self.taps = 0
        self.actions = []
        # Quantas leituras do compositor ainda encontram o botão desabilitado (o
        # aplicativo desabilita Enviar enquanto carrega o modelo).
        self.ready_after = ready_after
        self.ready_checks = 0

    def composer_ready(self):
        self.ready_checks += 1
        return self.ready_checks > self.ready_after

    def send(self, prompt, clear_log=True, typed_pause=0.0):
        self.actions.append(('send', prompt, clear_log))

    def composer_text(self):
        return self.field

    def clear_composer(self, size):
        self.actions.append(('clear', size))
        self.field = ''

    def tap(self, **selector):
        self.actions.append(('tap', selector))
        if selector.get('text') == 'Enviar':
            self.taps += 1
        return True

    def ui(self):
        # Tela mínima para a mensagem de erro do submit listar os rótulos visíveis.
        return ('<hierarchy><node package="com.ggufchat.app" class="android.widget.EditText" '
                'text="" enabled="true" bounds="[0,0][10,10]" />'
                '<node package="com.ggufchat.app" class="android.widget.Button" text="Enviar" '
                'enabled="true" bounds="[0,0][10,10]" /></hierarchy>')

    def wait(self, condition, what, timeout=20):
        for _ in range(5):
            result = condition()
            if result:
                return result
        raise AssertionError(f'Timeout: {what}')

    def read_json(self, name):
        if self.taps >= self.persist_after:
            return [{'id': 'chat-1', 'messages': [{'role': 'user', 'content': self.prompt}]}]
        return [{'id': 'chat-1', 'messages': []}]


def test_submit_insists_until_the_app_persists_the_prompt(tmp_path):
    """O botão Enviar pode estar desabilitado no primeiro toque (app carregando).

    Rodada 36247594609: o prompt nunca foi persistido e a rodada inteira caiu com
    'Timeout: prompt enviado'. Agora o toque é repetido até o app persistir.
    """
    device = SubmitDevice('Reply in English: ok', persist_after=2)
    device.prompt = 'Reply in English: ok'
    device.evidence = tmp_path
    device.last_chat = {'id': 'chat-1'}
    Android.submit(device, device.prompt, label='stage')
    assert device.taps == 2
    assert (tmp_path / 'stage-composer.txt').read_text().startswith('campo conferido')


def test_submit_retypes_when_the_field_did_not_receive_the_text(tmp_path):
    device = SubmitDevice('texto errado no campo', persist_after=1)
    device.prompt = 'o prompt correto'
    device.evidence = tmp_path
    device.last_chat = {'id': 'chat-1'}

    def composer_text():
        return device.field
    # O campo devolve o texto errado na primeira leitura e o certo depois de limpar.
    state = {'n': 0}

    def fake_composer():
        state['n'] += 1
        return device.field if state['n'] == 1 else device.prompt
    device.composer_text = fake_composer
    Android.submit(device, device.prompt, label='stage')
    assert ('clear', len('texto errado no campo')) in device.actions
    assert (tmp_path / 'stage-composer.txt').read_text().startswith('campo conferido')


def search_entry(used_ms, provider, sources=5):
    entry = perf_entry(9.0, 1.0, 0.9)
    entry['search'] = {'used_ms': used_ms, 'provider': provider, 'sources': sources,
                       'budget_ms': 12000, 'exhausted': False}
    return entry


def test_search_experiment_compares_sequence_and_race_in_the_same_round():
    perf = {'vulkan': perf_entry(1.0, 20.0, 18.0),
            'search-online': search_entry(1700, 'DuckDuckGo'),
            'search-race': search_entry(520, 'Wikipédia'),
            'search-cache': {'stage': 'search-cache',
                             'search': {'used_ms': 0, 'provider': 'Wikipédia', 'sources': 4}}}
    report = harness.performance_report(perf)
    experiment = report['search_experiment']
    assert experiment['status'] == 'MEDIDO'
    assert experiment['gain_x'] == pytest.approx(1700 / 520, abs=0.01)
    assert experiment['race_provider'] == 'Wikipédia'
    assert 'consulta repetida' in experiment['cache_detail']
    json.dumps(report)


def test_search_experiment_declares_absence_without_both_measurements():
    report = harness.performance_report({'vulkan': perf_entry(1.0, 20.0, 18.0),
                                         'search-online': search_entry(1700, 'DuckDuckGo')})
    assert report['search_experiment']['status'] == 'NOT_MEASURED'
    assert 'faltou a medição' in report['search_experiment']['detail']


def test_search_cache_hit_and_race_winner_read_the_engine_log():
    spec = importlib.util.spec_from_file_location('checks_search', ROOT / 'scripts/android_checks.py')
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)
    log = ('GGUF_SEARCH_CACHE hit=1 provider=Wikipédia results=4 age_ms=812 ttl_ms=60000 '
           'size=1 query=capital\n'
           'GGUF_SEARCH_RACE winner=Wikipédia results=4 candidates_pending=1 candidates=2\n')
    assert checks.search_cache_hit(log) == {'provider': 'Wikipédia', 'results': 4,
                                            'age_ms': 812, 'ttl_ms': 60000}
    assert checks.search_race_winner(log) == {'winner': 'Wikipédia', 'results': 4,
                                             'pending': 1, 'candidates': 2}
    # Rodada sem corrida nem cache: nada é inventado.
    assert checks.search_cache_hit('GGUF_SEARCH provider=DDG results=5 ms=1700 query=x') is None
    assert checks.search_race_winner('GGUF_SEARCH provider=DDG results=5 ms=1700 query=x') is None


def kv_entry(tokens_s, kv, ui_first=1.0):
    entry = perf_entry(tokens_s, ui_first, ui_first - 0.1)
    entry['kv_cache'] = {'kv': kv, 'flash_attn_requested': 'AUTO'}
    return entry


def test_kv_experiment_compares_the_two_caches_and_stays_out_of_the_throughput_race():
    perf = {'vulkan': perf_entry(1.0, 20.0, 18.0),
            'cpu-threads-auto': perf_entry(9.0, 0.4, 0.3),
            'decode-kv-f16': kv_entry(9.0, 'F16'),
            'decode-kv-q8': kv_entry(11.7, 'Q8_0')}
    report = harness.performance_report(perf)
    # A etapa de cache quantizado não entra na conta de ganho contra a linha de base.
    assert 'decode-kv-q8' not in report['candidates']
    experiment = report['kv_experiment']
    assert experiment['status'] == 'MEDIDO'
    assert experiment['gain_x'] == pytest.approx(1.3, abs=0.01)
    assert experiment['quantized_cache_applied'] == 'Q8_0'
    assert report['regressions'] == []
    json.dumps(report)


def test_kv_experiment_refuses_to_claim_a_gain_the_log_does_not_show():
    perf = {'vulkan': perf_entry(1.0, 20.0, 18.0),
            'decode-kv-f16': kv_entry(9.0, 'F16'),
            'decode-kv-q8': kv_entry(11.7, 'F16')}
    report = harness.performance_report(perf)
    # Sem o log provando o cache quantizado, não existe ganho declarado.
    assert report['kv_experiment']['status'] == 'NAO_APLICADO'
    assert 'não declara ganho' in report['kv_experiment']['detail']


def test_kv_experiment_declares_absence_instead_of_guessing():
    report = harness.performance_report({'vulkan': perf_entry(1.0, 20.0, 18.0),
                                         'decode-kv-q8': kv_entry(11.7, 'Q8_0')})
    assert report['kv_experiment']['status'] == 'NOT_MEASURED'
    assert 'faltou a taxa' in report['kv_experiment']['detail']


def test_kv_cache_reads_the_type_the_engine_logged():
    spec = importlib.util.spec_from_file_location('checks_kv', ROOT / 'scripts/android_checks.py')
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)
    log = ('GGUF_CONTEXT_TUNING batch=256 ubatch=128 threads=4 prefix_cache_supported=1 '
           'prefill_policy=larger_lots kv=Q8_0 fa_requested=AUTO')
    assert checks.kv_cache(log) == {'kv': 'Q8_0', 'flash_attn_requested': 'AUTO'}
    # Rodada antiga, sem os campos novos: nada é inventado.
    assert checks.kv_cache('GGUF_CONTEXT_TUNING batch=256 ubatch=128 threads=4 '
                           'prefix_cache_supported=1 prefill_policy=larger_lots') is None
    assert checks.context_tuning(log)['ubatch'] == 128


def test_submit_waits_for_the_composer_instead_of_tapping_a_disabled_button(tmp_path):
    """O aplicativo desabilita o compositor enquanto carrega o modelo.

    Rodada 36253269770: o toque em Enviar falhou com "Controle não encontrado"
    porque o `position` ignora controle desabilitado — o envio tem que esperar o
    aplicativo, e não desistir antes dele.
    """
    device = SubmitDevice('Reply in English: ok', persist_after=1, ready_after=2)
    device.prompt = 'Reply in English: ok'
    device.evidence = tmp_path
    device.last_chat = {'id': 'chat-1'}
    Android.submit(device, device.prompt, label='stage')
    assert device.ready_checks >= 3, 'o envio tocou o botão antes de o compositor ficar pronto'
    assert device.taps == 1


def test_submit_declares_when_the_composer_never_becomes_ready(tmp_path):
    device = SubmitDevice('', persist_after=1, ready_after=99)
    device.prompt = 'prompt'
    device.evidence = tmp_path
    device.last_chat = {'id': 'chat-1'}
    with pytest.raises(AssertionError) as error:
        Android.submit(device, device.prompt, label='stage')
    assert 'campo de mensagem e botão Enviar habilitados' in str(error.value)
    assert device.taps == 0, 'nenhum toque cego em Enviar quando o compositor não existe'


def test_submit_fails_with_the_field_and_the_visible_labels(tmp_path):
    device = SubmitDevice('', persist_after=99)
    device.prompt = 'nunca persiste'
    device.evidence = tmp_path
    device.last_chat = {'id': 'chat-1'}
    with pytest.raises(AssertionError) as error:
        Android.submit(device, device.prompt, label='stage')
    assert 'três toques' in str(error.value)
    assert device.taps == 3


class SendDevice:
    """Aparelho de mentira para o `send` de baixo nível (digitar e tocar em Enviar).

    O `SubmitDevice` acima substitui o próprio `send`, então não consegue provar o
    comportamento dele. Aqui só existem as primitivas que o `send` de verdade usa:
    `wait`, `composer_ready`, `field_focused`, `ui`, `tap`, `shell` e `adb`.
    """

    def __init__(self, ready_after=0, button_after=0):
        self.actions = []
        self.taps = 0
        # Leituras do compositor que ainda encontram campo/botão desabilitados.
        self.ready_after = ready_after
        self.ready_checks = 0
        # Leituras que ainda encontram o botão Enviar desabilitado depois da digitação.
        self.button_after = button_after
        self.button_checks = 0
        self.focused = False

    def adb(self, *args, check=True):
        self.actions.append(('adb', args))
        return ''

    def shell(self, command, check=True):
        self.actions.append(('shell', command))
        return ''

    def composer_ready(self):
        self.ready_checks += 1
        return self.ready_checks > self.ready_after

    def field_focused(self):
        return self.focused

    def ui(self):
        # `position` exige enabled=true e área positiva: é o que o extrator real vê
        # quando o aplicativo ainda carrega o modelo (Enviar desabilitado).
        self.button_checks += 1
        enabled = 'true' if self.button_checks > self.button_after else 'false'
        return ('<hierarchy><node package="com.ggufchat.app" class="android.widget.EditText" '
                'text="oi" enabled="true" bounds="[0,0][10,10]" />'
                f'<node package="com.ggufchat.app" class="android.widget.Button" text="Enviar" '
                f'enabled="{enabled}" bounds="[0,0][10,10]" /></hierarchy>')

    def wait(self, condition, what, timeout=20):
        for _ in range(50):
            result = condition()
            if result:
                return result
        raise AssertionError(f'Timeout: {what}')

    def tap(self, **selector):
        if selector.get('text') == 'Enviar':
            if self.button_checks <= self.button_after:
                raise AssertionError(f"Controle não encontrado: {selector}")  # toque cego
            self.taps += 1
        self.actions.append(('tap', selector))
        return True


def test_send_waits_for_the_composer_before_typing_and_before_tapping():
    """Rodada 36255713807: `send` tocava em Enviar sem esperar o compositor.

    A fase de desempenho morreu com "Controle não encontrado: Enviar" enquanto o
    aplicativo ainda carregava o modelo — o `submit` já esperava, o `send` não.
    """
    device = SendDevice(ready_after=2, button_after=2)
    Android.send(device, 'oi')
    assert device.ready_checks >= 3, 'digitou antes de o compositor estar habilitado'
    assert device.taps == 1, 'não tocou em Enviar exatamente uma vez depois de pronto'
    digitou = [a for a in device.actions if a[0] == 'shell' and 'input text' in a[1]]
    enviou = [a for a in device.actions if a[0] == 'tap' and a[1].get('text') == 'Enviar']
    assert digitou and enviou, 'faltou digitar ou enviar'
    assert device.actions.index(digitou[0]) > 0
    assert device.button_checks > device.button_after, 'o botão nunca foi conferido habilitado'


def test_send_declares_instead_of_tapping_a_composer_that_never_appears():
    device = SendDevice(ready_after=99)
    with pytest.raises(AssertionError) as error:
        Android.send(device, 'oi')
    assert 'compositor' in str(error.value)
    assert device.taps == 0, 'nenhum toque cego em Enviar'
    assert not [a for a in device.actions if a[0] == 'shell' and 'input text' in a[1]], \
        'não pode digitar num campo que não existe'


class ScreenDevice:
    """Aparelho de mentira que muda de tela: serve para o toque e a foto da janela.

    `ui` é o MÉTODO DE VERDADE: o que está sob teste é a retentativa dele quando a
    foto sai sem nenhum nó do aplicativo; o que o aparelho de mentira troca é só a
    origem da foto (`_ui_dump`).
    """

    ui = Android.ui

    def __init__(self, screens, evidence):
        self.screens = list(screens)
        self.actions = []
        self.dumps = 0
        self.evidence = evidence
        self.counter = 0
        self.last_ui_summary = None

    def _ui_dump(self):
        self.dumps += 1
        return self.screens[0] if len(self.screens) == 1 else self.screens.pop(0)

    def shell(self, command, check=True):
        self.actions.append(command)
        # O aplicativo existe nesta simulação: é o que a retentativa da foto exige.
        return '4321\n' if command.startswith('pidof') else ''

    def alive(self):
        return 1234

    def wait(self, condition, what, timeout=20):
        for _ in range(50):
            result = condition()
            if result:
                return result
        raise AssertionError(f'Timeout: {what}')


def test_tap_retries_a_control_that_a_transition_hid_for_a_moment(tmp_path):
    """Rodada 36255713807: o botão Enviar estava na tela e o toque desistiu.

    A foto pegou a janela de cima (teclado aberto numa transição), sem nós do
    aplicativo; o toque precisa de uma segunda foto antes de acusar ausência.
    """
    vazio = ('<hierarchy><node package="com.android.inputmethod" text="q" enabled="true" '
             'bounds="[0,0][10,10]" /></hierarchy>')
    device = ScreenDevice([vazio, screen('Escreva sua mensagem…', 'Enviar')], tmp_path)
    assert Android.tap(device, text='Enviar', contains=True) is True
    assert any(action.startswith('input tap') for action in device.actions)


def test_tap_says_the_control_is_missing_with_what_is_visible(tmp_path):
    device = ScreenDevice([screen('Ajustes')], tmp_path)
    with pytest.raises(AssertionError) as error:
        Android.tap(device, text='Enviar', contains=True)
    assert 'Controle não encontrado' in str(error.value)
    assert 'Ajustes' in str(error.value), 'a mensagem precisa listar o que estava na tela'


def test_ui_refuses_a_photo_of_another_window_and_hides_the_keyboard(tmp_path):
    """A foto pode sair da janela de cima; ESC recolhe o teclado sem fechar a tela."""
    vazio = ('<hierarchy><node package="com.android.inputmethod" text="q" enabled="true" '
             'bounds="[0,0][10,10]" /></hierarchy>')
    device = ScreenDevice([vazio, screen('Enviar')], tmp_path)
    xml = Android.ui(device)
    assert 'Enviar' in xml
    assert 'input keyevent 111' in device.actions, 'recolher o teclado antes da segunda foto'


class PickerDevice:
    """DocumentsUI de mentira: só marca o que for marcado com o gesto certo.

    `selecionados` muda de verdade quando chega um toque longo (swipe parado) ou um
    toque simples já em modo de seleção — é isso que o ajudante tem de provocar.
    """

    PACKAGE = 'com.google.android.documentsui'

    def __init__(self, names, modo):
        self.names = list(names)
        self.modo = modo           # 'toque-longo' (só o gesto longo marca) ou 'nunca'
        self.selecionados = set()
        self.actions = []
        self.rows_dumps = 0

    def ui(self):
        self.rows_dumps += 1
        linhas = []
        for indice, nome in enumerate(self.names):
            marcado = 'true' if nome in self.selecionados else 'false'
            topo = 200 + indice * 220
            linhas.append(
                f'<node package="{self.PACKAGE}" class="android.widget.LinearLayout" '
                f'resource-id="com.google.android.documentsui:id/item_root" selected="{marcado}" '
                f'bounds="[0,{topo}][1080,{topo + 198}]" clickable="true">'
                f'<node package="{self.PACKAGE}" class="android.widget.ImageView" '
                f'resource-id="com.google.android.documentsui:id/icon_thumb" '
                f'bounds="[44,{topo + 44}][154,{topo + 154}]" />'
                f'<node package="{self.PACKAGE}" class="android.widget.TextView" '
                f'text="{nome}" bounds="[198,{topo + 42}][838,{topo + 101}]" enabled="true" />'
                '</node>')
        contador = ''
        if self.selecionados:
            contador = (f'<node package="{self.PACKAGE}" class="android.widget.TextView" '
                        f'text="{len(self.selecionados)} selected" enabled="true" '
                        f'bounds="[0,0][10,10]" />')
        return '<hierarchy>' + ''.join(linhas) + contador + '</hierarchy>'

    def _linha(self, y):
        return self.names[(y - 200) // 220]

    def shell(self, command, check=True):
        self.actions.append(command)
        tokens = command.split()
        if tokens[:3] == ['input', 'motionevent', 'DOWN']:
            # O toque longo REAL: o dedo fica preso e o app entra em seleção com ele
            # ainda abaixado — é o que o harness tem de provocar (o UP vem depois).
            if self.modo == 'toque-longo':
                y = int(tokens[4])
                self.selecionados.add(self._linha(y))
                self.preso = (int(tokens[3]), y)
        elif tokens[:3] == ['input', 'motionevent', 'UP']:
            self.preso = None
        elif tokens[:2] == ['input', 'tap']:
            # Toque simples só marca se a seleção múltipla já estiver aberta.
            y = int(tokens[3])
            if self.modo == 'toque-longo' and self.selecionados:
                self.selecionados.add(self._linha(y))
        elif tokens[:2] == ['input', 'touchscreen']:
            # swipe x1 y1 x2 y2 duração — só marca com deslocamento de verdade.
            assert tokens[4] != tokens[6] or tokens[5] != tokens[7], \
                f'swipe sem MOVE não é toque longo: {command}'
            if self.modo == 'toque-longo':
                self.selecionados.add(self._linha(int(tokens[5])))
        return ''

    def wait(self, condition, what, timeout=20):
        for _ in range(6):
            resultado = condition()
            if resultado:
                return resultado
        raise AssertionError(f'Timeout: {what}')


def test_select_exact_documents_enters_selection_with_a_long_press():
    """Rodada 36261210088: toques simples no "ícone" não marcaram nada.

    O gesto que o Android garante é o toque longo para entrar em seleção múltipla;
    depois dele, toque simples alterna a marcação. A prova é o contador do próprio
    seletor.
    """
    device = PickerDevice(['SmolVLM-256M-Instruct-Q8_0.gguf', 'mmproj-SmolVLM-256M-Instruct-Q8_0.gguf'],
                          modo='toque-longo')
    select_exact_documents(device, list(device.names))
    gestos = ' | '.join(device.actions)
    assert 'input motionevent DOWN' in gestos, 'sem toque longo não há seleção múltipla'
    assert 'input motionevent UP' in gestos, 'o dedo tem de ser solto depois de marcar'
    assert device.selecionados == set(device.names)


def test_select_exact_documents_declares_when_no_gesture_marks_the_row():
    device = PickerDevice(['a.gguf', 'b.gguf'], modo='nunca')
    with pytest.raises(AssertionError) as error:
        select_exact_documents(device, list(device.names))
    assert 'não consegui marcar a.gguf' in str(error.value)
    assert 'não marcaram a linha' in str(error.value)
    # O último recurso tem de ter MOVE (swipe com deslocamento), nunca swipe parado.
    assert not any(a.startswith('input touchscreen swipe')
                   and a.split()[4] == a.split()[6] and a.split()[5] == a.split()[7]
                   for a in device.actions)


def test_ui_does_not_blame_the_app_when_another_package_is_on_screen(tmp_path):
    """A fixture de texto roda no aparelho SEM processo do aplicativo.

    A retentativa da foto (rodada 36255713807) chamava `alive()` e a fase de texto
    passou a falhar com "Processo do app ausente" mesmo com a fixture aprovada.
    """
    outro = ('<hierarchy><node package="com.ggufchat.texttest" '
             'text="Ok: inline=ok" enabled="true" bounds="[0,0][10,10]" /></hierarchy>')
    device = ScreenDevice([outro], tmp_path)
    device.shell_answers = {'pidof com.ggufchat.app': ''}

    def shell(command, check=True):
        device.actions.append(command)
        return device.shell_answers.get(command, '')
    device.shell = shell
    xml = Android.ui(device)
    assert 'texttest' in xml, 'a foto legítima de outro pacote precisa ser devolvida'
    assert 'input keyevent 111' not in device.actions, 'não há teclado do app para recolher'


def test_prefill_experiment_uses_its_own_metric_and_stays_out_of_the_throughput_race():
    perf = {'vulkan': perf_entry(1.0, 20.0, 18.0),
            'cpu-threads-auto': perf_entry(9.0, 0.4, 0.3),
            'prefill-ubatch-128': perf_entry(9.0, 6.0, 5.9, prompt=700, reused=0,
                                             prefill_ns=6_000_000_000),
            'prefill-ubatch-256': perf_entry(9.0, 4.0, 3.9, prompt=700, reused=0,
                                             prefill_ns=3_000_000_000)}
    report = harness.performance_report(perf)
    # A comparação de sub-lote mede pré-preenchimento: fora da conta de ganho/regressão.
    assert 'prefill-ubatch-128' not in report['candidates']
    assert 'prefill-ubatch-256' not in report['candidates']
    experiment = report['prefill_experiment']
    assert experiment['status'] == 'MEDIDO'
    assert experiment['best'] == 'prefill-ubatch-256'
    assert experiment['gain_x'] == pytest.approx(2.0, abs=0.01)
    assert 'regressions' in report and report['regressions'] == []
    json.dumps(report)  # a evidência precisa ser serializável


def test_prefill_experiment_declares_absence_instead_of_guessing():
    report = harness.performance_report({'vulkan': perf_entry(1.0, 20.0, 18.0),
                                         'prefill-ubatch-256': perf_entry(9.0, 4.0, 3.9)})
    assert report['prefill_experiment']['status'] == 'NOT_MEASURED'
    assert 'faltou a métrica' in report['prefill_experiment']['detail']


class FakeDevice:
    """Aparelho de mentira: só o que os ajudantes usam, com a tela que eu escolho."""

    def __init__(self, screens, package='com.ggufchat.app'):
        self.screens = list(screens)
        self.package = package
        self.actions = []

    def ui(self):
        # Devolve a tela atual; só avança quando há mais de uma (a última fica).
        return self.screens[0] if len(self.screens) == 1 else self.screens.pop(0)

    def shell(self, command, check=True):
        self.actions.append(command)
        return ''


def screen(*labels, package='com.ggufchat.app'):
    # enabled=true e bounds com área são exigidos pelo extrator real: um nó
    # invisível ou desabilitado não é um controle que o usuário alcança.
    nodes = ''.join(f'<node package="{package}" text="{label}" content-desc="" enabled="true" '
                    f'bounds="[0,0][10,10]" />' for label in labels)
    return f'<hierarchy>{nodes}</hierarchy>'


def test_pref_value_reads_the_two_formats_android_writes():
    """O ajuste persistido tem o valor como ATRIBUTO — `>1024<` nunca casaria."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('checks', ROOT / 'scripts/android_checks.py')
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)
    atributo = '<int name="contextSize" value="1024" />'
    elemento = '<int name="contextSize">1024</int>'
    assert checks.pref_value(atributo, 'contextSize') == '1024'
    assert checks.pref_value(elemento, 'contextSize') == '1024'
    assert checks.pref_value(atributo, 'nThreads') is None
    # A varredura precisa usar o leitor, não um casamento de texto improvisado.
    sweep = (ROOT / 'scripts/test_functions_android.py').read_text()
    assert "pref_value(prefs(), 'contextSize')" in sweep
    assert 'name="contextSize"[^>]*>' not in sweep


def test_visible_labels_lists_what_is_on_screen():
    sweep = load('sweep_under_test', 'scripts/test_functions_android.py')
    device = FakeDevice([screen('Nova conversa', 'Ajustes')])
    assert sweep.visible_labels(device) == ['Nova conversa', 'Ajustes']


def test_scroll_to_swipes_and_finds_the_label_below_the_fold():
    sweep = load('sweep_under_test', 'scripts/test_functions_android.py')
    device = FakeDevice([screen('Camadas na GPU')] * 8 +
                        [screen('Camadas na GPU', 'Salvar ajustes')])
    assert sweep.scroll_to(device, 'Salvar ajustes') is True
    assert any('swipe' in action for action in device.actions)


def tools_screen(labels, package='com.ggufchat.app', x_start=44, width=150):
    """Tela com a linha de ferramentas: cada botão deslocado para a direita."""
    nodes = []
    x = x_start
    for label in labels:
        nodes.append(f'<node package="{package}" class="android.widget.Button" text="{label}" '
                     f'content-desc="" enabled="true" bounds="[{x},1979][{x + width},2078]" />')
        x += width + 10
    return f'<hierarchy>{"".join(nodes)}</hierarchy>'


def test_tools_button_refuses_a_button_whose_centre_is_off_screen():
    """Rodada 36245048939: a linha terminava em "Áudio" cortado e "Arquivo" não existia
    como alvo de toque — o centro ficava fora da tela."""
    sweep = load('sweep_under_test', 'scripts/test_functions_android.py')
    # "Áudio" termina em 1036 (cortado) e "Arquivo" começa depois de 1080.
    device = FakeDevice([tools_screen(['Foto', 'Vídeo', 'Áudio', 'Arquivo', 'Ferramentas'],
                                      x_start=955)],)
    assert sweep.tools_button(device, 'Arquivo') is None
    assert sweep.tools_button(device, 'Áudio') is None


def test_scroll_tools_to_brings_the_last_button_into_reach():
    sweep = load('sweep_under_test', 'scripts/test_functions_android.py')
    # A cada rolagem a linha anda 200 px para a esquerda (o conteúdo é revelado).
    telas = [tools_screen(['Sistema', 'Thinking', 'Busca ON', 'Foto', 'Vídeo', 'Áudio',
                           'Arquivo', 'Ferramentas'], x_start=44),
             tools_screen(['Sistema', 'Thinking', 'Busca ON', 'Foto', 'Vídeo', 'Áudio',
                           'Arquivo', 'Ferramentas'], x_start=-160),
             tools_screen(['Sistema', 'Thinking', 'Busca ON', 'Foto', 'Vídeo', 'Áudio',
                           'Arquivo', 'Ferramentas'], x_start=-520),
             tools_screen(['Sistema', 'Thinking', 'Busca ON', 'Foto', 'Vídeo', 'Áudio',
                           'Arquivo', 'Ferramentas'], x_start=-520)]
    device = FakeDevice(telas)
    ponto = sweep.scroll_tools_to(device, 'Ferramentas')
    assert ponto is not None and ponto[0] <= 1070
    assert any('swipe' in action for action in device.actions)


def test_scroll_tools_to_says_nothing_when_the_button_is_nowhere():
    sweep = load('sweep_under_test', 'scripts/test_functions_android.py')
    device = FakeDevice([tools_screen(['Foto', 'Vídeo'], x_start=44)] * 12)
    assert sweep.scroll_tools_to(device, 'Ferramentas') is None


def test_scroll_to_finds_what_is_above_the_current_position():
    """A rodada 36238272473 ficou no fim da lista e procurava só para baixo."""
    sweep = load('sweep_under_test', 'scripts/test_functions_android.py')
    device = FakeDevice([screen('Tamanho de contexto (tokens)')] * 6 +
                        [screen('Rodapé da lista', 'Salvar ajustes')] * 8)
    assert sweep.scroll_to(device, 'Tamanho de contexto') is True


def test_scroll_to_gives_up_without_lying():
    sweep = load('sweep_under_test', 'scripts/test_functions_android.py')
    device = FakeDevice([screen('Camadas na GPU')] * 6)
    assert sweep.scroll_to(device, 'Salvar ajustes') is False
