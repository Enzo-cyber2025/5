# GGUF Vulkan Chats

Build Android assinado por GitHub Actions.

Recursos da build:
- UI gráfica organizada em chats.
- Importação persistente de 2 arquivos `.gguf` via seletor do Android.
- Inspeção nativa com `mmap` do cabeçalho GGUF.
- Detecção de Vulkan via `libvulkan.so`.
- Ferramentas de Thinking e Pesquisa.
- Foreground service com wake lock para continuar a geração com a tela bloqueada.

O APK de distribuição é publicado em GitHub Releases.
