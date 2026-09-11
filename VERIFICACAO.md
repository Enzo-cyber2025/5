# Verificação — crash ao abrir conversa (GGUF Chat)

Este documento registra **o que foi executado de fato no ambiente** para
reproduzir e validar a correção do crash ao abrir uma conversa, e o que **não é
possível** executar neste ambiente (e por quê).

## TL;DR

| Item | Resultado |
|---|---|
| Causa raiz identificada | ✅ `ggml_backend_vk_host_buffer_type_alloc_buffer` segue com ponteiro `nullptr` quando a memória "pinned" (host-visible) da GPU falha sem exceção |
| Crash reproduzido (nível ggml) | ✅ `GGML_ASSERT(base != NULL)` → `SIGABRT` (exit 134), o mesmo caminho do app |
| Correção validada (fallback CPU) | ✅ versão corrigida aloca buffer CPU e segue (exit 0) |
| Patch aplicado e auditado (arm64) | ✅ `libggml-vulkan.so` arm64 usa `ggml_backend_cpu_buffer_type` + `ggml_backend_buft_alloc_buffer` via PLT (verificado por `.rela.plt` + disassembly) |
| Patch aplicado e auditado (x86_64) | ✅ `libggml-vulkan.so` x86_64 (antes **idêntico ao original**) agora usa o mesmo fallback (trampoline, 80 bytes em 3 pontos) |
| Engine compilado no commit exato do APK | ✅ `llama.cpp` @ `50f068f` — build CPU **e** build Vulkan |
| GGUF mínimo válido + inferência | ✅ modelo gerado carrega e gera tokens no `llama cli` |
| Stack Vulkan compilada do zero | ✅ Vulkan-Headers + Vulkan-Loader + SwiftShader (ICD) + glslc |
| Rodar o backend Vulkan neste host | ⚠️ **impossível** — SwiftShader não implementa 16-bit storage / Float16 (limitação hardcoded do driver) |
| Emulador Android neste ambiente | ❌ **impossível** — `dl.google.com` bloqueado (SDK/emulador), sem KVM, sem Java |

## 1. O que foi pedido e o que dá para fazer aqui

O pedido foi: *"instala, executa, importa um gguf e um mmproj, tenta rodar via
vulkan, executa"*.

O app é um APK **arm64** (Android 7+). Executá-lo de verdade exige um runtime
Android. Neste sandbox **não há como**:

* **Baixar Android SDK / emulador / imagem de sistema**: o domínio
  `dl.google.com` está bloqueado pela rede do sandbox (testado: HTTP 000).
  Sem o SDK não há `adb`, `emulator` nem imagem de sistema.
* **Rodar o emulador mesmo se baixasse**: não há `/dev/kvm` (sem aceleração de
  hardware) e não há Java/JDK (o SDK exige). Emulador x86_64 sem KVM em
  software puro não inicializa em tempo útil; emulador arm64 num host x86_64
  exigiria TCG, ainda mais lento.
* **Executar as `.so` do APK direto no host**: são ELF Android (linkadas contra
  a bionic libc), não rodam em glibc/Debian.

Por isso, a reprodução foi feita **no nível exato em que o crash ocorre**: o
código nativo do ggml (mesmo commit do APK), compilado e executado no host.
Isso é o equivalente mais fiel possível sem um aparelho/emulador.

## 2. Causa raiz (confirmada no código do commit do APK)

Commit do ggml no APK: `50f068ffffc3e0e4c9c2e4139281c6075224f429`
(`ggml/src/ggml-vulkan/ggml-vulkan.cpp`):

```cpp
static ggml_backend_buffer_t ggml_backend_vk_host_buffer_type_alloc_buffer(ggml_backend_buffer_type_t buft, size_t size) {
    size += 32;
    void * ptr = nullptr;
    try {
        ptr = ggml_vk_host_malloc(vk_instance.devices[0], size);
    } catch (vk::SystemError& e) {
        // fallback to cpu buffer
        return ggml_backend_buft_alloc_buffer(ggml_backend_cpu_buffer_type(), size);
    }
    ggml_backend_buffer_t buffer = ggml_backend_cpu_buffer_from_ptr(ptr, size); // <-- ptr pode ser nullptr!
    ...
}
```

