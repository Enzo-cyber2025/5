#!/usr/bin/env bash
# Publish only the exact APK exercised by the real Android benchmark.
set -euo pipefail
mkdir -p .cache/ci-logs
python3 - <<'PY'
import hashlib,json,math,re,statistics,subprocess,sys,zipfile
from pathlib import Path
c=json.load(open('ci/speed-candidate.json'));v=json.load(open('.delivery/speed-acceptance.json'))
m=json.load(open('.delivery/mobile-signed.json'));u=json.load(open('.delivery/mobile-build.json'))
a=Path('.delivery/GGUF-Chat-mobile.apk');b=Path('.delivery/GGUF-Chat-mobile-unsigned.apk')
assert v['status']=='SIGNED_SPEED_ANDROID_PASS'
assert hashlib.sha256(a.read_bytes()).hexdigest()==v['apk_sha256']==c['apk_sha256']==m['apk_sha256']
assert hashlib.sha256(b.read_bytes()).hexdigest()==m['unsigned_sha256']==u['sha256']
assert c['source_commit']==m['source_commit']==u['source_commit']==u['native_source_commit']
assert c['signer_sha256']==m['signer_sha256']=='3dd851d414caaa20d06ea22391e75b752aab0d26c749168b3353dd389b1332da'
with zipfile.ZipFile(a) as x,zipfile.ZipFile(b) as y:
 assert x.namelist()==y.namelist()
 for n in x.namelist():assert x.read(n)==y.read(n),n
 for n,digest in u['native'].items():assert hashlib.sha256(x.read(n)).hexdigest()==digest,n

def api(path):return json.loads(subprocess.check_output(['gh','api','repos/Enzo-cyber2025/5/'+path],text=True))
r=api('actions/runs/'+str(v['run']));jobs=api('actions/runs/'+str(v['run'])+'/jobs?per_page=100')['jobs']
assert r['conclusion']=='success' and r['status']=='completed' and r['head_sha']==v['commit'] and r['run_attempt']==v['attempt']
assert r['path']=='.github/workflows/speed-android.yml' and r['head_branch']=='arena/01a09b42-5'
assert next(j for j in jobs if j['id']==v['job'])['conclusion']=='success'
s=json.load(open(f"ci-results/{v['run']}-{v['attempt']}/summary.json"))
assert s['status']=='PASS' and s['apk_sha256']==c['apk_sha256']
for k in ('same_certificate_update_preserves_models_chats','real_before_after_benchmark_identical_outputs','native_counters_persistence_footer_geometry','old_messages_not_fabricated','metrics_and_real_vision_generation_screen_off','real_image_inference_metrics'):assert s['checks'][k]=='PASS',k
# This snapshot is taken while asleep, BEFORE launch() force-stops/reopens.
sys.path.insert(0,'scripts')
from android_checks import active_wake_locks,completed_after_actual_sleep
root=Path(f"ci-results/{v['run']}-{v['attempt']}")
power=(root/'physical-speed-vision-asleep-power.txt').read_text()
assert 'mWakefulness=Asleep' in power and 'GGUFChat:LocalCompute' not in active_wake_locks(power)
log=(root/'physical-speed-vision-sleep-log.txt').read_text()
assert completed_after_actual_sleep(log)
metrics=re.search(r'GGUF_GENERATION_STATS tokens=(\d+) decode_ns=(\d+) prefill_ns=(\d+) callbacks=(\d+) success=1',log)
assert metrics
chat=json.load(open(root/'inference-speed-vision-chat.json'))
message=chat['messages'][-1];native=tuple(map(int,metrics.groups()))
assert message['role']=='assistant' and 'dog' in message['content'].lower()
j=message['generationMetrics']
assert (j['tokens'],j['decodeNs'],j['prefillNs'])==native[:3] and j['completed'] is True
bench=s['benchmark'];assert bench['repetitions']==3 and bench['warmup_excluded']==1
assert len(bench['before'])==len(bench['after'])==3
assert len({x['response'] for x in bench['before']+bench['after']})==1
for phase in ('before','after'):
 rates=[x['tokens']/x['prefill_and_generation_seconds'] for x in bench[phase]]
 assert math.isclose(statistics.median(rates),bench['median_'+phase])
assert bench['median_after']>=bench['median_before'],'Do not advertise a measured regression as an improvement'
build=api('actions/runs/'+str(c['build_run']));bj=api('actions/runs/'+str(c['build_run'])+'/jobs')['jobs']
assert build['conclusion']=='success' and build['head_sha']==c['source_commit']
assert next(j for j in bj if j['id']==c['build_job'])['conclusion']=='success'
review=v['ui_review'];assert review['status']=='PASS' and review['apk_sha256']==c['apk_sha256'] and len(review['images'])>=3
for image in review['images']:
 p=Path(image['path']);assert hashlib.sha256(p.read_bytes()).hexdigest()==image['sha256']
 assert p.parent==Path(f"ci-results/{v['run']}-{v['attempt']}")
notes=Path('docs/GENERATION_SPEED.md').read_text().replace('(../ci-results/','(https://github.com/Enzo-cyber2025/5/blob/arena/01a09b42-5/ci-results/')
assert c['apk_sha256'] in notes and 'não é uma medição em celular físico' in notes
Path('.cache/speed-notes.md').write_text(notes);Path('.cache/speed-tag').write_text(v['release_tag'])
print('SIGNED_SPEED_PUBLICATION_GATES_PASS')
PY
SIGNER=$(find "$ANDROID_HOME/build-tools" -path '*/apksigner' -type f | sort -V | tail -1)
"$SIGNER" verify --verbose --print-certs .delivery/GGUF-Chat-mobile.apk | tee .cache/ci-logs/speed-signature.txt
grep 'certificate SHA-256 digest: 3dd851d414caaa20d06ea22391e75b752aab0d26c749168b3353dd389b1332da' .cache/ci-logs/speed-signature.txt
TAG=$(cat .cache/speed-tag)
EXPECTED=$(python3 -c 'import json;print(json.load(open("ci/speed-candidate.json"))["apk_sha256"])')
if ! gh release view "$TAG" >/dev/null 2>&1; then gh release create "$TAG" --target "$GITHUB_SHA" --prerelease --latest=false --title 'GGUF Chat — geração otimizada e tokens/s por resposta' --notes-file .cache/speed-notes.md; fi
gh release edit "$TAG" --notes-file .cache/speed-notes.md
EXISTING=$(gh api "repos/Enzo-cyber2025/5/releases/tags/$TAG" --jq '.assets[]|select(.name=="GGUF-Chat-mobile.apk")|.digest')
if [ -n "$EXISTING" ]; then test "$EXISTING" = "sha256:$EXPECTED"; else gh release upload "$TAG" .delivery/GGUF-Chat-mobile.apk; fi
curl --fail --location --retry 3 --max-time 300 "https://github.com/Enzo-cyber2025/5/releases/download/$TAG/GGUF-Chat-mobile.apk" -o .cache/speed-public.apk
cmp .delivery/GGUF-Chat-mobile.apk .cache/speed-public.apk
sha256sum .cache/speed-public.apk
echo PUBLIC_SPEED_APK_BYTE_EXACT_PASS
