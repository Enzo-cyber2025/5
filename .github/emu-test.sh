#!/usr/bin/env bash
# The old permissive suite is replaced by assertions with nonzero exit status.
# Only disposable emulators: this resets com.ggufchat.app's data.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${ANDROID_SERIAL:?Set the disposable emulator serial (emulator-...)}"
: "${GGUF_TEST_MODEL:?Set a REAL text GGUF path; there is no tiny/fake fallback}"
args=(--serial "$ANDROID_SERIAL" --apk "${GGUF_OUTPUT_APK:-dist/GGUF-Chat-repaired.apk}"
      --model "$GGUF_TEST_MODEL" --allow-data-reset --evidence "${GGUF_EVIDENCE:-evidence}")
args+=(--model-setup "${GGUF_MODEL_SETUP:-saf}")
[[ "${GGUF_GENERATION_ONLY:-0}" != 1 ]] || args+=(--generation-only)
[[ "${GGUF_VULKAN_ONLY:-0}" != 1 ]] || args+=(--vulkan-only)
if [[ -n "${GGUF_TEST_VISION:-}" || -n "${GGUF_TEST_MMPROJ:-}" ]]; then
  : "${GGUF_TEST_VISION:?Both vision and mmproj paths are required}"
  : "${GGUF_TEST_MMPROJ:?Both vision and mmproj paths are required}"
  args+=(--vision "$GGUF_TEST_VISION" --mmproj "$GGUF_TEST_MMPROJ")
fi
[[ "${GGUF_REQUIRE_VULKAN:-0}" != 1 ]] || args+=(--require-vulkan)
exec python3 scripts/test_android.py "${args[@]}"
