#!/usr/bin/env bash
# Publica uma Release no GitHub com os APKs gerados (usa sua conta).
# Requer: gh autenticado e artefatos em artefatos/.
set -euo pipefail
cd "$(dirname "$0")/.."
cd artefatos
TAG="gguf-studio-v1.9.1-r$(date +%s)"
gh release create "$TAG" *.apk --repo Enzo-cyber2025/5 --title "GGUF Studio v1.9.1 — APK Android" --notes "APK universal + por ABI. SHA-256 nos arquivos .sha256."
echo "Release: https://github.com/Enzo-cyber2025/5/releases/tag/$TAG"
