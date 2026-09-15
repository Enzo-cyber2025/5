#!/usr/bin/env python3
"""Compile delivery helpers on the exact approved APK. Preserve ALL non-primary-DEX bytes."""
import hashlib,json,os,shutil,subprocess,sys,zipfile
from pathlib import Path
import jdk4py
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'apk-fix'))
from build_apk import rebuild_zip
from reply_notifications import patch_reply_notifications
BASE_SHA='eabd016935ac51cdd89063a97fbc1b562f7f9261981f54b5191d37734e7922eb'
base=ROOT/'.cache/reply-base.apk';assert hashlib.sha256(base.read_bytes()).hexdigest()==BASE_SHA
work=ROOT/'.cache/reply-build';work.mkdir(parents=True,exist_ok=True)
java=str(jdk4py.JAVA_HOME/'bin/java');tool=ROOT/'.cache/tools/package/lib/apktool.jar'
def run(*a):subprocess.run(list(map(str,a)),check=True)
dec=work/'decoded';run(java,'-jar',tool,'d','-f','-r',base,'-o',dec)
app=dec/'smali/com/ggufchat/app';before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in app.glob('*.smali')}
patch_reply_notifications(app)
changed=[n for n,h in before.items() if hashlib.sha256((app/n).read_bytes()).hexdigest()!=h]
assert set(changed)=={'GenerationService.smali','GenerationService$1.smali','GenerationService$2.smali'},changed
sdk=Path(os.environ['ANDROID_HOME']);bt=sorted((sdk/'build-tools').iterdir(),key=lambda p:[int(x) for x in p.name.split('.') if x.isdigit()])[-1]
android=sdk/'platforms/android-35/android.jar';classes=work/'classes';classes.mkdir(exist_ok=True);dex=work/'dex';dex.mkdir(exist_ok=True)
# WorkWakeLocks is a compile dependency only; its existing DEX class is unchanged.
run(Path(os.environ['JAVA_HOME'])/'bin/javac','--release','8','-classpath',android,'-d',classes,
    ROOT/'apk-fix/java/com/ggufchat/app/ReplyNotifications.java',ROOT/'apk-fix/java/com/ggufchat/app/WorkWakeLocks.java')
run(bt/'d8','--min-api','28','--lib',android,'--output',dex,*classes.rglob('*.class'))
helper=work/'helper.apk'
with zipfile.ZipFile(helper,'w') as z,zipfile.ZipFile(base) as a:
 z.writestr('AndroidManifest.xml',a.read('AndroidManifest.xml'));z.writestr('classes.dex',(dex/'classes.dex').read_bytes())
h=work/'helper';run(java,'-jar',tool,'d','-f','-r',helper,'-o',h)
added=[]
for p in (h/'smali/com/ggufchat/app').glob('ReplyNotifications*.smali'):
 assert p.name not in before;shutil.copyfile(p,app/p.name);added.append(p.name)
assert 'ReplyNotifications.smali' in added
compiled=work/'compiled.apk';run(java,'-jar',tool,'b',dec,'-o',compiled)
out=ROOT/'.delivery/GGUF-Chat-mobile-unsigned.apk'
with zipfile.ZipFile(compiled) as z:rebuild_zip(base,z.read('classes.dex'),out)
with zipfile.ZipFile(base) as a,zipfile.ZipFile(out) as b:
 assert a.namelist()==b.namelist()
 for n in a.namelist():
  if n!='classes.dex':assert a.read(n)==b.read(n),n
 native={n:hashlib.sha256(b.read(n)).hexdigest() for n in b.namelist() if n.startswith('lib/') and n.endswith('.so')}
m=json.load(open(ROOT/'.delivery/mobile-build.json'))
m.update(source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),native_source_commit='ce0118db8646f1523d11725a8c5c29b6e88230f2',sha256=hashlib.sha256(out.read_bytes()).hexdigest(),status='UNSIGNED_NOT_APPROVED',notification_base_sha256=BASE_SHA,changed_classes=changed,added_classes=added,native=native)
(ROOT/'.delivery/mobile-build.json').write_text(json.dumps(m,indent=2)+'\n');print(json.dumps(m,indent=2))
