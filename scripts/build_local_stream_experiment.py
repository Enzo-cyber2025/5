#!/usr/bin/env python3
"""DEX-only, opt-in experiment; retain all model/native/resource payload bytes."""
import hashlib,json,os,shutil,subprocess,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'apk-fix'));sys.path.insert(0,str(ROOT/'ci'))
from local_stream import patch
from build_apk import signature_entry
from perceptible_image_gate import BASELINE,CANDIDATE
from sign_gain_release import payload

def run(*args):subprocess.run(list(map(str,args)),check=True)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    os.chdir(ROOT);base=ROOT/'.delivery/GGUF-Chat-gain-approved-payload.apk'
    original=ROOT/'.delivery/GGUF-Chat-mobile.apk'
    assert sha(base)==CANDIDATE and sha(original)==BASELINE
    work=ROOT/'.cache/local-stream';work.mkdir(exist_ok=False)
    sdk=Path(os.environ['ANDROID_HOME']);jar=sdk/'platforms/android-35/android.jar';bt=sdk/'build-tools/35.0.0'
    tool=ROOT/'.cache/tools/package/lib/apktool.jar';decoded=work/'decoded'
    run('java','-jar',tool,'d','-f','-r','-o',decoded,base)
    app=decoded/'smali/com/ggufchat/app';patch(app)
    classes=work/'classes';classes.mkdir();dex=work/'dex';dex.mkdir()
    source=ROOT/'apk-fix/java/com/ggufchat/app/LocalGenerationStream.java'
    run('javac','--release','8','-classpath',jar,'-d',classes,source)
    run(bt/'d8','--min-api','28','--lib',jar,'--output',dex,*classes.rglob('*.class'))
    helper=work/'helper.apk'
    with zipfile.ZipFile(helper,'w') as z:z.write(dex/'classes.dex','classes.dex')
    helperdir=work/'helper';run('java','-jar',tool,'d','-f','-r','-o',helperdir,helper)
    for p in (helperdir/'smali/com/ggufchat/app').glob('*.smali'):
        assert p.name.startswith('LocalGenerationStream') and not (app/p.name).exists()
        shutil.copyfile(p,app/p.name)
    compiled=work/'compiled.apk';run('java','-jar',tool,'b',decoded,'-o',compiled)
    unsigned=work/'unsigned.apk'
    with zipfile.ZipFile(base) as a,zipfile.ZipFile(compiled) as c,zipfile.ZipFile(unsigned,'w') as b:
        for info in a.infolist():
            if signature_entry(info.filename):continue
            b.writestr(info,c.read(info.filename) if info.filename=='classes.dex' else a.read(info.filename))
    aligned=work/'aligned.apk';run(bt/'zipalign','-P','16','-f','4',unsigned,aligned)
    key=work/'test.p12'
    run('keytool','-genkeypair','-keystore',key,'-storepass','android','-alias','test','-keyalg','RSA','-keysize','2048','-validity','2','-dname','CN=Disposable stream experiment NOT release')
    for src,dest in ((aligned,work/'candidate.apk'),(original,work/'before.apk')):
        run(bt/'apksigner','sign','--ks',key,'--ks-pass','pass:android','--out',dest,src)
        run(bt/'apksigner','verify','--verbose',dest)
    key.unlink()
    run(bt/'zipalign','-c','-P','16','4',work/'candidate.apk')
    a,b=payload(base),payload(work/'candidate.apk')
    assert a.keys()==b.keys()
    changed=[n for n in sorted(a) if a[n]!=b[n]];assert changed==['classes.dex']
    assert payload(original)==payload(work/'before.apk')
    report=dict(status='BUILT_EXPERIMENT_NOT_RELEASE',baseline_original_sha256=BASELINE,
                image_candidate_base_sha256=CANDIDATE,candidate_original_sha256=sha(work/'candidate.apk'),
                before_sha256=sha(work/'before.apk'),after_sha256=sha(work/'candidate.apk'),resigning_payload_exact=True,
                changed_payload_entries=changed,native_hashes={n:b[n] for n in b if n.startswith('lib/')},
                default_enabled=False,source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip())
    Path('evidence').mkdir(exist_ok=True)
    Path('evidence/physical-local-stream-build.json').write_text(json.dumps(report,indent=2)+'\n')
if __name__=='__main__':main()