`ggml_vk_host_malloc` **retorna `nullptr`** (sem lançar exceção) quando a
memória host-visible não é obtida — comum em celulares reais ao carregar
modelos grandes com todas as camadas na GPU:

```cpp
if(!(buf->memory_property_flags & vk::MemoryPropertyFlagBits::eHostVisible)) {
    fprintf(stderr, "WARNING: failed to allocate ... pinned memory\n");
    device->device.freeMemory(buf->device_memory);
    device->device.destroyBuffer(buf->buffer);
    return nullptr;                     // <-- retorna nullptr, NÃO lança
}
```

O `try/catch` só pega `vk::SystemError` (exceção), então o `nullptr` passa
direto para `ggml_backend_cpu_buffer_from_ptr(nullptr, size)`.

**Consequência**: o buffer é criado com `context = nullptr`; quando o loader
pede a base (`ggml_backend_buffer_get_base`), dispara:

```
GGML_ASSERT(base != NULL && "backend buffer base cannot be NULL") failed
ggml_abort  ->  SIGABRT  ->  o processo nativo morre  ->  "crashou na hora de abrir"
```

A correção aplicada (patch binário no `libggml-vulkan.so` **arm64-v8a e x86_64**,
semânticamente idêntica ao fallback que o próprio upstream adotou depois) é checar
`ptr == nullptr` e cair no buffer CPU:

```cpp
if (ptr == nullptr) {
    return ggml_backend_buft_alloc_buffer(ggml_backend_cpu_buffer_type(), size);
}
```

### 2.1 Patch binário nas duas arquiteturas (auditoria byte a byte)

O patch foi **descoberto e auditado por engenharia reversa** (sem símbolos de
debug no `.so`): resolução completa dos stubs PLT via `.rela.plt` + disassembly
Capstone, comparando o `.so` original com o patchado.

**arm64-v8a** (`lib/arm64-v8a/libggml-vulkan.so`, sha256 `2e16a543df23df96`):

* Função `ggml_backend_vk_host_buffer_type_alloc_buffer` em `.text` VA
  `0x21a5740..0x21a5978`.
* PLT: `0x22d3eb0 = ggml_backend_cpu_buffer_type`, `0x22d3f10 =
  ggml_backend_cpu_buffer_from_ptr`, `0x22d3f40 = ggml_backend_buft_alloc_buffer`,
  `0x22d3f20 = fprintf`.
* Diferença de 56 bytes: `cbz x21,#0x21a58c8` (se `base == NULL` → fallback)
  inserido antes do `bl cpu_buffer_from_ptr`, e o bloco do `fprintf` substituído
  por `bl cpu_buffer_type; mov x1,x19; bl buft_alloc_buffer; b epílogo`.

**x86_64** (`lib/x86_64/libggml-vulkan.so`, sha256 `36c14b1549d17f12`):

* No APK anterior este `.so` estava **byte a byte idêntico ao original**
  (sha256 `8799494e...`), ou seja, **o x86_64 nunca tinha sido patchado**.
* A string `"WARNING: failed to allocate..."` em `.rodata` `0x52dc6` é referenciada
  pelo `lea rsi,[rip-0x2166bc1]` em `0x21b9980`, dentro da função em
  `0x21b97a0..0x21b9ac4`.
* PLT: `0x2323c10 = ggml_backend_cpu_buffer_type`, `0x2323c70 =
  ggml_backend_cpu_buffer_from_ptr`, `0x2323ca0 = ggml_backend_buft_alloc_buffer`,
  `0x2323c80 = fprintf`.
* Patch (80 bytes em 3 pontos): (1) o bloco `fprintf` `0x21b9945..0x21b998d`
  (73 bytes, única referência: o `je` em `0x21b981a`) foi substituído por um
  trampoline `test r12,r12; je fallback; ... call cpu_buffer_from_ptr ...` e o
  fallback `call cpu_buffer_type; mov rdi,rax; mov rsi,rbx; call buft_alloc_buffer`;
  (2) `je 0x21b9945` → `je 0x21b998e` (caminho não-host vai direto ao log);
  (3) `mov rdi,r12; mov rsi,rbx` em `0x21b990a` → `jmp 0x21b9945` + nop.
* ELF estruturalmente íntegro: seções/relocações idênticas, alvos de PLT
  re-resolvidos após o patch.

