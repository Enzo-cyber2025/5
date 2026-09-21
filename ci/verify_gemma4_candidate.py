"""Verify exact new signed bytes and unchanged unsigned payload before Android."""
import hashlib,json,zipfile
from pathlib import Path
expected=json.loads(Path('ci/gemma4-candidate.json').read_text())
meta=json.loads(Path('.delivery/mobile-signed.json').read_text())
unsigned_meta=json.loads(Path('.delivery/mobile-build.json').read_text())
a=Path('.delivery/GGUF-Chat-mobile.apk');b=Path('.delivery/GGUF-Chat-mobile-unsigned.apk')
assert hashlib.sha256(a.read_bytes()).hexdigest()==expected['apk_sha256']==meta['apk_sha256']
assert a.stat().st_size==expected['size']
assert meta['signer_sha256']==expected['signer_sha256']=='9a368c9a1e4f3b3b0b6ecfb86aa3768d633a925855afba27eab3b9189177955a'
assert meta['source_commit']==expected['source_commit']==unsigned_meta['source_commit']
assert meta['llama_commit']==expected['llama_commit']=='b29c606e28a01b1bc8c1351026a0fa6e616bf6c4'
assert hashlib.sha256(b.read_bytes()).hexdigest()==meta['unsigned_sha256']==unsigned_meta['sha256']
with zipfile.ZipFile(b) as original,zipfile.ZipFile(a) as signed:
    assert original.namelist()==signed.namelist()
    for name in original.namelist():assert original.read(name)==signed.read(name),name
p=Path('evidence');p.mkdir(exist_ok=True)
(p/'physical-gemma4-signed-provenance.json').write_text(json.dumps(dict(expected,status='PASS',payload='All ZIP entries byte-identical to unsigned compilation'),indent=2))
print('GEMMA4_SIGNED_CANDIDATE_PROVENANCE_PASS')
