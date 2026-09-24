"""O harness mede o que diz medir — e não estima quando falta medição.

Dois pontos são testados aqui sem emulador, porque são lógica de medição:
  * o envio com pausa de digitação entra em duas passadas (é o cenário que
    permite ao aplicativo aquecer o prompt enquanto o usuário escreve);
  * `warmup_experiment` só declara comparação quando as duas medições existem na
    mesma rodada; faltando uma, ele diz que não comparou em vez de extrapolar.
"""
import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'apk-fix'))


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    module = importlib.import_module('test_android')
    return module


def make_recorder(module, tmp_path):
    class Recorder(module.Android):
        def __init__(self):
            super().__init__('emulator-test', tmp_path)
            self.calls = []

        def adb(self, *args, check=True, timeout=45, binary=False, with_status=False):
            self.calls.append(('adb',) + tuple(map(str, args)))
            return ''

        def shell(self, command, **kwargs):
            self.calls.append(('shell', command))
            return ''

        def tap(self, **selector):
            self.calls.append(('tap', json.dumps({k: sorted(v) if isinstance(v, set) else v
                                                   for k, v in selector.items()}, sort_keys=True)))
            return True

    return Recorder()


def test_typed_send_splits_the_text_in_two_passes_with_a_pause(harness, tmp_path, monkeypatch):
    device = make_recorder(harness, tmp_path)
    monkeypatch.setattr(harness.time, 'sleep', lambda seconds: device.calls.append(('sleep', seconds)))
    device.send('Reply in English with a short greeting.', typed_pause=1.2)
    texts = [call[1] for call in device.calls if call[0] == 'shell']
    assert len(texts) == 2, texts
    parts = [text.split('input text ', 1)[1].strip("'").replace('%s', ' ') for text in texts]
    assert ''.join(parts) == 'Reply in English with a short greeting.'  # nada é perdido
    # A pausa fica entre as duas passadas, nunca depois do envio.
    order = [call[0] for call in device.calls]
    assert order.index('sleep') == order.index('shell') + 1
    assert device.calls[-1][0] == 'tap' and 'Enviar' in device.calls[-1][1]


def test_plain_send_stays_a_single_pass(harness, tmp_path):
    device = make_recorder(harness, tmp_path)
    device.send('Reply in English with a short greeting.')
    texts = [call[1] for call in device.calls if call[0] == 'shell']
    assert texts == ['input text Reply%sin%sEnglish%swith%sa%sshort%sgreeting.']  # uma passada
    assert all(call[0] != 'sleep' for call in device.calls)


def test_warmup_experiment_refuses_to_claim_without_both_measurements(harness):
    only_on = {'gpu-preferred-cold': {'ui_first_text_s': 1.5, 'tokens_s': 10.0,
                                      'prefill_s': 0.02, 'reused_tokens': 62}}
    report = harness.warmup_experiment(only_on)
    assert report['compared'] is False
    assert 'wait_speedup_cold' not in report
    assert 'off' in report['scope']


def test_warmup_experiment_computes_the_ratio_from_measured_values(harness):
    perf = {
        'gpu-off-cold': {'ui_first_text_s': 3.0, 'first_token_s': 2.9, 'prefill_s': 1.6,
                         'reused_tokens': 0, 'tokens_s': 10.0},
        'gpu-preferred-cold': {'ui_first_text_s': 0.6, 'first_token_s': 0.5, 'prefill_s': 0.02,
                               'reused_tokens': 63, 'tokens_s': 10.1},
        'gpu-preferred-typed': {'ui_first_text_s': 0.55, 'tokens_s': 10.2},
    }
    report = harness.warmup_experiment(perf)
    assert report['compared'] is True
    assert report['wait_speedup_cold'] == 5.0
    assert report['reused_tokens_off'] == 0
    assert report['reused_tokens_cold'] == 63
    assert report['wait_speedup_typed'] == round(0.6 / 0.55, 3)


