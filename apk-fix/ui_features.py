"""Hooks for the visible feature set: image detach, separate reasoning, real search
sources and inline formatting. Java-side classes carry the logic; this module only
reroutes the exact existing call sites and refuses to patch anything unexpected."""
from unified_mobile import replace_method

MESSAGE_FIELD = '.field public searchSources:Ljava/lang/String;'


def patch_message_field(app):
    p = app / 'Message.smali'
    s = p.read_text()
    if MESSAGE_FIELD in s:
        raise AssertionError('Message.searchSources already present')
    s = s.replace('# direct methods', MESSAGE_FIELD + '\n\n# direct methods', 1)
    assert s.count(MESSAGE_FIELD) == 1
    for method, call, args in [('.method public static fromJson(', 'read', 'v0, p0'),
                               ('.method public toJson(', 'write', 'p0, v0')]:
        a = s.index(method); b = s.index('.end method', a); part = s[a:b]
        marker = '    return-object v0'
        assert part.count(marker) == 1, method
        part = part.replace(marker, '    invoke-static {%s}, Lcom/ggufchat/app/SearchTool;->%s'
                                    '(Ljava/lang/Object;Lorg/json/JSONObject;)V\n' % (args, call) + marker)
        s = s[:a] + part + s[b:]
    p.write_text(s)


def patch_search_service(app):
    """A consulta real passa a registrar provedor, consulta e fontes na mensagem."""
    p = app / 'GenerationService.smali'
    s = p.read_text()
    a = s.index('.method private runGeneration('); b = s.index('.end method', a)
    part = s[a:b]
    old = '    invoke-static {v4, v5}, Lcom/ggufchat/app/WebSearch;->search(Ljava/lang/String;I)Ljava/util/List;'
    assert part.count(old) == 1, 'WebSearch call site changed'
    replacement = ('    invoke-static {v4, v5}, Lcom/ggufchat/app/SearchTool;->searchText'
                   '(Ljava/lang/String;I)Ljava/lang/String;')
    part = part.replace(old, replacement)
    lines = part.split('\n')
    start = next(i for i, line in enumerate(lines) if line.strip() == replacement.strip())
    end = None
    for i in range(start + 1, len(lines)):
        if lines[i].strip() == 'move-object v10, v4':
            end = i
            break
        assert 'move-result-object v4' in lines[i] or 'toPromptText' in lines[i] or lines[i].strip() == '' \
            or lines[i].strip().startswith('.line'), 'Unexpected instructions in the search block'
    assert end is not None, 'Search result handoff changed'
    assert sum('toPromptText' in line for line in lines[start:end + 1]) == 1
    lines[start + 1:end + 1] = ['', '    move-result-object v10', '']
    part = '\n'.join(lines)
    assert 'toPromptText' not in part
    marker = '    invoke-static {v7}, Lcom/ggufchat/app/GenerationStats;->attach(Ljava/lang/Object;)V'
    assert part.count(marker) == 1, 'Message construction changed'
    part = part.replace(marker, marker + '\n    invoke-static {v7}, Lcom/ggufchat/app/SearchTool;->attach(Ljava/lang/Object;)V')
    s = s[:a] + part + s[b:]
    p.write_text(s)


def patch_chat_activity(app):
    p = app / 'ChatActivity.smali'
    s = p.read_text()
    # 1. Streaming: raciocínio separado, resposta segue no renderizador incremental.
    old = '    invoke-static {v0, p1}, Lcom/ggufchat/app/CodeBlocks;->append(Landroid/widget/TextView;Ljava/lang/String;)V'
    assert s.count(old) == 1, 'Streaming append call site changed'
    s = s.replace(old, '    invoke-static {p0, v0, p1}, Lcom/ggufchat/app/StreamingUi;->token'
                       '(Landroid/app/Activity;Landroid/widget/TextView;Ljava/lang/String;)V')
    # 2. Fim da geração: o estado de streaming é liberado junto com a View.
    a = s.index('.method private onDone()V'); b = s.index('.end method', a); part = s[a:b]
    marker = '    .prologue'
    assert part.count(marker) == 1
    part = part.replace(marker, marker + '\n    invoke-static {p0}, Lcom/ggufchat/app/StreamingUi;->finish'
                                        '(Landroid/app/Activity;)V', 1)
    s = s[:a] + part + s[b:]
    # 3. Histórico: painel recolhível de raciocínio, negrito/itálico/código e fontes.
    marker = ('    invoke-static {p0, v4, v0}, Lcom/ggufchat/app/GenerationStatsUi;->caption'
              '(Landroid/content/Context;Landroid/widget/LinearLayout;Ljava/lang/Object;)V')
    assert s.count(marker) == 1, 'Rendered-message hook changed'
    s = s.replace(marker, marker + '\n'
                  '    invoke-static {p0, v4}, Lcom/ggufchat/app/ThinkingView;->upgrade'
                  '(Landroid/content/Context;Landroid/widget/LinearLayout;)V\n'
                  '    invoke-static {p0, v4, v0}, Lcom/ggufchat/app/SearchTool;->decorateMessage'
                  '(Landroid/content/Context;Landroid/widget/LinearLayout;Ljava/lang/Object;)V')
    # 4. Linha de status informa a consulta pedida antes da geração.
    marker = '    invoke-static {p0}, Lcom/ggufchat/app/ResponseTiming;->sent(Landroid/app/Activity;)V'
    assert s.count(marker) == 1, 'Send hook changed'
    s = s.replace(marker, marker + '\n    invoke-static {p0}, Lcom/ggufchat/app/StreamingUi;->announce'
                                  '(Landroid/app/Activity;)V')
    p.write_text(s)


def patch_ui_features(app):
    patch_message_field(app)
    patch_search_service(app)
    patch_chat_activity(app)
