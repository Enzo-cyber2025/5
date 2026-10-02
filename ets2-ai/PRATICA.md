# Fazer a IA PRATICAR no ETS2 (telemetria real)

Este é o caminho do **treino/aprendizado no jogo de verdade**: a IA lê a
telemetria do ETS2, **aprende a estrada dirigindo com você**, depois dirige
sozinha — e cada correção sua vira dado de treino (DAgger). Sem captura de
tela, sem mexer no jogo: só o plugin oficial de telemetria da SCS + teclas.

```
   ETS2 ──(DLL RenCloud)──> memoria Local\SCSTelemetry ──> ets2ai.practice
                                                        │
     mapa da pista aprendida (practice/mapa.json) <──────┤ gravar/refinar
                                                        │
   teclado <──(SendInput, volante PWM)───────────────────┴── rede 290×13
```

## 0) Requisitos (uma vez só)

1. **ETS2 original 64-bit** (Steam) no Windows.
2. **Plugin de telemetria RenCloud** (scs-sdk-plugin, V.1.12+):
   - Baixe o `scs-telemetry.dll` (x64) em
     <https://github.com/RenCloud/scs-sdk-plugin/releases>;
   - Copie para `Documentos\Euro Truck Simulator 2\bin\win_x64\plugins\`
     (crie a pasta `plugins` se não existir);
   - Abra o ETS2 e confira em `Documentos\Euro Truck Simulator 2\game.log.txt`
     a linha `telemetry plugin` — sem erro.
3. **Python + bridge**: no PC do jogo, com o repo (ou o `ETS2-AI-bridge.exe`
   do release — os modos de prática já estão embutidos):
   ```
   cd ets2-ai
   python -m ets2ai.practice record
   ```

> Como funciona por dentro: `ets2ai/telemetry.py` lê os 32 KB de
> `Local\SCSTelemetry` (layout oficial do plugin, offsets travados por
> testes). O SDK **não** dá offset na faixa nem curvatura à frente — por isso
> o `ets2ai/roadmap.py` **aprende a estrada** com as passadas que você dirige
> (linha central + curvaturas a 8/18/40/90/170 m, os mesmos 5 olhares da rede).
> A conversão de eixos do jogo é **calibrada automaticamente** na primeira
> dirigida com curvas (detecção de espelhamento).

## 1) `record` — você dirige, a IA aprende a estrada (1ª sessão, ~5 min)

```
python -m ets2ai.practice record            # ou: ETS2-AI-bridge.exe --ets2 record
```

- Dirija um trecho **com curvas** no começo (calibra os eixos do mundo).
- Na **1ª passada** o mapa é construído; da **2ª passada** em diante tudo
  vira dado de treino (gravado em `practice/record-<data>.csv`).
- Quanto mais passadas, mais refinada a linha central (média das passadas).
- Ctrl+C encerra e salva `practice/mapa.json` (o "cérebro da estrada").

## 2) `shadow` — a IA observa e dá o veredito (segurança primeiro)

```
python -m ets2ai.practice shadow
```

Você dirige; a IA só calcula o que faria. No HUD aparece a **concordância**
entre a IA e você:

- `sinais OK (concordancia 8x%)` → pode ir para o modo drive;
- `ESPELHADO` → rode `record` de novo em trechos com curvas (a calibração
  vai corrigir) antes de deixar a IA dirigir.

## 3) `drive` — a IA dirige de verdade

```
python -m ets2ai.practice drive --inject --window "Euro Truck"
```

- **ESC = kill switch** (solta todas as teclas na hora).
- Teclas usadas: setas (volante em PWM proporcional, aceleração, freio) —
  binds padrão do ETS2.
- Seguranças embutidas: sem telemetria/menu → solta as teclas; estrada sem
  mapa → limita a ~30 km/h; curva à frente → freia antes (governador ESC);
  fim da rota → para na linha da entrega; nunca para no meio da estrada
  (anti-stall).
- **Você é o professor**: encoste no teclado a qualquer momento — a IA
  detecta, solta o volante e grava sua correção como dado prioritário
  (DAgger). Quando você solta, ela volta a dirigir.

## 4) `finetune` — a sessão vira aprendizado (o "praticar" de verdade)

```
python -m ets2ai.finetune --recordings practice/record-*.csv practice/drive-*.csv
```

- Se o relatório aprovar (MSE ≤ 0,150 e circuito fechado ≥ 75%), promova:
  ```
  cp artifacts-finetuned/model-weights.json artifacts/model-weights.json
  ```
- Os pesos promovidos valem para **TUDO**: o `.exe` do bridge, o APK
  (recarregando os pesos no app) e o modo drive da próxima sessão.

## 5) Repita

Cada ciclo record → drive → finetune deixa a IA melhor **na sua estrada, no
seu caminhão, no seu estilo**. O mapa cresce sozinho conforme você dirige
rotas novas (a IA estende o mapa onde ele não existe).

## Perguntas frequentes

- **Funciona em qualquer mapa/mod?** Sim — nada é extraído dos arquivos do
  jogo; a estrada é aprendida dirigindo.
- **Dá para treinar só no Kaggle?** Não. O ETS2 é um jogo Windows pago, sem
  interface programática de input/telemetria na nuvem. O Kaggle treina a rede
  base (1B de amostras do simulador); a prática no jogo adapta a base à
  realidade (é mais rápida exatamente por isso: minutos de correções valem
  mais que milhares de km dirigidos).
- **Perde algo em relação ao simulador?** Os radares: o SDK não expõe a
  posição das câmeras — a rede recebe "sem radar à frente" e respeita o
  limite da via (feature real `speed_limit` da telemetria).
- **Desempenho no N5030/4 GB?** Loop de 20 Hz, numpy puro, um forward de
  1M parâmetros por tick (~1 ms) — provado pelo `--bench` do bridge.
- **A IA dirige mal no início da estrada nova** — normal: sem mapa não há
  offset/curvatura; ela anda devagar (30 km/h) até você gravar uma passada.
