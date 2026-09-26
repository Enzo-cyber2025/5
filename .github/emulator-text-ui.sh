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
mkdir -p evidence

phase() {
  local label="$1"; shift
  if bash ci/log_step.sh "$label" "$@"; then
    return 0
  fi
  status=1
  # Uma fase que morre antes de escrever qualquer coisa deixa registro próprio:
  # sem isto o passo de publicação não tinha o que publicar e ainda dizia sucesso.
  echo "$(date -u +%H:%M:%S) fase $label falhou (exit != 0)" >> evidence/phases-failed.txt
  echo "::warning title=GGUF $label failed::Fase $label falhou; as demais fases continuam para não perder evidência real."
}

"${ADB[@]}" wait-for-device
# Pré-verificação do aparelho: um emulador recém-nascido às vezes fica com o
# launcher travado ("Pixel Launcher isn't responding") e nenhum app chega ao
# primeiro plano — foi o que derrubou as cinco fases da rodada 36188984196 sem
# nada de errado no aplicativo. Espera o boot, mantém a tela acesa e fecha o que
# estiver na frente antes de medir qualquer coisa.
for _ in $(seq 1 30); do
  [ "$("${ADB[@]}" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ] && break
  sleep 5
done
"${ADB[@]}" shell svc power stayon true >/dev/null 2>&1 || true
"${ADB[@]}" shell input keyevent KEYCODE_WAKEUP >/dev/null 2>&1 || true
sleep 10
for _ in $(seq 1 6); do
  top="$("${ADB[@]}" shell dumpsys activity activities 2>/dev/null | grep -m1 topResumedActivity || true)"
  case "$top" in
    *nexuslauncher*|*NexusLauncher*) break;;
    "") sleep 5;;
    *) "${ADB[@]}" shell input keyevent KEYCODE_BACK >/dev/null 2>&1 || true; sleep 3;;
  esac
done
"${ADB[@]}" install -r -g "$GGUF_TEST_APK"
"${ADB[@]}" shell pm list packages | grep -q com.ggufchat.app
echo "installed candidate: $GGUF_TEST_APK"
phase text-renderer .venv/bin/python scripts/test_text_android.py
"${ADB[@]}" shell am force-stop com.ggufchat.texttest
phase attachments-detach .venv/bin/python scripts/test_detach_android.py
phase emulator bash .github/emu-test.sh
# Lê o que o harness mediu (não mede nada novo) e reprova se o alvo não foi atingido.
phase performance .venv/bin/python scripts/check_performance.py
# Varredura funcional: cada função visível exercitada, com PASS/FAIL/SKIP declarado.
# Roda por último porque exclui o modelo de propósito, ao testar "Excluir modelo".
# Com o par de visão presente, a varredura também prova imagem de ponta a ponta
# (importar por SAF, anexar e o motor avaliar) em vez de declarar SKIP.
VISAO=()
if [ -n "${GGUF_TEST_VISION:-}" ] && [ -n "${GGUF_TEST_MMPROJ:-}" ]; then
  VISAO=(--vision "$GGUF_TEST_VISION" --mmproj "$GGUF_TEST_MMPROJ")
fi
phase functions .venv/bin/python scripts/test_functions_android.py \
  --serial "$ANDROID_SERIAL" --apk "${GGUF_OUTPUT_APK:-dist/GGUF-Chat-repaired.apk}" \
  --model "$GGUF_TEST_MODEL" --allow-data-reset --evidence "$GGUF_EVIDENCE" "${VISAO[@]}"
exit "$status"
