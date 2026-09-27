"""A entrega publica o que foi MEDIDO — e nunca um pino que envelheceu.

O link de download já foi publicado uma vez com pino manual (`ci-results/36041334551…`,
`tested_commit b55d4b1`) e passou a comparar contra uma rodada antiga: o fluxo continuaria
"verde" enquanto os bytes entregues não fossem mais os exercitados. Estes testes fixam o
contrato novo, no host, antes de gastar qualquer runner.
"""
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/deliver-gpu-warmup.yml'


@pytest.fixture()
def workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def steps_by_name(workflow):
    return {step.get('name'): step for step in workflow['jobs']['deliver']['steps']}


def test_no_hand_written_run_pins_remain():
    text = WORKFLOW.read_text()
    assert 'ci-results/36041334551' not in text
    assert 'b55d4b1f13545dd1417c3673cc6fa4b4e19d1515' not in text
    assert "'tested_run': 36041334551" not in text
    # a rodada vem da API, com o resultado exigido declarado
    assert 'status=success' in text and 'text-ui.yml/runs' in text


def test_the_resolved_run_must_be_the_commit_being_delivered():
    """Recibo de outra revisão não vale: os hashes dele descrevem outros bytes.

    Entre a rodada verde e o commit da entrega só podem existir commits que NÃO
    mudam o APK (evidência publicada pela própria rodada, notas, este fluxo). Se
    qualquer arquivo de `apk-fix/**`, `ci/**` ou do fluxo do emulador aparecer na
    diferença, a entrega para — e os hashes do recibo continuam sendo a última
    palavra antes de publicar qualquer byte.
    """
    text = WORKFLOW.read_text()
    assert '[ "$sha" != "$(git rev-parse HEAD)" ]' in text
    assert 'skip=1' in text and "steps.green.outputs.skip != '1'" in text
    # A lista de permitidos existe, é explícita e não inclui o código do aplicativo.
    assert 'permitidos=' in text
    permitidos = text.split('permitidos=', 1)[1].split('\n', 1)[0]
    for caminho in ('ci-results/', 'docs/', 'tests/', 'scripts/', 'README', '.delivery/'):
        assert caminho in permitidos, caminho
    for caminho in ('apk-fix/', 'ci/emulator', 'emulator-text-ui'):
        assert caminho not in permitidos, caminho
    assert 'mudanca_apk=$(git diff --name-only "$sha" HEAD' in text
    assert 'payload diferente do testado' in text


def test_the_expensive_steps_do_not_run_without_a_green_run(workflow):
    steps = steps_by_name(workflow)
    for name in ('Compile the native stack, helper Java and patched DEX',
                 'Sign with a key generated here and verify the tested payload',
                 'Publish the release and the receipt'):
        assert steps[name]['if'] == "steps.green.outputs.skip != '1'", name


def test_the_receipt_is_confronted_against_the_resolved_run(workflow):
    text = WORKFLOW.read_text()
    assert "os.environ['GREEN_RECEIPT']" in text
    assert "os.environ['GREEN_SHA']" in text
    assert "'tested_run': int(os.environ['GREEN_RUN'])" in text
    assert 'payload diferente do testado' in text


def test_release_notes_come_from_the_measurement_not_from_typed_numbers():
    text = WORKFLOW.read_text()
    assert "notes-medidos.md" in text
    assert "physical-text-ui-build.json" in text
    # números escritos à mão na nota antiga não podem voltar
    assert '2,140 s' not in text
    assert '3,79x' not in text
    assert "perf.get('warmup_experiment')" in text
    assert "functions-sweep.txt" in text

def test_a_lista_de_permitidos_casa_arquivos_dentro_das_pastas_nao_a_pasta_como_string():
    """O bug que pulou a publicação (rodada 36350833517).

    A regex estava ancorada com `$` no grupo inteiro, então só casava a string
    exata "ci-results/" — nenhum arquivo DENTRO da pasta. A diferença até o commit
    de evidência (que o CI empurra com [skip ci]) era lida como "mexeu no
    aplicativo" e a entrega pulava os passos de build/assinatura/publicação,
    deixando a release antiga no ar sem publicar nada. Este teste roda a regex como
    o `grep -vE` do fluxo roda, em caminhos reais.
    """
    import re
    texto = WORKFLOW.read_text()
    permitidos = texto.split('permitidos=', 1)[1].split('\n', 1)[0].strip().strip("'")
    for caminho in ('ci-results/36346929204-1-text-ui/apk-payload.json',
                    'ci-results/36346929204-1-text-ui/physical-text-ui-build.json',
                    'ci-results/delivery-gpu-warmup.json',
                    'docs/GPU_WARMUP_NPU.md', 'tests/test_sweep_coverage.py',
                    'scripts/test_android.py', '.delivery/nota.md', 'README.md',
                    '.github/workflows/deliver-gpu-warmup.yml'):
        assert re.search(permitidos, caminho), f'a entrega precisa permitir {caminho}'
    for caminho in ('apk-fix/native/mobile.cpp', 'apk-fix/java/com/ggufchat/app/SearchTool.java',
                    'ci/emulator-text-ui.sh', '.github/workflows/text-ui.yml',
                    'README1.md', 'ci-resultsx/qualquer'):
        assert not re.search(permitidos, caminho), f'a entrega NÃO pode permitir {caminho}'
