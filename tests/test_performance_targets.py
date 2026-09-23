"""Contratos desta entrega: backend declarado, medição auditável e metas.

Estas verificações fixam o que foi entregue para desempenho e para a interface
inspirada no Off Grid AI. Elas não produzem números: os números vêm do emulador
(contadores nativos) e são conferidos por `scripts/check_performance.py`.
"""
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'apk-fix'))

NATIVE = ROOT / 'apk-fix/native/mobile.cpp'


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_software_vulkan_is_refused_and_the_choice_is_visible():
    cpp = NATIVE.read_text()
    assert 'software_vulkan_device(vulkan_devices[0],&description)' in cpp
    assert 'allow_software_vulkan()' in cpp and 'debug.gguf.allow_software_vulkan' in cpp
    for needle in ('llvmpipe', 'lavapipe', 'swiftshader'):
        assert needle in cpp, f'dispositivo por software não reconhecido: {needle}'
    assert 'GGUF_VULKAN_SOFTWARE_DEVICE' in cpp and 'GGUF_BACKEND_NOTICE' in cpp
    assert 'Java_com_ggufchat_app_BackendNotice_read' in cpp
    java = (ROOT / 'apk-fix/java/com/ggufchat/app/BackendNotice.java').read_text()
    assert 'public static native String read()' in java
    assert 'statusLine' in java, 'o aviso precisa aparecer na tela, não só no log'
    stream = (ROOT / 'apk-fix/java/com/ggufchat/app/StreamingUi.java').read_text()
    assert stream.count('BackendNotice.show(activity)') == 2, 'aviso no envio e no primeiro texto'


def test_prefill_lots_scale_with_context_and_decode_stays_one_token():
    cpp = NATIVE.read_text()
    assert 'const uint32_t prefill_batch=context>=1024?512:(context>=512?256:128);' in cpp
    assert 'const uint32_t prefill_ubatch=context>=1024?128:64;' in cpp
    assert 'cp.n_batch=prefill_batch; cp.n_ubatch=prefill_ubatch;' in cpp
    assert 'prefill_policy=larger_lots' in cpp
    # Um token por decodificação: lote só afeta a entrada do prompt.
    assert 'llama_batch_get_one(&t,1)' in cpp
    assert 'cp.n_outputs_max=1' in cpp


def test_native_counters_and_first_text_are_logged_and_parsed():
    java = (ROOT / 'apk-fix/java/com/ggufchat/app/StatsLog.java').read_text()
    flat = ' '.join(java.split())
    assert ('"GGUF_GENERATION_STATS tokens=%d decode_ns=%d prefill_ns=%d tokens_s=%.3f " '
            '+"first_token_ns=%d prompt_tokens=%d reused_tokens=%d completed=%d version=3"') in flat
    # GenerationStats precisa continuar compilável sem android.jar.
    stats = (ROOT / 'apk-fix/java/com/ggufchat/app/GenerationStats.java').read_text()
    assert 'import android' not in stats and 'StatsLog' in stats and 'Class.forName' in stats
    from android_checks import generation_stats, software_vulkan_refused, ui_first_text_s
    log = ('I GGUFStats: GGUF_GENERATION_STATS tokens=64 decode_ns=3200000000 prefill_ns=900000000 '
           'tokens_s=99.000 first_token_ns=1500000000 prompt_tokens=41 reused_tokens=0 completed=1 version=3\n'
           'I GGUFUiTiming: GGUF_UI_FIRST_TEXT send_to_first_ui_ns=1700000000\n'
           'I GGUFVulkan: GGUF_VULKAN_SOFTWARE_DEVICE description="llvmpipe (LLVM 21.0.0)" '
           'action=cpu_fallback requested_layers=99 reason=software_driver_is_slower_than_cpu\n')
    stats = generation_stats(log)
    # A taxa é recalculada dos inteiros nativos, nunca lida do texto formatado.
    assert stats['tokens'] == 64 and stats['tokens_s'] == pytest.approx(20.0)
    assert stats['first_token_s'] == pytest.approx(1.5) and stats['completed'] is True
    assert ui_first_text_s(log) == pytest.approx(1.7)
    assert software_vulkan_refused(log).startswith('llvmpipe')
    assert generation_stats('sem medição') is None and ui_first_text_s('sem medição') is None


