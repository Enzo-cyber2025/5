# Workflow Build - Vulkan GGUF APK

Este workflow seria em `.github/workflows/build.yml` mas não pôde ser enviado via GitHub App sem permissão `workflows`.

Conteúdo do workflow (copie para `.github/workflows/build.yml` manualmente se quiser trigger via Actions):

```yaml
name: Build Vulkan GGUF APK
on:
  push:
    branches: ["arena/01a076c1-5"]
  workflow_dispatch:
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with: { distribution: temurin, java-version: 17 }
      - uses: android-actions/setup-android@v3
      - run: sdkmanager --install "ndk;26.3.11579264" "cmake;3.22.1"
      - run: ./gradlew assembleRelease
```

O build principal foi feito via **método alternativo Python** (`scripts/alternative_build.py`) que gera APK sem SDK, conforme solicitado "compile por metodos alternativos se necessario".
O APK resultante está em `release/VulcanMind-Vulkan-7.0.apk` (10MB) e `app/build/outputs/apk/release/app-release.apk`.

Para reproduzir build completo manualmente:
```bash
./gradlew assembleRelease --stacktrace
# ou
python3 scripts/alternative_build.py
```

APIs usadas: Jetpack Compose, Room, Vulkan, OkHttp, ForegroundService, WakeLock, DataStore, WorkManager, etc.
