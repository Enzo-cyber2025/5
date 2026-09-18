#!/usr/bin/env python3
"""Sign a gain-approved, immutable APK payload with a locally retained key.
Never signs/presents a candidate from a failed or incomplete gate. No private
signing material is uploaded to Git/CI or printed. Does not install/uninstall.
"""
import hashlib,json,os,re,secrets,subprocess,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'ci'))
from perceptible_image_gate import evaluate,CANDIDATE
from perceptible_text_gate import evaluate as evaluate_text

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def signature_entry(name):
    n=name.upper()
    if not n.startswith('META-INF/'):return False
    tail=n[len('META-INF/'):]
    return '/' not in tail and (tail=='MANIFEST.MF' or tail.endswith(('.SF','.RSA','.DSA','.EC')) or tail.startswith('SIG-'))
def payload(path):
    with zipfile.ZipFile(path) as z:
        names=z.namelist()
        if len(names)!=len(set(names)):raise ValueError('Duplicate ZIP entries')
        return {n:hashlib.sha256(z.read(n)).hexdigest() for n in names if not signature_entry(n)}

def main(report_dir,text_report_dir):
    source=ROOT/'.delivery/GGUF-Chat-gain-approved-payload.apk'
    report=json.loads((Path(report_dir)/'summary.json').read_text())
    assert report['status']=='PASS_GAIN_GATE_RETAINED_IMAGES_ONLY'
    gate=evaluate(report);assert gate['gain_gate_passed']
    text_report=json.loads((Path(text_report_dir)/'summary.json').read_text())
    assert text_report['status']=='PASS_TEXT_GAIN_GATE','Text gain has not passed; combined delivery is blocked'
    text_gate=evaluate_text(text_report);assert text_gate['text_gain_passed']
    assert sha(source)==CANDIDATE,'Only the exact validated compiled payload may be signed'
    destination=ROOT/'entrega/GGUF-Chat-acelerado.apk'
    if destination.exists():raise RuntimeError('Delivery file already exists; never silently replace a signed release')
    import jdk4py
    java=Path(jdk4py.JAVA_HOME)/'bin/java';keytool=java.with_name('keytool')
    signer=ROOT/'.cache/tools/package/lib/apksigner.jar';assert java.exists() and keytool.exists() and signer.exists()
    private=ROOT/'.signing';private.mkdir(exist_ok=True);private.chmod(0o700)
    key=private/'ggufchat-speed.p12';password=private/'ggufchat-speed.password'
    if key.exists()!=password.exists():raise RuntimeError('Incomplete signing state; do not rotate or overwrite keys')
    if not key.exists():
        old_umask=os.umask(0o077)
        try:
            with password.open('x') as f:f.write(secrets.token_hex(32)+'\n')
            temp=private/'ggufchat-speed.new.p12'
            if temp.exists():raise RuntimeError('Unresolved signing transaction')
            subprocess.run([str(keytool),'-genkeypair','-keystore',str(temp),'-storetype','PKCS12',
                            '-storepass:file',str(password),'-keypass:file',str(password),'-alias','ggufchat-speed',
                            '-keyalg','RSA','-keysize','3072','-validity','36500',
                            '-dname','CN=GGUF Chat Speed, O=GGUF Chat'],check=True,capture_output=True)
            temp.rename(key)
        finally:os.umask(old_umask)
    key.chmod(0o600);password.chmod(0o600)
    work=ROOT/'.cache/gain-release';work.mkdir(parents=True,exist_ok=True)
    candidate=work/'signed.apk'
    subprocess.run([str(java),'-jar',str(signer),'sign','--ks',str(key),'--ks-key-alias','ggufchat-speed',
                    '--ks-pass','file:'+str(password),'--key-pass','file:'+str(password),
                    '--v1-signing-enabled','false','--v2-signing-enabled','true','--v3-signing-enabled','true',
                    '--out',str(candidate),str(source)],check=True,capture_output=True)
    verified=subprocess.check_output([str(java),'-jar',str(signer),'verify','--verbose','--print-certs',str(candidate)],text=True)
    cert=re.search(r'Signer #1 certificate SHA-256 digest: ([0-9a-f]{64})',verified);assert cert
    assert payload(source)==payload(candidate),'Signing changed non-signature APK data'
    assert 'Verified using v2 scheme (APK Signature Scheme v2): true' in verified
    destination.parent.mkdir(exist_ok=True);candidate.replace(destination)
    (ROOT/'.delivery/gain-release-signature.txt').write_text(verified)
    record={'status':'SIGNED_AFTER_PERCEPTIBLE_IMAGE_GATE','apk_path':str(destination.relative_to(ROOT)),
            'apk_sha256':sha(destination),'signer_sha256':cert[1],'payload_source_sha256':CANDIDATE,
            'compiled_source':'81bc70c8c1025fb8d46f7d99a8f9ee63af95b711','non_signature_payload_identical':True,
            'gate':gate,'text_gate':text_gate,'signing_key_retained_locally':True,'old_delivered_apk_preserved':True,
            'update_warning':'Different certificate from delivered 7295. Not an in-place update; do not uninstall the existing app without preserving its data.',
            'scope':'Measured retained-image reactivation benefit only; not first-image or general text/GPU speed certification. GPU input-packing/batch/QKV experiments are not enabled.'}
    (ROOT/'.delivery/perceptible-speed-delivery.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({'apk':str(destination),'sha256':record['apk_sha256'],'signer_sha256':cert[1]},indent=2))
if __name__=='__main__':
    if len(sys.argv)!=3:raise SystemExit('Usage: sign_gain_release.py IMAGE_REPORT_DIR TEXT_REPORT_DIR; both gates required')
    main(sys.argv[1],sys.argv[2])
