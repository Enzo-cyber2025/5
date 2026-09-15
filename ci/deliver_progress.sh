#!/usr/bin/env bash
# Only the exact APK approved by BOTH named Android suites can be published.
set -euo pipefail
python3 ci/verify_progress_candidate.py
for SUITE in gemma4 regression; do
  RUN=$(python3 -c "import json;print(json.load(open('.delivery/progress-acceptance.json'))['$SUITE']['run'])")
  gh api "repos/Enzo-cyber2025/5/actions/runs/$RUN" > "/tmp/atomic-$SUITE-run.json"
  gh api "repos/Enzo-cyber2025/5/actions/runs/$RUN/jobs?per_page=100" > "/tmp/atomic-$SUITE-jobs.json"
done
python3 - <<'PY'
import json,hashlib
from pathlib import Path
v=json.loads(Path('.delivery/progress-acceptance.json').read_text());e=json.loads(Path('ci/progress-candidate.json').read_text())
assert v['status']=='SIGNED_PROGRESS_ANDROID_PASS' and v['apk_sha256']==e['apk_sha256']
reports={}
for suite in ('gemma4','regression'):
    ref=v[suite];run=json.loads(Path(f'/tmp/atomic-{suite}-run.json').read_text())
    jobs=json.loads(Path(f'/tmp/atomic-{suite}-jobs.json').read_text())['jobs']
    assert run['status']=='completed' and run['head_sha']==ref['commit'] and run['run_attempt']==ref['attempt']
    assert run['head_branch']=='arena/01a09b42-5' and run['path']=='.github/workflows/progress-android.yml'
    job=next(j for j in jobs if j['name']=='test ('+suite+')')
    assert job['status']=='completed' and job['conclusion']=='success' and job['id']==ref['job']
    p=Path(f"ci-results/{ref['run']}-{ref['attempt']}-{suite}")
    s=json.loads((p/'summary.json').read_text());reports[suite]=s
    assert s['status']=='PASS' and s['apk_sha256']==e['apk_sha256']
    if suite=='gemma4':
        proof=json.loads((p/'physical-gemma4-android-tensors.json').read_text())
        assert proof['status']=='PASS' and proof['apk_sha256']==e['apk_sha256']
        assert proof['tensor_count']==len(proof['tensors'])==2012 and proof['size']==3431306464
        assert proof['unified_sha256']=='cb17b173deb6b62c1b8a2e914ea9bbdde75ae8a9a41baef23aaff2d074056066'
g,r=reports['gemma4'],reports['regression']
for key in ('atomic_native_validated_one_file_commit','real_SAF_pair_to_one_GGUF_all_2012_tensors','single_file_survives_restart','native_Gemma4_same_file_vision_Vulkan_Jinja','native_image_history_after_restart','native_Gemma4_text_only'):
    assert g['checks'][key]=='PASS',key
if e['signer_sha256']!=e['previous_signer_sha256']:
    assert e['replacement_signature_authorized'] is True
    assert g['checks']['different_signature_update_blocked_without_losing_old_private_data']=='PASS'
else:assert g['checks']['same_signature_update_retains_private_data']=='PASS'
assert e['signer_sha256']==e['previous_signer_sha256']=='9b658c30f602e0f2ff65c176423cb95bea8fbdeb660c306ab908862f90d9bc3c'
assert g['checks']['measured_per_file_identification_merge_verify_progress']=='PASS'
for key in ('measured_pair_progress','measured_single_vision_progress','measured_single_text_progress','empty_library_shortcut_uses_canonical_import'):
    assert r['physical_checks'][key]=='PASS',key
