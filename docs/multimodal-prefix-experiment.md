# Evitar refazer o prefill de imagens já presentes no histórico

## Hipótese, ainda não ganho aprovado

O cache visual entregue evita repetir o encoder, mas `generate()` ainda limpa
TODO o KV quando recebe imagens. Assim, até uma continuação com as mesmas fotos
reavalia no modelo de linguagem os embeddings e textos anteriores. Este
experimento tenta preservar esse prefixo; não acelera por si só a geração de
cada token e não promete ganho em fotos novas.

## Isolamento e segurança

- Compilação exige `GGUF_EXPERIMENT_MEDIA_PREFIX=1`; CMake default OFF. O teste
  local remove os blocos condicionais e confere o SHA do corpo nativo anterior:
  o caminho normal continua idêntico ao de `3608876`.
- No APK experimental, o runtime ainda exige `GGUF_MEDIA_PREFIX=1`. Nunca
  habilitar via flag global em um APK de entrega sem qualificação.
- Primeiro recorte de suporte: Vulkan estrito, decoder causal `llama`, sem
  encoder/recorrência/híbrido, sem SWA declarado, sem M-RoPE, posições iguais ao
  número de tokens e sem blocos não causais. Os demais seguem o caminho original.
- Identidade do prefixo: tokens reais e SHA-256 dos pixels preparados + metadados
  e geometria completos, não nome/caminho do arquivo. Ordem e tamanho dos blocos
  também precisam coincidir. Metadados pertencem a um único Engine/modelo.
- Reusar apenas blocos completos. Reavaliar sempre o último bloco de TEXTO para
  obter logits atuais. Não mudar o batch/ubatch 128/32 nem dividir uma imagem.
- Verificar presença do KV desde posição zero até o fim do prompt anterior;
  remover o sufixo na API real. Sem suporte/prefixo/remoção bem-sucedida: limpar e
  avaliar normalmente na GPU selecionada, **não** fazer fallback de cálculo CPU.
- Erro/cancelamento limpa metadados. Alternar para texto também invalida o
  prefixo visual. Desativação/alteração/reordenação de fotos não herda embeddings
  de outra imagem. O cache de embeddings mantém a política de proteção dos itens
  usados na requisição, mesmo quando seus KV são reutilizados.
- Não duplica pesos ou buffers KV: mantém o contexto existente e pequenos
  descritores no host. Diagnóstico de referência, em separado, copia KV para
  comparar bytes; não confundir sua memória/custo com o caminho medido.
- QKV, batch2 e RGB Vulkan ficam desligados. O cache de embeddings já entregue
  permanece habilitado **nos dois braços**.

## Verificação antes de medir

O workflow `media-prefix.yml` compila um APK descartável, sem substituir a
entrega. Primeiro executa controle e tratamento com a mesma foto, continuação,
adição de outra foto, exclusão, restauração e edição do prompt de sistema.
Quando há reutilização, o diagnóstico copia o estado KV completo, refaz todo o
prefill original no mesmo backend e exige igualdade byte a byte do estado
serializado (K/V, posições e metadados). As respostas completas, tokens,
configurações e históricos também precisam coincidir entre modos.

Só então libera três jobs: imagens ON, imagens OFF e controle de texto ON/OFF.
Cada um usa três pares AB/BA/AB e warmup separado. Qualquer melhoria positiva
em todos os pares de continuação visual é válida. A geração de tokens, o
primeiro uso da imagem e os controles de texto não podem piorar mais de 3% por
observação nem ter mediana negativa. Sem leituras de KV de diagnóstico nessas
medições. Código/Copy, rodapé, sono real e aviso de conclusão continuam testados.

### Fim natural não é corte de orçamento

Na execução combinada anterior `35392374636`, o modelo visual respondeu ao
warmup de texto com 103 tokens e EOS, embora `nPredict=128`. A asserção de
exatamente 128 interrompeu esse controle **antes da comparação**; não é prova de
lentidão nem aprovação. O teste novo mantém `nPredict=128`, exige espaço para o
orçamento inteiro, motivo de término real (`eog` ou `length`), conteúdo e número
de tokens iguais entre modos. Texto com menos de 64 tokens não é aceito como
medição representativa. Não forçar tokens após EOS nem encurtar o limite.

## Limites de qualquer resultado

Até passar no Android/Vulkan não há ganho medido deste experimento. Mesmo uma
vitória fica `release_approved=false`: faltam comparação da configuração final
contra o APK efetivamente entregue, revisão de suporte, custo de memória e
continuidade de assinatura. A chave da entrega anterior está indisponível; não
criar substituta silenciosamente. Vulkan por software não certifica aparelhos
físicos. O teste de QKV+batch2 continua separado, sem misturar seus ganhos.
