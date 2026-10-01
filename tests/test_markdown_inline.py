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
