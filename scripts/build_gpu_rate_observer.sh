#!/usr/bin/env bash
# Test signatures only; assert every non-signature byte of each target APK stays exact.
set -euo pipefail
SDK=${ANDROID_HOME:?}
BT="$SDK/build-tools/35.0.0"
JAR="$SDK/platforms/android-35/android.jar"
OUT=.cache/gpu-rate
mkdir -p "$OUT/classes" "$OUT/dex" evidence
if [[ -n "${GGUF_ROW_TILE_TEST_IMPORT:-}" ]]; then
  [[ -z "${GGUF_REPACKED_TEST_IMPORT:-}" && -z "${GGUF_EXPANDED_TEST_IMPORT:-}" ]]
  export GGUF_EXPANDED_TEST_IMPORT="$GGUF_ROW_TILE_TEST_IMPORT"
fi
if [[ -n "${GGUF_REPACKED_TEST_IMPORT:-}" ]]; then
  [[ -z "${GGUF_EXPANDED_TEST_IMPORT:-}" ]]
  export GGUF_EXPANDED_TEST_IMPORT="$GGUF_REPACKED_TEST_IMPORT"
fi
KEY="$RUNNER_TEMP/gpu-rate-observer.p12"
keytool -genkeypair -keystore "$KEY" -storetype PKCS12 -storepass android -alias test -keyalg RSA -keysize 2048 -validity 2 -dname 'CN=Disposable unchanged-native GPU benchmark NOT release'
trap 'rm -f "$KEY"' EXIT
"$BT/aapt2" link -I "$JAR" --manifest tests/android-gpu-rate/AndroidManifest.xml -o "$OUT/observer.apk"
javac --release 8 -classpath "$JAR" -d "$OUT/classes" tests/android-gpu-rate/src/com/ggufchat/gpurate/*.java
"$BT/d8" --lib "$JAR" --min-api 28 --output "$OUT/dex" $(find "$OUT/classes" -name '*.class')
(cd "$OUT/dex" && zip -q ../observer.apk classes.dex)
"$BT/apksigner" sign --ks "$KEY" --ks-pass pass:android "$OUT/observer.apk"
"$BT/apksigner" sign --ks "$KEY" --ks-pass pass:android --out "$OUT/before.apk" .cache/pre-acceleration.apk
"$BT/apksigner" sign --ks "$KEY" --ks-pass pass:android --out "$OUT/after.apk" entrega/GGUF-Chat-acelerado.apk
if [[ -n "${GGUF_EXPANDED_TEST_IMPORT:-}" ]]; then
  "$BT/apksigner" sign --ks "$KEY" --ks-pass pass:android --out "$OUT/candidate.apk" "$GGUF_EXPANDED_TEST_IMPORT/candidate.apk"
  "$BT/apksigner" verify --verbose "$OUT/candidate.apk"
fi
for apk in before after observer; do "$BT/apksigner" verify --verbose "$OUT/$apk.apk"; done
python3 - <<'PY'
import hashlib,json,sys,os
from pathlib import Path
sys.path[:0]=['scripts','ci']
from sign_gain_release import payload
from evaluate_gpu_rate import HASHES
out=Path('.cache/gpu-rate');reports={}
for phase,src in [('before',Path('.cache/pre-acceleration.apk')),('after',Path('entrega/GGUF-Chat-acelerado.apk'))]:
    original=hashlib.sha256(src.read_bytes()).hexdigest();assert original==HASHES[phase]
    dst=out/(phase+'.apk');entries=payload(src);assert entries==payload(dst),'Signing changed executable/resources'
    reports[phase]=dict(original_sha256=original,test_sha256=hashlib.sha256(dst.read_bytes()).hexdigest(),
                       non_signature_payload_identical=True,native={k:v for k,v in entries.items() if k.startswith('lib/')},
                       entry_manifest_sha256=hashlib.sha256(json.dumps(entries,sort_keys=True).encode()).hexdigest())
experiment=None
if os.environ.get('GGUF_EXPANDED_TEST_IMPORT'):
    folder=Path(os.environ['GGUF_EXPANDED_TEST_IMPORT']);experiment=json.loads((folder/'build.json').read_text())
    flag='experimental_repacked_weights_build' if os.environ.get('GGUF_REPACKED_TEST_IMPORT') else 'experimental_expanded_weights_build'
    if os.environ.get('GGUF_ROW_TILE_TEST_IMPORT'):flag='experimental_row_tile_build'
    assert experiment[flag] is True and experiment['default_enabled'] is False and experiment['release_approved'] is False
    src=folder/'candidate.apk';dst=out/'candidate.apk'
    original=hashlib.sha256(src.read_bytes()).hexdigest();assert original==experiment['apk_sha256']
    entries=payload(src);assert entries==payload(dst),'Candidate signing changed executable/resources'
    reports['candidate']=dict(original_sha256=original,test_sha256=hashlib.sha256(dst.read_bytes()).hexdigest(),non_signature_payload_identical=True,
        native={k:v for k,v in entries.items() if k.startswith('lib/')},entry_manifest_sha256=hashlib.sha256(json.dumps(entries,sort_keys=True).encode()).hexdigest())
r=dict(payloads=reports,observer_sha256=hashlib.sha256((out/'observer.apk').read_bytes()).hexdigest(),release_approved=False,experiment=experiment)
(out/'build.json').write_text(json.dumps(r,indent=2));Path('evidence/physical-gpu-rate-build.json').write_text(json.dumps(r,indent=2))
PY
