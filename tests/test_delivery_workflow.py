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
    """Recibo de outra revisão não vale: os hashes dele descrevem outros bytes."""
    text = WORKFLOW.read_text()
    assert '[ "$sha" != "$(git rev-parse HEAD)" ]' in text
    assert 'skip=1' in text and "steps.green.outputs.skip != '1'" in text


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
