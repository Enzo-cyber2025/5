"""O aviso da GPU diz QUAL dispositivo executa e o que o driver OFERECE.

Motivo direto: o aparelho do relato é um Galaxy A55 (Exynos 1480) com GPU Xclipse
530 (AMD RDNA). O emulador do CI não tem Xclipse — o `Vulkan0` dele é o
rasterizador por software `llvmpipe`, que o aplicativo recusa. Então o que dá para
fazer aqui, e é o que estes testes travam, é: (a) o nome do dispositivo vem do
driver e aparece na tela; (b) o aplicativo declara o que o backend encontrou
(matrizes cooperativas, FP16, dot inteiro), em vez de prometer aceleração; (c) a
escolha do sub-lote do pré-preenchimento é por CLASSE de dispositivo, e a classe
vai para o log.

A linha usada como exemplo de Xclipse é ILUSTRATIVA (a forma que o backend imprime;
não foi colhida de um A55) — o valor real, em cada aparelho, é o que o driver
reporta.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'apk-fix/native'
CPP = (NATIVE / 'mobile.cpp').read_text()

PROBE = r'''
#include <cstdio>
#include <string>
#include "device_caps.h"

static void show(const char *label, const char *line) {
    const DeviceCaps caps = device_caps_parse(line);
    printf("%s|%s|%s|%s|%s|%s\n", label, caps.device.c_str(), caps.matrix_cores.c_str(),
           caps.fp16.c_str(), caps.warp_size.c_str(), device_caps_summary(caps).c_str());
}

int main() {
    // Linha real do emulador do CI (llvmpipe), como ela sai no log da rodada.
    show("software",
         "ggml_vulkan: 0 = llvmpipe (LLVM 21.0.0, 256 bits) | uma: 1 | fp16: 0 | bf16: 0 | "
         "warp size: 32 | shared memory: 32768 | int dot: 0 | matrix cores: none\n");
    // Forma que um driver de GPU real imprime (Xclipse 530 = GPU do Galaxy A55).
    show("xclipse",
         "ggml_vulkan: 0 = Xclipse 530 (Samsung, Vulkan 1.3) | uma: 1 | fp16: 1 | bf16: 1 | "
         "warp size: 64 | shared memory: 65536 | int dot: 1 | matrix cores: KHR\n");
    // Linha que não é a de dispositivos: nada a declarar.
    show("outra", "load_tensors: offloaded 31/31 layers to GPU\n");
    show("vazia", nullptr);
    return 0;
}
'''


@pytest.fixture(scope='module')
def caps_output():
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
        return {line.split('|')[0]: line.split('|')[1:] for line in run.stdout.splitlines()}


def test_a_linha_do_rasterizador_por_software_e_declarada_como_tal(caps_output):
    device, matrix, fp16, warp, resumo = caps_output['software']
    assert device == 'llvmpipe (LLVM 21.0.0, 256 bits)'
    assert matrix == 'none' and fp16 == '0' and warp == '32'
    assert resumo == 'coopmat nenhum', 'sem matrizes cooperativas, o aviso diz isso'


def test_a_linha_de_uma_gpu_real_e_lida_por_inteiro(caps_output):
    device, matrix, fp16, warp, resumo = caps_output['xclipse']
    assert device == 'Xclipse 530 (Samsung, Vulkan 1.3)'
    assert (matrix, fp16, warp) == ('KHR', '1', '64')
    assert resumo == 'coopmat KHR', 'o caminho rápido do driver é declarado pelo nome'


def test_linha_que_nao_e_de_dispositivos_nao_declara_nada(caps_output):
    for chave in ('outra', 'vazia'):
        device, matrix, fp16, warp, resumo = caps_output[chave]
        assert (device, matrix, resumo) == ('', '', ''), chave
        assert (fp16, warp) == ('', ''), chave


def test_o_aviso_e_o_log_do_nativo_usam_essa_leitura():
    assert '#include "device_caps.h"' in CPP
    assert 'static DeviceCaps g_device_caps;' in CPP
    assert 'const DeviceCaps caps=device_caps_parse(text);' in CPP
    assert 'GGUF_DEVICE_CAPS device=\\"%s\\" uma=%s fp16=%s int_dot=%s warp=%s shared=%s matrix_cores=%s' in CPP
    assert 'const std::string extras=device_caps_summary(g_device_caps);' in CPP
    # O aviso continua sendo escrito UMA vez por carga, e com o nome do dispositivo.
    assert CPP.count('g_backend_notice="GPU (Vulkan, "+device_name') == 1
    assert CPP.count('GGUF_BACKEND_NOTICE') >= 3


def test_o_documento_do_aparelho_declara_o_que_nao_foi_medido():
    doc = (ROOT / 'docs/GPU_WARMUP_NPU.md').read_text()
    assert 'Xclipse 530' in doc
    assert 'coopmat' in doc
    assert 'llvmpipe' in doc
    assert 'nada nesta página afirma ganho medido' in doc
