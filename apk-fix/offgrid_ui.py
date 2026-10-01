"""Linguagem visual única inspirada no Off Grid AI, aplicada às quatro telas.

A referência é de estilo, não de código: tipografia monoespaçada, base neutra,
acento esmeralda único, bordas de fio, cantos de 8 dp. Nenhum rótulo é alterado,
porque os testes de interface procuram os textos reais no aparelho.
"""
from unified_mobile import replace_method

SCREEN = '    invoke-static {p0}, Lcom/ggufchat/app/OffgridUi;->screen(Landroid/app/Activity;)V'
CHAT = '    invoke-static {p0}, Lcom/ggufchat/app/OffgridUi;->chat(Landroid/app/Activity;)V'


def after_set_content(path, activity, call):
    """Insere a chamada logo depois da tela ser montada. Telas que outro patch
    já redirecionou para a MainActivity não têm conteúdo próprio para estilizar."""
    s = path.read_text()
    marker = f'    invoke-virtual {{p0, v0}}, Lcom/ggufchat/app/{activity};->setContentView(Landroid/view/View;)V'
    if marker not in s:
        return False
    assert s.count(marker) == 1, f'{activity}: chamada única esperada para setContentView'
    s = s.replace(marker, marker + '\n\n' + call)
    path.write_text(s)
    return True


def patch_offgrid_ui(app):
    # Cada tela recebe a linguagem depois de montada, sem tocar no conteúdo.
    after_set_content(app / 'MainActivity.smali', 'MainActivity', SCREEN)
    # ModelsActivity foi unificada na página Importar da MainActivity.
    after_set_content(app / 'ModelsActivity.smali', 'ModelsActivity', SCREEN)
    after_set_content(app / 'SettingsActivity.smali', 'SettingsActivity', SCREEN)
    s = (app / 'ChatActivity.smali').read_text()
    marker = '    invoke-virtual {p0, v2}, Lcom/ggufchat/app/ChatActivity;->setContentView(Landroid/view/View;)V'
    assert s.count(marker) == 1
    s = s.replace(marker, marker + '\n\n' + CHAT)

    # A mensagem recém-criada entra na mesma linguagem das já exibidas.
    decorated = '    invoke-static {v4, p2}, Lcom/ggufchat/app/CodeBlocks;->decorate(Landroid/widget/LinearLayout;Z)V'
    assert s.count(decorated) == 1, 'ponto de decoração da mensagem ausente; revise a ordem dos patches'
    s = s.replace(decorated, decorated + '\n\n    invoke-static {v4}, Lcom/ggufchat/app/OffgridUi;->bubble(Landroid/view/View;)V')
    (app / 'ChatActivity.smali').write_text(s)

    # Barra inferior: acento esmeralda no destino ativo, neutro nos demais.
    p = app / 'MainActivity.smali'
    s = p.read_text()
    tail = ('''    invoke-virtual {v1, v2}, Landroid/widget/Button;->setTextColor(I)V

    invoke-static {v5, v0}, Lcom/ggufchat/app/Ui;->rounded(II)Landroid/graphics/drawable/GradientDrawable;

    move-result-object v3

    invoke-virtual {v1, v3}, Landroid/widget/Button;->setBackground(Landroid/graphics/drawable/Drawable;)V

    return-void''')
    assert s.count(tail) == 1, 'método de troca de aba fora do formato esperado'
    s = s.replace(tail, tail.replace('    return-void',
        '    invoke-static {p0, p1}, Lcom/ggufchat/app/OffgridUi;->tabs(Landroid/app/Activity;I)V\n\n    return-void'))
    p.write_text(s)