Após o patch, o APK foi re-assinado em v2 e a assinatura verificada de forma
independente (digest de conteúdo + RSA OK). SHA-256 do APK final:
`02f97871a28936b4374001e0df7352461821181957a5f740207fa5eea4117281`.

## 3. Crash reproduzido no host (nível ggml, mesmo commit)

Fonte: [`host-repro/repro_crash.cpp`](host-repro/repro_crash.cpp) — linkado
contra a `libggml-base` real do llama.cpp @ `50f068f`.

Saída real (bug):

```
buffer criado com ptr=nullptr, agora get_base (é aqui que crasha):
ggml/src/ggml-backend.cpp:147: GGML_ASSERT(base != NULL && "backend buffer base cannot be NULL") failed
... ggml_abort ... ggml_backend_buffer_get_base ...
Aborted                 ./repro_bug
bug exit=134
```

Saída real (fix):

```
FIX OK: buffer CPU alocado, base=0x7ff92caff040, size=1048608
fix exit=0
```

## 4. Engine compilado e executado (commit exato do APK)

* `llama.cpp` no commit `50f068f` compilado com sucesso em **CPU** e com
  **backend Vulkan** (`-DGGML_VULKAN=ON`), usando `glslc` compilado do zero
  (shaderc) para gerar os shaders SPIR-V.
* Gerado um GGUF mínimo **válido** (ver [`host-repro/gen_tiny_gguf.py`](host-repro/gen_tiny_gguf.py)):
  - dimensões de tensor corretas (gguf-py grava em ordem reversa — corrigido),
  - 256 tokens de byte `<0xXX>` (exigidos pelo tokenizer SentencePiece),
  - arquitetura `llama` completa (atenção + FFN + RoPE + tokenizer).
* Inferência CPU: o modelo carrega e gera (saída lixo, esperado — pesos
  aleatórios, mas **o caminho de carga + inferência funciona**):

```
build      : b1-50f068f
model      : /tmp/tiny-llama.gguf
ftype      : F16
modalities : text
> world
...
[ Prompt: 21353.6 t/s | Generation: 1531.4 t/s ]
```

### 4.1 Execução desta rodada (reconstrução do zero, ambiente resetado)

O ambiente foi reiniciado (perdeu `/tmp/llamacpp`, keystore, venv, cmake/clang),
então **tudo foi refeito do zero e executado de verdade** — com o motor
compilado do **commit exato do APK** (`50f068fff`), pois a rede mudou (pip e
GitHub funcionam; `dl.google.com`, `huggingface.co`, `deb.debian.org`,
`conda.anaconda.org`, `gitlab.freedesktop.org` e os hosts de assets do GitHub
continuam bloqueados):

* **Ferramentas**: `cmake 4.4.3` + `ninja` instalados via pip; 4 GiB de swap.
* **Build CPU**: 419/419 passos; todos os binários linkados
  (`llama-completion`, `llama-mtmd-cli`, `llama-tokenize`, …). Só o binário
  unificado `llama` falhou (faltam `-lllama-server-impl`/`-lllama-cli-impl`).
* **Inferência de texto (executada)**: GGUF mínimo válido
  [`host-repro/gen_tiny_llama.py`](host-repro/gen_tiny_llama.py) carrega e gera:
  `load time = 1.91 ms`, `eval time = 0.72 ms / 23 runs` (exit 0).
* **Caminho multimodal gguf+mmproj (executado)**: gerado um projetor LLaVA
  mínimo [`host-repro/gen_mmproj.py`](host-repro/gen_mmproj.py) e rodado
  `llama-mtmd-cli -m tiny-llama.gguf --mmproj tiny-mmproj.gguf --image ...` —
  os 16 tensores do encoder de visão + projetor carregam, a imagem é codificada
  e a saída final é `mtmd batch encoding done` com **exit 0**. Isso é o
  equivalente, no nível do motor, de "importar um GGUF e um mmproj e rodar".
* **Crash reproduzido com a lib exata**: [`host-repro/repro_v2.cpp`](host-repro/repro_v2.cpp)
  linkado contra a `libggml-base.so` recém-compilada do commit do APK —
  caminho original → `GGML_ASSERT(base != NULL ...) failed` → **SIGABRT**
  (exit 134); caminho corrigido → buffer CPU alocado, `get_base()=0x7f...`
  (exit 0).

