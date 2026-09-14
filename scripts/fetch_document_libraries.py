#!/usr/bin/env python3
"""Version-pinned Maven artifacts, verified against repository checksums; never run downloaded code."""
import hashlib,json,urllib.request,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def fetch():
    out=ROOT/'.cache/document-libs';out.mkdir(parents=True,exist_ok=True)
    artifacts=['com/tom-roush/pdfbox-android/2.0.27.0/pdfbox-android-2.0.27.0.aar']
    artifacts += ['org/bouncycastle/'+a+'/1.78.1/'+a+'-1.78.1.jar' for a in ('bcprov-jdk18on','bcpkix-jdk18on','bcutil-jdk18on')]
    jars=[];assets={};hashes={}
    for artifact in artifacts:
        url='https://repo.maven.apache.org/maven2/'+artifact
        p=out/Path(artifact).name
        expected=urllib.request.urlopen(url+'.sha1',timeout=60).read().decode().strip().split()[0]
        if not p.exists() or hashlib.sha1(p.read_bytes()).hexdigest()!=expected:
            with urllib.request.urlopen(url,timeout=120) as src,p.open('wb') as dst:
                while True:
                    b=src.read(131072)
                    if not b:break
                    dst.write(b)
        assert hashlib.sha1(p.read_bytes()).hexdigest()==expected,artifact
        hashes[p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
        if p.suffix=='.aar':
            with zipfile.ZipFile(p) as z:
                jar=out/'pdfbox.jar';jar.write_bytes(z.read('classes.jar'));jars.append(jar)
                for n in z.namelist():
                    if n.startswith('assets/') and not n.endswith('/'):assets[n]=z.read(n)
        else:
            # Android does not load JDK multi-release implementations/module-info.
            jar=out/(p.stem+'-android.jar')
            with zipfile.ZipFile(p) as z,zipfile.ZipFile(jar,'w') as dest:
                for n in z.namelist():
                    if not n.startswith('META-INF/versions/') and n!='module-info.class':dest.writestr(n,z.read(n))
            jars.append(jar)
    (out/'sha256.json').write_text(json.dumps(hashes,indent=2));print('Document library SHA256:',json.dumps(hashes))
    return jars,assets
if __name__=='__main__':fetch()
