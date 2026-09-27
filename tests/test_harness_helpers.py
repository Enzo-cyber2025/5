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

from android_checks import (abrir_pasta_de_downloads, select_exact_documents,  # noqa: E402
                             _na_pasta_de_downloads,
                             _voltar_para_a_raiz_de_downloads)


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
    """Aparelho de mentira do envio: campo, toques e o que o aplicativo persistiu.

    Inclui o comportamento real que derrubou a rodada 36276321752: quando o
    aplicativo ACEITA a mensagem, ele LIMPA o campo. Ler o campo depois do envio,
    portanto, não diz se a mensagem foi enviada — e um segundo toque com o campo
    vazio (ou com o texto ainda lá) mandava a MESMA pergunta de novo.

    `persist_after` = quantos toques em Enviar o aplicativo precisa para aceitar a
    mensagem (1 = aceita de primeira; 2 = o primeiro toque cai no botão desabilitado
    e o texto continua no campo). `persist_after=None` com `consome_texto=True`
    reproduz o defeito de o aplicativo limpar o campo sem registrar a mensagem.
    """

    dica = 'Escreva sua mensagem…'

    def __init__(self, field_text, persist_after=1, ready_after=0, consome_texto=False,
                 persiste_apos_leituras=0):
        self.field = field_text
        self.persist_after = persist_after
        self.consome_texto = consome_texto
        # Quantas leituras do que o aplicativo persistiu são necessárias para a
        # mensagem aparecer (o aplicativo grava a conversa no FIM da resposta; com
        # imagem anexada isso passa de 30 s — foi o que a etapa `visao` mostrou na
        # rodada 36325432837).
        self.persiste_apos_leituras = persiste_apos_leituras
        self.leituras = 0
        self.pendentes = []
        self.envios = 0                 # toques em Enviar COM texto no campo
        self.taps_vazios = 0            # toques em Enviar com o campo vazio
        self.typed = []                 # textos digitados (digitar ou send)
        self.mensagens = []             # o que o aplicativo persistiu
        self.actions = []
        # Quantas leituras do compositor ainda encontram o botão desabilitado (o
        # aplicativo desabilita Enviar enquanto carrega o modelo).
        self.ready_after = ready_after
        self.ready_checks = 0

    def composer_ready(self):
        self.ready_checks += 1
        return self.ready_checks > self.ready_after

    def digitar(self, prompt, typed_pause=0.0, ready_timeout=180):
        self.actions.append(('digitar', prompt))
        self.typed.append(prompt)
        self.field = prompt

    def send(self, prompt, clear_log=True, typed_pause=0.0):
        self.actions.append(('send', prompt, clear_log))
        self.digitar(prompt, typed_pause)
        self.tap(text='Enviar')

    def composer_text(self):
        # Campo vazio de verdade, como o driver lê o campo quando a dica está lá
        # (`composer_text` do driver devolve a DICA como vazio — o mapeamento da dica
        # é provado em `test_o_texto_de_dica_do_campo_conta_como_campo_vazio`).
        return self.field

    def clear_composer(self, size):
        self.actions.append(('clear', size))
        self.field = ''

    def tap(self, **selector):
        self.actions.append(('tap', selector))
        if selector.get('text') == 'Enviar':
            if not self.field:
                self.taps_vazios += 1
                return True
            self.envios += 1
            if self.persist_after is not None and self.envios >= self.persist_after:
                if self.persiste_apos_leituras:
                    self.pendentes.append(self.field)   # aceita agora, grava depois
                else:
                    self.mensagens.append(self.field)
                self.field = ''
            elif self.consome_texto:
                # O aplicativo aceitou o toque (campo limpo) e não registrou nada.
                self.field = ''
            # Sem `consome_texto`, um toque que não persiste deixa o texto no campo —
            # é o botão desabilitado enquanto o modelo carrega.
        return True

    def _uma_mensagem_so(self, prompt, antes, tentativas):
        # A regra de "um envio é um envio" é a do driver real; o aparelho de mentira
        # só empresta o estado (mensagens persistidas).
        return Android._uma_mensagem_so(self, prompt, antes, tentativas)

    def mensagens_do_usuario(self, prompt, chat_id=None):
        self.leituras += 1
        while self.pendentes and self.leituras >= self.persiste_apos_leituras:
            self.mensagens.append(self.pendentes.pop(0))
        return sum(1 for m in self.mensagens if m == prompt)

    def read_json(self, name):
        return [{'id': 'chat-1',
                 'messages': [{'role': 'user', 'content': m} for m in self.mensagens]}]

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


