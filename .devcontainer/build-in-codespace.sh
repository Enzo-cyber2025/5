#!/usr/bin/env bash
# ============================================================================
# GGUF Studio — build automático do APK dentro de um GitHub Codespace.
#
# O Codespace tem acesso total à internet (diferente da sandbox do agente),
# então aqui conseguimos baixar Android SDK/NDK, Gradle e as dependências
# Maven do Google, compilar o llama.cpp com Vulkan e gerar o APK final.
#
# Este script roda sozinho (postCreateCommand). Ao final, o APK fica em:
#   <workspace>/artefatos/
# e, se o GitHub CLI estiver disponível, uma Release é publicada com os
# links diretos de download.
# ============================================================================
set -euxo pipefail

export DEBIAN_FRONTEND=noninteractive
REPO_ROOT="$(pwd)"
UPSTREAM_PIN="cfb38bb24308d6b38ba9da41a247ac5435e435b0"
NDK_PIN="27.2.12479018"
GLSLC_NDK_ZIP_URL="https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip"

echo "==> [1/8] Dependências do sistema (Vulkan + ferramentas)"
sudo apt-get update -qq
sudo apt-get install -y -qq wget unzip git libvulkan-dev spirv-headers

echo "==> [2/8] Android SDK + NDK (download oficial do Google)"
SDK_ROOT="$HOME/android-sdk"
mkdir -p "$SDK_ROOT/cmdline-tools"
cd "$(mktemp -d)"
wget -q "$GLSLC_NDK_ZIP_URL" -O cmdtools.zip
unzip -q cmdtools.zip
mv cmdline-tools/* "$SDK_ROOT/cmdline-tools/latest"
yes | "$SDK_ROOT/cmdline-tools/latest/bin/sdkmanager" \
  --sdk_root="$SDK_ROOT" \
  "platforms;android-36" \
  "build-tools;36.0.0" \
  "ndk;$NDK_PIN" >/dev/null || true

echo "==> [3/8] Vulkan: glslc do NDK + headers (receita do upstream)"
GLSLC="$SDK_ROOT/ndk/$NDK_PIN/shader-tools/linux-x86_64/glslc"
test -x "$GLSLC"
VKINC="$HOME/vk-headers/include"
mkdir -p "$VKINC"
for d in vulkan vk_video spirv; do
  [ -d "/usr/include/$d" ] && cp -r "/usr/include/$d" "$VKINC/"
done
test -f "$VKINC/vulkan/vulkan.hpp"
test -f "$VKINC/spirv/unified1/spirv.hpp"
SPIRV_CFG="$(find /usr -name SPIRV-HeadersConfig.cmake 2>/dev/null | head -1)"
test -n "$SPIRV_CFG"
export VULKAN_GLSLC="$GLSLC"
export VULKAN_HEADERS_DIR="$VKINC"
export SPIRV_HEADERS_INCLUDE_DIR="$VKINC"
export SPIRV_HEADERS_DIR="$(dirname "$SPIRV_CFG")"
export ANDROID_HOME="$SDK_ROOT"
export ANDROID_SDK_ROOT="$SDK_ROOT"

echo "==> [4/8] Código-fonte upstream pinado (LMPlayground MIT + llama.cpp)"
cd "$HOME"
rm -rf lmp-src
git clone --quiet https://github.com/andriydruk/LMPlayground.git lmp-src
cd lmp-src
git checkout --quiet "$UPSTREAM_PIN"
git submodule update --init --recursive

echo "==> [5/8] Aplica customizações GGUF Studio"
git apply --verbose --whitespace=nowarn "$REPO_ROOT"/patches/*.patch
grep -m1 'name="app_name"' app/src/main/res/values/strings.xml

echo "==> [6/8] Compila APK release (llama.cpp + mtmd, Vulkan, arm64 + x86_64)"
sed -i 's/org.gradle.jvmargs=-Xmx2048m/org.gradle.jvmargs=-Xmx6144m -XX:MaxMetaspaceSize=2g/' gradle.properties
./gradlew :app:assembleRelease --no-daemon --stacktrace

echo "==> [7/8] Reúne artefatos + checksums"
mkdir -p "$REPO_ROOT/artefatos"
cd app/build/outputs/apk/release
for f in *.apk; do
  sha256sum "$f" > "$f.sha256"
  cp "$f" "$f.sha256" "$REPO_ROOT/artefatos/"
done
ls -la "$REPO_ROOT/artefatos/"

echo "==> [8/8] Publica Release (se gh disponível — no Codespace usa sua conta)"
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  SHA_SUM="$(awk '{print $1}' app-universal-release.apk.sha256)"
  TAG="gguf-studio-v1.9.1-codespace"
  NOTES="$HOME/notes.md"
  cat > "$NOTES" <<EOF
**GGUF Studio v1.9.1** — APK Android compilado em Codespace.

Baixe \`app-universal-release.apk\` (celular arm64 ou emulador) ou \`app-arm64-v8a-release.apk\`.

SHA-256 (universal): \`$SHA_SUM\`

Recursos: 100% offline · importa GGUF da memória · Vulkan com fallback CPU · chats ·
multimodal (visão/mmproj) · thinking · busca na web · gera com a tela bloqueada.
Créditos: LM Playground (MIT) + llama.cpp (MIT).
EOF
  gh release create "$TAG" \
    app-universal-release.apk app-arm64-v8a-release.apk app-x86_64-release.apk \
    --repo "Enzo-cyber2025/5" \
    --title "GGUF Studio v1.9.1 — APK Android (Codespace)" \
    --notes-file "$NOTES" || echo "Release falhou (sem permissão?) — APKs estão em artefatos/"
else
  echo "gh não disponível — APKs prontos em: $REPO_ROOT/artefatos/"
fi

echo
echo "================================================================"
echo " PRONTO! APK em: $REPO_ROOT/artefatos/"
echo " (baixe pelo painel do Codespace ou pela Release, se publicada)"
echo "================================================================"
