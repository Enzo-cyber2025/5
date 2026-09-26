"""Os ajudantes do harness também rodam no host — antes de gastar um emulador.

Motivo direto: a rodada 36192982173 perdeu as fases de desempenho e de funções
porque `prefill_metric` chamava `re.findall` sem o módulo importado. Nada disso
precisava de um aparelho para ser descoberto: as funções são puras (ou quase) e
podem ser exercitadas aqui, com um aparelho de mentira.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# Os módulos do harness importam uns aos outros pelo nome (android_checks vive em
# scripts/), então o caminho entra antes de qualquer import deles.
sys.path.insert(0, str(ROOT / 'scripts'))


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


harness = load('harness_under_test', 'scripts/test_android.py')


def perf_entry(tokens_s, ui_first, first_token, prompt=800, reused=40, prefill_ns=800_000_000):
    return {'tokens_s': tokens_s, 'ui_first_text_s': ui_first, 'first_token_s': first_token,
            'prefill': {'prompt_tokens': prompt, 'reused_tokens': reused,
                        'fresh_tokens': prompt - reused, 'prefill_s': prefill_ns / 1e9,
                        'prefill_ms_per_token': round(prefill_ns / 1e6 / (prompt - reused), 3)}}


def test_prefill_experiment_uses_its_own_metric_and_stays_out_of_the_throughput_race():
    perf = {'vulkan': perf_entry(1.0, 20.0, 18.0),
            'cpu-threads-auto': perf_entry(9.0, 0.4, 0.3),
            'prefill-ubatch-128': perf_entry(9.0, 6.0, 5.9, prompt=700, reused=0,
                                             prefill_ns=6_000_000_000),
            'prefill-ubatch-256': perf_entry(9.0, 4.0, 3.9, prompt=700, reused=0,
                                             prefill_ns=3_000_000_000)}
    report = harness.performance_report(perf)
    # A comparação de sub-lote mede pré-preenchimento: fora da conta de ganho/regressão.
    assert 'prefill-ubatch-128' not in report['candidates']
    assert 'prefill-ubatch-256' not in report['candidates']
    experiment = report['prefill_experiment']
    assert experiment['status'] == 'MEDIDO'
    assert experiment['best'] == 'prefill-ubatch-256'
    assert experiment['gain_x'] == pytest.approx(2.0, abs=0.01)
    assert 'regressions' in report and report['regressions'] == []
    json.dumps(report)  # a evidência precisa ser serializável


def test_prefill_experiment_declares_absence_instead_of_guessing():
    report = harness.performance_report({'vulkan': perf_entry(1.0, 20.0, 18.0),
                                         'prefill-ubatch-256': perf_entry(9.0, 4.0, 3.9)})
    assert report['prefill_experiment']['status'] == 'NOT_MEASURED'
    assert 'faltou a métrica' in report['prefill_experiment']['detail']


class FakeDevice:
    """Aparelho de mentira: só o que os ajudantes usam, com a tela que eu escolho."""

    def __init__(self, screens, package='com.ggufchat.app'):
        self.screens = list(screens)
        self.package = package
        self.actions = []

    def ui(self):
        return self.screens[0] if len(self.screens) == 1 else self.screens.pop(0)

    def shell(self, command, check=True):
        self.actions.append(command)
        return ''


def screen(*labels, package='com.ggufchat.app'):
    # enabled=true e bounds com área são exigidos pelo extrator real: um nó
    # invisível ou desabilitado não é um controle que o usuário alcança.
    nodes = ''.join(f'<node package="{package}" text="{label}" content-desc="" enabled="true" '
                    f'bounds="[0,0][10,10]" />' for label in labels)
    return f'<hierarchy>{nodes}</hierarchy>'


def test_visible_labels_lists_what_is_on_screen():
    sweep = load('sweep_under_test', 'scripts/test_functions_android.py')
    device = FakeDevice([screen('Nova conversa', 'Ajustes')])
    assert sweep.visible_labels(device) == ['Nova conversa', 'Ajustes']


def test_scroll_to_swipes_and_finds_the_label_below_the_fold():
    sweep = load('sweep_under_test', 'scripts/test_functions_android.py')
    device = FakeDevice([screen('Camadas na GPU'), screen('Camadas na GPU'),
                         screen('Camadas na GPU', 'Salvar ajustes')])
    assert sweep.scroll_to(device, 'Salvar ajustes') is True
    assert any('swipe' in action for action in device.actions)


def test_scroll_to_gives_up_without_lying():
    sweep = load('sweep_under_test', 'scripts/test_functions_android.py')
    device = FakeDevice([screen('Camadas na GPU')] * 6)
    assert sweep.scroll_to(device, 'Salvar ajustes') is False
