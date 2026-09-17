#!/usr/bin/env python3
"""Read a gain-approved APK from an immutable public repository archive.
Avoids storing the whole archive; pins APK SHA-256, validates the gain first.
Does not authenticate, change branches, sign, install, or expose credentials.
"""
import hashlib,json,re,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'ci'))
from perceptible_image_gate import evaluate,CANDIDATE

def main(report_dir,commit):
    assert re.fullmatch(r'[0-9a-f]{40}',commit)
    s=json.loads((Path(report_dir)/'summary.json').read_text())
    assert s['status']=='PASS_GAIN_GATE_RETAINED_IMAGES_ONLY' and evaluate(s)['gain_gate_passed']
    destination=ROOT/'.delivery/GGUF-Chat-gain-approved-payload.apk'
    if destination.exists():
        assert hashlib.sha256(destination.read_bytes()).hexdigest()==CANDIDATE;return
    from stream_unzip import stream_unzip
    work=ROOT/'.cache/gain-fetch';work.mkdir(parents=True,exist_ok=True)
    temporary=work/'approved.apk'
    url='https://codeload.github.com/Enzo-cyber2025/5/zip/'+commit
    wanted=f'5-{commit}/.delivery/GGUF-Chat-gain-approved-payload.apk'.encode()
    compressed=expanded=0
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'GainApprovedAPKReader'}),timeout=60) as response:
        def chunks():
            nonlocal compressed
            while True:
                data=response.read(65536)
                if not data:return
                compressed+=len(data)
                if compressed>180*1024*1024:raise ValueError('Archive input safety bound exceeded')
                yield data
        for name,size,data in stream_unzip(chunks()):
            target=name==wanted
            if size is not None and size>100*1024*1024:raise ValueError('Unexpected archive member size')
            digest=hashlib.sha256()
            f=temporary.open('wb') if target else None
            try:
                for chunk in data:
                    expanded+=len(chunk)
                    if expanded>180*1024*1024:raise ValueError('Archive expansion safety bound exceeded')
                    if f:f.write(chunk);digest.update(chunk)
            finally:
                if f:f.close()
            if target:
                assert digest.hexdigest()==CANDIDATE,'Approved payload hash mismatch'
                temporary.replace(destination)
                (ROOT/'.delivery/gain-payload-download.json').write_text(json.dumps({'archive_commit':commit,'url':url,'apk_sha256':CANDIDATE,'gain_checked_before_download':True},indent=2)+'\n')
                print('GAIN_APPROVED_PAYLOAD_FETCHED',destination);return
    raise ValueError('Gain-approved APK absent from pinned archive')
if __name__=='__main__':main(sys.argv[1],sys.argv[2])
