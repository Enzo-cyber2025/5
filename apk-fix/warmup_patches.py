"""Aquecimento do prefixo: o bloco system deixa de ser pago no primeiro envio.

O gancho é o mesmo ponto das outras camadas de interface — logo depois de a tela
da conversa ser montada —, e só insere uma chamada: nenhum texto, nenhum rótulo e
nenhum fluxo do aplicativo é alterado. De lá, `ResponseWarmup` espera o modelo
ficar pronto, observa o campo de texto e aquece, no nativo, exatamente o prefixo
que o envio real vai reutilizar.
"""

import os

CALL = '    invoke-static {p0}, Lcom/ggufchat/app/ResponseWarmup;->install(Landroid/app/Activity;)V'
MARKER = '    invoke-virtual {p0, v2}, Lcom/ggufchat/app/ChatActivity;->setContentView(Landroid/view/View;)V'
ENV = 'GGUF_EXPERIMENT_WARMUP'


def enabled():
    """O aquecimento entra no APK só quando este canal pede.

    Cada canal de medição deste repositório monta o próprio APK a partir das
    mesmas camadas. Inserir o gancho em todos mudaria silenciosamente o que os
    outros canais medem (o primeiro envio passaria a reutilizar o prefixo), então
    ele é opt-in por variável de ambiente — e a rodada que o liga também mede o
    resultado com ele desligado.
    """
    return os.environ.get(ENV) == '1'


def patch_warmup(app):
    path = app / 'ChatActivity.smali'
    s = path.read_text()
    assert s.count(MARKER) == 1, 'ChatActivity: chamada única esperada para setContentView'
    if not enabled():
        assert CALL not in s, 'aquecimento não pedido, mas já instalado'
        return False
    assert CALL not in s, 'aquecimento já instalado'
    path.write_text(s.replace(MARKER, MARKER + '\n\n' + CALL))
    return True
