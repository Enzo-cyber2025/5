#!/usr/bin/env python3
"""Build a disposable UI experiment from delivered 323fd5; retain EVERY non-DEX
payload entry byte for byte. Debug signing is for a fresh CI emulator ONLY, not
an installable update for users. Never overwrite .delivery or use a release key.
"""
import argparse,hashlib,importlib.util,json,os,shutil,subprocess,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'apk-fix'))
from ui_overhead import patch_delivered_ui
from build_apk import signature_entry
PREVIOUS_UI_SOURCE='63913d1f5e60b1d912eae085c49bc237a30711d5'
BASE_SHA='323fd5a33667c6cab278699e97c89fe253e1bb7acead45b869729bf022eb9f5c'

def run(*args):subprocess.run(list(map(str,args)),check=True)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--previous-ui',action='store_true',help='Reconstruct the previous UI code, not its discarded signature')
    previous=parser.parse_args().previous_ui
    os.chdir(ROOT)
    base=ROOT/'.delivery/GGUF-Chat-mobile.apk';assert sha(base)==BASE_SHA
    work=ROOT/('.cache/ui-previous' if previous else '.cache/ui-experiment');work.mkdir(exist_ok=False)
    sdk=Path(os.environ['ANDROID_HOME']);jar=sdk/'platforms/android-35/android.jar'
    bt=sdk/'build-tools/35.0.0';tool=ROOT/'.cache/tools/package/lib/apktool.jar'
    decoded=work/'decoded'
    run('java','-jar',tool,'d','-f','-r','-o',decoded,base)
    app=decoded/'smali/com/ggufchat/app'
    names=('ScrollTail','PreviewCadence','ReplyNotifications','GenerationStats','WorkWakeLocks')
    sources=[]
    if previous:
        def pinned(path):return subprocess.check_output(['git','show',PREVIOUS_UI_SOURCE+':'+path])
        assert pinned('apk-fix/unified_mobile.py')==(ROOT/'apk-fix/unified_mobile.py').read_bytes()
        recipe=work/'previous_ui_overhead.py';recipe.write_bytes(pinned('apk-fix/ui_overhead.py'))
        spec=importlib.util.spec_from_file_location('previous_ui_recipe',recipe)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        module.patch_delivered_ui(app)
        for name in names:
            source=work/(name+'.java');source.write_bytes(pinned(f'apk-fix/java/com/ggufchat/app/{name}.java'));sources.append(source)
    else:
        patch_delivered_ui(app)
        names+=('CodeBlocks','CodeFenceParser')
        sources=[ROOT/f'apk-fix/java/com/ggufchat/app/{n}.java' for n in names]
    classes=work/'classes';classes.mkdir();dex=work/'dex';dex.mkdir()
    run('javac','--release','8','-classpath',jar,'-d',classes,*sources)
    run(bt/'d8','--min-api','28','--lib',jar,'--output',dex,*classes.rglob('*.class'))
    helper=work/'helper.apk'
    with zipfile.ZipFile(helper,'w') as z:z.write(dex/'classes.dex','classes.dex')
    helperdir=work/'helper'
    run('java','-jar',tool,'d','-f','-r','-o',helperdir,helper)
    for name in names:
        for p in [app/f'{name}.smali',*app.glob(name+'$*.smali')]:p.unlink(missing_ok=True)
    for p in (helperdir/'smali/com/ggufchat/app').glob('*.smali'):shutil.copyfile(p,app/p.name)
    compiled=work/'compiled.apk';run('java','-jar',tool,'b',decoded,'-o',compiled)
    unsigned=work/'unsigned.apk'
    with zipfile.ZipFile(base) as a,zipfile.ZipFile(compiled) as c,zipfile.ZipFile(unsigned,'w') as b:
        for info in a.infolist():
            if signature_entry(info.filename):continue
            data=c.read(info.filename) if info.filename=='classes.dex' else a.read(info.filename)
            b.writestr(info,data)
    aligned=work/'aligned.apk';run(bt/'zipalign','-P','16','-f','4',unsigned,aligned)
    # Disposable test key, never uploaded, committed, or used for delivery.
    key=work/'test.p12'
    run('keytool','-genkeypair','-keystore',key,'-storepass','android','-alias','test','-keyalg','RSA','-keysize','2048','-validity','7','-dname','CN=Disposable UI experiment NOT release')
    candidate=work/'candidate.apk'
    run(bt/'apksigner','sign','--ks',key,'--ks-pass','pass:android','--out',candidate,aligned)
    run(bt/'apksigner','verify','--verbose',candidate)
    run(bt/'zipalign','-c','-P','16','4',candidate)
    key.unlink() # No future release/update can accidentally reuse the test key.
    with zipfile.ZipFile(base) as a,zipfile.ZipFile(candidate) as b:
        an={n for n in a.namelist() if not signature_entry(n)};bn={n for n in b.namelist() if not signature_entry(n)}
        assert an==bn
        changed=[n for n in sorted(an) if a.read(n)!=b.read(n)]
        assert changed==['classes.dex'],changed
        native={n:hashlib.sha256(b.read(n)).hexdigest() for n in sorted(bn) if n.startswith('lib/')}
    report=dict(baseline_kind='delivered_323fd5',ui_recipe_source_commit=PREVIOUS_UI_SOURCE if previous else subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),status='BUILT_NOT_ANDROID_ACCEPTED',baseline_sha256=BASE_SHA,candidate_sha256=sha(candidate),changed_payload_entries=changed,native_hashes=native,scope='Same native binaries, resources, manifest, models/settings unchanged. Fresh disposable emulator signing only. NOT a release or same-key update test.',source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip())
    Path('evidence').mkdir(exist_ok=True)
    if not previous:
        before=json.loads(Path('evidence/physical-ui-previous-build.json').read_text())
        assert before['ui_recipe_source_commit']==PREVIOUS_UI_SOURCE
        assert before['native_hashes']==report['native_hashes']
        report.update(payload_origin_sha256=BASE_SHA,baseline_sha256=before['candidate_sha256'],baseline_kind='reconstructed_previous_ui',baseline_ui_source_commit=PREVIOUS_UI_SOURCE)
    filename='physical-ui-previous-build.json' if previous else 'physical-ui-build.json'
    Path('evidence',filename).write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':main()
