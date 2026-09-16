"""Download the immutable, hash-verified APK used in BOTH signed comparisons."""
import hashlib
import json
from pathlib import Path
import re
import subprocess


def main():
    c=json.load(open('ci/vulkan-candidate.json'))
    commit=c.get('baseline_commit','0b448fe59427ff9dd018d1799741a0b8a41f50f5')
    assert re.fullmatch(r'[a-f0-9]{40}',commit)
    assert re.fullmatch(r'[a-f0-9]{64}',c['baseline_sha256'])
    dest=Path('.cache/vulkan-baseline.apk');dest.parent.mkdir(exist_ok=True)
    url=f'https://raw.githubusercontent.com/Enzo-cyber2025/5/{commit}/.delivery/GGUF-Chat-mobile.apk'
    subprocess.run(['curl','-fL','--retry','3',url,'-o',str(dest)],check=True)
    assert hashlib.sha256(dest.read_bytes()).hexdigest()==c['baseline_sha256']
    print('IMMUTABLE_VULKAN_BASELINE_HASH_PASS',commit)


if __name__=='__main__':main()