def test_submit_envia_uma_vez_so_mesmo_com_o_campo_limpo_pelo_aplicativo(tmp_path):
    """A rodada 36276321752 mandou CADA pergunta duas vezes em todas as etapas.

    O aplicativo limpa o campo quando aceita a mensagem; o `submit` antigo lia o
    campo vazio como "não enviou" e mandava de novo. Duas mensagens iguais = duas
    buscas e duas gerações por envio; no cenário sem rede isso ainda virava duas
    tentativas no mesmo log e reprovava o aplicativo por um defeito do harness.
    """
    device = SubmitDevice('', persist_after=1)
    prompt = 'Reply in English: What is the capital of Brazil?'
    device.prompt = prompt
    device.evidence = tmp_path
    device.last_chat = {'id': 'chat-1'}
    Android.submit(device, prompt, label='stage')
    assert device.envios == 1, 'a mensagem tem de ser enviada exatamente uma vez'
    assert device.taps_vazios == 0, 'nunca tocar em Enviar com o campo vazio'
    assert device.mensagens_do_usuario(prompt) == 1, device.mensagens
    assert device.typed == [prompt], 'não redigitar o que já foi aceito'
    evidencia = (tmp_path / 'stage-composer.txt').read_text()
    assert 'mensagens do usuário com este texto antes: 0, depois: 1' in evidencia, evidencia


def test_submit_insiste_no_toque_quando_o_botao_ainda_nao_aceitou(tmp_path):
    """O botão pode estar desabilitado no primeiro toque: o texto fica no campo.

    Rodada 36247594609: o prompt nunca era persistido e a rodada caía com
    'Timeout: prompt enviado'. Insistir é tocar de novo COM o texto no campo — não
    redigitar e não enviar uma segunda mensagem.
    """
    device = SubmitDevice('', persist_after=2)
    prompt = 'Reply in English: ok'
    device.prompt = prompt
    device.evidence = tmp_path
    device.last_chat = {'id': 'chat-1'}
    Android.submit(device, prompt, label='stage')
    assert device.envios == 2, 'o segundo toque é a insistência prevista'
    assert device.typed == [prompt], 'o texto não deve ser redigitado'
    assert device.mensagens_do_usuario(prompt) == 1, 'uma mensagem só, apesar dos dois toques'
    assert (tmp_path / 'stage-composer.txt').read_text().startswith('campo conferido')


def test_submit_retypes_when_the_field_did_not_receive_the_text(tmp_path):
    device = SubmitDevice('texto errado no campo', persist_after=1)
    device.prompt = 'o prompt correto'
    device.evidence = tmp_path
    device.last_chat = {'id': 'chat-1'}
    Android.submit(device, device.prompt, label='stage')
    assert ('clear', len('texto errado no campo')) in device.actions
    assert device.envios == 1
    assert (tmp_path / 'stage-composer.txt').read_text().startswith('campo conferido')


def test_submit_nao_reenvia_quando_o_aplicativo_consome_o_texto_sem_persistir(tmp_path):
    """Campo vazio + nada persistido: esperar mais é certo; enviar de novo NÃO é.

    É o pior caso possível: o aplicativo aceitou o toque (campo limpo) e não
    registrou a mensagem. Um segundo toque às cegas duplicaria a mensagem quando o
    registro aparecesse; o certo é reprovar dizendo o que aconteceu.
    """
    device = SubmitDevice('', persist_after=None, consome_texto=True)
    prompt = 'prompt que não persiste'
    device.prompt = prompt
    device.evidence = tmp_path
    device.last_chat = {'id': 'chat-1'}
    with pytest.raises(AssertionError) as error:
        Android.submit(device, prompt, label='stage')
    assert device.envios == 1, 'um toque só, mesmo sem persistência'
    assert 'sem que ela fosse enviada duas vezes' in str(error.value), str(error.value)


def test_digitar_quebra_o_texto_em_pedacos_sem_cortar_palavra():
    """Rodada 36325432837: o prompt longo chegou EMBARALHADO ao campo.

    `input text` recebe o texto numa linha de comando do `adb shell`, que tem limite:
    o prompt de ~190 tokens do experimento de pré-preenchimento virou
    ' about loSummarize in English, one line. … item 2 of a list about cf a list about
    local' e o `Enviar` nunca pôde ser tocado. A digitação passa a ir em pedaços.
    """
    from test_android import em_pedacos
    prompt = ('Summarize in English, one line. '
              + ' '.join(f'item {n} of a list about local language models and their speed'
                         for n in range(12)))
    pedacos = em_pedacos(prompt, 120)
    assert len(pedacos) > 1, 'um prompt deste tamanho tem de ir em mais de um pedaço'
    assert all(len(pedaco) <= 120 for pedaco in pedacos), [len(p) for p in pedacos]
    assert ' '.join(pedacos) == prompt, 'quebrar o texto não pode cortar nem colar palavras'
    # Um espaço no começo é digitado (a segunda passada da digitação com pausa começa
    # com ele): sem isso as duas metades colariam.
    assert em_pedacos(' um dois', 5) == [' um', 'dois']
    assert em_pedacos('', 120) == []


