#!/usr/bin/env bash
set -euo pipefail
mkdir -p .cache evidence
curl --fail --location --retry 3 'https://github.com/Enzo-cyber2025/5/releases/download/gguf-progress-dba56b2/GGUF-Chat-mobile.apk' -o .cache/import-ui-base.apk
python3 ci/verify_import_ui.py
RUN=$(python3 -c 'import json;print(json.load(open(".delivery/import-ui-acceptance.json"))["run"])')
gh api "repos/Enzo-cyber2025/5/actions/runs/$RUN" > /tmp/import-ui-run.json
gh api "repos/Enzo-cyber2025/5/actions/runs/$RUN/jobs?per_page=100" > /tmp/import-ui-jobs.json
python3 - <<'PY'
import hashlib,json
from pathlib import Path
v=json.load(open('.delivery/import-ui-acceptance.json'));c=json.load(open('ci/import-ui-candidate.json'));r=json.load(open('/tmp/import-ui-run.json'));jobs=json.load(open('/tmp/import-ui-jobs.json'))['jobs']
assert v['status']=='SIGNED_IMPORT_UI_ANDROID_PASS' and v['apk_sha256']==c['apk_sha256']
assert r['status']=='completed' and r['conclusion']=='success' and r['head_sha']==v['commit'] and r['run_attempt']==v['attempt']
assert r['head_branch']=='arena/01a09b42-5' and r['path']=='.github/workflows/import-ui.yml'
j=next(j for j in jobs if j['name']=='test');assert j['id']==v['job'] and j['conclusion']=='success'
s=json.load(open(f"ci-results/{v['run']}-{v['attempt']}/summary.json"));assert s['status']=='PASS' and s['apk_sha256']==c['apk_sha256']
for k in ('same_signature_upgrade_and_launch_preserve_private_data','empty_library_one_import_button','legacy_activity_cold_and_warm_use_same_screen','real_multi_select_pair_one_file_native_validation_exact_tensors','three_file_selection_imports_all_and_survives_restart'):assert s['checks'][k]=='PASS',k
local=json.load(open('.delivery/import-ui-local-validation.json'));assert local['status']=='PASS' and local['apk_sha256']==c['apk_sha256'] and local['unchanged_classes']==6802
assert v['ui_review']['status']=='PASS' and len(v['ui_review']['images'])>=3
for image in v['ui_review']['images']:assert hashlib.sha256(Path(image['path']).read_bytes()).hexdigest()==image['sha256']
notes=Path('docs/SINGLE_IMPORT_UI.md').read_text().replace('(../ci-results/','(https://github.com/Enzo-cyber2025/5/blob/arena/01a09b42-5/ci-results/')
Path('/tmp/import-ui-notes.md').write_text(notes);Path('/tmp/import-ui-tag').write_text(v['release_tag'])
PY
SIGNER=$(find "$ANDROID_HOME/build-tools" -path '*/apksigner' -type f | sort -V | tail -1)
"$SIGNER" verify --verbose --print-certs .delivery/GGUF-Chat-mobile.apk | tee /tmp/import-ui-signature.txt
grep 'certificate SHA-256 digest: 9b658c30f602e0f2ff65c176423cb95bea8fbdeb660c306ab908862f90d9bc3c' /tmp/import-ui-signature.txt
TAG=$(cat /tmp/import-ui-tag)
EXPECTED=$(python3 -c 'import json;print(json.load(open("ci/import-ui-candidate.json"))["apk_sha256"])')
if ! gh release view "$TAG" >/dev/null 2>&1; then gh release create "$TAG" --target "$GITHUB_SHA" --prerelease --latest=false --title 'GGUF Chat — um botão Importar GGUF, seleção múltipla' --notes-file /tmp/import-ui-notes.md; fi
gh release edit "$TAG" --notes-file /tmp/import-ui-notes.md
EXISTING=$(gh api "repos/Enzo-cyber2025/5/releases/tags/$TAG" --jq '.assets[]|select(.name=="GGUF-Chat-mobile.apk")|.digest')
if [ -n "$EXISTING" ]; then test "$EXISTING" = "sha256:$EXPECTED"; else gh release upload "$TAG" .delivery/GGUF-Chat-mobile.apk; fi
curl --fail --location --retry 3 --max-time 300 "https://github.com/Enzo-cyber2025/5/releases/download/$TAG/GGUF-Chat-mobile.apk" -o /tmp/import-ui-public.apk
cmp .delivery/GGUF-Chat-mobile.apk /tmp/import-ui-public.apk
sha256sum /tmp/import-ui-public.apk
echo PUBLIC_IMPORT_UI_APK_BYTE_EXACT_PASS