def test_performance_report_keeps_the_regression_veto(harness):
    """O aquecimento não pode virar permissão para regressão de taxa."""
    perf = {
        'vulkan': {'tokens_s': 10.0, 'ui_first_text_s': 2.0, 'first_token_s': 1.9},
        'gpu-preferred-cold': {'tokens_s': 9.0, 'ui_first_text_s': 0.4, 'first_token_s': 0.3},
    }
    report = harness.performance_report(perf)
    assert report['regressions'] == ['gpu-preferred-cold']
    assert report['warmup_experiment']['compared'] is False


def test_gpu_experiment_suite_is_opt_in(harness, monkeypatch):
    monkeypatch.delenv('GGUF_EXPERIMENT_SUITE', raising=False)
    assert harness.gpu_experiments_enabled() is False
    monkeypatch.setenv('GGUF_EXPERIMENT_SUITE', '0')
    assert harness.gpu_experiments_enabled() is False
    monkeypatch.setenv('GGUF_EXPERIMENT_SUITE', '1')
    assert harness.gpu_experiments_enabled() is True


def test_warmup_state_requires_the_native_counter(harness):
    from android_checks import warmup_state
    java_only = 'I GGUFWarmup: GGUF_WARMUP_UI ok=1 chars=180'
    assert warmup_state(java_only)['ran'] is False
    native = ('I GGUFChatNative: GGUF_WARMUP input_tokens=64 prefilled=63 reused_tokens=0 gpu=0 aborted=0\n'
              + java_only)
    state = warmup_state(native)
    assert state['ran'] is True and state['prefilled'] == 63 and state['ui_ok'] is True
    off = 'I GGUFChatNative: GGUF_WARMUP_SKIPPED reason=property'
    assert warmup_state(off) == {'ran': False, 'skipped': 'property', 'ui_ok': False, 'typed_passes': 0}


def test_backend_classification_follows_the_native_declaration(harness):
    """O log do carregador não decide o backend: a declaração do nativo decide.

    Caso real medido na rodada 36038199713: o Vulkan por software foi recusado
    (execução na CPU), mas o carregador ainda escreveu "offloaded 31/31 layers to
    GPU" porque o pedido de camadas era INT_MAX. Classificar por essa linha
    chamaria de GPU uma execução na CPU.
    """
    from android_checks import backend_execution, gpu_offloaded
    refused = ('GGUF_VULKAN_SOFTWARE_DEVICE description="llvmpipe (LLVM 21.0.0)" '
               'action=cpu_fallback requested_layers=-1\n'
               'load_tensors: offloaded 31/31 layers to GPU\n'
               'GGUF_BACKEND_EXECUTION backend=cpu reason=software_vulkan_refused\n')
    assert backend_execution(refused) == 'cpu'
    assert gpu_offloaded(refused) is False
    strict = ('load_tensors: offloaded 31/31 layers to GPU\n'
              'GGUF_BACKEND_EXECUTION backend=vulkan layers=31 total=31\n')
    assert backend_execution(strict) == 'vulkan' and gpu_offloaded(strict) is True
    # Logs anteriores à declaração continuam classificáveis pelo texto antigo.
    legacy = 'load_tensors: offloaded 31/31 layers to GPU\n'
    assert backend_execution(legacy) is None and gpu_offloaded(legacy) is True
    cpu_choice = 'GGUF_BACKEND_EXECUTION backend=cpu reason=cpu_choice\n'
    assert gpu_offloaded(cpu_choice) is False


def test_software_refusal_really_forces_cpu_in_the_native():
    """A recusa precisa valer: sem zerar n_gpu_layers o carregador ainda anuncia GPU."""
    native = (ROOT / 'apk-fix/native/mobile.cpp').read_text()
    start = native.index('software_vulkan_device(vulkan_devices[0],&description)')
    block = native[start:native.index('} else {', start)]
    assert 'mp.n_gpu_layers=0;' in block, 'recusa sem efeito: o pedido de camadas continua valendo'
    assert 'mp.devices=no_accelerators;' in block
    # O aviso de GPU só pode ser escrito quando o dispositivo estrito existe.
    assert 'const bool gpu_executes=(e->layers>0 && e->strict_device!=nullptr);' in native
    assert native.count('GGUF_BACKEND_EXECUTION backend=vulkan') == 1
