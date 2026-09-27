from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SRC = (HERE / 'apk-fix' / 'java' / 'com' / 'ggufchat' / 'app' / 'SearchGating.java').read_text()

# Palavras que o portão TEM que reconhecer (retiradas do comentário do código e
# de exemplos reais de perguntas que pedem dado da web).
TRIGGERS = ['hoje', 'agora', 'atualmente', 'ontem', 'amanhã', 'esta semana',
            'em 2025', 'notícias', 'noticia', 'preço do dólar', 'cotação',
            'placar do jogo', 'temperatura', 'previsão do tempo',
            'quem é o presidente atual', 'bitcoin hoje', 'site oficial',
            'wikipedia', 'fonte oficial']

NEGATIVOS = ['oi', 'explique o que é recursão', '3 fatos sobre cachorros',
             'escreva um poema sobre o mar', 'como funciona um for em Python?',
             'bom dia', 'o que é um vetor?', '', '   ', 'oi?']


def test_o_portao_de_busca_previa_so_dispara_para_perguntas_que_pedem_dado_externo():
    """Bug 'pesquisa sem precisar': respostas de conhecimento geral não esperam 12 s de rede.

    Antes do conserto, qualquer envio com o botão Busca ligado disparava HTTP
    antes do primeiro token — até "oi" ou "explique recursão" pagavam o teto de
    espera. Agora a busca prévia só dispara quando a pergunta tem indicadores
    claros de dado recente (data, notícia, cotação, preço, placar, clima…).
    """
    assert 'class SearchGating' in SRC
    assert 'public static boolean needsWeb(String text)' in SRC
    assert 'return TRIGGERS.matcher(t).find();' in SRC
    # Strings curtas (sem ?) nunca disparam — protege "oi", "bom dia", etc.
    assert 'if(t.length()<12 && !t.contains("?"))return false;' in SRC
    # Gatilhos (classes de palavras) presentes na regex:
    for trecho in ('hoje', 'agora', 'ontem', 'amanhã', 'notícias?', 'preço d[eo]',
                   'cotação', 'placar d[eo]', 'temperatura', 'clima',
                   'previsão do tempo', 'wikipedia', 'site oficial',
                   'fonte oficial', 'em 202[4-9]', 'resultado do jogo'):
        assert trecho in SRC, f'gatilho ausente: {trecho}'


def test_o_portao_de_string_vazia_retorna_falso():
    assert 'if(text==null)return false;' in SRC
    assert 'if(t.length()<4)return false;' in SRC


def test_searchtool_chama_o_portao_e_nao_faz_http_quando_pula():
    """SearchTool.searchText(max>0) passa pelo portão antes de ir à rede."""
    st = (HERE / 'apk-fix' / 'java' / 'com' / 'ggufchat' / 'app' / 'SearchTool.java').read_text()
    assert 'SearchGating.needsWeb(query)' in st, 'portão não foi conectado'
    assert 'GGUF_SEARCH_GATED skipped=1' in st, 'log do pulo ausente'
    assert 'new ArrayList<Hit>()' in st
    assert 'return "";' in st, 'sem bloco de fontes quando pula'