def test_performance_report_requires_both_targets_from_measured_values():
    harness = _module('harness_under_test', ROOT / 'scripts/test_android.py')
    baseline = {'tokens_s': 10.0, 'first_token_s': 3.0}
    good = {'baseline': 'vulkan',
            'vulkan': baseline,
            'cpu': {'tokens_s': 15.5, 'first_token_s': 1.0},
            'cpu-threads-auto': {'tokens_s': 12.0, 'first_token_s': 2.9}}
    report = harness.performance_report(good)
    assert report['targets_met'] == ['cpu'], 'só a etapa que cumpre as DUAS metas é aprovada'
    assert report['candidates']['cpu']['throughput_gain_vs_baseline'] == pytest.approx(1.55)
    assert report['candidates']['cpu']['first_token_speedup_vs_baseline'] == pytest.approx(3.0)
    assert report['candidates']['cpu-threads-auto']['targets'] == {'throughput_1_5x': False, 'first_token_3x': False}
    assert 'primeiro texto' in report['scope'] and 'tokens nativos' in report['scope']


def test_performance_gate_reads_the_measurement_and_flags_the_interpretation(tmp_path):
    gate = (ROOT / 'scripts/check_performance.py').read_text()
    assert 'tokens nativos' in gate
    assert 'impossível' in gate, 'a leitura literal de -300% precisa ficar registrada'
    missing = Path(tmp_path) / 'nao-existe.json'
    with pytest.raises(SystemExit):
        sys.argv = ['check_performance.py', str(missing)]
        _module('gate_under_test', ROOT / 'scripts/check_performance.py').main()


def test_offgrid_ui_covers_every_screen_without_renaming_labels():
    java = (ROOT / 'apk-fix/java/com/ggufchat/app/OffgridUi.java').read_text()
    assert 'Typeface.MONOSPACE' in java and '0xFF34D399' in java
    assert 'dp(view, 8)' in java, 'cantos de 8 dp da referência'
    # Nenhum rótulo muda de caixa nem é reescrito: os testes procuram o texto real.
    assert 'setAllCaps(true)' not in java
    assert 'setText(' not in java and 'const-string' not in java
    patch = (ROOT / 'apk-fix/offgrid_ui.py').read_text()
    for hook in ('OffgridUi;->screen', 'OffgridUi;->chat', 'OffgridUi;->tabs', 'OffgridUi;->bubble'):
        assert hook in patch, f'gancho ausente: {hook}'


def test_offgrid_ui_patch_lands_on_all_real_screens(tmp_path):
    base = ROOT / '.cache/original-decoded/smali/com/ggufchat/app'
    if not base.is_dir():
        pytest.skip('APK decodificado local ausente; a cadeia roda no CI')
    app = Path(tmp_path) / 'app'
    shutil.copytree(base, app)
    import build_mobile
    build_mobile.ui_patches(app)
    main = (app / 'MainActivity.smali').read_text()
    chat = (app / 'ChatActivity.smali').read_text()
    settings = (app / 'SettingsActivity.smali').read_text()
    assert main.count('OffgridUi;->screen') == 1 and main.count('OffgridUi;->tabs') == 1
    assert chat.count('OffgridUi;->chat') == 1 and chat.count('OffgridUi;->bubble') == 1
    assert settings.count('OffgridUi;->screen') == 1
    # Os ganchos só inserem chamadas de estilo: nenhum texto, nenhum const-string.
    patch = (ROOT / 'apk-fix/offgrid_ui.py').read_text()
    inserted = [line for line in patch.splitlines() if 'OffgridUi;->' in line]
    assert len(inserted) >= 4
    assert all('setText' not in line and 'const-string' not in line for line in inserted)
