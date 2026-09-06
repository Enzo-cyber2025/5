#!/usr/bin/env bash
# ============================================================================
# GGUF Studio — build local do APK (máquina com Android SDK instalado)
# Requer: JDK 17+ (de preferência 21), Android SDK (ANDROID_HOME) com
# NDK 27.2.12479018, e internet liberada (Maven Google/Central + dl.google.com).
# Uso: bash scripts/build-local.sh
# ============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UPSTREAM_PIN="cfb38bb24308d6b38ba9da41a247ac5435e435b0"
NDK_PIN="27.2.12479018"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

command -v java >/dev/null || { echo "JDK 21 necessário (ex.: instale via sdkman/jdk4py)"; exit 1; }
[ -n "${ANDROID_HOME:-}" ] || { echo "ANDROID_HOME não definido"; exit 1; }
SDKMANAGER="$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager"
[ -x "$SDKMANAGER" ] || { echo "cmdline-tools não encontrado em $ANDROID_HOME"; exit 1; }

echo "==> SDK/NDK"
yes | "$SDKMANAGER" --install "platforms;android-36" "build-tools;36.0.0" "ndk;$NDK_PIN" >/dev/null

echo "==> Vulkan toolchain"
GLSLC="$ANDROID_HOME/ndk/$NDK_PIN/shader-tools/linux-x86_64/glslc"
test -x "$GLSLC"
if [ ! -f "/usr/include/vulkan/vulkan.hpp" ] && [ ! -f "/usr/local/include/vulkan/vulkan.hpp" ]; then
  echo "Instale libvulkan-dev e spirv-headers (apt)"; exit 1
fi
VKINC="$WORK/vk-inc/include"; mkdir -p "$VKINC"
for d in vulkan vk_video spirv; do
  [ -d "/usr/include/$d" ] && cp -r "/usr/include/$d" "$VKINC/"
done
SPIRV_CFG="$(find /usr -name SPIRV-HeadersConfig.cmake 2>/dev/null | head -1)"

export VULKAN_GLSLC="$GLSLC"
export VULKAN_HEADERS_DIR="$VKINC"
export SPIRV_HEADERS_INCLUDE_DIR="$VKINC"
export SPIRV_HEADERS_DIR="$(dirname "$SPIRV_CFG")"

echo "==> Fonte upstream pinada"
git clone --quiet https://github.com/andriydruk/LMPlayground.git "$WORK/src"
git -C "$WORK/src" checkout --quiet "$UPSTREAM_PIN"
git -C "$WORK/src" submodule update --init --recursive

echo "==> Patch GGUF Studio"
git -C "$WORK/src" apply --verbose "$REPO_ROOT"/patches/*.patch

echo "==> Build (pode levar 1-3h)"
sed -i 's/org.gradle.jvmargs=-Xmx2048m/org.gradle.jvmargs=-Xmx6144m -XX:MaxMetaspaceSize=2g/' "$WORK/src/gradle.properties"
cd "$WORK/src" && ./gradlew :app:assembleRelease --no-daemon

echo "==> Artefatos em $REPO_ROOT/artefatos/"
mkdir -p "$REPO_ROOT/artefatos"
cd app/build/outputs/apk/release
for f in *.apk; do sha256sum "$f" > "$f.sha256"; cp "$f" "$f.sha256" "$REPO_ROOT/artefatos/"; done
ls -la "$REPO_ROOT/artefatos/"
