# Correção Vulkan — 13/09/2026

## Resultado atual: PASS — geração Vulkan por software

[Execução 34778868262](https://github.com/Enzo-cyber2025/5/actions/runs/34778868262),
commit `f6dc954`, Android 15/API 35 x86_64 com llvmpipe:

| Verificação | Resultado |
|---|---|
| Build e assinatura v2/v3 | PASS |
| Ferramentas / classes reais DEX→JVM | **94 / 33 PASS** |
| Controle C++ original vs runtime oficial | PASS |
| Instalar, abrir, conferir SHA do modelo real | PASS |
| Criação do dispositivo Vulkan | VK_SUCCESS |
| Offload no último carregamento | **31/31 camadas, gpu_offload=1** |
| Conclusão nativa | **GGUF_REPAIR_GENERATION_OK** |
| Assistant persistido após o prompt exato | PASS |
| Resultado integrado Vulkan | **PASS** |

- [Resumo](../ci-results/34778868262-1/summary.json).
- [Backend e conclusão](../ci-results/34778868262-1/vulkan-backend.txt).
- [Conversa](../ci-results/34778868262-1/vulkan-chats.json) e [resposta](../ci-results/34778868262-1/vulkan-reply.txt).
- [APK testado, em ZIP](https://github.com/Enzo-cyber2025/5/actions/runs/34778868262/artifacts/10324333917), retenção de 7 dias.
- SHA-256: `b3ae6a0df9c9cd38f947f67df6c19fe01ea6dfd39eb4f39979cd13009c62a0f6`.
- Certificado SHA-256: `ab4e33215e2987d859101c714a0f8692f1afcc3f32cf88a02e3bb6c365abd876`.

### Terceira causa corrigida: limite de tokens não é erro

A inspeção do JNI original identificou que apenas EOG marcava sucesso. Quando todos
os tokens solicitados eram produzidos/decodificados sem erro, o retorno e `onDone`
ainda recebiam false. Por isso os runs anteriores salvavam texto e reprovavam.

`patch_generation.py` corrige somente as saídas normais por limite de tokens:
41 bytes alterados no x86_64 e 3 no ARM64, dentro de faixas de instruções verificadas.
O hash integral das bibliotecas originais é obrigatório, e o tamanho é preservado.
Erros na decodificação (inclusive no último token), cancelamento antes do fim,
handle inválido e limites não positivos continuam retornando falha. EOG continua
sendo término normal. O Java e o teste integrado continuam exigindo retorno true;
não houve alteração para aceitar uma resposta salva como substituto de sucesso.

Os novos testes executam as instruções reais de ambas as ABIs sob Unicorn, com
**doubles explícitos nas chamadas externas**, para comparar original/corrigido em
limites 1, 2, 3 e 128 e em erros em cada decode gerado. Eles são regressões de fluxo,
não inferência nem aprovação de aparelho ARM64. Nada disso entra no APK.
A aprovação de inferência veio separadamente do APK real no emulador Android.

### Limites da aprovação

Vulkan é software, não GPU física. O modelo foi provisionado, não importado via SAF.
Qualidade das respostas não foi aprovada: a saída ainda é longa/inadequada ao pedido
de uma saudação curta. UTF-8, visão e aparelho ARM64 seguem sem correção/validação
completa. O APK é assinado com chave de teste diferente da original; preserve dados
antes de qualquer desinstalação. O download local do artefato falhou (EOF); o link
acima identifica o binário exato testado, não um APK antigo do workspace.

---

# Histórico anterior à correção de conclusão por tokens

As reprovações abaixo foram preservadas como controles/histórico e não representam
o estado atual do teste Vulkan. Seus hashes e limites são específicos daqueles runs.

## Repetição solicitada — resultado final: FAIL

[Run 34776335305](https://github.com/Enzo-cyber2025/5/actions/runs/34776335305),
revisão `47fad43`, executado novamente em Android API 35 x86_64:

| Verificação | Resultado |
|---|---|
| Build e assinatura v2/v3 | PASS |
| Regressões de ferramentas / JVM | 66 / 33 PASS |
| Controle C++ original vs oficial | PASS: defeito reproduzido e correção confirmada |
| Instalação, abertura, SHA-256 do modelo no emulador | PASS |
| `vkCreateDevice` | `VK_SUCCESS` (0) |
| Camadas no Vulkan | **31/31**, `gpu_offload=1` |
| Texto de assistant persistido | Sim, 619 caracteres após o prompt exato |
| Conclusão nativa bem-sucedida | **FAIL: GGUF_REPAIR_GENERATION_FAILED** |
| Resultado integrado | **FAIL** |

A falha se reproduziu sem alterar o código de inferência ou os critérios. Os logs
não mostram o SIGSEGV dos testes anteriores, mas o retorno falso de geração ainda
impede aprovação. Texto salvo sozinho não equivale a conclusão nativa bem-sucedida.
Não foi um timeout do teste. A causa desse retorno falso continua por diagnosticar.

- [Resumo](../ci-results/34776335305-1/summary.json).
- [Log](../ci-results/34776335305-1/vulkan-final-logcat.txt).
- [Conversa](../ci-results/34776335305-1/vulkan-chats.json).
- [Controle ABI](../ci-results/34776335305-1/runtime-regression.json).
- SHA-256 do APK: `4c1f3aebfea4667a0baee55ef7356f71907a1579ad2f907e25301a95faebed58`.

Vulkan aqui é **software (llvmpipe)**. Não houve validação de GPU física, ARM64,
SAF ou visão. A qualidade não foi aprovada; a resposta segue excessivamente longa
para a saudação curta solicitada. Nenhuma nova entrega foi rotulada como aprovada.

## Estado: inicialização/offload confirmados; geração completa reprovada

A conexão GitHub voltou e o resultado do
[run 34774462755](https://github.com/Enzo-cyber2025/5/actions/runs/34774462755)
foi recuperado. Build/assinatura e testes host passaram. No Android API 35:

```text
GGUFVulkanCompat: Core 1.1 16-bit storage verified; omitted unadvertised KHR alias; vkCreateDevice=0
load_tensors: offloaded 31/31 layers to GPU
model loaded: n_ctx=1024 n_params=134515008 gpu_offload=1
GGUF_REPAIR_GENERATION_FAILED
```

O dispositivo foi criado e houve offload real, mas `Native.generate()` informou
falha. Há texto de assistant persistido, sem a confirmação nativa obrigatória.
Portanto o teste integrado continua **FAIL**, não aprovação Vulkan completa.
Não houve o crash anterior nesses logs. A causa do retorno falso ainda não foi isolada.
A resposta salva também não atende à saudação curta solicitada.

- [Resumo](../ci-results/34774462755-1/summary.json).
- [Log completo](../ci-results/34774462755-1/vulkan-final-logcat.txt).
- [Conversa persistida](../ci-results/34774462755-1/vulkan-chats.json).
- APK testado: `80c256ed2f0c66c38b6182f69ee71e8204c070d6e50e32f4ca8f7b65a3a01cca`.

A repetição acima foi disparada pelo push nesta mesma branch, pois a API recusou
rerun e workflow_dispatch. Nenhum critério de aprovação foi relaxado e nenhum
código de inferência foi alterado para essa repetição.

## 1. Runtime C++ incompatível — correção comprovada

O `libc++_shared.so` x86_64 original reservava quatro bytes para
`pthread_mutexattr_t`, mas Bionic LP64 usa oito. O construtor de
`std::recursive_mutex` sobrescrevia parte do registrador RBX salvo na pilha.
O construtor do dispositivo Vulkan usava esse registrador como ponteiro e sofria
SIGSEGV no construtor de `shared_mutex`.

Substituição: runtime oficial **Android NDK r28c / 28.2.13676358**, nas duas ABIs.
O teste de ABI foi executado em Android x86_64, não em aparelho ARM64:

| Controle | RBX observado | Saída |
|---|---|---|
| Biblioteca original | `11223344ffffffff` | 1: corrupção reproduzida |
| Runtime oficial | `1122334455667788` | 0: registrador preservado |

O probe chama o construtor real da biblioteca via assembly; não simula inferência.
Ele mantém o runtime mapeado, descarrega stdout e usa `_Exit` para isolar o teste
do comportamento de descarregamento/destrutores globais da biblioteca original.
Um SIGSEGV arbitrário não é aceito como controle negativo válido.

- [Resultado dos controles](../ci-results/34773992015-1/runtime-regression.json).
- [Proveniência e hashes por ABI](../ci-results/34773992015-1/runtime-provenance.json).
- [Execução 34773992015](https://github.com/Enzo-cyber2025/5/actions/runs/34773992015):
  build/assinatura e 64 testes de ferramentas + 33 JVM passaram. Android confirmou
  a correção do runtime, mas a inferência Vulkan falhou pelo segundo problema.

## 2. Extensão promovida ao Vulkan principal — criação/offload confirmados

Depois de corrigir o runtime, o backend chegou à criação do dispositivo:

```text
vk::PhysicalDevice::createDevice: ErrorExtensionNotPresent
```

O driver Android anuncia Vulkan 1.3 e suporte real a `storageBuffer16BitAccess`,
mas não anuncia o alias `VK_KHR_16bit_storage`. O backend exige esse nome de extensão,
embora seu recurso já tenha sido promovido ao Vulkan 1.1. Após a falha, uma tentativa
subsequente reutilizou estado incompleto e chamou `vkCreateFence` com dispositivo
nulo, encerrando o processo. Não foi contado como offload nem como geração.

A correção adiciona `libggufvk.so`, um adaptador pequeno que:

1. Usa exclusivamente o loader e o driver Vulkan reais do Android.
2. Verifica a versão **do dispositivo físico**, o recurso real e as extensões anunciadas.
3. Remove somente o nome `VK_KHR_16bit_storage` de `vkCreateDevice` quando a versão
   é pelo menos 1.1, o recurso existe e esse alias não é anunciado.
4. Preserva os bits de features, a cadeia `pNext`, filas, demais extensões e o
   resultado real do driver. Não inventa capacidades nem transforma erro em sucesso.

`patch_vulkan.py` altera somente **14 bytes de metadados ELF por ABI**: quatro nomes
de imports e o nome da dependência. Imports próprios evitam colisão com o loader do
sistema. Código executável, shaders/`.rodata`, `.data`, tamanhos e endereços do backend
permanecem intactos. O build rejeita mudanças diferentes desse patch exato.

Validação local: **66 testes de ferramentas passaram**, incluindo política de
compatibilidade e integridade das duas bibliotecas do APK original. O run 34774462755 confirmou criação do dispositivo e offload,
mas não conclusão nativa bem-sucedida da inferência.

## Critérios que continuam obrigatórios

- Backend Vulkan selecionado, offload real de mais de zero camadas no último carregamento.
- Conclusão nativa e assistant persistido depois do prompt exato.
- Mesmo processo: reinício após crash reprova, sem repetir silenciosamente.
- `Vulkan-ready`, disponibilidade de biblioteca ou fallback CPU não aprovam Vulkan.

## Ambiente e limites

Os testes recentes usam Android 15/API 35 x86_64 e llvmpipe/Mesa do emulador.
**É Vulkan por software, não aprovação de GPU física nem de celular ARM64.**
A exposição do dispositivo CPU número 0 é opt-in exclusivo do emulador.

Modelo: SmolLM2-135M-Instruct Q4_K_M, SHA-256
`2e8040ceae7815abe0dcb3540b9995eaa1fa0d2ca9e797d0a635ae4433c68c2d`.
Foi provisionado diretamente; não valida SAF. Os problemas anteriores de pertinência
e UTF-8 continuam sem correção comprovada. Visão e execução ARM64 também não foram aprovadas.

O APK local em `entrega/` **é anterior a estas correções Vulkan**. Não o confunda com
o artefato da execução mais recente. Ainda não há nova entrega Vulkan validada.

Histórico: o [run 34771124245](https://github.com/Enzo-cyber2025/5/actions/runs/34771124245)
usou API 30/SwiftShader, retornou backend NULL e gerou pela CPU. Suas evidências
permanecem em `ci-results/34771124245-1/`; aquele teste continua reprovado para Vulkan.
