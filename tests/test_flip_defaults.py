"""O script que vira padrão só age com ganho MEDIDO — e só nos arquivos certos.

Regra da entrega: nenhum padrão de busca ou de pré-preenchimento muda por palpite.
`scripts/flip_search_defaults.py` recebe o ganho medido na mesma rodada e só
reescreve o código quando ele passa de 1,1× (abaixo disso é ruído); abaixo do
mínimo ele não escreve UM byte. Estes testes rodam o script de verdade, numa cópia
dos arquivos reais, para travar isso.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/flip_search_defaults.py'
TOOL = ROOT / 'apk-fix/java/com/ggufchat/app/SearchTool.java'
NATIVE = ROOT / 'apk-fix/native/mobile.cpp'
RODADA = '36165160000'


def copia(tmp_path):
    """Cópia dos dois arquivos que o script edita, no caminho que ele espera."""
    (tmp_path / 'apk-fix/java/com/ggufchat/app').mkdir(parents=True)
    (tmp_path / 'apk-fix/native').mkdir(parents=True)
    shutil.copy(TOOL, tmp_path / 'apk-fix/java/com/ggufchat/app/SearchTool.java')
    shutil.copy(NATIVE, tmp_path / 'apk-fix/native/mobile.cpp')
    return tmp_path


def roda(tmp_path, *args):
    return subprocess.run([sys.executable, str(SCRIPT), '--round', RODADA, *args],
                          cwd=tmp_path, capture_output=True, text=True)


def tool(tmp_path):
    return (tmp_path / 'apk-fix/java/com/ggufchat/app/SearchTool.java').read_text()


def nativo(tmp_path):
    return (tmp_path / 'apk-fix/native/mobile.cpp').read_text()


def test_ganho_abaixo_do_minimo_nao_escreve_um_byte(tmp_path):
    work = copia(tmp_path)
    antes_tool, antes_nativo = tool(work), nativo(work)
    resultado = roda(work, '--race-gain', '1.05', '--ubatch-gain', '1.04', '--kv-gain', '1.02')
    assert resultado.returncode == 1, resultado.stdout
    assert 'NADA foi mudado' in resultado.stdout
    assert 'a corrida e o cache NÃO mudam' in resultado.stdout
    assert tool(work) == antes_tool and nativo(work) == antes_nativo


def test_ganho_medido_vira_padrao_com_a_rodada_no_codigo(tmp_path):
    work = copia(tmp_path)
    resultado = roda(work, '--race-gain', '1.25', '--ubatch-gain', '1.30', '--kv-gain', '1.20')
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    texto = tool(work)
    assert 'private static boolean raceEnabled(){return intProperty(RACE_PROPERTY,1)!=0;}' in texto
    assert 'private static int cacheMs(){return Math.max(0,intProperty(CACHE_PROPERTY,60000));}' in texto
    assert RODADA in texto and '1.25' in texto, 'a rodada e o ganho ficam no comentário'
    assert 'debug.gguf.search_race 0' in texto, 'o desligamento continua documentado'
    codigo = nativo(work)
    assert ': (context>=1024?256:64);' in codigo, 'sub-lote 256 com o ganho medido'
    assert f'rodada {RODADA}' in codigo
    assert 'debug_int("debug.gguf.kv_type",8)' in codigo, 'cache K/V em Q8_0 com o ganho medido'


def test_uma_alavanca_com_ganho_muda_sozinha_sem_as_outras(tmp_path):
    """K/V medido e corrida não: o cache K/V vira Q8_0 e a busca fica como está."""
    work = copia(tmp_path)
    antes_tool = tool(work)
    resultado = roda(work, '--kv-gain', '1.30')
    assert resultado.returncode == 0, resultado.stdout
    assert 'debug_int("debug.gguf.kv_type",8)' in nativo(work)
    assert tool(work) == antes_tool, 'a corrida não foi medida: não pode ser ligada'
    assert ': (context>=1024?128:64);' in nativo(work), 'o sub-lote não foi medido: não muda'


def test_ensaio_mostra_o_que_faria_sem_escrever(tmp_path):
    work = copia(tmp_path)
    antes_tool, antes_nativo = tool(work), nativo(work)
    resultado = roda(work, '--race-gain', '2.0', '--ubatch-gain', '1.5', '--kv-gain', '1.4', '--dry-run')
    assert resultado.returncode == 0, resultado.stdout
    assert 'ensaio' in resultado.stdout
    assert tool(work) == antes_tool and nativo(work) == antes_nativo


def test_os_arquivos_do_repositorio_tem_os_apoios_que_o_script_precisa():
    """Se alguém reescrever esses trechos, o script avisa em vez de mentir."""
    texto, codigo = TOOL.read_text(), NATIVE.read_text()
    assert re.search(r'private static boolean raceEnabled\(\)\{return intProperty\(RACE_PROPERTY,[01]\)', texto)
    assert re.search(r'private static int cacheMs\(\)\{return Math\.max\(0,intProperty\(CACHE_PROPERTY,\d+\)\);\}', texto)
    assert re.search(r'const long kv_tuned=debug_int\("debug\.gguf\.kv_type",[08]\);', codigo)
    assert ': (context>=1024?128:64);' in codigo or ': (context>=1024?256:64);' in codigo
