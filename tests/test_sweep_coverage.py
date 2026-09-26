"""Contratos da varredura funcional: toda função declarada, todo veredito real.

O pedido foi "testa TODAS as funções". Estes testes protegem o que faz a varredura
valer: cada função da lista tem implementação, o veredito é PASS/FAIL/SKIP com
motivo, SKIP existe para peça ausente (nunca PASS por omissão), a visão só é
aprovada com o motor tendo avaliado a imagem, e o caminho do par visão/mmproj está
ligado no CI quando as peças existem.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SWEEP = ROOT / 'scripts/test_functions_android.py'
SCRIPT = ROOT / '.github/emulator-text-ui.sh'
WORKFLOW = ROOT / '.github/workflows/text-ui.yml'


def test_every_listed_function_has_an_implementation():
    source = SWEEP.read_text()
    ordem = re.search(r'ordem = \[(.*?)\n    \]', source, re.DOTALL).group(1)
    nomes = re.findall(r"\('(\w+)', (\w+)\)", ordem)
    assert len(nomes) == 20, nomes
    for nome, funcao in nomes:
        assert f'def {funcao}():' in source, f'{nome} não tem implementação ({funcao})'


def test_verdicts_are_declared_with_reason_and_skip_is_not_a_pass():
    source = SWEEP.read_text()
    # Três vereditos, e o SKIP carrega o motivo de peça ausente.
    assert "self.results[name] = {'status': 'SKIP', 'detail': str(skip)}" in source
    assert "self.results[name] = {'status': 'FAIL', 'detail': detail}" in source
    assert "self.results[name] = {'status': 'PASS', 'detail': detail}" in source
    assert 'class SkipCheck(Exception):' in source
    # O relatório é reprovado por qualquer falha e sai com o resumo completo.
    assert "if report['status'] != 'PASS':" in source
    assert 'functions-sweep.txt' in source and 'functions-sweep.json' in source


def test_vision_is_only_approved_when_the_engine_evaluated_the_image():
    source = SWEEP.read_text()
    funcao = source[source.index('    def visao():'):source.index('    def notificacao():')]
    # Sem o par: SKIP declarado, nunca aprovação por omissão.
    assert 'raise SkipCheck' in funcao
    # Com o par: o que prova é o motor ter avaliado a imagem e a resposta persistida.
    assert 'GGUF_IMAGE_EVALUATED' in funcao
    assert 'GGUF_IMAGE_EVALUATED' in source
    assert "assistant_reply" in funcao
    assert '--vision' in source and "'--vision'" in source
    # A cópia do anexo é a mesma do caminho já provado (SAF + hash conferido).
    assert 'attach(device, chat, [nome])' in funcao
    # O par entra como o APLICATIVO o entrega: UMA seleção, dois arquivos, um GGUF
    # físico. Duas seleções separadas deixam mmprojPath=null (rodada 36258711211).
    assert 'device.pair_import(args.vision, args.mmproj)' in funcao
    assert 'import_model(args.vision)' not in funcao
    # E o botão Foto é provado na conversa multimodal (não só desenhado).
    assert 'foto_com_par(device)' in funcao


def test_pair_import_is_one_selection_and_needs_the_app_own_unification():
    harness = (ROOT / 'scripts/test_android.py').read_text()
    funcao = harness[harness.index('    def pair_import(self'):harness.index('    def new_chat(self')]
    # Seleção múltipla REAL no seletor do sistema, com os ícones de marcação.
    assert 'select_exact_documents(self, [vision.name, projector.name])' in funcao
    # E a unificação tem de vir do próprio aplicativo, com o log dele.
    assert 'GGUF_PHYSICAL_UNIFICATION_OK' in funcao
    assert 'unificado' in funcao
    # Duas seleções separadas não são aceitas como par.
    assert 'import_model(args.vision)' not in harness
    # A fase de texto não pode mais aceitar o formato legado como par importado agora.
    assert 'unified_vision(device.read_json("models.json"))' in harness
    # Foto: a decisão é do MODELO DA CONVERSA, não da flag do runner.
    sweep = SWEEP.read_text()
    seletores = sweep[sweep.index('    def seletores():'):sweep.index('    def ferramentas_dialogo():')]
    assert 'if args.mmproj:' not in seletores, 'a flag do runner não decide o comportamento do aplicativo'


def test_deleting_a_model_removes_every_listed_model():
    source = SWEEP.read_text()
    funcao = source[source.index('    def excluir_modelo():'):source.index('    def sem_modelo():')]
    # Com o par de visão importado há mais de um modelo: apagar só o primeiro deixaria
    # a função seguinte ("sem modelo") medindo outra coisa.
    assert 'for modelo in models:' in funcao
    assert 'all(m.get(\'name\') != nome for m in restantes)' in funcao


def test_ci_passes_the_vision_pair_to_the_sweep_when_the_pieces_exist():
    script = SCRIPT.read_text()
    assert 'VISAO=(--vision "$GGUF_TEST_VISION" --mmproj "$GGUF_TEST_MMPROJ")' in script
    assert '"${VISAO[@]}"' in script
    workflow = WORKFLOW.read_text()
    assert 'GGUF_TEST_VISION: .cache/mobile-models/SmolVLM-256M-Instruct-Q8_0.gguf' in workflow
    assert ('GGUF_TEST_MMPROJ: .cache/mobile-models/'
            'mmproj-SmolVLM-256M-Instruct-Q8_0.gguf') in workflow
    # As peças baixadas e conferidas por hash são exatamente essas.
    models = (ROOT / 'ci/mobile-models.sh').read_text()
    assert 'SmolVLM-256M-Instruct-Q8_0.gguf' in models
    assert 'mmproj-SmolVLM-256M-Instruct-Q8_0.gguf' in models


def test_unload_is_proven_by_the_engine_log_not_by_an_expiring_toast():
    """Rodada 36255713807: o \"descarregar modelo\" era aprovado só pelo toast.

    O toast vive poucos segundos e não diz se HAVIA motor para descarregar; a
    rodada falhou ao lê-lo antes de expirar. A prova passou a ser o log do próprio
    binário (GGUF_UNIT_RELEASED found=1) mais a recarga real (GGUF_UNIT_LOADED).
    """
    sweep = SWEEP.read_text()
    assert 'GGUF_UNIT_RELEASED' in sweep, 'a varredura precisa exigir o log do motor'
    assert "liberado.group(1) != '1'" in sweep, 'só found=1 prova que havia motor para liberar'
    assert 'GGUF_UNIT_LOADED' in sweep, 'a recarga real continua sendo exigida'
    # Sem o MESMO processo, o botão não teria motor carregado para liberar: a prova
    # tem de vir de uma resposta gerada antes, sem reiniciar o aplicativo.
    funcao = sweep[sweep.index('    def descarregar_e_recarregar():'):sweep.index('    def nova_conversa():')]
    assert 'device.generate(model, 0, \'functions-unload-pre\'' in funcao
    assert "device.alive() != pid" in funcao
    assert 'device.launch()' not in funcao.split('device.generate(model, 0, \'functions-unload-pre\'')[1].split('GGUF_UNIT_RELEASED')[0], \
        'reiniciar o aplicativo antes do toque esvazia a prova: sem motor, não há o que descarregar'
    native = (ROOT / 'apk-fix/native/mobile.cpp').read_text()
    assert 'GGUF_UNIT_RELEASED found=%d remaining=%zu' in native, \
        'Native.destroy é quem sabe se havia motor; sem esse log a prova volta a ser um toast'
    assert 'Java_com_ggufchat_app_Native_destroy' in native
