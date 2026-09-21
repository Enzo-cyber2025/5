> Histórico da revisão `120e7dc` (SHA `409985de…`). A revisão atual tem registro único, olho e projetor Vulkan: [UNIFIED.md](UNIFIED.md).

# Vulkan no APK já entregue — execução real

**Execução de backend: PASS. Qualidade das respostas: resultado misto, não aprovação geral.**

- Teste Android: [34787006475](https://github.com/Enzo-cyber2025/5/actions/runs/34787006475).
- Evidência original: [`ci-results/34787006475-1`](../ci-results/34787006475-1/summary.json), incluindo logcat, conversas persistidas e capturas autênticas.
- APK **inalterado**, 16.741.431 bytes, SHA-256 `409985de54388cbcb1429a8db4cd26139cc47a5764864c6cd4b408c75f07099f`.
- Android 15 x86_64 em emulador, Mesa/Lavapipe no host. É execução da API Vulkan **por software**, não aceleração em GPU física, benchmark ou validação de ARM64.
- Arquivos GGUF reais, hashes conferidos antes e depois da transferência. Provisionamento direto no emulador descartável: este teste **não revalida a importação SAF**.

| Modelo | Camadas de linguagem em Vulkan | Gerações concluídas | PID durante carga e ambas as mensagens | Projetor |
|---|---|---|---|---|
| SmolVLM-256M-Instruct Q8_0 | 31/31 | 34 e 6 tokens, ambas `eog` | 4006, sem reinício | mmproj Q8_0 real, carregado pela mtmd na **CPU** |
| SmolLM2-135M-Instruct Q4_K_M | 31/31 | 128 tokens (`length`) e 61 (`eog`) | 5368, sem reinício | Não se aplica |

O teste exige offload positivo no último carregamento, conclusão nativa nova para cada prompt, resposta persistida para aquele prompt e PID inalterado. Disponibilidade do driver ou fallback para CPU não passam. Há reinícios intencionais na preparação de cada caso, antes da medição. Offload de todas as camadas não significa que toda operação auxiliar execute no Vulkan.

## Qualidade: olhar as respostas, não apenas o indicador verde

Prompts: `Reply in English with a short greeting.` e `Reply in English: What is two plus two?`.

- **SmolVLM:** começou com “Hello”, mas a saudação foi pouco pertinente. Para a conta respondeu corretamente **“Two + two = four.”**. O verificador original não aceitava essa grafia e registrou um falso negativo. Corrigimos apenas o conjunto de respostas aceitas, adicionamos regressões contra respostas erradas e reavaliamos os textos salvos: o teste básico agora passa. Isso não é avaliação ampla de qualidade. O `summary.json` original permanece intocado e mostra o resultado do verificador antigo.
- **SmolLM2:** saudação longa e inadequada (“Houston, …”), encerrada no limite de 128 tokens. Na conta confundiu soma com multiplicação/quadrado e não deu a resposta correta. **Qualidade básica reprovada.** A causa não foi isolada entre comportamento do modelo, formatação da conversa e caminho de inferência; não atribuímos a falha automaticamente ao Vulkan.

Não houve recompilação ou troca do APK para esses testes. Não houve avaliação de imagem: carregar o mmproj e gerar texto não prova reconhecimento de fotos, nem execução do projetor no Vulkan.

## Tentativas anteriores preservadas

- `34786476438`: parou no seletor SAF, antes de carregar modelo. Sem resultado do backend.
- `34786767435`: carregou 31/31 camadas, mas o cadastro de teste tinha somente o registro de linguagem, sem o registro separado de projetor exigido pela busca `ModelStore.byPath`. O teste recusou o resultado. Corrigida a preparação, não o APK.
- `34787006475`: completou os dois casos acima.

## Reavaliação local da qualidade, sem inventar nova execução Android

```bash
PYTHONPATH=scripts .venv/bin/python - <<'PY'
from pathlib import Path
from android_checks import basic_response_quality
p = Path('ci-results/34787006475-1')
for model in ('smolvlm', 'smollm2'):
    try:
        basic_response_quality(*[(p / f'{model}-{i}-reply.txt').read_text() for i in (1, 2)])
        print(model, 'PASS básico, somente textos já salvos')
    except AssertionError as e:
        print(model, 'FAIL', e)
PY
```

## Histórico de outra versão

O relatório extenso do APK anterior está preservado em [VULKAN-LEGACY.md](VULKAN-LEGACY.md). Seus hashes e resultados não validam o APK mobile atual.
