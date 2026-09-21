import json,hashlib,zipfile
from pathlib import Path

def verify():
 c=json.load(open('ci/performance-candidate.json'));m=json.load(open('.delivery/mobile-signed.json'));u=json.load(open('.delivery/mobile-build.json'))
 assert c['apk_sha256']==m['apk_sha256']==hashlib.sha256(Path('.delivery/GGUF-Chat-mobile.apk').read_bytes()).hexdigest()
 assert c['source_commit']==m['source_commit']==u['source_commit']==u['native_source_commit']
 assert c['signer_sha256']==m['signer_sha256']
 assert m['unsigned_sha256']==u['sha256']==hashlib.sha256(Path('.delivery/GGUF-Chat-mobile-unsigned.apk').read_bytes()).hexdigest()
 with zipfile.ZipFile('.delivery/GGUF-Chat-mobile.apk') as a,zipfile.ZipFile('.delivery/GGUF-Chat-mobile-unsigned.apk') as b:
  assert a.namelist()==b.namelist()
  for n in a.namelist():assert a.read(n)==b.read(n),n
  for n,h in u['native'].items():assert hashlib.sha256(a.read(n)).hexdigest()==h,n
  for abi in ('arm64-v8a','x86_64'):assert f'lib/{abi}/libggufcpu.so' in a.namelist()
  for v in ('dotprod','i8mm'):assert f'lib/arm64-v8a/libaijni_{v}.so' in a.namelist()
 print('PERFORMANCE_CANDIDATE_EXACT_PAYLOAD_PASS')
if __name__=='__main__':verify()