assert r['progress_single_failure_check'].startswith('PASS:')
assert len(r['progress_failure_checks'])==4 and all(x.startswith('PASS') for x in r['progress_failure_checks'].values())
assert set(g['response_quality'])=={'gemma4-image','gemma4-restart','gemma4-text'}
assert all(x['status']=='PASS' and x['response'].strip() for x in g['response_quality'].values())
for key in ('atomic_native_validated_one_file_commit','one_physical_file_and_all_tensor_hashes','restart_persistence','same_file_language_projector_visual_inference_vulkan','independent_external_format_single_file_import_and_inference','parameter_detection_not_filename','system_global_override_json_restart_and_generation','system_reset_to_global_and_default','single_file_scoped_delete'):
    assert r['physical_checks'][key]=='PASS',key
for key in ('two_real_language_models','two_real_projectors','truncated_second_input','native_loader_rejects_structurally_mergeable_fake_weights'):
    assert r['atomic_checks'][key].startswith('PASS:'),key
for key in ('record.txt','record.pdf','record.docx','frame-a.jpg','frame-b.jpg','image_history_after_restart','two_images','scanned_pdf_visual','oversize_explicit_no_truncation','invalid_image_explicit','normal_model_image_rejected'):
    assert r['content_checks'][key].startswith('PASS'),key
for key in ('multiple_photos_from_files','mixed_types_empty_large_and_exact_bytes','draft_survives_restart','multiple_attachments_bound_to_message','normal_model_multi_file_import','delete_conversation_cleans_only_its_files','unsupported_archive_explicit_error','remove_one_preserves_others'):
    assert r['attachment_checks'][key]=='PASS',key
assert len(r['attachment_checks']['two_real_camera_photos'])==2
notes=Path('docs/IMPORT_PROGRESS.md').read_text()
assert 'Qualidade geral' in notes and 'assinatura' in notes
for results in (r['system_response_quality'],r['recovery_response_quality']):
    for stage,x in results.items():
        assert x['status'] in ('PASS','FAIL') and 'response' in x
        if x['status']=='FAIL':print('::warning title=Model quality::'+stage+' failed; raw evidence and limitations preserved.')
notes=notes.replace('(../ci-results/','(https://github.com/Enzo-cyber2025/5/blob/arena/01a09b42-5/ci-results/')
Path('/tmp/atomic-notes.md').write_text(notes);Path('/tmp/atomic-tag').write_text(v['release_tag'])
PY
SIGNER=$(find "$ANDROID_HOME/build-tools" -path '*/apksigner' -type f | sort -V | tail -1)
"$SIGNER" verify --verbose --print-certs .delivery/GGUF-Chat-mobile.apk | tee /tmp/atomic-signature.txt
CERT=$(python3 -c 'import json;print(json.load(open("ci/progress-candidate.json"))["signer_sha256"])')
grep -F "certificate SHA-256 digest: $CERT" /tmp/atomic-signature.txt
TAG=$(cat /tmp/atomic-tag)
EXPECTED=$(python3 -c 'import json;print(json.load(open("ci/progress-candidate.json"))["apk_sha256"])')
if ! gh release view "$TAG" >/dev/null 2>&1; then
  gh release create "$TAG" --target "$GITHUB_SHA" --prerelease --latest=false --title 'GGUF Chat — porcentagens por arquivo e etapa, mesma assinatura' --notes-file /tmp/atomic-notes.md
fi
gh release edit "$TAG" --notes-file /tmp/atomic-notes.md
EXISTING=$(gh api "repos/Enzo-cyber2025/5/releases/tags/$TAG" --jq '.assets[]|select(.name=="GGUF-Chat-mobile.apk")|.digest')
if [ -n "$EXISTING" ]; then test "$EXISTING" = "sha256:$EXPECTED"; else gh release upload "$TAG" .delivery/GGUF-Chat-mobile.apk; fi
curl --fail --location --retry 3 --max-time 300 "https://github.com/Enzo-cyber2025/5/releases/download/$TAG/GGUF-Chat-mobile.apk" -o /tmp/atomic-public.apk
cmp .delivery/GGUF-Chat-mobile.apk /tmp/atomic-public.apk
sha256sum /tmp/atomic-public.apk
echo PUBLIC_PROGRESS_APK_BYTE_EXACT_PASS
