# Execução Vulkan — 13/09/2026

## Resultado: REPROVADO — fallback CPU confirmado

O teste real foi executado exigindo Vulkan, mas **não houve geração via Vulkan**.
A biblioteca falhou na inicialização; o motor registrou CPU e carregou o modelo com
`gpu_offload=0`. A resposta terminou e foi salva, porém pela CPU.

[Execução 34771124245](https://github.com/Enzo-cyber2025/5/actions/runs/34771124245),
revisão `e075cb0`; evidências publicadas na mesma branch em `1d427f7`.

| Verificação | Resultado |
|---|---|
| Build, assinatura e regressões host | PASS: 46 ferramentas + 33 JVM |
| Instalar e abrir no Android | PASS |
| Preparar modelo real e conferir SHA-256 no emulador | PASS |
| Solicitar 99 camadas GPU | Executado |
| Inicializar backend Vulkan | **FAIL: retornou NULL** |
| Offload Vulkan positivo | **FAIL: CPU selecionada, gpu_offload=0** |
| Concluir geração nativa e persistir assistant após o prompt | PASS, em CPU |
| Resultado global do teste Vulkan | **FAIL**, sem aceitar fallback como sucesso |

## Ambiente e parâmetros

- Android 11/API 30, Google APIs, x86_64, perfil Pixel 5, 4 GB de RAM.
- Emulador configurado com `-gpu swiftshader -feature Vulkan`.
- **SwiftShader é Vulkan por software, não uma GPU física.** Mesmo que o backend
  tivesse funcionado, isso não comprovaria aceleração em hardware nem suporte no celular.
- SmolLM2-135M-Instruct Q4_K_M, contexto 1024, 2 threads, 128 tokens, temperatura 0.
- Modelo preparado diretamente: este teste não valida importação SAF.
- SHA-256 do modelo: `2e8040ceae7815abe0dcb3540b9995eaa1fa0d2ca9e797d0a635ae4433c68c2d`.
- SHA-256 do APK CI executado: `0a82302f6286b21ba9082f0e73ffb9858fb2dd97632a256fea6f088e1b4e8ead`.
  É um build CI com chave descartável, não o binário local em `entrega/`.

## Evidência decisiva

Trechos do log do processo do aplicativo, PID 5687:

```text
libggml-vulkan.so backend init returned NULL (unsupported device?)
registered CPU backend (best score 1)
engine loaded: libllama.so (Vulkan-ready)
model loaded: n_ctx=1024 n_params=134515008 gpu_offload=0
GGUF_REPAIR_GENERATION_OK
```

A expressão `Vulkan-ready` **não prova uso do backend**. As linhas anteriores e o
`gpu_offload=0` demonstram fallback. O teste exige backend Vulkan inicializado,
camadas efetivamente offloaded > 0 e geração nativa concluída com resposta persistida.
Os logs de preload agora são preservados para não perder a seleção do backend.

- [Resumo do teste](../ci-results/34771124245-1/summary.json).
- [Backend](../ci-results/34771124245-1/vulkan-backend.txt) e [log do processo](../ci-results/34771124245-1/vulkan-final-logcat.txt).
- [Diagnóstico Vulkan do Android](../ci-results/34771124245-1/vulkan-device.json), [features](../ci-results/34771124245-1/vulkan-features.txt) e [propriedades gráficas](../ci-results/34771124245-1/graphics-properties.txt).
- [Resposta salva](../ci-results/34771124245-1/vulkan-reply.txt) e [conversas](../ci-results/34771124245-1/vulkan-chats.json).

O Android anuncia features Vulkan, mas o diagnóstico devolveu `devices: [{}]`, sem
propriedades úteis do dispositivo. Isso não identifica qual recurso ou extensão fez
o backend falhar. A causa exata da inicialização NULL ainda não foi isolada; não é
possível concluir, a partir deste emulador, que todo aparelho será incompatível.

## Limites e próximo passo

A resposta novamente foi uma carta sobre Houston, não a saudação curta solicitada.
O modo Vulkan não avalia qualidade: os problemas de pertinência/UTF-8 descritos em
[GERACAO.md](GERACAO.md) permanecem, assim como os limites de SAF, visão e ARM64 físico.

Para obter aprovação Vulkan, ainda é necessário diagnosticar a compatibilidade entre
biblioteca e driver e repetir a inferência com offload positivo. Para aprovar aceleração
real, será necessário executar em dispositivo/runner com GPU física compatível.
Nenhuma biblioteca Vulkan foi alterada nesta etapa e nenhum APK foi declarado aprovado.

O workflow agora usa Vulkan obrigatório por padrão nesta branch. Na execução manual,
marque `run_android=true`; `android_mode=vulkan` exige offload, enquanto `android_mode=cpu`
executa o teste CPU com as duas respostas e sua verificação básica de pertinência.
Não houve novo teste Android em modo CPU desde a adição desse verificador.
