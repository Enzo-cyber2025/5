#!/usr/bin/env bash
# Disposable CI emulator only (adb root, external APKs and a data reset happen here).
# Order matters: the two new UI checks run before the long integration suite, so
# their evidence exists even when a later recommendation-independent check fails.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${ANDROID_SERIAL:?Set by the emulator action}"
: "${GGUF_TEST_APK:?}"
ADB=(adb -s "$ANDROID_SERIAL")
"${ADB[@]}" wait-for-device
"${ADB[@]}" install -r -g "$GGUF_TEST_APK"
"${ADB[@]}" shell pm list packages | grep -q com.ggufchat.app
echo "installed candidate: $GGUF_TEST_APK"
bash ci/log_step.sh text-renderer .venv/bin/python scripts/test_text_android.py
"${ADB[@]}" shell am force-stop com.ggufchat.texttest
bash ci/log_step.sh attachments-detach .venv/bin/python scripts/test_detach_android.py
bash ci/log_step.sh emulator bash .github/emu-test.sh
