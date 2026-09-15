import json,hashlib,zipfile
from pathlib import Path
c=json.load(open('ci/import-ui-candidate.json'));m=json.load(open('.delivery/mobile-signed.json'));u=json.load(open('.delivery/mobile-build.json'))
a=Path('.delivery/GGUF-Chat-mobile.apk');b=Path('.delivery/GGUF-Chat-mobile-unsigned.apk');old=Path('.cache/import-ui-base.apk')
assert hashlib.sha256(a.read_bytes()).hexdigest()==c['apk_sha256']==m['apk_sha256']
assert a.stat().st_size==c['size']
assert c['signer_sha256']==m['signer_sha256']==c['previous_signer_sha256']=='9b658c30f602e0f2ff65c176423cb95bea8fbdeb660c306ab908862f90d9bc3c'
assert m['source_commit']==u['source_commit']==c['source_commit']
assert hashlib.sha256(b.read_bytes()).hexdigest()==u['sha256']==m['unsigned_sha256']
assert hashlib.sha256(old.read_bytes()).hexdigest()==c['ui_base_apk_sha256']=='afaf22c63022b44320604407246abe47a921c4e4d1fe55694ce7428abb047e86'
with zipfile.ZipFile(a) as signed,zipfile.ZipFile(b) as unsigned,zipfile.ZipFile(old) as base:
 assert signed.namelist()==unsigned.namelist()==base.namelist()
 for n in signed.namelist():
  assert signed.read(n)==unsigned.read(n),n
  if n!='classes.dex':assert signed.read(n)==base.read(n),n
p=Path('evidence');p.mkdir(exist_ok=True)
(p/'physical-import-ui-provenance.json').write_text(json.dumps(dict(c,status='PASS',scope='All resources, native libraries, second DEX and assets byte-identical to last approved release; signed payload matches UI-only compilation'),indent=2))
print('IMPORT_UI_SIGNATURE_AND_UNCHANGED_PAYLOAD_PASS')
