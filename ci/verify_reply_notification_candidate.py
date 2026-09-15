"""Fail closed on changed weights/native/resources, signing payload or source pins."""
import hashlib,json,zipfile
from pathlib import Path
BASE='eabd016935ac51cdd89063a97fbc1b562f7f9261981f54b5191d37734e7922eb'
SIGNER='4f75afe8637f28ccb167db407e3b2bc9b260e1cfe6059b7377ea20b0b4dc2ac3'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def verify():
 c=json.load(open('ci/reply-notification-candidate.json'));u=json.load(open('.delivery/mobile-build.json'));m=json.load(open('.delivery/mobile-signed.json'))
 assert c['baseline_sha256']==u['notification_base_sha256']==BASE==sha('.cache/reply-base.apk')
 assert c['apk_sha256']==m['apk_sha256']==sha('.delivery/GGUF-Chat-mobile.apk')
 assert u['sha256']==m['unsigned_sha256']==sha('.delivery/GGUF-Chat-mobile-unsigned.apk')
 assert c['source_commit']==m['source_commit']==u['source_commit']
 assert m['signer_sha256']==c['signer_sha256']==SIGNER
 assert u['native_source_commit']==m['native_source_commit']=='ce0118db8646f1523d11725a8c5c29b6e88230f2'
 assert set(u['changed_classes'])=={'GenerationService.smali','GenerationService$1.smali','GenerationService$2.smali'}
 assert 'ReplyNotifications.smali' in u['added_classes'] and all(n.startswith('ReplyNotifications') for n in u['added_classes'])
 with zipfile.ZipFile('.cache/reply-base.apk') as a,zipfile.ZipFile('.delivery/GGUF-Chat-mobile-unsigned.apk') as b,zipfile.ZipFile('.delivery/GGUF-Chat-mobile.apk') as s:
  assert a.namelist()==b.namelist()==s.namelist()
  assert a.read('classes.dex')!=b.read('classes.dex')
  for name in b.namelist():
   assert s.read(name)==b.read(name),name
   if name!='classes.dex':assert a.read(name)==b.read(name),name
  for name,digest in u['native'].items():assert hashlib.sha256(s.read(name)).hexdigest()==digest
 print('NOTIFICATION_CANDIDATE_EXACT_PAYLOAD_PASS')
if __name__=='__main__':verify()
