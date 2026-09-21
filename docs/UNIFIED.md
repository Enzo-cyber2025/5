# Modelo único: GGUF + mmproj, olho e Vulkan

## APK desta revisão

- [Download direto, somente APK](https://github.com/Enzo-cyber2025/5/releases/download/gguf-unified-72d4429/GGUF-Chat-mobile.apk).
- Fonte: `72d4429fceb22f15353a5fddd634d1a9ac8bf0bf`; [compilação 34787804515](https://github.com/Enzo-cyber2025/5/actions/runs/34787804515).
- **16.745.526 bytes**, Android 9+, ARM64 e x86_64.
- SHA-256: `ab30020d22076701d68db939c8c1a33ca10e50e6f7f598ae1e7a9d59665ecc03`.
- Mesmo certificado fixo da revisão mobile anterior: `68f248a224075d66df9ff97ba336556b0a84b724112e644c28e607612da633f5`.
- Pode atualizar a revisão `gguf-mobile-120e7dc` sem exigir desinstalação por troca de assinatura. A versão antiga `gguf-apk-f6dc954` usa outra chave; exporte dados antes de desinstalá-la.

## O que significa unificado

A seleção conjunta de **um GGUF de linguagem e seu mmproj compatível** agora salva **uma única entrada em `models.json`**, com um ID, caminho de linguagem, caminho de projetor, tamanho total e sinalizador multimodal. Não apenas oculta um segundo registro.

Os dois componentes continuam como arquivos GGUF válidos no armazenamento privado do app. É uma unidade lógica gerenciada pelo aplicativo, **não um novo arquivo GGUF obtido concatenando bytes**, nem treinamento/fusão dos pesos das duas redes. Os arquivos originais selecionados não são alterados. Pesos não vêm embutidos no APK.

- **Olho:** deriva da união persistida com o mmproj, na biblioteca e no seletor de conversa; não de palavras como “vision” no nome.
- **Sem olho:** GGUF importado sozinho, mesmo quando metadados sugerem arquitetura multimodal.
- **Tamanho:** soma dos componentes. O par SmolVLM usado no teste ocupa **278.824.384 bytes**.
- **Carregamento:** a conversa lê os dois caminhos da mesma entrada; não precisa procurar um segundo modelo nem adivinhar outro projetor pelo nome. Um único handle nativo possui os dois contextos.
- **Exclusão:** remove a entrada e ambos os arquivos privados, preservando componentes ainda referenciados por outras unidades.
- **Migração:** pares antigos são normalizados para uma entrada, sem mover os arquivos ou alterar caminhos das conversas. A lógica de migração tem teste Java com doubles explícitos; não houve teste de atualização Android completo entre as duas versões.
- **Reimportação:** produz uma nova unidade independente, sem trocar o projetor de uma unidade anterior.

## GPU dos dois componentes

Novas configurações usam 99 camadas solicitadas em Vulkan; preferências explícitas já salvas são respeitadas. O GGUF seleciona `Vulkan0`, e o projetor usa o mesmo backend Vulkan, em vez de ficar fixo na CPU. CPU continua disponível como escolha explícita (`0` camadas).

Falha de GPU **não aciona fallback automático para CPU**. A interface só informa Vulkan depois de confirmar camadas realmente offloaded e, para uma unidade multimodal, concluir o carregamento do projetor nesse backend. Erros de capacidade, memória ou compatibilidade continuam sendo erros.

Carregar pesos no Vulkan não significa que toda operação auxiliar execute nele: o scheduler pode usar CPU para operações não suportadas. Também não significa que uma imagem já foi processada.

## Teste Android real — PASS

[Execução 34788194324](https://github.com/Enzo-cyber2025/5/actions/runs/34788194324) · [resumo original](../ci-results/34788194324-1/summary.json).

Desta vez houve **seleção múltipla pelo SAF real**, sem provisionamento direto do banco de modelos:

1. Importação do SmolVLM-256M Q8_0 + mmproj Q8_0; hashes dos arquivos copiados conferidos.
2. Exatamente **um registro**, tamanho somado e olho; preservação após reinício.
3. Linguagem: **31/31 camadas em Vulkan**.
4. Projetor: **198 tensores, 103.756.800 bytes de buffer no Vulkan0**.
5. Duas gerações de texto concluídas e persistidas, 34 e 6 tokens, mesmo PID **4851** durante carga e geração.
6. Barra compacta preservada, inicialmente fechada, uma linha, intervalos de 10 px.
7. Reimportação preservando a unidade anterior.
8. SmolLM2-135M importado sozinho, sem olho e sem projetor associado.
9. Exclusão pela interface removendo os dois componentes da unidade escolhida e preservando os outros modelos.

Registros nativos:

```text
load_tensors: offloaded 31/31 layers to GPU
clip_ctx: CLIP using Vulkan0 backend
GGUF_PROJECTOR_WEIGHTS backend=Vulkan0 bytes=103756800 tensors=198
GGUF_UNIT_LOADED language=Vulkan layers=31 projector=Vulkan
GGUF_NATIVE_COMPLETE tokens=34 reason=eog projector=1
GGUF_NATIVE_COMPLETE tokens=6 reason=eog projector=1
```

A verificação básica dos textos passou; a conta recebeu “Two + two = four.”. A saudação continua pouco pertinente, portanto não afirmamos qualidade geral aprovada. O SmolLM2 foi usado nesta execução para testar importação normal/ausência de olho, não para gerar texto.

Compilação: 102 testes de ferramentas/política/lógica Java passaram na CI, incluindo a classe real `Pairing.java` com doubles de Android/store. Após assinatura, 33 testes DEX→JVM passaram, incluindo recusa do fallback automático de GPU. Esses testes não substituem inferência Android.

## Limites

O ambiente é **Android 15 x86_64 + Mesa/Lavapipe: Vulkan por software**, não GPU física nem benchmark de aceleração. ARM64 foi compilado, não executado nesta validação.

O teste demonstra importação, armazenamento unificado, carregamento de ambos os componentes no Vulkan e geração de texto. **Não foi implementada/validada avaliação de anexos de imagem pelo mtmd. O olho identifica a unidade com projetor, não promete reconhecimento de fotos já funcional.**

[Captura autêntica: unidade com olho e modelo normal sem olho](../ci-results/34788194324-1/unified-after-delete.png).