## 5. Stack Vulkan compilada do zero (e por que não roda neste host)

Compilados a partir do código-fonte (GitHub, que é acessível):

| Componente | Origem | Resultado |
|---|---|---|
| Vulkan-Headers | KhronosGroup/Vulkan-Headers | ✅ instalado em `/tmp/vk-prefix` |
| Vulkan-Loader | KhronosGroup/Vulkan-Loader | ✅ `libvulkan.so.1.4.362` |
| SwiftShader (ICD por software) | google/swiftshader | ✅ `libvk_swiftshader.so` (20 MB) |
| glslc | google/shaderc + glslang/SPIRV-Tools | ✅ `glslc` (shaderc v2026.4) |

Teste de dispositivo (loader + ICD funcionando):

```
device0=SwiftShader Device (LLVM 10.0.0) api=1.3.0
storageBuffer16BitAccess=0  uniformAndStorageBuffer16BitAccess=0  shaderFloat16=0  shaderInt8=0
deviceType=4 (CPU)
```

O backend ggml-vulkan, **fielmente**, recusa o SwiftShader por dois motivos que
são **hardcoded** no próprio SwiftShader (não são flag de build):

1. `deviceType = eCpu` — o ggml-vulkan só aceita `DiscreteGpu`/`IntegratedGpu`
   (nos celulares reais é sempre GPU dedicada/integrada).
2. `storageBuffer16BitAccess = VK_FALSE` (hardcoded em
   `swiftshader/src/Vulkan/VkPhysicalDevice.cpp:111`) e o compilador de shaders
   não implementa Float16 (`OpFConvert` / capability 4433) — o ggml-vulkan exige
   `VK_KHR_16bit_storage` e usa operações F16 nos shaders.

Ou seja: **o SwiftShader não tem como executar os shaders do ggml-vulkan**, e o
único ICD por software que teria (lavapipe/Mesa) exige LLVM novo + build do Mesa
com dependências que não podem ser baixadas aqui (apt bloqueado). Isso **não
afeta o aparelho real**: GPUs Adreno/Mali têm 16-bit storage e o backend entra
normalmente — e é exatamente nesse caminho (alocação de memória pinned) que o
crash original ocorria, e que a correção do §3 cobre.

> Nota: para confirmar o diagnóstico acima, foi aplicado um patch **local e
> apenas de teste** (no clone em `/tmp`, NÃO no APK) relaxando os gates de
> device, e o backend de fato passou a inicializar o device e a tentar
> compilar shaders — parando exatamente nos erros de Float16 do SwiftShader
> listados acima. O APK **não** contém essas alterações de teste.

## 6. Como verificar no aparelho real / no emulador

O fluxo de emulador (x86_64) já está pronto em
[`emu-test.workflow.yml`](emu-test.workflow.yml) (copiar para
`.github/workflows/emu-test.yml` e disparar em **Actions**). Ele:

> **Atualização:** como o `libggml-vulkan.so` **x86_64** agora também está
> patchado (antes estava idêntico ao original), este fluxo de emulador passa a
> exercitar de fato a correção — não só no arm64.

1. instala o APK (`adb install -r -g`),
2. baixa e injeta um GGUF real (`stories15M-q4_0.gguf`) + `models.json` + `chats.json`,
3. abre 5 chats: lançamento, CPU (`gpuLayers=0`), Vulkan (`gpuLayers=-1`),
   caminho inexistente e **modelo+mmproj vinculados** (carga multimodal/unificada),
4. captura `FATAL`/`SIGSEGV`/`SIGABRT`/logs `ggml`/`vulkan` de cada abertura.

Num **aparelho real arm64** (o caso que crashava): instalar o APK, importar um
GGUF e, se for de visão, o mmproj correspondente, e abrir a conversa. Com a
correção, uma falha de memória pinned agora cai em **CPU** e a conversa abre
(não derruba mais o app).

## 7. Reproduzir localmente (Linux)

```bash
# requer g++, make, python3, cmake, numpy e gguf
bash host-repro/run.sh
```

O script: clona/compila o llama.cpp no commit exato do APK, gera o GGUF mínimo,
roda inferência CPU e executa o repro do crash (`bug` → SIGABRT, `fix` → OK).
