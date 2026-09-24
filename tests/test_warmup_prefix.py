"""Duas garantias das quais o aquecimento de prefixo depende, testadas no host.

1. `reusable_prefix` nunca reaproveita o último token do prompt. É esse teto que
   mantém os logits da geração pertencendo ao prompt atual: o aquecimento
   pré-preenche o KV, mas o último token é sempre decodificado pela geração real.
   O teste compila o cabeçalho de produção (`apk-fix/native/prompt_cache.h`) com
   g++ e verifica o comportamento, não o texto do arquivo.

2. A política de NPU reconhece o SoC pelo que o Android expõe e responde "sem
   backend" quando não há backend embarcado — nunca promete aceleração.
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'apk-fix/native'
DECODED = ROOT / '.cache/original-decoded/smali'

PROBE = r'''
#include <cstdio>
#include <string>
#include <vector>
#include "prompt_cache.h"
#include "npu_policy.h"

int main() {
    const std::vector<int> a{1,2,3}, b{1,2,3,4}, c{1,2,9}, empty{};
    printf("unsupported=%zu\n", reusable_prefix(a, b, false, 0, 2));
    printf("single_token=%zu\n", reusable_prefix(a, std::vector<int>{7}, true, 0, 2));
    printf("no_cache=%zu\n", reusable_prefix(empty, b, true, 0, -1));
    printf("pos_mismatch=%zu\n", reusable_prefix(a, b, true, 1, 2));
    printf("evicted=%zu\n", reusable_prefix(a, b, true, 0, 1));
    printf("longer_input=%zu\n", reusable_prefix(a, b, true, 0, 2));
    printf("equal_sizes=%zu\n", reusable_prefix(a, a, true, 0, 2));
    printf("divergent=%zu\n", reusable_prefix(c, b, true, 0, 2));
    printf("longer_cache=%zu\n", reusable_prefix(b, a, true, 0, 3));
    const char *identities[] = {
        "ro.soc.model=Exynos 1480|ro.board.platform=s5e8845",
        "ro.hardware=exynos1480",
        "ro.board.platform=sm8550",
        "ro.soc.model=Zuma",
        "ro.board.platform=mt6789",
        "",
    };
    for (int i = 0; i < 6; ++i) {
        NpuAssessment a = npu_assess(identities[i]);
        printf("npu%d=%s|%d|%s\n", i, a.soc[0] ? a.soc : "unknown",
               (int)a.npu_present, a.backend[0] ? a.backend : "none");
    }
    return 0;
}
'''


@pytest.fixture(scope='module')
def probe_output():
    compiler = shutil.which('g++')
    if not compiler:
        pytest.skip('g++ indisponível neste host')
    with tempfile.TemporaryDirectory() as work:
        source = Path(work) / 'probe.cpp'
        source.write_text(PROBE)
        binary = Path(work) / 'probe'
        built = subprocess.run([compiler, '-std=c++17', '-O1', '-I', str(NATIVE),
                                str(source), '-o', str(binary)],
                               capture_output=True, text=True)
        assert built.returncode == 0, built.stderr
        run = subprocess.run([str(binary)], capture_output=True, text=True)
        assert run.returncode == 0, run.stderr
        return dict(line.split('=', 1) for line in run.stdout.splitlines() if '=' in line)


def test_prefix_reuse_never_consumes_the_last_prompt_token(probe_output):
    # cached == input: o último token fica para a decodificação real.
    assert probe_output['equal_sizes'] == '2'
    # cached maior que o prompt: teto é input.size()-1.
    assert probe_output['longer_cache'] == '2'
    assert probe_output['longer_input'] == '3'


def test_prefix_reuse_requires_a_true_prefix(probe_output):
    assert probe_output['divergent'] == '2'  # 1,2,3 vs 1,2,9 -> reusa 1,2
    assert probe_output['unsupported'] == '0'
    assert probe_output['single_token'] == '0'  # não há prefixo sem sobrar token
    assert probe_output['no_cache'] == '0'


def test_prefix_reuse_respects_kv_positions(probe_output):
    # pos_min != 0 indica prefixo deslocado/evictado; pos_max curto indica buraco.
    assert probe_output['pos_mismatch'] == '0'
    assert probe_output['evicted'] == '0'


def test_npu_policy_recognises_the_galaxy_a55_soc_without_a_backend(probe_output):
    soc, present, backend = probe_output['npu0'].split('|')
    assert (soc, present, backend) == ('Exynos 1480', '1', 'none')
    assert probe_output['npu1'] == 'Exynos 1480|1|none'   # ro.hardware
    assert probe_output['npu2'] == 'Snapdragon 8 Gen 2|1|none'  # outros SoCs, mesmo veredito
    assert probe_output['npu3'] == 'Tensor G3|1|none'


def test_npu_policy_says_unknown_instead_of_promising(probe_output):
    assert probe_output['npu4'] == 'unknown|0|none'
    assert probe_output['npu5'] == 'unknown|0|none'


def test_native_symbol_matches_the_java_declaration():
    """O símbolo JNI tem de casar com a classe que o declara — senão é falha em tempo de execução."""
    java = (ROOT / 'apk-fix/java/com/ggufchat/app/ResponseWarmup.java').read_text()
    declared = re.findall(r'public static native \w+ (\w+)\(', java)
    assert declared == ['nativeWarmup'], declared
    native = (NATIVE / 'mobile.cpp').read_text()
    assert 'Java_com_ggufchat_app_ResponseWarmup_nativeWarmup' in native
    assert 'Java_com_ggufchat_app_Native_generate' in native


def test_jni_registration_table_covers_every_native_method():
    """Todo `native` declarado no Java precisa do símbolo no C++ ou da entrada em RegisterNatives."""
    native = "\n".join(path.read_text() for path in sorted(NATIVE.glob('*.[ch]pp')) + sorted(NATIVE.glob('*.c')))
    java_sources = sorted((ROOT / 'apk-fix/java').rglob('*.java'))
    missing = []
    for path in java_sources:
        text = path.read_text()
        package = re.search(r'package ([\w.]+);', text)
        if not package:
            continue
        owner = package.group(1).replace('.', '_') + '_' + path.stem
        for name in re.findall(r'static native [\w\[\]<>., $?]+ (\w+)\(', text):
            symbol = f'Java_{owner}_{name}'
            registered = re.search(r'\{"' + re.escape(name) + r'",\s*"', text)
            if symbol not in native and not registered:
                missing.append(symbol)
    assert not missing, missing


def test_prefix_warmup_is_inserted_once_and_after_the_screen_exists():
    """O gancho do aquecimento entra depois de a tela existir, e só uma vez."""
    import sys
    sys.path.insert(0, str(ROOT / 'apk-fix'))
    from warmup_patches import CALL, MARKER
    if not (DECODED / 'com/ggufchat/app/ChatActivity.smali').is_file():
        pytest.skip('APK original decodificado ausente (.cache/original-decoded)')
    text = (DECODED / 'com/ggufchat/app/ChatActivity.smali').read_text()
    assert text.count(MARKER) == 1
    assert CALL not in text  # o APK base não traz o gancho
    assert CALL.index('ResponseWarmup') > 0 and 'install(Landroid/app/Activity;)V' in CALL


def test_factory_gpu_default_is_automatic_in_the_base_apk():
    """O padrão de fábrica já pede o modelo inteiro na GPU; o pipeline não o rebaixa."""
    if not (DECODED / 'com/ggufchat/app/Settings.smali').is_file():
        pytest.skip('APK original decodificado ausente (.cache/original-decoded)')
    settings = (DECODED / 'com/ggufchat/app/Settings.smali').read_text()
    start = settings.index('.method public static gpuLayers(')
    body = settings[start:settings.index('.end method', start)]
    assert 'const/4 v2, -0x1' in body
    build = (ROOT / 'apk-fix/build_mobile.py').read_text()
    assert "assert 'const/4 v2, -0x1' in s[a:b]" in build, 'o pipeline precisa travar esse padrão'
    assert "replace('const/4 v2, -0x1'" not in build, 'o pipeline não pode rebaixar o padrão de GPU'


def test_native_sources_pass_the_host_syntax_gate():
    """A mesma checagem que o NDK faria, antes de gastar a rodada de emulador."""
    script = ROOT / 'scripts/check_native_syntax.py'
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'sintaxe ok' in result.stdout or 'SKIP' in result.stdout


def test_java_helpers_compile_with_javac_when_available():
    """Onde existe javac (o CI tem), os ajudantes precisam compilar de verdade."""
    script = ROOT / 'scripts/check_java_compile.py'
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'compila' in result.stdout or 'SKIP' in result.stdout
