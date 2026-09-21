"""Fail before emulator startup if the signed artifact/provenance/payload differs."""
import hashlib,json,zipfile
from pathlib import Path
signed=Path('.delivery/GGUF-Chat-mobile.apk');unsigned=Path('.delivery/GGUF-Chat-mobile-unsigned.apk')
m=json.loads(Path('.delivery/mobile-signed.json').read_text())
assert m['source_commit']=='4fa8dbca578a70df91798c3b80b24d66f6c485f0'
assert m['apk_sha256']=='4d1697c2ee9b80ba38a03ee78ab0241dc8aa3d5464c956707e2412be70b11ce6'
assert m['signer_sha256']=='9a368c9a1e4f3b3b0b6ecfb86aa3768d633a925855afba27eab3b9189177955a'
assert hashlib.sha256(signed.read_bytes()).hexdigest()==m['apk_sha256']
assert hashlib.sha256(unsigned.read_bytes()).hexdigest()==m['unsigned_sha256']=='93ddb8a94c35bebce45db4c0bfcc2517895f4573701c363c30f402427151111c'
with zipfile.ZipFile(unsigned) as a,zipfile.ZipFile(signed) as b:
    assert a.namelist()==b.namelist()
    for name in a.namelist():assert a.read(name)==b.read(name),name
p=Path('evidence');p.mkdir(exist_ok=True)
(p/'physical-signed-provenance.json').write_text(json.dumps({'status':'PASS','source_commit':m['source_commit'],'unsigned_sha256':m['unsigned_sha256'],'apk_sha256':m['apk_sha256'],'signer_sha256':m['signer_sha256'],'payload':'All ZIP entries byte-identical to the compiled unsigned APK; only signing container changes.'},indent=2))
print('SIGNED_PHYSICAL_PAYLOAD_PROVENANCE_PASS')
