#!/usr/bin/env python3
"""Sign the verified relay APK using the private persistent LOCAL key.

Never creates a replacement key, never copies the key/password to Git or CI.
Run with the workspace venv containing jdk4py and the pinned APK signing tool.
"""
import hashlib,json,os,subprocess,zipfile
from pathlib import Path
import jdk4py

ROOT=Path(__file__).resolve().parents[1]
key=ROOT/'.signing/gguf-stable.p12'
password=ROOT/'.signing/password'
if not key.is_file() or not password.is_file():
    raise SystemExit('Persistent signing key unavailable. Refusing to silently change signature.')
source=ROOT/'.delivery/GGUF-Chat-mobile-unsigned.apk'
metadata=json.loads((ROOT/'.delivery/mobile-build.json').read_text())
if hashlib.sha256(source.read_bytes()).hexdigest()!=metadata['sha256']:
    raise SystemExit('Unsigned APK does not match its build provenance')
signer=ROOT/'.cache/tools/package/lib/apksigner.jar'
if hashlib.sha256(signer.read_bytes()).hexdigest()!='eefdd6aed9db9fb849e4c98a50d8741e19d1b674ba6547220bcb9c3ed152123a':
    raise SystemExit('Unexpected APK signing tool')
out=ROOT/'.delivery/GGUF-Chat-mobile.apk'
env=dict(os.environ,GGUF_KEYSTORE_PASSWORD=password.read_text())
java=str(jdk4py.JAVA_HOME/'bin/java')
subprocess.run([java,'-jar',str(signer),'sign','--ks',str(key),'--ks-key-alias','gguf-stable',
               '--ks-pass','env:GGUF_KEYSTORE_PASSWORD','--v1-signing-enabled','false',
               '--v2-signing-enabled','true','--v3-signing-enabled','true','--v4-signing-enabled','false',
               '--out',str(out),str(source)],env=env,check=True)
verification=subprocess.check_output([java,'-jar',str(signer),'verify','--verbose','--print-certs',str(out)],text=True)
print(verification)
with zipfile.ZipFile(source) as a,zipfile.ZipFile(out) as b:
    assert a.namelist()==b.namelist(), 'Signing changed ZIP payload names'
    for name in a.namelist():assert a.read(name)==b.read(name), name
metadata['unsigned_sha256']=metadata.pop('sha256')
metadata['apk_sha256']=hashlib.sha256(out.read_bytes()).hexdigest()
metadata['signer_sha256']=next(line.split(': ',1)[1] for line in verification.splitlines() if line.startswith('Signer #1 certificate SHA-256 digest:'))
expected=ROOT/'.signing/certificate.sha256'
if expected.exists():
    assert expected.read_text().strip()==metadata['signer_sha256'],'SIGNING CERTIFICATE CHANGED'
else: expected.write_text(metadata['signer_sha256']+'\n')
metadata['status']='SIGNED_PENDING_ANDROID_TEST'
(ROOT/'.delivery/mobile-signed.json').write_text(json.dumps(metadata,indent=2))
print('Signed exact payload:',out,'SHA-256:',metadata['apk_sha256'])
