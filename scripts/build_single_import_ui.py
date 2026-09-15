#!/usr/bin/env python3
"""Compile the UI-only fix on the exact last approved APK, preserving all other entries.
Full source builds apply the same patch through build_mobile.ui_patches.
"""
import hashlib,json,subprocess,sys,zipfile
from pathlib import Path
import jdk4py
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'apk-fix'))
from single_import_ui import patch_single_import_ui
from build_apk import rebuild_zip,signature_entry
BASE_SHA='afaf22c63022b44320604407246abe47a921c4e4d1fe55694ce7428abb047e86'
base=ROOT/'.cache/import-ui-base.apk';assert hashlib.sha256(base.read_bytes()).hexdigest()==BASE_SHA
work=ROOT/'.cache/import-ui-build';work.mkdir(exist_ok=True)
java=str(jdk4py.JAVA_HOME/'bin/java');tool=ROOT/'.cache/tools/package/lib/apktool.jar'
dec=work/'decoded';subprocess.run([java,'-jar',str(tool),'d','-f','-r',str(base),'-o',str(dec)],check=True)
# Hash every decoded class; only the two navigation Activities may change.
before={p.relative_to(dec).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in dec.glob('smali*/**/*.smali')}
patch_single_import_ui(dec/'smali/com/ggufchat/app')
changed=[n for n,h in before.items() if hashlib.sha256((dec/n).read_bytes()).hexdigest()!=h]
assert set(changed)=={'smali/com/ggufchat/app/MainActivity.smali','smali/com/ggufchat/app/ModelsActivity.smali'}
compiled=work/'compiled.apk';subprocess.run([java,'-jar',str(tool),'b',str(dec),'-o',str(compiled)],check=True)
out=ROOT/'.delivery/GGUF-Chat-mobile-unsigned.apk'
with zipfile.ZipFile(compiled) as z:rebuild_zip(base,z.read('classes.dex'),out)
with zipfile.ZipFile(base) as a,zipfile.ZipFile(out) as b:
 assert a.namelist()==b.namelist()
 for n in a.namelist():
  if n!='classes.dex':assert a.read(n)==b.read(n),n
meta=json.loads((ROOT/'.delivery/mobile-build.json').read_text())
meta.update(source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),sha256=hashlib.sha256(out.read_bytes()).hexdigest(),status='UNSIGNED_NOT_APPROVED',ui_base_apk_sha256=BASE_SHA,changed_classes=changed)
(ROOT/'.delivery/mobile-build.json').write_text(json.dumps(meta,indent=2)+'\n')
print(json.dumps(meta,indent=2))