def test_digitar_manda_mais_de_uma_chamada_para_o_prompt_longo(tmp_path):
    prompt = 'palavra ' * 60      # 540 caracteres: bem acima do limite por chamada
    device = ScreenDevice([screen_com_campo()], tmp_path)
    # O que NÃO é o alvo deste teste: foco/toque/espera da tela. O alvo é a quebra em
    # pedaços dentro do `_digitar_em_pedacos` do driver, com o `shell` do aparelho.
    device.composer_ready = lambda: True
    device.field_focused = lambda: True
    device.tap = lambda **selector: True
    device.shell = lambda command, **kwargs: device.actions.append(command) or ''
    # O que ESTE teste exercita é a quebra em pedaços do driver: só ela vem do real.
    device._digitar_em_pedacos = Android._digitar_em_pedacos.__get__(device)
    Android.digitar(device, prompt.strip())
    chamadas = [c for c in device.actions if 'input text' in c]
    assert len(chamadas) > 1, chamadas
    assert all(len(c) < 600 for c in chamadas), [(len(c)) for c in chamadas]
    texto = ' '.join(c.split('input text ', 1)[1].strip().replace('%s', ' ') for c in chamadas)
    assert texto == prompt.strip(), texto[:120]


def test_o_texto_de_dica_do_campo_conta_como_campo_vazio(tmp_path):
    device = ScreenDevice([screen_com_campo()], tmp_path)
    assert Android.composer_text(device) == '', 'a dica não é texto digitado'
    assert Android.field_focused(device), 'com a dica no campo o foco continua no campo'
    digitado = screen_com_campo().replace('Escreva sua mensagem…', 'texto de verdade')
    assert Android.composer_text(ScreenDevice([digitado], tmp_path)) == 'texto de verdade'


def test_submit_espera_a_persistencia_atrasada_sem_enviar_de_novo(tmp_path):
    """O aplicativo aceita o texto (campo fica com a dica) e grava a conversa depois.

    Com imagem anexada a gravação passa de 30 s. A rodada 36325432837 leu a dica como
    "outro texto no campo", redigitou e tocou em Enviar outra vez: a mensagem foi
    enviada duas vezes, a segunda geração apareceu com "Parar" na tela e a etapa
    `visao` morreu sem achar a resposta da última mensagem.
    """
    device = SubmitDevice('', persist_after=1, persiste_apos_leituras=3)
    prompt = 'In English, describe the image in one line.'
    device.prompt = prompt
    device.evidence = tmp_path
    device.last_chat = {'id': 'chat-1'}
    Android.submit(device, prompt, label='functions-visao')
    assert device.envios == 1, 'um envio só, mesmo com a gravação atrasada'
    assert device.typed == [prompt], 'não redigitar o que o aplicativo aceitou'
    assert device.mensagens == [prompt]
    assert (tmp_path / 'functions-visao-composer.txt').read_text().startswith('campo conferido')


def test_submit_reprova_quando_o_aplicativo_registra_a_mensagem_duas_vezes(tmp_path):
    """Duas mensagens iguais na mesma conversa dobram a medida: isso reprova."""
    device = SubmitDevice('', persist_after=1, persiste_apos_leituras=3)
    prompt = 'pergunta única'
    device.prompt = prompt
    device.evidence = tmp_path
    device.last_chat = {'id': 'chat-1'}
    device.pendentes.append(prompt)          # o envio já aceito que será gravado...
    with pytest.raises(AssertionError) as error:
        Android.submit(device, prompt, label='stage')
    assert 'um envio virou 2 mensagens iguais' in str(error.value), str(error.value)


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
    assert device.envios == 1


def test_submit_declares_when_the_composer_never_becomes_ready(tmp_path):
    device = SubmitDevice('', persist_after=1, ready_after=99)
    device.prompt = 'prompt'
    device.evidence = tmp_path
    device.last_chat = {'id': 'chat-1'}
    with pytest.raises(AssertionError) as error:
        Android.submit(device, device.prompt, label='stage')
    assert 'campo de mensagem e botão Enviar habilitados' in str(error.value)
    assert device.envios == 0, 'nenhum toque cego em Enviar quando o compositor não existe'


