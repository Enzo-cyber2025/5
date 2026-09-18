# Pequenos ganhos combinados: qualificar, não somar porcentagens

O usuário reiterou que qualquer ganho estável é válido. Batch2 (+1,40%) e QKV
(+0,49%) tiveram dois pares exploratórios positivos, mas isolados, ambos com
RGB Vulkan e sem prova da combinação. O APK entregue bd7c45d continua intacto.

## Experimento isolado

- Um único APK, mesmos GGUF, entrada integral, contexto, sampling e orçamento.
- Controle: processamento serial/separado, **RGB original na CPU**. Tratamento:
  batch2 + QKV, **o mesmo RGB original**. Não importar o antigo experimento RGB
  como suposto ganho nem multiplicar porcentagens de runners diferentes.
- Uma terceira autorização explícita `GGUF_PROJECTOR_COMBINATION=1` é exigida
  além das duas flags. Não habilitar a combinação no build/uso normal.
- Primeiro, em GPU, conferir bytes dos pesos e **todos** os embeddings combinados
  contra encodes individuais com projeções originais, no mesmo contexto. A
  política real de atenção AUTO deve coincidir também entre modos/processos.
- Qualquer diferença ou erro impede que os jobs de velocidade comecem.
- Depois, três pares AB/BA/AB aquecidos em quatro tarefas separadas: imagens
  ON, imagens OFF, texto ON/OFF com o mesmo modelo visual carregado e cache de
  imagens habilitado. Cache fica desligado nos dois lados dos testes do encoder.
- Sem mínimo antigo de 5%: qualquer ganho positivo **nos três pares ON**, tanto
  no encoder quanto Send→primeiro texto, é elegível. Outros testes não podem
  apresentar queda >3% por observação nem mediana negativa. Isso é consistência
  observada em poucas amostras, não garantia estatística ou para todo aparelho.
- Código/Copy, respostas completas, tokens, dimensões, bytes de upload e rotas
  estritas também precisam passar. Sono deve ser real, com aviso de conclusão.
- Reportar bytes extras de QKV, PSS e tempo de abertura do chat. PSS depois da
  geração não é pico nem memória total de GPU. Não esconder o custo de memória.

A inicialização QKV atual só aceita um subconjunto de Idefics3. Mesmo uma vitória
nos testes não autoriza habilitar a flag indiscriminadamente em todos os modelos:
a ativação segura por capacidade/arquitetura e as implicações de memória ainda
precisam ser tratadas antes de outra entrega. Não trocar o APK assinado atual ou
sua chave por causa deste experimento. A chave privada do certificado atual não
está disponível no ambiente restaurado; não gerar substituta silenciosamente.
