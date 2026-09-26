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
