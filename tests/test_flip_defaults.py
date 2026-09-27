"""O padrão do aplicativo só muda com ganho medido — e é o script que muda.

`scripts/flip_search_defaults.py` é a única porta pela qual uma melhoria medida vira
padrão (corrida entre provedores, cache de consulta repetida, sub-lote do
pré-preenchimento e cache K/V). Estes testes rodam o script de verdade, sobre CÓPIAS dos
arquivos do aplicativo, e exigem:

* ganho abaixo de 1,1x: NADA é escrito e o script reprova;
* ganho medido: o padrão muda, com o número da rodada e o ganho no próprio código;
* `--dry-run`: nada é escrito.

Numeração e texto importam: quem ler o código depois tem de saber de onde veio o padrão.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/flip_search_defaults.py'
TOOL = 'apk-fix/java/com/ggufchat/app/SearchTool.java'
NATIVE = 'apk-fix/native/mobile.cpp'


def copia_do_repositorio(tmp_path):
    for relativo in (TOOL, NATIVE):
        destino = tmp_path / relativo
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relativo, destino)
    return tmp_path


def roda(tmp_path, *args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=tmp_path,
                          capture_output=True, text=True)


def test_ganho_abaixo_do_minimo_nao_muda_nada(tmp_path):
    copia_do_repositorio(tmp_path)
    antes = (tmp_path / TOOL).read_text(), (tmp_path / NATIVE).read_text()
    resultado = roda(tmp_path, '--race-gain', '1,05', '--round', '36200000000')
    assert resultado.returncode == 1, resultado.stdout + resultado.stderr
    assert 'menor que 1.1x' in resultado.stdout
    assert (antes[0], antes[1]) == ((tmp_path / TOOL).read_text(), (tmp_path / NATIVE).read_text()), \
        'nenhum byte pode mudar sem ganho medido'


def test_dry_run_nao_escreve(tmp_path):
    copia_do_repositorio(tmp_path)
    antes = (tmp_path / TOOL).read_text(), (tmp_path / NATIVE).read_text()
    resultado = roda(tmp_path, '--race-gain', '1,3', '--ubatch-gain', '1,2', '--kv-gain', '1,2',
                     '--round', '36200000000', '--dry-run')
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    assert '(ensaio)' in resultado.stdout
    assert (antes[0], antes[1]) == ((tmp_path / TOOL).read_text(), (tmp_path / NATIVE).read_text())


def test_ganho_medido_vira_padrao_com_a_rodada_no_codigo(tmp_path):
    copia_do_repositorio(tmp_path)
    resultado = roda(tmp_path, '--race-gain', '1,25', '--ubatch-gain', '1,4', '--kv-gain', '1,15',
                     '--round', '36200000000')
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    tool = (tmp_path / TOOL).read_text()
    nativo = (tmp_path / NATIVE).read_text()
    assert 'intProperty(RACE_PROPERTY,1)!=0' in tool, 'a corrida vira padrão e continua desligável'
    assert 'intProperty(CACHE_PROPERTY,60000)' in tool, 'a consulta repetida sai da memória'
    assert '36200000000' in tool and '1.25' in tool, 'o ganho e a rodada ficam registrados'
    assert 'prefill_ubatch=context>=1024?256:64' in nativo
    assert 'debug.gguf.kv_type",8' in nativo, 'cache K/V Q8_0 por padrão'
    assert nativo.count('36200000000') == 2, 'as duas mudanças nativas citam a rodada'
    # A propriedade de depuração continua mandando: é ela que permite comparar de novo.
    assert 'debug.gguf.search_race 0' in tool


def test_os_arquivos_do_repositorio_tem_os_apoios_que_o_script_precisa():
    """O script procura textos exatos: se um deles sumir, a próxima virada falharia calada."""
    tool = (ROOT / TOOL).read_text()
    nativo = (ROOT / NATIVE).read_text()
    assert re.search(r'private static boolean raceEnabled\(\)\{return intProperty\(RACE_PROPERTY,[01]\)', tool)
    assert re.search(r'private static int cacheMs\(\)\{return Math\.max\(0,intProperty\(CACHE_PROPERTY,\d+\)\);\}', tool)
    assert re.search(r'const long kv_tuned=debug_int\("debug\.gguf\.kv_type",[08]\);', nativo)
    assert ('uint32_t prefill_ubatch=context>=1024?128:64;' in nativo
            or 'uint32_t prefill_ubatch=context>=1024?256:64;' in nativo)
