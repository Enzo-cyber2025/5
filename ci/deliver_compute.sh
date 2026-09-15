#!/usr/bin/env bash
set -euo pipefail
mkdir -p .cache/ci-logs
python3 - <<'PY'
import hashlib,json,subprocess,zipfile
from pathlib import Path
c=json.load(open('ci/compute-candidate.json'));v=json.load(open('.delivery/compute-acceptance.json'));m=json.load(open('.delivery/mobile-signed.json'));u=json.load(open('.delivery/mobile-build.json'))
a=Path('.delivery/GGUF-Chat-mobile.apk');b=Path('.delivery/GGUF-Chat-mobile-unsigned.apk')
assert v['status']=='SIGNED_COMPUTE_ANDROID_PASS'
assert hashlib.sha256(a.read_bytes()).hexdigest()==v['apk_sha256']==c['apk_sha256']==m['apk_sha256']
assert hashlib.sha256(b.read_bytes()).hexdigest()==m['unsigned_sha256']==u['sha256']
assert c['source_commit']==m['source_commit']==u['source_commit']
assert c['replacement_signature_authorized'] is True and c['signer_sha256']==m['signer_sha256']=='3dd851d414caaa20d06ea22391e75b752aab0d26c749168b3353dd389b1332da'
with zipfile.ZipFile(a) as x,zipfile.ZipFile(b) as y:
 assert x.namelist()==y.namelist()
 for name in x.namelist():assert x.read(name)==y.read(name),name
 for name,digest in u['native'].items():assert hashlib.sha256(x.read(name)).hexdigest()==digest,name

def api(path):return json.loads(subprocess.check_output(['gh','api','repos/Enzo-cyber2025/5/'+path],text=True))
r=api('actions/runs/'+str(v['run']));jobs=api('actions/runs/'+str(v['run'])+'/jobs?per_page=100')['jobs']
assert r['conclusion']=='success' and r['status']=='completed' and r['head_sha']==v['commit'] and r['run_attempt']==v['attempt']
assert r['path']=='.github/workflows/compute-android.yml' and r['head_branch']=='arena/01a09b42-5'
for suite in ('small','gemma'):
 job=next(j for j in jobs if j['name']==f'test ({suite})');assert job['id']==v['jobs'][suite] and job['conclusion']=='success'
 s=json.load(open(f"ci-results/{v['run']}-{v['attempt']}-{suite}/summary.json"));assert s['status']=='PASS' and s['apk_sha256']==c['apk_sha256']
 for k in ('real_pair_import_and_native_validation_screen_off','independent_tensor_and_same_file_audit','real_native_generation_and_saved_response_screen_off','reply_survives_reopen'):assert s['checks'][k]=='PASS'
 if suite=='gemma':assert s['checks']['real_gemma_load_succeeds_where_old_memory_formula_rejected']=='PASS'
build=api('actions/runs/'+str(c['build_run']));bj=api('actions/runs/'+str(c['build_run'])+'/jobs')['jobs']
assert build['conclusion']=='success' and build['head_sha']==c['source_commit']
assert next(j for j in bj if j['id']==c['build_job'])['conclusion']=='success'
review=v['ui_review'];assert review['status']=='PASS' and review['apk_sha256']==c['apk_sha256'] and len(review['images'])>=3
for image in review['images']:
 p=Path(image['path']);assert hashlib.sha256(p.read_bytes()).hexdigest()==image['sha256']
 s=json.load(open(p.parent/'summary.json'));assert s['status']=='PASS' and s['apk_sha256']==c['apk_sha256']
notes=Path('docs/COMPUTE_UPDATE.md').read_text().replace('(../ci-results/','(https://github.com/Enzo-cyber2025/5/blob/arena/01a09b42-5/ci-results/')
assert 'Não é uma atualização compatível' in notes and c['apk_sha256'] in notes
Path('/tmp/compute-notes.md').write_text(notes);Path('/tmp/compute-tag').write_text(v['release_tag'])
print('SIGNED_COMPUTE_PUBLICATION_GATES_PASS')
PY
SIGNER=$(find "$ANDROID_HOME/build-tools" -path '*/apksigner' -type f | sort -V | tail -1)
"$SIGNER" verify --verbose --print-certs .delivery/GGUF-Chat-mobile.apk | tee .cache/ci-logs/compute-signature.txt
grep 'certificate SHA-256 digest: 3dd851d414caaa20d06ea22391e75b752aab0d26c749168b3353dd389b1332da' .cache/ci-logs/compute-signature.txt
TAG=$(cat /tmp/compute-tag)
EXPECTED=$(python3 -c 'import json;print(json.load(open("ci/compute-candidate.json"))["apk_sha256"])')
if ! gh release view "$TAG" >/dev/null 2>&1; then gh release create "$TAG" --target "$GITHUB_SHA" --prerelease --latest=false --title 'GGUF Chat — memória, IA com tela apagada e ícones vetoriais' --notes-file /tmp/compute-notes.md; fi
gh release edit "$TAG" --notes-file /tmp/compute-notes.md
EXISTING=$(gh api "repos/Enzo-cyber2025/5/releases/tags/$TAG" --jq '.assets[]|select(.name=="GGUF-Chat-mobile.apk")|.digest')
if [ -n "$EXISTING" ]; then test "$EXISTING" = "sha256:$EXPECTED"; else gh release upload "$TAG" .delivery/GGUF-Chat-mobile.apk; fi
curl --fail --location --retry 3 --max-time 300 "https://github.com/Enzo-cyber2025/5/releases/download/$TAG/GGUF-Chat-mobile.apk" -o /tmp/compute-public.apk
cmp .delivery/GGUF-Chat-mobile.apk /tmp/compute-public.apk
sha256sum /tmp/compute-public.apk
echo PUBLIC_COMPUTE_APK_BYTE_EXACT_PASS
