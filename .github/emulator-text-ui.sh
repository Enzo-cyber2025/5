#!/usr/bin/env bash
# Disposable CI emulator only (adb root, external APKs and a data reset happen here).
# Every phase runs even when an earlier one fails, so one 25-minute run always
# yields the maximum real evidence; the script still exits non-zero at the end.
set -uo pipefail
cd "$(dirname "$0")/.."
: "${ANDROID_SERIAL:?Set by the emulator action}"
: "${GGUF_TEST_APK:?}"
ADB=(adb -s "$ANDROID_SERIAL")
status=0

phase() {
  local label="$1"; shift
  if bash ci/log_step.sh "$label" "$@"; then
    return 0
  fi
  status=1
  echo "::warning title=GGUF $label failed::Fase $label falhou; as demais fases continuam para não perder evidência real."
}

"${ADB[@]}" wait-for-device
"${ADB[@]}" install -r -g "$GGUF_TEST_APK"
"${ADB[@]}" shell pm list packages | grep -q com.ggufchat.app
echo "installed candidate: $GGUF_TEST_APK"
phase text-renderer .venv/bin/python scripts/test_text_android.py
"${ADB[@]}" shell am force-stop com.ggufchat.texttest
phase attachments-detach .venv/bin/python scripts/test_detach_android.py
phase emulator bash .github/emu-test.sh
exit "$status"
