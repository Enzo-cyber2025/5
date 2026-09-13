# Reparos do APK original

## Fluxo único

1. `patch_dex.py`: valida o SHA-256 do DEX original e aplica cinco patches do mesmo
   tamanho, mantendo offsets, branches e handlers intactos; recalcula SHA-1/Adler32.
2. `build_apk.py`: decodifica o DEX corrigido com Apktool 2.9.3.
3. `patch_smali.py`: substitui `EngineManager` pela versão com cache completo e
   validação básica de arquivos; adiciona `GenerationResult` e sua chamada dentro
   do `try/catch` existente de `GenerationService`.
4. Corrige o filtro de modelos, o guarda de envio e os acessos privados dos workers.
5. Acrescenta `libdl.so` ao DT_NEEDED da ponte JNI ARM64/x86_64 com patchelf 0.17.2.4;
   verifica SONAME, arquitetura e igualdade das seções de código/dados protegidas.
6. Substitui `libc++_shared.so` nas duas ABIs pelo runtime oficial do NDK
   **28.2.13676358**. Compila o helper de diagnóstico nativo e um probe de ABI
   separado para testar corrupção de RBX no construtor de `std::recursive_mutex`.
   O probe e o runtime antigo são fixtures externas ao APK, não motores substitutos.
7. `patch_vulkan.py` direciona quatro imports a `libggufvk.so` (14 bytes ELF por
   ABI), sem mudar código/shaders/dados. O adaptador só omite o alias de extensão
   16-bit quando o suporte real pelo Vulkan 1.1+ foi conferido; nunca simula Vulkan.
8. Recompila, copia o novo DEX para o ZIP original e os componentes nativos explicitamente autorizados,
   remove assinaturas antigas, alinha dados não comprimidos e assina com apksigner 0.9.
9. Verifica assinatura v2/v3, alinhamento e igualdade dos demais payloads.

A geração nativa foi executada no emulador, mas a qualidade das respostas não passou.
Veja [o relatório](../docs/GERACAO.md). O erro de UTF-8 da ponte nativa continua pendente.

Não execute patches em APKs de procedência/versão diferente. A checagem de hash usa
`ValueError`, não `assert`, e continua ativa com `python -O`.

## Offsets no classes.dex ORIGINAL

| Offset | Correção |
|---|---|
| `0xB470` | `Chat.fromJson`: caminho principal válido não pode virar null |
| `0xB4A6` | `Chat.fromJson`: caminho do projetor válido não pode virar null |
| `0x11C28` | `ModelInfo.fromJson`: persistência do vínculo mmproj |
| `0xD808` | `EngineManager.load`: não anular projetor válido |
| `0x11190` | `showMmprojPicker`: substituir dp(int incorreto) por reutilização de padding já calculado |

Os offsets não se aplicam ao DEX final recompilado. Os três primeiros guardas de JSON
normalizam `null`, string vazia e texto `"null"`, mas preservam caminhos válidos.
A versão completa de EngineManager possui o mesmo contrato de normalização.

Os substitutos `Native`/`JSONObject` usados nos testes ficam exclusivamente em
`tests/fixtures/`. Eles **nunca são copiados para o APK de entrega**.

Veja [README principal](../README.md) e [validação](../docs/VALIDACAO.md).
