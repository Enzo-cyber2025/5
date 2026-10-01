"""Mobile packaging/policy unit tests; NOT substitutes for Android inference."""
import re
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'apk-fix'))
from mobile_manifest import enforce_min_sdk


def test_actual_manifest_minimum_and_payload_preservation():
    if not (ROOT/'.cache/gguf/GGUF-Chat.apk').is_file():
        pytest.skip('APK original verificado ausente; scripts/fetch_original.py baixa')

    with zipfile.ZipFile(ROOT/'.cache/gguf/GGUF-Chat.apk') as z:
        original=z.read('AndroidManifest.xml')
    patched=enforce_min_sdk(original)
    changed=[i for i,(a,b) in enumerate(zip(original,patched)) if a!=b]
    assert len(changed)==1 and len(original)==len(patched)
    assert original[changed[0]]==24 and patched[changed[0]]==28
    assert enforce_min_sdk(patched)==patched
    assert enforce_min_sdk(patched,24)==patched


def test_invalid_manifest_not_silently_packaged():
    with pytest.raises((ValueError,struct.error)):
        enforce_min_sdk(b'not a manifest')
    with pytest.raises(ValueError):
        enforce_min_sdk(struct.pack('<HHI',3,8,8))


def test_real_native_utf8_chunk_boundary_function(tmp_path):
    source=(ROOT/'apk-fix/native/mobile.cpp').read_text()
    function=re.search(r'static size_t complete_utf8\(.*?\n}',source,re.S).group()
    cpp=tmp_path/'utf8.cpp'
    cpp.write_text('#include <string>\n#include <cassert>\n'+function+r'''
int main() {
    const std::string texts[]={u8"Olá",u8"🔧",u8"ação",u8"你好",u8"Hello 🔧 Brasil"};
    for(const auto &text:texts) {
        std::string pending,result;
        for(char byte:text) {
            pending+=byte;
            auto n=complete_utf8(pending);
            result+=pending.substr(0,n);pending.erase(0,n);
        }
        assert(pending.empty());assert(result==text);
    }
    assert(complete_utf8("\xc3")==0);
    assert(complete_utf8("\xf0\x9f\x94")==0);
    assert(complete_utf8("abc\xf0\x9f\x94")==3);
}
''')
    executable=tmp_path/'utf8'
    subprocess.run(['g++','-std=c++17',str(cpp),'-o',str(executable)],check=True)
    subprocess.run([str(executable)],check=True)
