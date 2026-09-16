"""Inspect compiled ARM executable sections, not runtime/throughput certification.
Optional local tooling: capstone==5.0.6 pyelftools==0.33.
"""
import hashlib
import io
import json
from collections import Counter
from pathlib import Path
import zipfile

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from elftools.elf.elffile import ELFFile


def inspect(apk):
    report = dict(status='COMPILED_ARM_ISA_SELECTION_PASS',
                  apk_sha256=hashlib.sha256(apk.read_bytes()).hexdigest(), libraries={})
    decoder = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    decoder.skipdata = True
    with zipfile.ZipFile(apk) as archive:
        for name in ('libaijni.so', 'libaijni_dotprod.so', 'libaijni_i8mm.so', 'libggufcpu.so'):
            data = archive.read('lib/arm64-v8a/' + name)
            elf = ELFFile(io.BytesIO(data))
            assert elf['e_machine'] == 'EM_AARCH64'
            counts = Counter()
            for section in elf.iter_sections():
                if section['sh_flags'] & 4:  # SHF_EXECINSTR only
                    counts.update(mnemonic for _, _, mnemonic, _ in
                                  decoder.disasm_lite(section.data(), section['sh_addr'])
                                  if mnemonic in ('sdot', 'udot', 'smmla', 'ummla', 'usmmla'))
            report['libraries'][name] = dict(sha256=hashlib.sha256(data).hexdigest(),
                                             optional_instruction_counts=dict(sorted(counts.items())))
    libs = report['libraries']
    assert not libs['libaijni.so']['optional_instruction_counts']
    assert not libs['libggufcpu.so']['optional_instruction_counts']
    assert libs['libaijni_dotprod.so']['optional_instruction_counts']['sdot'] > 0
    assert libs['libaijni_i8mm.so']['optional_instruction_counts']['smmla'] > 0
    report['scope'] = ('Disassembly of real APK executable ELF sections, limited to listed dot-product/i8mm mnemonics; '
                       'not an exhaustive ISA compatibility audit, physical ARM execution, or speed benchmark.')
    return report


if __name__ == '__main__':
    result = inspect(Path('.delivery/GGUF-Chat-mobile.apk'))
    Path('.delivery/performance-arm-isa.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
