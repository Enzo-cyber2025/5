"""A busca na web tem teto de tempo — provado no host e conferido no código.

O defeito relatado: com a busca ligada, o aplicativo ficava minutos em
"Pesquisando na web" e o modelo não respondia. A causa medida no código: quatro
provedores em sequência, cada um com 8 s de conexão e 12 s de leitura, sem teto
total e sem desistir quando a rede já havia falhado — tudo antes de o modelo
carregar e antes do primeiro token.

Estes testes fixam o conserto:
  * o orçamento é único para a busca inteira e cada fatia usa, no máximo, o que
    resta (executado de verdade no JVM, quando há javac);
  * falha de rede (DNS/recusa/sem rota) interrompe a cadeia de provedores;
  * o SearchTool usa o orçamento em TODAS as tentativas e declara o motivo;
  * o usuário vê o limite na linha de status em vez de uma espera sem fim.
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
JAVA = ROOT / 'apk-fix/java/com/ggufchat/app'
SRC = ROOT / 'scripts/test_android.py'
TOOL = JAVA / 'SearchTool.java'
BUDGET = JAVA / 'SearchBudget.java'
SELF_TEST = ROOT / 'tests/java/SearchBudgetSelfTest.java'


def run_self_test(tmp_path):
    javac = shutil.which('javac')
    if not javac:
        pytest.skip('sem javac neste host; o CI executa o autoteste')
    classes = tmp_path / 'classes'
    classes.mkdir()
    compiled = subprocess.run([javac, '-d', str(classes), str(BUDGET),
                               str(JAVA / 'SearchNotice.java'), str(SELF_TEST)],
                              capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stderr
    java = shutil.which('java') or str(Path(javac).with_name('java'))
    result = subprocess.run([java, '-cp', str(classes), 'com.ggufchat.app.SearchBudgetSelfTest'],
                            capture_output=True, text=True, timeout=120)
    return result


def test_budget_math_holds_when_executed(tmp_path):
    result = run_self_test(tmp_path)
    assert 'SEARCH_BUDGET_OK' in result.stdout, result.stdout + result.stderr
    assert result.returncode == 0
    assert 'FAIL' not in result.stdout


@pytest.mark.skipif(not SELF_TEST.is_file(), reason='autoteste ausente')
def test_self_test_is_not_a_fake_pass(tmp_path):
    """Se o teto for quebrado, o autoteste precisa reprovar — senão não vale nada."""
    javac = shutil.which('javac')
    if not javac:
        pytest.skip('sem javac neste host')
    broken = (tmp_path / 'broken').mkdir(parents=True) or (tmp_path / 'broken')
    package = broken / 'com/ggufchat/app'
    package.mkdir(parents=True)
    # Mesmo teste, orçamento sabotado: as fatias passam a ignorar o restante.
    # A sabotagem precisa existir NESTE arquivo: a primeira versão mirava um trecho
    # que já não existia, virava no-op e a "prova negativa" provava nada.
    original = BUDGET.read_text()
    text = original.replace('int share = remaining / 2;', 'int share = Integer.MAX_VALUE;')
    assert text != original, 'a sabotagem não encontrou o trecho: reveja este teste'
    (package / 'SearchBudget.java').write_text(text)
    shutil.copyfile(JAVA / 'SearchNotice.java', package / 'SearchNotice.java')
    shutil.copyfile(SELF_TEST, package / 'SearchBudgetSelfTest.java')
    classes = tmp_path / 'classes'
    classes.mkdir()
    compiled = subprocess.run([javac, '-d', str(classes), str(package / 'SearchBudget.java'),
                               str(package / 'SearchNotice.java'),
                               str(package / 'SearchBudgetSelfTest.java')], capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stderr
    java = shutil.which('java') or str(Path(javac).with_name('java'))
    result = subprocess.run([java, '-cp', str(classes), 'com.ggufchat.app.SearchBudgetSelfTest'],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode != 0 and 'FAIL' in result.stdout, result.stdout


def test_every_search_attempt_is_bounded_by_the_budget():
    tool = TOOL.read_text()
    assert 'new SearchBudget()' in tool, 'a busca precisa criar o orçamento'
    # Cada tentativa é registrada pelo orçamento (contagem = tentativas no código).
    attempts = re.findall(r'Attempt \w+=attempt\(', tool)
    assert len(attempts) == 4, attempts
    # As duas fatias de cada requisição vêm do orçamento (conexão e leitura), e
    # uma fatia zero não pode abrir requisição nenhuma: zero é "sem limite".
    assert 'int[] timeouts=budget.slices(CONNECT_TIMEOUT,READ_TIMEOUT);' in tool
    assert 'if(connect<=0||read<=0){' in tool
    budget = BUDGET.read_text()
    assert 'int[] slices(int connectConfigured, int readConfigured, long nowNanos)' in budget
    assert 'int share = remaining / 2;' in budget
    assert 'if (remaining < MIN_SLICE_MS) return new int[]{0, 0};' in budget
    # Nenhuma conexão pode ser aberta sem passar pela fatia do orçamento.
    assert tool.count('get(') >= 4
    assert 'get(url,connect,read)' in tool
    # O teto não pode ser maior que a soma dos timeouts por tentativa sem a fatia.
    assert 'Connection.setConnectTimeout(CONNECT_TIMEOUT)' not in tool


def test_network_failure_short_circuits_the_provider_chain():
    tool = TOOL.read_text()
    assert 'SearchBudget.connectivityFailure(ex)' in tool
    assert 'demais provedores ignorados' in tool
    # A decisão de parar vem da tentativa, não de um contador manual.
    assert tool.count('if(searx.stop)') == 1 and tool.count('if(ddg.stop)') == 1 and tool.count('if(lite.stop)') == 1


def test_failure_reports_the_reason_and_the_budget():
    tool = TOOL.read_text()
    assert 'orçamento de "+budget.totalMs()+" ms esgotado' in tool
    assert 'GGUF_SEARCH_BUDGET total_ms=' in tool
    assert 'budget_exhausted' in tool and 'budget_ms' in tool
    # JSON antigo (sem os campos novos) continua legível.
    assert 'root.optLong("budget_ms",SearchBudget.DEFAULT_MS)' in tool
    panel = tool[tool.index('TextView header=new TextView(context);'):]
    assert 'ms de "+report.budgetMs+" ms' in panel[:1200]


def test_status_line_tells_the_user_the_limit():
    streaming = (JAVA / 'StreamingUi.java').read_text()
    assert 'SearchBudget.configuredMs()' in streaming
    assert 'até ' in streaming and ' antes de responder' in streaming
    assert 'GGUF_SEARCH_ANNOUNCED query_pending=1 budget_ms=' in streaming


def test_failed_search_tells_the_model_there_are_no_sources():
    """O prompt de sistema manda citar as fontes "abaixo"; sem fontes, o modelo é avisado."""
    tool = TOOL.read_text()
    assert 'SearchNotice.failure(report.error)' in tool
    assert 'GGUF_SEARCH_PROMPT mode=indisponivel' in tool
    assert 'GGUF_SEARCH_PROMPT mode=fontes' in tool
    notice = (JAVA / 'SearchNotice.java').read_text()
    assert 'import android' not in notice  # roda no host
    assert 'Não há resultados de busca para citar' in notice


def test_search_stages_use_the_stage_chat_id():
    """As fases de busca precisam do id da conversa DAQUELA etapa.

    `generate()` devolve o logcat (string). Guardar esse retorno e indexá-lo como
    conversa custou duas rodadas de 25 minutos de emulador ("string indices must be
    integers", depois "'Android' object has no attribute 'last_chat'"). Esta
    checagem de host impede a terceira: nada indexa o retorno de `generate()` e o
    único id usado vem de `last_chat`, gravado em `new_chat`.
    """
    import ast
    source = SRC.read_text()
    tree = ast.parse(source)
    # Guardar o LOG é legítimo (outras etapas fazem isso); o erro é tratá-lo como
    # conversa, indexando por chave de texto.
    logs = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        if isinstance(call.func, ast.Attribute) and call.func.attr == 'generate':
            logs.update(t.id for t in node.targets if isinstance(t, ast.Name))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript) or not isinstance(node.value, ast.Name):
            continue
        if node.value.id not in logs:
            continue
        index = node.slice
        assert not (isinstance(index, ast.Constant) and isinstance(index.value, str)), (
            f'{node.value.id} é o logcat de uma geração, não uma conversa: '
            f'indexá-lo com {index.value!r} é o bug que custou duas rodadas')
    assert source.count('self.last_chat = chat') == 1, 'new_chat precisa gravar a conversa da etapa'
    assert source.count('device.last_chat["id"]') == 2, 'as duas fases de busca usam o id da etapa'
    assert 'search_chat[' not in source


def test_timing_reports_flag_an_attempt_over_the_remaining_budget():
    """A invariante que o emulador confere também tem prova de host, nos dois sentidos."""
    from android_checks import search_timing
    good = ('GGUF_SEARCH_ATTEMPT provider=DDG budget_ms=12000 remaining_ms=12000 '
            'connect_ms=3000 read_ms=4000\nGGUF_SEARCH_BUDGET total_ms=12000 used_ms=900 '
            'exhausted=0 provider=nenhum\n')
    assert search_timing(good)['attempt_slices_within_budget'] is True
    bad = good.replace('read_ms=4000', 'read_ms=12000')
    assert search_timing(bad)['attempt_slices_within_budget'] is False


def test_search_prompt_block_is_bounded_for_latency():
    """O bloco de fontes entra no prompt: cada caractere é tempo de espera.

    Medido no emulador: pré-preenchimento a ~40 tokens/s, então um prompt de 829
    tokens custava 20,25 s até o primeiro texto. O teto e os cortes precisam
    existir no código, e o log precisa dizer o tamanho real do bloco.
    """
    tool = TOOL.read_text()
    assert 'MAX_PROMPT_CHARS=1400' in tool
    assert 'PROMPT_HITS=3, PROMPT_SNIPPET=140, PROMPT_URL=100' in tool
    assert 'private static String clip(String value,int max)' in tool
    assert 'out.length()' in tool and 'GGUF_SEARCH_PROMPT_SIZE chars=' in tool
    # o corte é declarado, nunca silencioso
    assert 'fonte(s) a mais no painel' in tool


def test_prefill_ubatch_is_tunable_and_logged():
    """O ajuste do sub-lote precisa ser medível: propriedade + registro do usado."""
    native = (ROOT / 'apk-fix/native/mobile.cpp').read_text()
    assert 'debug_int("debug.gguf.prefill_ubatch",0)' in native
    assert 'GGUF_CONTEXT_TUNING batch=%u ubatch=%u' in native
    harness = SRC.read_text()
    assert '"prefill-ubatch-128", 128' in harness and '"prefill-ubatch-256", 256' in harness
    assert 'prefill_ms_per_token' in harness
    # A comparação de sub-lote mede pré-preenchimento (prompt longo, sem aquecimento)
    # e por isso fica fora da conta de ganho/regressão de decodificação.
    assert "if name.startswith('prefill-ubatch-'):" in harness
    assert "report['prefill_experiment'] = prefill_experiment(perf)" in harness
    assert 'long_prompt' in harness  # mesmo texto nas duas etapas: só o sub-lote muda
    checks = (ROOT / 'scripts/android_checks.py').read_text()
    assert 'GGUF_CONTEXT_TUNING' in checks


def test_search_panel_accepts_what_the_app_persists():
    """Busca persistida: as fontes são um OBJETO JSON; em memória, string.

    Aceitar só a string reprovou o aplicativo por culpa do teste na rodada
    36085765567 — o app gravou as fontes certas e o helper devolveu None.
    """
    from android_checks import search_panel
    objeto = [{'id': 'x', 'messages': [
        {'role': 'user', 'content': 'q'},
        {'role': 'assistant', 'content': 'a', 'searchSources': {'provider': 'DuckDuckGo', 'hits': [1, 2]}}]}]
    assert search_panel(objeto, 'x', 'q')['provider'] == 'DuckDuckGo'
    string = [{'id': 'x', 'messages': [
        {'role': 'user', 'content': 'q'},
        {'role': 'assistant', 'content': 'a',
         'searchSources': '{"provider": "Wikipédia", "hits": [1]}'}]}]
    assert search_panel(string, 'x', 'q')['provider'] == 'Wikipédia'
    lixo = [{'id': 'x', 'messages': [
        {'role': 'user', 'content': 'q'},
        {'role': 'assistant', 'content': 'a', 'searchSources': 'nao-e-json'}]}]
    assert search_panel(lixo, 'x', 'q') is None


def test_function_sweep_covers_every_labelled_control():
    """A varredura cobre os controles que o próprio aplicativo anuncia.

    Os rótulos vêm da tabela de strings do dex do APK original (lida sem JDK):
    cada um deles tem de aparecer na varredura, senão "todas as funções" seria
    uma promessa sem lastro.
    """
    sweep = (ROOT / 'scripts/test_functions_android.py').read_text()
    for rotulo in ('Nova conversa', 'Importar GGUF', 'Importar 2 GGUFs', 'Salvar ajustes',
                   'Parar', 'Thinking', 'Busca', 'Foto', 'Vídeo', 'Áudio', 'Arquivo', 'Ferramentas',
                   'Excluir conversa', 'Excluir modelo', 'Descarregar'):
        assert rotulo in sweep, f'"{rotulo}" não é exercitado pela varredura'
    for funcao in ('estado_vazio', 'abas', 'ajustes', 'nova_conversa', 'parar_geracao',
                   'raciocinio', 'busca_fontes', 'gaveta_ferramentas', 'seletores_de_anexo',
                   'anexo_texto', 'visao', 'notificacao', 'historico', 'excluir_conversa',
                   'excluir_modelo', 'sem_modelo'):
        assert f"('{funcao}'" in sweep, f'função {funcao} fora da ordem da varredura'


def test_public_signatures_are_what_the_search_calls():
    """Tipos declarados conferem — o javac do CI pegou `int slices(...)` em vez de `int[]`.

    Este host não tem javac: sem esta checagem, um erro de tipo só apareceria no
    CI, depois de um ciclo inteiro de emulador. javalang lê os tipos declarados.
    """
    import javalang
    tree = javalang.parse.parse(BUDGET.read_text())
    expected = {
        ('sliceMs', 1): 'int', ('slices', 2): 'int[]',
        ('remainingMs', 0): 'int', ('totalMs', 0): 'int', ('expired', 0): 'boolean',
    }
    def declared(node):
        """Tipo como aparece na assinatura: 'int[]', não 'int' (javalang guarda a
        dimensão à parte, e foi exatamente aí que o erro passou)."""
        kind = node.return_type
        name = getattr(kind, 'name', None) or str(kind)
        return name + '[]' * len(getattr(kind, 'dimensions', None) or [])

    found = {}
    for _, method in tree.filter(javalang.tree.MethodDeclaration):
        found[(method.name, len(method.parameters or []))] = declared(method)
    for key, wanted in expected.items():
        assert found.get(key) == wanted, f'{key}: esperado {wanted}, encontrado {found.get(key)}'
    static = {m.name for _, m in tree.filter(javalang.tree.MethodDeclaration)
              if 'static' in m.modifiers}
    assert 'connectivityFailure' in static and 'configuredMs' in static


def test_budget_class_stays_pure_java():
    """Nada de Android no arquivo que o teste de host executa."""
    text = BUDGET.read_text()
    assert 'import android' not in text
    assert 'java.net.' in text
    assert 'public static final int DEFAULT_MS = 12000;' in text
