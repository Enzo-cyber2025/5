"""Um dump de UI vazio é repetido, nunca tratado como tela ou falha do app.

A rodada 36026742459 reprovou a fase de anexos com

    ParseError: syntax error: line 1, column 0

porque o `uiautomator` respondeu sucesso sem produzir XML enquanto a janela do
seletor de arquivos trocava, e o retry existia só na subclasse usada por outros
testes. O comportamento agora é da classe base: repete a coleta até obter um XML
válido e só então segue. Nada é reaproveitado de uma coleta anterior.
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from test_android import Android  # noqa: E402

VALID = "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><hierarchy rotation=\"0\">" \
        "<node index=\"0\" text=\"Ajustes\" content-desc=\"\" class=\"android.widget.Button\" package=\"com.ggufchat.app\" " \
        "enabled=\"true\" bounds=\"[0,0][10,10]\"/></hierarchy>"


class FakeAndroid(Android):
    def __init__(self, dumps, evidence):
        Android.__init__(self, 'emulator-9999', evidence)
        self.dumps = list(dumps)
        self.reads = 0

    def _ui_dump(self):
        self.reads += 1
        return self.dumps.pop(0) if self.dumps else ''

    def alive(self):
        return 4242

    def sleep(self, seconds):
        pass


def test_empty_dump_is_retried_until_a_real_screen_arrives(tmp_path, monkeypatch):
    monkeypatch.setattr('test_android.time.sleep', lambda seconds: None)
    d = FakeAndroid(['', '   ', VALID], tmp_path)
    xml = d.ui()
    assert d.reads == 3, 'as coletas vazias precisam ser repetidas'
    assert 'Ajustes' in xml


def test_persistent_empty_dump_still_fails(tmp_path, monkeypatch):
    monkeypatch.setattr('test_android.time.sleep', lambda seconds: None)
    d = FakeAndroid(['', '', ''], tmp_path)
    with pytest.raises(ET.ParseError):
        d.ui()


def test_no_stale_dump_is_reused(tmp_path, monkeypatch):
    monkeypatch.setattr('test_android.time.sleep', lambda seconds: None)
    d = FakeAndroid([VALID], tmp_path)
    first = d.ui()
    d.dumps = ['']          # a tela seguinte não produziu dump
    with pytest.raises(ET.ParseError):
        d.ui()
    assert first != '' , 'o dump anterior não pode substituir a coleta falhada'
    assert not list(tmp_path.glob('ui-0002.xml')), 'nenhum XML vazio é arquivado'
