#!/usr/bin/env bash
# Publish only the exact APK whose full Android acceptance completed successfully.
set -euo pipefail
TAG=gguf-inference-e37df03
RUN=34848915081
EXPECTED=3d17116aac387bbda402ddad2f7dc19b42115eec33d7ec89f7c20dde9a87f2c9
gh api "repos/Enzo-cyber2025/5/actions/runs/$RUN" > /tmp/inference-test.json
python3 - <<'PY'
import hashlib,json,zipfile
from pathlib import Path
assert json.loads(Path('/tmp/inference-test.json').read_text())['conclusion']=='success'
s=json.loads(Path('ci-results/34848915081-1/summary.json').read_text())
expected='3d17116aac387bbda402ddad2f7dc19b42115eec33d7ec89f7c20dde9a87f2c9'
assert s['status']=='PASS' and s['apk_sha256']==expected
assert set(s['recovery_response_quality'])=={'oversize','broken-image','normal-image'}
for stage,result in s['recovery_response_quality'].items():
    assert result['status'] in ('PASS','FAIL')
    if result['status']=='FAIL':print('::warning title=Model quality, not hidden::Greeting instruction-following failed at '+stage+'; see unedited evidence and release limitations.')
for key in ('record.txt','record.pdf','record.docx','frame-a.jpg','frame-b.jpg','image_history_after_restart','two_images','scanned_pdf_visual','oversize_explicit_no_truncation','invalid_image_explicit','normal_model_image_rejected'):
    assert s['content_checks'][key].startswith('PASS'),key
for key in ('image_inference','single_stored_unit_and_eye','vulkan_language_and_projector_weights','normal_model_without_eye'):
    assert s['checks'][key]=='PASS',key
for key in ('multiple_photos_from_files','mixed_types_empty_large_and_exact_bytes','draft_survives_restart','multiple_attachments_bound_to_message','normal_model_multi_file_import','delete_conversation_cleans_only_its_files','unsupported_archive_explicit_error'):
    assert s['attachment_checks'][key]=='PASS',key
assert len(s['attachment_checks']['two_real_camera_photos'])==2
apk=Path('.delivery/GGUF-Chat-mobile.apk')
assert apk.stat().st_size==21717999
assert hashlib.sha256(apk.read_bytes()).hexdigest()==expected
assert json.loads(Path('.delivery/mobile-signed.json').read_text())['signer_sha256']=='35a93f1428120a740adbe95be2621ee9b03fe4342aa363814bdfea0acb2cf7cf'
with zipfile.ZipFile(apk) as z:assert 'assets/third-party/PDFBox-Android.txt' in z.namelist()
notes=Path('docs/INFERENCE.md').read_text().replace('(../ci-results/', '(https://github.com/Enzo-cyber2025/5/blob/arena/01a09b42-5/ci-results/')
Path('/tmp/inference-notes.md').write_text(notes)
PY
if ! gh release view "$TAG" >/dev/null 2>&1; then
  gh release create "$TAG" --target e37df03054f56c9e3a041504461e7121ccff6387 --prerelease --latest=false --title 'GGUF Chat — leitura de documentos e visão real' --notes-file /tmp/inference-notes.md
fi
gh release edit "$TAG" --notes-file /tmp/inference-notes.md
gh release upload "$TAG" .delivery/GGUF-Chat-mobile.apk --clobber
mkdir -p /tmp/inference-download
curl --fail --location --retry 3 --max-time 180 \
  "https://github.com/Enzo-cyber2025/5/releases/download/$TAG/GGUF-Chat-mobile.apk" \
  -o /tmp/inference-download/GGUF-Chat-mobile.apk
cmp .delivery/GGUF-Chat-mobile.apk /tmp/inference-download/GGUF-Chat-mobile.apk
sha256sum /tmp/inference-download/GGUF-Chat-mobile.apk
echo PUBLIC_INFERENCE_DOWNLOAD_BYTE_EXACT_PASS
gh api "repos/Enzo-cyber2025/5/releases/tags/$TAG" > /tmp/inference-release.json
python3 - <<'PY'
import json
from pathlib import Path
r=json.loads(Path('/tmp/inference-release.json').read_text())
a=next(a for a in r['assets'] if a['name']=='GGUF-Chat-mobile.apk')
assert a['size']==21717999
assert a['digest']=='sha256:3d17116aac387bbda402ddad2f7dc19b42115eec33d7ec89f7c20dde9a87f2c9'
assert not r['draft']
print('::notice title=Verified standalone APK::'+a['browser_download_url'])
PY
gh api "repos/Enzo-cyber2025/5/releases/tags/$TAG" --jq '.assets[]|select(.name=="GGUF-Chat-mobile.apk")|{size,digest,browser_download_url}'