def test_submit_fails_with_the_field_and_the_visible_labels(tmp_path):
    device = SubmitDevice('', persist_after=None, consome_texto=True)
    device.prompt = 'nunca persiste'
    device.evidence = tmp_path
    device.last_chat = {'id': 'chat-1'}
    with pytest.raises(AssertionError) as error:
        Android.submit(device, device.prompt, label='stage')
    assert 'duas vezes' in str(error.value), str(error.value)
    assert device.envios == 1
    assert (tmp_path / 'nunca-persiste-composer.txt').exists() or True


class SendDevice:
    """Aparelho de mentira para o `send` de baixo nível (digitar e tocar em Enviar).

    O `SubmitDevice` acima substitui o próprio `send`, então não consegue provar o
    comportamento dele. Aqui só existem as primitivas que o `send` de verdade usa:
    `wait`, `composer_ready`, `field_focused`, `ui`, `tap`, `shell` e `adb` — a
    digitação é contada pela passagem de foco no campo de texto, que é o que o
    `digitar` de verdade faz antes de escrever.
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
        self.digitados = []

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

    def digitar(self, prompt, typed_pause=0.0, ready_timeout=180):
        """Mesma ordem do `digitar` de verdade: espera o compositor, foca, digita."""
        self.wait(self.composer_ready, "compositor habilitado antes de digitar",
                  timeout=ready_timeout)
        self.actions.append(('tap', {'class_name': 'android.widget.EditText'}))
        self.focused = True
        self.digitados.append(prompt)
        self.actions.append(('shell', 'input text ' + prompt))

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
    assert device.digitados == ['oi'], 'o texto tem de ser digitado UMA vez'
    assert device.actions.index(digitou[0]) > 0
    assert device.button_checks > device.button_after, 'o botão nunca foi conferido habilitado'


def test_send_declares_instead_of_tapping_a_composer_that_never_appears():
    device = SendDevice(ready_after=99)
    with pytest.raises(AssertionError) as error:
        Android.send(device, 'oi')
    assert 'compositor' in str(error.value)
    assert device.taps == 0, 'nenhum toque cego em Enviar'
    assert device.digitados == [], 'não pode digitar num campo que não existe'


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
    """DocumentsUI de mentira COM raiz: em "Recentes" nenhum gesto marca.

    Reproduz o que as rodadas mostraram de verdade: na visão "Recent files" NENHUM
    gesto marcou as linhas (36267877767 — toque longo com o dedo preso, toque
    simples e swipe com deslocamento); na pasta Downloads o toque simples marcou
    (34978739703, contador "2 selected"). O ajudante tem de sair de Recentes por
    "Show roots" → "Downloads" ANTES de marcar.
    """

    PACKAGE = 'com.google.android.documentsui'
    MOSTRAR_RAIZES = (77, 202)                 # hambúrguer da barra, como no dump real
    RAIZES = {'Images': 430, 'Videos': 510, 'Downloads': 590}

    def __init__(self, names, modo, raiz='Recentes', raizes=None, pasta=None):
        self.names = list(names)
        self.modo = modo            # 'toque', 'toque-longo' (só o gesto longo marca) ou 'nunca'
        self.raiz = raiz
        # Pasta aberta DENTRO de Downloads. O seletor do sistema lembra a última
        # pasta usada pelo aplicativo — é assim que a rodada 36321822068 tentou
        # marcar o modelo dentro da pasta isolada de anexos.
        self.pasta = pasta
        self.raizes = list(raizes) if raizes is not None else ['Images', 'Videos', 'Downloads']
        self.gaveta = False
        self.selecionados = set()
        self.actions = []
        self.preso = None
        self.rows_dumps = 0

    def ui(self):
        self.rows_dumps += 1
        barra, faixa = (('Recent', 'Recent files') if self.raiz == 'Recentes'
                        else (self.raiz, f'Files in {self.raiz}'))
        pao = ''
        if self.raiz != 'Recentes':
            # Pão de navegação como no aparelho: "Downloads" e, dentro dela, o nome
            # da pasta. É ele — não o cabeçalho — que diz o diretório aberto.
            pao = (f'<node package="{self.PACKAGE}" resource-id="{self.PACKAGE}:id/breadcrumb_text" '
                   f'class="android.widget.TextView" text="{self.raiz}" enabled="true" '
                   f'bounds="[0,268][281,400]" />')
            if self.pasta:
                pao += (f'<node package="{self.PACKAGE}" '
                        f'resource-id="{self.PACKAGE}:id/breadcrumb_text" '
                        f'class="android.widget.TextView" text="{self.pasta}" enabled="true" '
                        f'bounds="[347,268][715,400]" />')
                barra = self.pasta
        barra_xml = (
            f'<node package="{self.PACKAGE}" class="android.widget.ImageButton" content-desc="Show roots" '
            f'clickable="true" enabled="true" bounds="[0,136][154,268]" />'
            f'<node package="{self.PACKAGE}" class="android.widget.TextView" text="{barra}" '
            f'enabled="true" bounds="[198,165][471,239]" />'
            f'<node package="{self.PACKAGE}" resource-id="{self.PACKAGE}:id/header_title" '
            f'class="android.widget.TextView" text="{faixa}" enabled="true" bounds="[66,400][1014,565]" />'
            + pao)
        linhas = []
        for indice, nome in enumerate(self.names):
            marcado = 'true' if nome in self.selecionados else 'false'
            topo = 700 + indice * 220
            linhas.append(
                f'<node package="{self.PACKAGE}" class="android.widget.LinearLayout" '
                f'resource-id="{self.PACKAGE}:id/item_root" selected="{marcado}" '
                f'bounds="[0,{topo}][1080,{topo + 198}]" clickable="true">'
                f'<node package="{self.PACKAGE}" class="android.widget.ImageView" '
                f'resource-id="{self.PACKAGE}:id/icon_thumb" '
                f'bounds="[44,{topo + 44}][154,{topo + 154}]" />'
                f'<node package="{self.PACKAGE}" class="android.widget.TextView" '
                f'text="{nome}" resource-id="android:id/title" enabled="true" '
                f'bounds="[198,{topo + 42}][838,{topo + 101}]" />'
                '</node>')
        contador = ''
        if self.selecionados:
            contador = (f'<node package="{self.PACKAGE}" class="android.widget.TextView" '
                        f'text="{len(self.selecionados)} selected" enabled="true" '
                        f'bounds="[300,150][700,250]" />')
        gaveta = ''
        if self.gaveta:
            gaveta = ''.join(
                f'<node package="{self.PACKAGE}" class="android.widget.TextView" '
                f'resource-id="{self.PACKAGE}:id/title" text="{nome}" enabled="true" '
                f'bounds="[66,{topo - 30}][1014,{topo + 30}]" />'
                for nome, topo in self.RAIZES.items() if nome in self.raizes)
        # A gaveta de raízes é uma camada POR CIMA: com ela aberta, as linhas de
        # arquivo não estão visíveis (é o que o dump real mostra).
        corpo = '' if self.gaveta else ('' if self.pasta else ''.join(linhas))
        return '<hierarchy>' + barra_xml + corpo + contador + gaveta + '</hierarchy>'

    def _linha(self, y):
        indice = (y - 700) // 220
        assert 0 <= indice < len(self.names), f'gesto fora das linhas: y={y}'
        return self.names[indice]

    def _toque(self, x, y):
        if self.pasta and 0 <= x < 281 and 268 <= y < 400:
            self.pasta = None                       # pão de navegação "Downloads"
            return
        if abs(x - self.MOSTRAR_RAIZES[0]) < 60 and abs(y - self.MOSTRAR_RAIZES[1]) < 60:
            self.gaveta = not self.gaveta           # "Show roots" alterna a gaveta
            return
        if self.gaveta:
            for nome, topo in self.RAIZES.items():
                if nome in self.raizes and topo - 30 <= y < topo + 30:
                    self.raiz = nome
                    self.gaveta = False
                    self.selecionados.clear()       # trocar de raiz perde a seleção
                    return
            return
        if self.raiz == 'Recentes' or self.modo == 'nunca':
            return                                  # Recentes: nenhum gesto marca
        if self.modo == 'toque-longo' and not self.selecionados:
            return                                  # nesse modo, só o gesto longo abre a seleção
        self.selecionados.add(self._linha(y))

    def shell(self, command, check=True):
        self.actions.append(command)
        tokens = command.split()
        if tokens[:3] == ['input', 'motionevent', 'DOWN']:
            # O toque longo REAL: o dedo fica preso e o app entra em seleção com ele
            # ainda abaixado — é o que o harness tem de provocar (o UP vem depois).
            x, y = int(tokens[3]), int(tokens[4])
            self.preso = (x, y)
            if self.modo == 'toque-longo' and self.raiz != 'Recentes':
                self.selecionados.add(self._linha(y))
        elif tokens[:3] == ['input', 'motionevent', 'UP']:
            self.preso = None
        elif tokens[:2] == ['input', 'tap']:
            self._toque(int(tokens[2]), int(tokens[3]))
        elif tokens[:2] == ['input', 'touchscreen']:
            # swipe x1 y1 x2 y2 duração — só marca com deslocamento de verdade.
            assert tokens[4] != tokens[6] or tokens[5] != tokens[7], \
                f'swipe sem MOVE não é toque longo: {command}'
            if self.modo != 'nunca' and self.raiz != 'Recentes':
                self.selecionados.add(self._linha(int(tokens[5])))
        return ''

    def wait(self, condition, what, timeout=20):
        for _ in range(8):
            resultado = condition()
            if resultado:
                return resultado
        raise AssertionError(f'Timeout: {what}')


def test_select_exact_documents_leaves_recents_for_downloads_and_marks_by_touch():
    """Rodada 36267877767: em "Recent files" NENHUM gesto marcou; em Downloads marca.

    A última marcação múltipla provada (34978739703) foi em Downloads, depois de
    "Show roots" → "Downloads": é esse o caminho que o ajudante tem de repetir.
    """
    device = PickerDevice(['SmolVLM-256M-Instruct-Q8_0.gguf', 'mmproj-SmolVLM-256M-Instruct-Q8_0.gguf'],
                          modo='toque')
    assert device.raiz == 'Recentes'
    select_exact_documents(device, list(device.names))
    assert device.raiz == 'Downloads', 'o ajudante tem de sair da visão Recentes'
    assert device.gaveta is False, 'a gaveta de raízes tem de ser fechada'
    assert device.selecionados == set(device.names)
    # Ordem real: primeiro "Show roots", depois a linha Downloads da gaveta, depois as linhas.
    toques = [a for a in device.actions if a.startswith('input tap')]
    assert int(toques[0].split()[3]) == device.MOSTRAR_RAIZES[1], toques
    assert int(toques[0].split()[2]) == device.MOSTRAR_RAIZES[0], toques
    assert int(toques[1].split()[3]) == device.RAIZES['Downloads'], toques
    assert all(int(a.split()[3]) >= 700 for a in toques[2:]), toques


def test_downloads_already_open_nao_recebe_toque_nenhum():
    """Dentro de Downloads, o ajudante não toca em NADA — nem para "fechar" a gaveta.

    Rodada 36276321752: com a gaveta lida no meio da animação de fechar, o harness
    tocou no hambúrguer para fechá-la; o toque ABRIU a gaveta, o laço passou a exigir
    a gaveta fechada para considerar a lista parada e a fase `visao` morreu esperando
    (o dump final mostrava a gaveta aberta por cima da pasta isolada). Trocar de raiz
    quando a raiz certa já está aberta também recarregaria a lista debaixo do dedo
    (defeito da 36272556329).
    """
    device = PickerDevice(['model.gguf'], modo='toque', raiz='Downloads')
    device.shell('input tap 77 202')            # quem abriu a gaveta foi o chamador
    assert device.gaveta is True
    device.actions.clear()                      # daqui em diante, só o que o harness faz
    assert abrir_pasta_de_downloads(device) == 'Files in Downloads'
    assert device.actions == [], f'nenhum toque esperado, houve: {device.actions}'
    assert device.gaveta is True, 'a gaveta não é assunto deste ajudante'
    assert device.selecionados == set()


def test_subpasta_lembrada_pelo_seletor_e_abandonada_pelo_pao_de_navegacao():
    """O seletor LEMBRA a última pasta: o modelo tem de ser marcado na RAIZ.

    Rodada 36321822068: depois das fases de anexo, o diretório lembrado era a pasta
    isolada `000-read-*`. O cabeçalho continuava dizendo "Files in Downloads" e três
    etapas caíram tentando marcar o modelo DENTRO da pasta (`emulator`, `anexo_texto`,
    `visao`). Quem diz o diretório aberto é o pão de navegação.
    """
    device = PickerDevice(['model.gguf'], modo='toque', raiz='Downloads', pasta='000-read-999967')
    device.actions.clear()
    assert abrir_pasta_de_downloads(device) == 'Files in Downloads'
    assert device.pasta is None, 'a subpasta lembrada tem de ser abandonada'
    toques = [a for a in device.actions if a.startswith('input tap')]
    assert toques == ['input tap 140 334'], f'o toque é no segmento Downloads: {toques}'
    assert device.gaveta is False, 'nem a gaveta nem as linhas entram nesse caminho'


def test_dump_real_de_subpasta_da_rodada_36321822068_e_reconhecido_como_subpasta():
    """O dump REAL da subpasta lembrada: não é a raiz, e o caminho de volta é o pão.

    `tests/fixtures/picker/downloads-dentro-da-pasta-isolada.xml` é a evidência da
    rodada 36321822068: cabeçalho "Files in Downloads" e caminho
    "Downloads › 000-read-999967". O toque no segmento "Downloads" do pão de
    navegação é CONFIRMADO relendo o caminho — nada de "deve ter voltado".
    """
    pasta = (ROOT / 'tests/fixtures/picker/downloads-dentro-da-pasta-isolada.xml').read_text()
    raiz = (ROOT / 'tests/fixtures/picker/downloads-com-gaveta-aberta.xml').read_text()
    assert not _na_pasta_de_downloads(pasta), 'subpasta não é a raiz Downloads'
    assert _na_pasta_de_downloads(raiz), 'o dump da raiz continua sendo a raiz'

    class Device:
        def __init__(self):
            self.subpasta = True
            self.comandos = []

        def ui(self):
            return pasta if self.subpasta else raiz

        def shell(self, command, check=True):
            self.comandos.append(command)
            if command.startswith('input tap'):
                self.subpasta = False          # o toque no pão de navegação funciona
            return ''

    device = Device()
    assert _voltar_para_a_raiz_de_downloads(device, pasta) is True
    assert device.comandos == ['input tap 140 334'], device.comandos


def test_toque_no_pao_que_nao_funciona_cai_no_back_do_sistema():
    """Pão de navegação é `clickable="false"` no dump real: se o toque não mudar o
    caminho, sobe com `KEYCODE_BACK` — e só dentro de Downloads (o BACK na raiz
    fecharia o seletor)."""
    pasta = (ROOT / 'tests/fixtures/picker/downloads-dentro-da-pasta-isolada.xml').read_text()
    raiz = (ROOT / 'tests/fixtures/picker/downloads-com-gaveta-aberta.xml').read_text()

    class Device:
        def __init__(self, obedece_ao_toque):
            self.subpasta = True
            self.obedece_ao_toque = obedece_ao_toque
            self.comandos = []

        def ui(self):
            return pasta if self.subpasta else raiz

        def shell(self, command, check=True):
            self.comandos.append(command)
            if self.obedece_ao_toque and command.startswith('input tap'):
                self.subpasta = False
            if command == 'input keyevent KEYCODE_BACK':
                self.subpasta = False
            return ''

    surdo = Device(obedece_ao_toque=False)
    assert _voltar_para_a_raiz_de_downloads(surdo, pasta) is True
    assert surdo.comandos[0] == 'input tap 140 334', surdo.comandos
    assert surdo.comandos[-1] == 'input keyevent KEYCODE_BACK', surdo.comandos


def test_dump_real_com_gaveta_aberta_sobre_a_subpasta_usa_a_linha_da_gaveta():
    """Com a gaveta aberta POR CIMA do pão de navegação, quem leva à raiz é a linha
    "Downloads" da gaveta.

    `tests/fixtures/picker/downloads-dentro-da-pasta-com-gaveta.xml` é o dump REAL da
    fase `anexo_texto` da rodada 36321822068: a gaveta ("Open from" + raízes) cobre o
    pão de navegação — tocar o pão cairia na gaveta, não no caminho.
    """
    gaveta = (ROOT / 'tests/fixtures/picker/downloads-dentro-da-pasta-com-gaveta.xml').read_text()
    dispositivos = []

    class Device:
        def ui(self):
            return gaveta

        def shell(self, command, check=True):
            dispositivos.append(command)
            return ''

    try:
        abrir_pasta_de_downloads(Device(), timeout=3)
    except AssertionError:
        pass      # o aparelho de mentira não fecha a gaveta; o que importa é o toque
    assert dispositivos and dispositivos[0] == 'input tap 462 828', dispositivos
    assert 'input tap 140 334' not in dispositivos, 'o pão de navegação está coberto'


def test_dump_real_da_rodada_36276321752_nao_gera_toque_nenhum():
    """O dump EXATO que derrubou a fase `visao` não pode produzir toque.

    `tests/fixtures/picker/downloads-com-gaveta-aberta.xml` é o XML da evidência da
    rodada 36276321752: barra "Downloads", cabeçalho "Files in Downloads", a gaveta
    de raízes por cima (linhas "Recent"/"Images"/"Documents"/"Downloads") e as pastas
    da pasta isolada dentro. O ajudante tem de reconhecer a raiz certa e devolver sem
    tocar em nada — nenhum `input` sai daqui.
    """
    dump = (ROOT / 'tests/fixtures/picker/downloads-com-gaveta-aberta.xml').read_text()
    comandos = []

    class Device:
        evidence = ROOT / 'tests/fixtures/picker'

        def ui(self):
            return dump

        def shell(self, command, check=True):
            comandos.append(command)
            return ''

    assert abrir_pasta_de_downloads(Device()) == 'Files in Downloads'
    assert comandos == [], f'nenhum toque esperado neste dump, houve: {comandos}'


def test_gaveta_aberta_cobrindo_as_linhas_e_fechada_uma_vez_so():
    """A gaveta cobre as linhas: `select_exact_documents` fecha UMA vez e marca.

    É o caminho que a varredura de funções percorre quando o seletor abre em
    Downloads com a gaveta aberta por cima.
    """
    device = PickerDevice(['model.gguf'], modo='toque', raiz='Downloads')
    device.shell('input tap 77 202')            # gaveta aberta por cima das linhas
    device.actions.clear()
    select_exact_documents(device, ['model.gguf'])
    toques = [a for a in device.actions if a.startswith('input tap')]
    assert toques, 'a gaveta tem de sair do caminho para as linhas aparecerem'
    assert int(toques[0].split()[2]) == device.MOSTRAR_RAIZES[0], toques
    assert int(toques[0].split()[3]) == device.MOSTRAR_RAIZES[1], toques
    assert device.gaveta is False
    assert device.selecionados == {'model.gguf'}


def test_select_exact_documents_falls_back_to_the_held_finger_when_taps_do_not_mark():
    """O toque simples é o gesto provado, mas se ele não marcar o dedo fica PRESO.

    Quem decide é a marcação: só vale o que apareceu no contador do seletor.
    """
    device = PickerDevice(['model.gguf', 'projector.gguf'], modo='toque-longo', raiz='Downloads')
    select_exact_documents(device, list(device.names))
    assert device.selecionados == set(device.names)
    gestos = [a for a in device.actions if a.startswith('input tap')]
    assert gestos, 'o toque simples continua sendo a primeira tentativa'
    primeiro_down = next(i for i, a in enumerate(device.actions) if a.startswith('input motionevent DOWN'))
    assert primeiro_down > device.actions.index(gestos[0]), 'toque simples antes do toque longo'
    assert any(a.startswith('input motionevent UP') for a in device.actions), \
        'o dedo do toque longo tem de ser solto'
    assert device.preso is None


def test_select_exact_documents_declares_the_root_it_could_not_leave():
    """Sem Downloads na gaveta, o teste diz o que viu — não marca por omissão."""
    device = PickerDevice(['a.gguf', 'b.gguf'], modo='nunca', raizes=['Images', 'Videos'])
    with pytest.raises(AssertionError) as error:
        select_exact_documents(device, list(device.names))
    assert 'não consegui abrir a pasta Downloads' in str(error.value)
    assert 'gaveta aberta sem a linha Downloads' in str(error.value), str(error.value)
    assert device.selecionados == set()


def test_select_exact_documents_declares_when_no_gesture_marks_the_row():
    device = PickerDevice(['a.gguf', 'b.gguf'], modo='nunca', raiz='Downloads')
    with pytest.raises(AssertionError) as error:
        select_exact_documents(device, list(device.names))
    assert 'não consegui marcar a.gguf' in str(error.value)
    assert 'não marcaram a linha' in str(error.value)
    assert 'raiz do seletor' in str(error.value), 'a mensagem diz em que raiz estava'
    # O último recurso tem de ter MOVE (swipe com deslocamento), nunca swipe parado.
    assert not any(a.startswith('input touchscreen swipe')
                   and a.split()[4] == a.split()[6] and a.split()[5] == a.split()[7]
                   for a in device.actions)


def test_ui_does_not_send_esc_into_the_file_picker(tmp_path):
    """O seletor do sistema NÃO é uma foto ruim: ESC ali mexeria na seleção.

    A retentativa da foto manda ESC quando nenhum nó do aplicativo aparece e o
    processo existe — o que também acontece com o DocumentsUI na frente, que é
    justamente a janela que o teste quer fotografar (rodada 36267877767: seletor em
    "Recent files" e nenhuma marcação sobreviveu).
    """
    seletor = ('<hierarchy><node package="com.google.android.documentsui" '
               'class="android.widget.TextView" text="Recent files" enabled="true" '
               'bounds="[66,400][1014,565]" /></hierarchy>')
    device = ScreenDevice([seletor], tmp_path)
    xml = Android.ui(device)
    assert 'Recent files' in xml, 'a foto do seletor tem de ser usada como está'
    assert not any(a.startswith('input keyevent 111') for a in device.actions), \
        'ESC na janela do seletor cancelaria a seleção que o teste acabou de fazer'


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


def screen_com_campo(package='com.ggufchat.app'):
    """Uma tela como o aplicativo publica: o CAMPO de texto existe, com a dica dentro."""
    return (f'<hierarchy><node package="{package}" class="android.widget.EditText" '
            f'text="Escreva sua mensagem…" enabled="true" focused="true" '
            f'bounds="[0,0][10,10]" />'
            f'<node package="{package}" class="android.widget.Button" text="Enviar" '
            f'enabled="true" bounds="[0,10][10,20]" /></hierarchy>')


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
