#!/usr/bin/env bash
# Publish only after BOTH exact-signed-APK Android suites pass.
set -euo pipefail
RUN=$(python3 -c 'import json;print(json.load(open(".delivery/gemma4-acceptance.json"))["run"])')
gh api "repos/Enzo-cyber2025/5/actions/runs/$RUN" > /tmp/gemma4-accepted-run.json
REGRESSION_RUN=$(python3 -c 'import json;print(json.load(open(".delivery/gemma4-acceptance.json"))["regression"]["run"])')
gh api "repos/Enzo-cyber2025/5/actions/runs/$REGRESSION_RUN" > /tmp/gemma4-regression-run.json
python3 - <<'PY'
import hashlib,json
from pathlib import Path
v=json.loads(Path('.delivery/gemma4-acceptance.json').read_text())
e=json.loads(Path('ci/gemma4-candidate.json').read_text())
run=json.loads(Path('/tmp/gemma4-accepted-run.json').read_text())
assert v['status']=='SIGNED_ANDROID_FUNCTIONAL_PASS'
assert v['apk_sha256']==e['apk_sha256'] and v['source_commit']==e['source_commit']
assert run['conclusion']=='success' and run['status']=='completed' and run['head_sha']==v['acceptance_commit']
assert run['head_branch']=='arena/01a09b42-5'
assert run['path']=='.github/workflows/gemma4-android.yml' and run['run_attempt']==v['attempt']
regression_run=json.loads(Path('/tmp/gemma4-regression-run.json').read_text())
rv=v['regression']
assert regression_run['conclusion']=='success' and regression_run['status']=='completed'
assert regression_run['head_sha']==rv['acceptance_commit'] and regression_run['run_attempt']==rv['attempt']
assert regression_run['head_branch']=='arena/01a09b42-5' and regression_run['path']=='.github/workflows/gemma4-android.yml'
b=Path(f"ci-results/{v['run']}-{v['attempt']}")
g=json.loads(Path(str(b)+'-gemma4/summary.json').read_text())
r=json.loads(Path(f"ci-results/{rv['run']}-{rv['attempt']}-regression/summary.json").read_text())
for s in (g,r):assert s['status']=='PASS' and s['apk_sha256']==e['apk_sha256']
for key in ('same_signature_update_retains_private_data','real_SAF_pair_to_one_GGUF_all_2012_tensors','single_file_survives_restart','native_Gemma4_same_file_vision_Vulkan_Jinja','native_image_history_after_restart','image_inference','native_Gemma4_text_only'):
    assert g['checks'][key]=='PASS',key
assert set(g['response_quality'])=={'gemma4-image','gemma4-restart','gemma4-text'}
assert all(x['status']=='PASS' for x in g['response_quality'].values())
proof=json.loads(Path(str(b)+'-gemma4/physical-gemma4-android-tensors.json').read_text())
assert proof['status']=='PASS' and proof['apk_sha256']==e['apk_sha256'] and proof['tensor_count']==len(proof['tensors'])==2012
assert proof['unified_sha256']=='cb17b173deb6b62c1b8a2e914ea9bbdde75ae8a9a41baef23aaff2d074056066'
for key in ('one_physical_file_and_all_tensor_hashes','restart_persistence','same_file_language_projector_visual_inference_vulkan','independent_external_format_single_file_import_and_inference','parameter_detection_not_filename','system_global_override_json_restart_and_generation','system_reset_to_global_and_default','single_file_scoped_delete'):
    assert r['physical_checks'][key]=='PASS',key
for key in ('record.txt','record.pdf','record.docx','frame-a.jpg','frame-b.jpg','image_history_after_restart','two_images','scanned_pdf_visual','oversize_explicit_no_truncation','invalid_image_explicit','normal_model_image_rejected'):
    assert r['content_checks'][key].startswith('PASS'),key
for key in ('multiple_photos_from_files','mixed_types_empty_large_and_exact_bytes','draft_survives_restart','multiple_attachments_bound_to_message','normal_model_multi_file_import','delete_conversation_cleans_only_its_files','unsupported_archive_explicit_error','remove_one_preserves_others'):
    assert r['attachment_checks'][key]=='PASS',key
assert len(r['attachment_checks']['two_real_camera_photos'])==2
for results in (g['response_quality'],r['system_response_quality'],r['recovery_response_quality']):
    for stage,result in results.items():
        assert result['status'] in ('PASS','FAIL') and 'response' in result
        if result['status']=='FAIL':print('::warning title=Model quality::'+stage+' failed; actual response preserved and release limitations disclose it.')
p=Path('.delivery/GGUF-Chat-mobile.apk')
assert p.stat().st_size==e['size'] and hashlib.sha256(p.read_bytes()).hexdigest()==e['apk_sha256']
assert json.loads(Path('.delivery/mobile-signed.json').read_text())['signer_sha256']==e['signer_sha256']=='9a368c9a1e4f3b3b0b6ecfb86aa3768d633a925855afba27eab3b9189177955a'
Path('/tmp/gemma4-tag').write_text(v['release_tag'])
notes=Path('docs/GEMMA4.md').read_text().replace('(../ci-results/', '(https://github.com/Enzo-cyber2025/5/blob/arena/01a09b42-5/ci-results/')
for document in ('SIGNED_PHYSICAL.md','STANDALONE_500M.md'):
    notes=notes.replace('('+document+')','(https://github.com/Enzo-cyber2025/5/blob/arena/01a09b42-5/docs/'+document+')')
Path('/tmp/gemma4-notes.md').write_text(notes)
PY
TAG=$(cat /tmp/gemma4-tag)
EXPECTED=$(python3 -c 'import json;print(json.load(open("ci/gemma4-candidate.json"))["apk_sha256"])')
if ! gh release view "$TAG" >/dev/null 2>&1; then
  gh release create "$TAG" --target "${GITHUB_SHA:-$(git rev-parse HEAD)}" --prerelease --latest=false --title 'GGUF Chat — Gemma 4, GGUF físico único e assinatura preservada' --notes-file /tmp/gemma4-notes.md
fi
gh release edit "$TAG" --notes-file /tmp/gemma4-notes.md
existing=$(gh api "repos/Enzo-cyber2025/5/releases/tags/$TAG" --jq '.assets[]|select(.name=="GGUF-Chat-mobile.apk")|.digest')
if [ -n "$existing" ]; then
  test "$existing" = "sha256:$EXPECTED"
else
  gh release upload "$TAG" .delivery/GGUF-Chat-mobile.apk
fi
curl --fail --location --retry 3 --max-time 300 "https://github.com/Enzo-cyber2025/5/releases/download/$TAG/GGUF-Chat-mobile.apk" -o /tmp/Gemma4-public.apk
cmp .delivery/GGUF-Chat-mobile.apk /tmp/Gemma4-public.apk
sha256sum /tmp/Gemma4-public.apk
echo PUBLIC_GEMMA4_DOWNLOAD_BYTE_EXACT_PASS
gh api "repos/Enzo-cyber2025/5/releases/tags/$TAG" > /tmp/gemma4-release.json
python3 - <<'PY'
import json
from pathlib import Path
r=json.loads(Path('/tmp/gemma4-release.json').read_text());e=json.loads(Path('ci/gemma4-candidate.json').read_text())
a=next(a for a in r['assets'] if a['name']=='GGUF-Chat-mobile.apk')
assert a['size']==e['size'] and a['digest']=='sha256:'+e['apk_sha256'] and not r['draft']
print('::notice title=Verified standalone APK::'+a['browser_download_url'])
PY
