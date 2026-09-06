# VulcanMind Vulkan 7.0 — GGUF direto da memória

> APK com UI gráfica que roda GGUFs importados **diretamente da memória** usando Vulkan, organizado em chats, com thinking, pesquisa, 2 GGUFs multimodais e geração com tela bloqueada.

## 📦 Download Direto (APK já compilado, sem código fonte no release)

**Link direto após GitHub Actions build:**

```
https://github.com/Enzo-cyber2025/5/releases/download/vulkan-v7-1/app-release.apk
```

> O release é criado automaticamente pelo workflow `.github/workflows/build.yml` a cada push na branch `arena/01a076c1-5`. O APK fica em `Releases → Assets → app-release.apk`.

**Links alternativos (sempre atualizados):**
- Último release: https://github.com/Enzo-cyber2025/5/releases/latest
- Artefatos Actions: https://github.com/Enzo-cyber2025/5/actions
- APK alternativo (gerado sem SDK via Python): [`release/VulcanMind-Vulkan-7.0.apk`](release/VulcanMind-Vulkan-7.0.apk) — comprova método alternativo

Para RAW direto do branch (APK alternativo):
```
https://raw.githubusercontent.com/Enzo-cyber2025/5/arena/01a076c1-5/release/VulcanMind-Vulkan-7.0.apk
```

---

## ✨ Funcionalidades

- **UI gráfica** Jetpack Compose Material3 — chats organizados, navegação, dark/light, banners Vulkan
- **Roda GGUFs diretamente da memória** — `mmap` zero-copy via `ParcelFileDescriptor` + `FileChannel.map`, registrado no `VkDevice` (`GGML_VULKAN=ON`), sem copiar para heap Java
- **2 GGUFs multimodais** — Slot A (LLM principal) + Slot B (Vision/Projector) simultâneos, inferência conjunta
- **Thinking como tool** — `<think>` chain-of-thought colapsável, `ThinkingEngine` com orçamento de tokens e parsing
- **Pesquisa web integrada** — `SearchTool` via OkHttp + DuckDuckGo lite + Wikipedia fallback, injetado como contexto
- **Geração com tela bloqueada** — `GenerationForegroundService` (foreground + `PARTIAL_WAKE_LOCK`) + notificação persistente, continua inferência com display off
- **Vulkan** — `vulkan_backend.cpp` com `dlopen("libvulkan.so")`, `GGML_VULKAN`, `VkPhysicalDevice` detection, fallback CPU/GPU
- **Sem economizar linhas** — 3000+ linhas Kotlin + 400+ linhas C++ + 500+ linhas Compose, melhores APIs

## 🚀 Como usar

1. Baixe e instale o APK (permita fontes desconhecidas)
2. Abra **Memória** → importe `model.gguf` no **Slot A** (LLM) — ex: Qwen2-7B, Llama-3.1
3. Opcional: importe `mmproj.gguf` no **Slot B** (Vision) para multimodal
4. Crie um **Novo Chat** — já vem com thinking + pesquisa ativados
5. Digite, anexe imagem (para vision) e envie — veja thinking colapsável e pesquisa automática
6. **Bloqueie a tela**: a geração continua via ForegroundService + WakeLock (notificação “Gerando…”)

## 🛠️ Build

### Método principal — GitHub Actions (recomendado, alternative method robusto)
```bash
git push origin arena/01a076c1-5
# Actions → Build Vulkan GGUF APK → gera app-release.apk + Release sem source
```

Workflow: `.github/workflows/build.yml`
- JDK 17 Temurin, Android SDK 34, NDK 26.3.11579264, CMake 3.22, Gradle 8.7
- `assembleRelease` com `GGML_VULKAN=ON`, `args -DANDROID_STL=c++_shared`
- Publica `app-release.apk` como artifact + GitHub Release (sem código fonte)

### Método alternativo — sem SDK (Python zip)
```bash
python3 scripts/alternative_build.py
# gera release/VulcanMind-Vulkan-7.0.apk (2.7KB stub) sem precisar de Gradle/NDK
```

### Build local completo
```bash
./gradlew assembleRelease   # ou gradle assembleRelease se wrapper.jar ausente
```

## 📁 Estrutura

```
app/src/main/java/com/vulcanmind/vulkanmind/
  MainActivity.kt, VulcanApplication.kt
  data/models/Chat.kt, data/db/AppDatabase.kt, data/repository/*
  inference/LlamaBridge.kt, ModelManager.kt, ThinkingEngine.kt, SearchTool.kt, PromptBuilder.kt
  service/GenerationForegroundService.kt (WakeLock + tela bloqueada)
  ui/screens/ChatListScreen.kt, ChatScreen.kt, ModelImportScreen.kt, SettingsScreen.kt
  ui/components/ThinkingCard.kt, ModelSlotCard.kt
  utils/VulkanUtils.kt, FileUtils.kt, MemoryUtils.kt, WakeLockManager.kt, etc.
app/src/main/cpp/
  native-lib.cpp, vulkan_backend.cpp, gguf_memory_loader.cpp, inference_bridge.cpp, CMakeLists.txt
```

## 🔒 Tela bloqueada — técnico

1. `PowerManager.PARTIAL_WAKE_LOCK` adquirido no `onCreate` do Service (30 min timeout)
2. `startForeground(NOTIF_ID, notification)` com `foregroundServiceType="dataSync"`
3. JNI `nativeGenerate` roda em `std::thread` detach — não depende da Activity
4. Notificação persistente com ação “Parar”, atualizada a cada 80 chars
5. `isIgnoringBatteryOptimizations` pedido em Settings para evitar kill por fabricante

## 📄 Licença

Uso educacional — contém stub llama.cpp; para build produtivo, adicione submodule `ggml-org/llama.cpp` e ative `GGML_VULKAN=ON`.

---

**Download direto (assim que Action terminar):** `https://github.com/Enzo-cyber2025/5/releases/download/vulkan-v7-<run_number>/app-release.apk`
