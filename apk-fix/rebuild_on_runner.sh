#!/usr/bin/env bash
# Single build entrypoint. No duplicate byte patches or handwritten signing.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${GGUF_KEYSTORE_PASSWORD:?Set the signing password in the environment}"
python3 apk-fix/build_apk.py "${GGUF_ORIGINAL_APK:-.cache/gguf/GGUF-Chat.apk}" \
  "${GGUF_OUTPUT_APK:-dist/GGUF-Chat-repaired.apk}" \
  --keystore "${GGUF_KEYSTORE:-.cache/signing/gguf-repair.p12}" \
  --alias "${GGUF_KEY_ALIAS:-gguf-repair}"
