#!/usr/bin/env bash
# Publish only the exact APK whose full Android acceptance completed successfully.
set -euo pipefail
TAG=gguf-physical-4fa8dbc
RUN=34892580054
EXPECTED=4d1697c2ee9b80ba38a03ee78ab0241dc8aa3d5464c956707e2412be70b11ce6
gh api "repos/Enzo-cyber2025/5/actions/runs/$RUN" > /tmp/physical-test.json
python3 - <<'PY'
import hashlib,json,zipfile
from pathlib import Path
run=json.loads(Path('/tmp/physical-test.json').read_text())
assert run['conclusion']=='success' and run['head_sha']=='f66f66d0ce7680a327088a92aed9af0851acfa94'
assert run['head_branch']=='arena/01a09b42-5'
s=json.loads(Path('ci-results/34892580054-1/summary.json').read_text())
expected='4d1697c2ee9b80ba38a03ee78ab0241dc8aa3d5464c956707e2412be70b11ce6'
assert s['status']=='PASS' and s['apk_sha256']==expected
assert 'exact signed APK' in s['environment']
assert set(s['recovery_response_quality'])=={'oversize','broken-image','normal-image'}
for stage,result in s['recovery_response_quality'].items():
    assert result['status'] in ('PASS','FAIL')
    if result['status']=='FAIL':print('::warning title=Model quality, not hidden::Greeting instruction-following failed at '+stage+'; see unedited evidence and release limitations.')
for key in ('record.txt','record.pdf','record.docx','frame-a.jpg','frame-b.jpg','image_history_after_restart','two_images','scanned_pdf_visual','oversize_explicit_no_truncation','invalid_image_explicit','normal_model_image_rejected'):
    assert s['content_checks'][key].startswith('PASS'),key
assert s['checks']['image_inference']=='PASS'
for key in ('one_physical_file_and_all_tensor_hashes','restart_persistence','same_file_language_projector_visual_inference_vulkan','independent_external_format_single_file_import_and_inference','parameter_detection_not_filename','system_global_override_json_restart_and_generation','system_reset_to_global_and_default','single_file_scoped_delete'):
    assert s['physical_checks'][key]=='PASS',key
proof=json.loads(Path('ci-results/34892580054-1/physical-tensor-proof.json').read_text())
assert proof['status']=='PASS' and proof['tensor_count']==471 and proof['apk_sha256']==expected
assert len(proof['tensors'])==471 and proof['size']==278824896
assert proof['unified_sha256']=='6ba9ca75ac0a80adcc380220252ef1d016153149521b815079710ede777ab4e9'
provenance=json.loads(Path('ci-results/34892580054-1/physical-signed-provenance.json').read_text())
assert provenance['status']=='PASS' and provenance['apk_sha256']==expected
assert set(s['system_response_quality'])=={'system-global','system-chat'}
for stage,result in s['system_response_quality'].items():
    assert result['status'] in ('PASS','FAIL')
    if result['status']=='FAIL':print('::warning title=System prompt model quality::Instruction-following failed at '+stage+'; actual response is preserved in release evidence.')
for key in ('multiple_photos_from_files','mixed_types_empty_large_and_exact_bytes','draft_survives_restart','multiple_attachments_bound_to_message','normal_model_multi_file_import','delete_conversation_cleans_only_its_files','unsupported_archive_explicit_error'):
    assert s['attachment_checks'][key]=='PASS',key
assert s['attachment_checks']['remove_one_preserves_others']=='PASS'
assert s['attachment_checks']['multimodal_controls']['camera_enabled'] is True
assert s['attachment_checks']['normal_controls']['camera_enabled'] is False
photos=s['attachment_checks']['two_real_camera_photos']
assert len(photos)==2 and len({p['sha256'] for p in photos})==2
assert all(p['size']>0 and p['width']>0 and p['height']>0 for p in photos)
apk=Path('.delivery/GGUF-Chat-mobile.apk')
assert apk.stat().st_size==21730287
assert hashlib.sha256(apk.read_bytes()).hexdigest()==expected
metadata=json.loads(Path('.delivery/mobile-signed.json').read_text())
assert metadata['status']=='SIGNED_ANDROID_FUNCTIONAL_PASS' and metadata['android_run']==34892580054
assert metadata['signer_sha256']=='9a368c9a1e4f3b3b0b6ecfb86aa3768d633a925855afba27eab3b9189177955a'
with zipfile.ZipFile(apk) as z:assert 'assets/third-party/PDFBox-Android.txt' in z.namelist()
notes=Path('docs/SIGNED_PHYSICAL.md').read_text().replace('(../ci-results/', '(https://github.com/Enzo-cyber2025/5/blob/arena/01a09b42-5/ci-results/')
Path('/tmp/physical-notes.md').write_text(notes)
PY
if ! gh release view "$TAG" >/dev/null 2>&1; then
  gh release create "$TAG" --target 4fa8dbca578a70df91798c3b80b24d66f6c485f0 --prerelease --latest=false --title 'GGUF Chat — GGUF físico único, visão e prompts' --notes-file /tmp/physical-notes.md
fi
gh release edit "$TAG" --notes-file /tmp/physical-notes.md
# Never replace an existing different binary, even on this new release tag.
existing=$(gh api "repos/Enzo-cyber2025/5/releases/tags/$TAG" --jq '.assets[]|select(.name=="GGUF-Chat-mobile.apk")|.digest')
if [ -n "$existing" ]; then
  test "$existing" = "sha256:$EXPECTED"
else
  gh release upload "$TAG" .delivery/GGUF-Chat-mobile.apk
fi
mkdir -p /tmp/physical-download
curl --fail --location --retry 3 --max-time 180 \
  "https://github.com/Enzo-cyber2025/5/releases/download/$TAG/GGUF-Chat-mobile.apk" \
  -o /tmp/physical-download/GGUF-Chat-mobile.apk
cmp .delivery/GGUF-Chat-mobile.apk /tmp/physical-download/GGUF-Chat-mobile.apk
sha256sum /tmp/physical-download/GGUF-Chat-mobile.apk
echo PUBLIC_PHYSICAL_DOWNLOAD_BYTE_EXACT_PASS
gh api "repos/Enzo-cyber2025/5/releases/tags/$TAG" > /tmp/physical-release.json
python3 - <<'PY'
import json
from pathlib import Path
r=json.loads(Path('/tmp/physical-release.json').read_text())
a=next(a for a in r['assets'] if a['name']=='GGUF-Chat-mobile.apk')
assert a['size']==21730287
assert a['digest']=='sha256:4d1697c2ee9b80ba38a03ee78ab0241dc8aa3d5464c956707e2412be70b11ce6'
assert not r['draft']
print('::notice title=Verified standalone APK::'+a['browser_download_url'])
PY
gh api "repos/Enzo-cyber2025/5/releases/tags/$TAG" --jq '.assets[]|select(.name=="GGUF-Chat-mobile.apk")|{size,digest,browser_download_url}'
