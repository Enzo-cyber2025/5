# GGUF Studio — APK (CI recipe)

Repositório de *entrega*: contém apenas a receita de CI e os artefatos APK compilados.

- `patches/gguf-studio.patch` — customizações aplicadas sobre o upstream LMPlayground (MIT) no commit pinado.
- `.github/workflows/build-apk.yml` — build Android do APK (llama.cpp + Vulkan).
- `apk/` — artefatos compilados (adicionados pelo CI).
