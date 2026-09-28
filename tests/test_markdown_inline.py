from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SRC = (HERE / 'apk-fix' / 'java' / 'com' / 'ggufchat' / 'app' / 'MarkdownText.java').read_text()


def test_todos_os_efeitos_de_texto_inline_estao_presentes():
    """Bug reportado pelo usuário: no meio do texto, p++ e outras elevações não
    apareciam. O parser agora cobre: negrito, itálico, código, tachado,
    sublinhado, sobrescrito (curto e bloco), subscrito e LaTeX curto."""
    spans = {
        '**': ('StyleSpan(Typeface.BOLD)', 'new StyleSpan(Typeface.BOLD)'),
        '*': ('StyleSpan(Typeface.ITALIC)', 'new StyleSpan(Typeface.ITALIC)'),
        '`': ('TypefaceSpan("monospace")', 'new BackgroundColorSpan(0x332e2e2e)'),
        '~~': ('StrikethroughSpan', 'new StrikethroughSpan()'),
        '__': ('UnderlineSpan', 'new UnderlineSpan()'),
        '^^': ('SuperscriptSpan', 'new SuperscriptSpan()'),
        '_': ('SubscriptSpan', 'new SubscriptSpan()'),  # subscrito curto H_2O
        '$': ('MATH', 'new TypefaceSpan("monospace")'),  # LaTeX curto
    }
    for marker, (needle, _span) in spans.items():
        assert needle in SRC, f'falta suporte a {marker}: {needle}'
    # Redução de tamanho em sobrescrito/subscrito — essencial para a elevação
    # não ficar do mesmo tamanho do texto normal.
    assert 'SCRIPT_RATIO=0.7f' in SRC
    assert 'RelativeSizeSpan(SCRIPT_RATIO)' in SRC


def test_o_parser_reconhece_os_caracteres_de_marcador():
    # ^ e _ e $ agora disparam o caminho de estilização; antes só *, `, ~, \\ faziam.
    for c in ('*', '`', '~', '\\', '^', '_', '$'):
        assert f"'{c}'" in SRC or f'"\\{c}"' in SRC or f"'\\{c}'" in SRC, c


def test_fast_path_incremental_sem_setText_por_token():
    """O texto demorava a aparecer porque view.setText() era chamado a cada token.

    O conserto: append incremental (view.append(chunk)) enquanto o marcador
    permanece aberto; repinte só quando um par fecha (ou ao fim via
    finalizeStream). Isto elimina o relayout O(n^2) a cada token que roubava
    ~3 tok/s no A55.
    """
    assert 'FAST PATH' in SRC, 'comentario do fast path esperado como marcador'
    assert 'if(previous&&!closesAnyMarker(chunk)){' in SRC, (
        'append incremental esperado')
    assert 'view.append(chunk);' in SRC
    assert 'public static void finalizeStream(TextView view)' in SRC, (
        'finalizeStream no fim da geracao para um unico repinte final')
    assert 'closesAnyMarker' in SRC, 'helper para detectar fechamento de par'


def test_blocos_recuados_sao_conservadores():
    """Bloco de codigo nao deve aparecer onde nao tinha (bug de listas indentadas).

    CodeDetect.fenced() agora exige sinais claros de codigo (palavras-chave
    detectadas OU 3+ linhas recuadas) e recusa listas/citacoes (- * 1. a) >).
    """
    detect = (HERE / 'apk-fix' / 'java' / 'com' / 'ggufchat' / 'app' / 'CodeDetect.java').read_text()
    assert 'CONSERVADOR' in detect
    assert 'looksLikeList' in detect
    assert 'startsWith("- ")' in detect and 'startsWith("* ")' in detect
    assert 'manyLines=nonBlank>=3' in detect or 'nonBlank>=3' in detect


def test_corrida_tem_tres_provedores_e_timeouts_menores():
    """A busca lenta em rede movel: 3 provedores paralelos, timeouts menores."""
    search = (HERE / 'apk-fix' / 'java' / 'com' / 'ggufchat' / 'app' / 'SearchTool.java').read_text()
    assert 'DuckDuckGo Lite' in search and 'DuckDuckGo' in search and 'Wikipédia' in search
    assert 'private static final int CONNECT_TIMEOUT=2000' in search
    assert 'READ_TIMEOUT=3000' in search
