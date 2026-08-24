# 🚨 Estimador de Distância com IA e Alerta Sonoro — APK Android

**Dispositivo alvo:** Samsung Galaxy A55 (SM-A556E) · **ABI:** `arm64-v8a` · **Android mínimo:** 8.0 (API 26) · **Alvo:** Android 14 (API 34)

Aplicativo de visão computacional que estima **distância em tempo real** de objetos à frente da câmera usando o modelo **Depth Anything 3 Small** acelerado por **GPU (LiteRT — API `CompiledModel`, runtime ML Drift)**, transmitindo **as duas câmeras traseiras simultaneamente** via **Camera2** e emitindo um **alerta sonoro intermitente de alta frequência (SoundPool)** quando um objeto entra na **zona de perigo** configurada pelo usuário.

---

## 📦 Conteúdo deste repositório

| Arquivo | Descrição |
|---|---|
| `DA3-Distance-Alert-v1.0-arm64-v8a.apk` | Aplicativo **assinado** (release), pronto para instalar |
| `SHA256SUMS.txt` | Hash de integridade do APK |
| `README.md` | Este documento |

> Este repositório contém **apenas o APK assinado e sua documentação** — sem código-fonte, conforme a especificação da entrega.

---

## ⬇️ Instalação

1. Transfira o APK para o aparelho (ou rode `adb install DA3-Distance-Alert-v1.0-arm64-v8a.apk`).
2. Toque no arquivo no celular e autorize **instalar apps de fontes desconhecidas** quando o Android pedir.
3. Verifique a integridade, se quiser: `sha256sum -c SHA256SUMS.txt`.

## 🤖 Primeira execução — download único dos recursos de IA

Para manter o APK minúsculo (~90 KB) e o repositório leve, o app baixa **uma única vez**, na primeira execução, os recursos de IA diretamente dos servidores oficiais (sempre via HTTPS):

| Componente | Origem oficial | Tamanho aprox. |
|---|---|---|
| Runtime **LiteRT 2.1.6** (AAR: classes + libs nativas arm64-v8a) | `dl.google.com` (repositório Maven do Google) | ~15–30 MB |
| `kotlin-stdlib` (dependência do runtime LiteRT) | Maven Central | ~2 MB |
| Modelo **Depth Anything 3 Small — TFLite (fp32)** | **Qualcomm AI Hub** (artefato oficial `qai-hub-models`, S3) | ~27 MB |

Fluxo na tela: abra o app → toque em **BAIXAR RECURSOS DE IA** → aguarde a barra de progresso → pronto. Depois disso o app funciona **100 % offline**.

- O download é atômico (arquivos `.part` + renomeação) e com 3 tentativas automáticas por arquivo.
- Se o link do modelo estiver indisponível/mudou, há a opção **SELECIONAR MODELO .TFLITE** para importar um modelo DA3 convertido por você (a geometria de entrada é detectada automaticamente — suporta `[1,3,896,504]`, `[1,3,518,518]` e outras).
- Os arquivos ficam no armazenamento privado do app; desinstalar/remove tudo.

**Permissões:** `Câmera` (obrigatória, pedida ao tocar INICIAR) e `Internet` (usada apenas nesse download inicial).

---

## 🎮 Como usar

1. Toque em **INICIAR** e conceda a permissão de câmera.
2. O modelo é carregado na **GPU** (se o delegate falhar, o app avisa e usa CPU).
3. **Primeira vez: calibre.** Coloque um objeto a **exatamente 1,0 m** da câmera, centrado no retículo, e toque em **CALIBRAR 1,0 m**. (A profundidade monocular é *relativa*; a calibração converte para metros. Com a 2ª câmera + chave estéreo ligada, a escala métrica é refinada automaticamente por disparidade estéreo.)
4. Ajuste a **zona de perigo** no controle deslizante: **0,5 m a 5,0 m** (passos de 0,1 m).
5. Leitura em tempo real: distância do objeto no **centro do quadro** (região de interesse de 40 % do quadro), mapa de profundidade colorido no canto e FPS.
6. **Objeto dentro da zona de perigo** → moldura vermelha + flash na tela + **bipe intermitente agudo (3 kHz)** cujo ritmo acelera quanto mais perto o objeto estiver (SoundPool, `USAGE_ALARM`). Ao sair da zona (com pequena histerese anti-oscilação), o som **para imediatamente**.
7. **PARAR** encerra as câmeras e libera o modelo. O app também pausa sozinho ao sair da tela.

**Chave “Escala estéreo (2ª câmera)”:** usa os frames **pareados por timestamp do sensor** das duas câmeras traseiras; correspondência por blocos NCC na linha central + baseline físico/focal → distância métrica real de referência, que ancora a escala do modelo de IA. Mostra a âncora (ex.: `âncora: 2,31 m · 9 pts`) na barra inferior.

---

## 🏗️ Arquitetura (o que está dentro do APK)

| Bloco | Implementação |
|---|---|
| **Câmera dupla** | Camera2 API: 1º tenta câmera lógica multi-física; 2º abre **dois `CameraDevice` traseiros concorrentes** (validado contra `getConcurrentCameraIds`); 3º degrada p/ monocam. Sessões com `SessionConfiguration` (fallback p/ API < 30). Pareamento por **timestamp do sensor**. Resolução de captura 1280×720 @ 15–30 fps. |
| **Modelo de profundidade** | Depth Anything 3 Small (TFLite), entrada float32 NCHW com **normalização ImageNet** (mean/std 0.485/0.229 etc.), saída densa `[1,1,H,W]`. Pré-processamento YUV→RGB portrait + empacotamento NCHW em thread dedicada. |
| **Inferência GPU** | **LiteRT `CompiledModel`** (`create` com `Accelerator.GPU` → delegate ML Drift; `createInputBuffers`/`writeFloat`/`run`/`readFloat`). Fallback p/ CPU com aviso visível quando o delegate GPU não inicializa. Runtime carregado via `DexClassLoader` (arquivos marcados read-only, exigência do Android 14+). |
| **Distância** | Percentil 80 da região central (estatística robusta do objeto mais próximo) → `distância = escala / proximidade`, com mediana-de-3 + suavização EMA. Escala vinda da calibração 1-toque ou da âncora estéreo (EMA própria, com detecção automática da polaridade disparidade/profundidade via correlação). |
| **Alerta** | **SoundPool** (`maxStreams=6`, `USAGE_ALARM`): WAV de bipe de 120 ms/3 kHz (+2ª harmônica, fade in/out) **sintetizado em runtime**; duty-cycle de repetição proporcional à severidade; dispara/para na hora conforme a histerese. |
| **UI** | Preview `TextureView` + overlay (retículo/ROI + inset do mapa de profundidade com colormap *turbo*), leitor de distância grande, indicador PERIGO/SEGURO, flash vermelho 220 ms, SeekBar da zona de perigo, INICIAR/PARAR, CALIBRAR, chave estéreo, barra de status com FPS das câmeras/IA e Δ de sincronização. Tudo em código (sem resources). |
| **Estéreo (extra)** | NCC 9×9 em patches da faixa central, disparidade mediana → `z = f·B/d`; escala = mediana(z·proximidade); filtros: NCC ≥ 0,75 · ≤ 12 ms de dessincronia · ≥ 8 correspondências. |

### Mapa da especificação

| Requisito | Atendimento |
|---|---|
| Camera2 com as duas traseiras simultâneas | ✅ (com degradação elegante se o HAL barrar a 2ª) |
| Pareamento por timestamp do sensor | ✅ (Δ exibido na barra de status) |
| DA3-Small em TFLite/LiteRT, ImageNet norm | ✅ (modelo oficial Qualcomm AI Hub; geometria auto-detectada; também aceita 896×504 via importação) |
| GPU via `CompiledModel` (ML Drift), sem fallback silencioso | ✅ (CPU só com aviso explícito) |
| SoundPool agudo intermitente, parada imediata | ✅ |
| Zona de perigo 0,5–5,0 m via SeekBar | ✅ |
| UI: preview, distância, iniciar/parar, status de alerta, calibrar | ✅ tudo |

### Limitações honestas

- Profundidade **monocular é relativa**: sem calibração (ou estéreo) as distâncias não aparecem (`-- m`). Recalibre se trocar de modelo/ambiente.
- É um **alarme de proximidade**, não um instrumento de medição — tolerância típica de dezenas de centímetros em pouca luz/textura pobre.
- O binário do modelo é baixado do **artefato público oficial da Qualcomm AI Hub** (fp32 518×518). Se preferir exatamente `[1,3,896,504]`, importe um `.tflite` próprio pela opção avançada — o app se adapta automaticamente.
- Se o driver do aparelho não aceitar o delegate GPU (ML Drift), o app continua em CPU com aviso (mais lento).

## 🔐 Integridade e segurança

- APK **assinado em esquema v1 (JAR)** com chave de release própria (PKCS#12/RSA/SHA-256) — verificado com `java.util.jar` (modo estrito) e **androguard** (manifesto/permissões/activity) antes da publicação.
- Downloads do primeiro uso só por **HTTPS** de domínios oficiais (`dl.google.com`, `repo1.maven.org`, S3 da Qualcomm).
- Zero permissões de armazenamento/localização/rede em uso normal; nenhum dado sai do aparelho.

## 🛠️ Problemas comuns

| Sintoma | Solução |
|---|---|
| Download falha / HTTP 404 do modelo | Verifique a internet e toque **TENTAR NOVAMENTE**; em último caso, use **SELECIONAR MODELO .TFLITE** com um arquivo DA3 convertido |
| “GPU indisponível — usando CPU” | O driver não aceitou o delegate; o app funciona, porém mais lento |
| “2ª câmera indisponível” | O HAL do aparelho não liberou streaming concorrente; o app segue em monocam (estéreo desligado) |
| Distância mostra `-- m` | Falta calibrar (objeto a 1,0 m + botão CALIBRAR) ou aguardar a âncora estéreo |

## 📚 Créditos

- **Depth Anything 3** — model (tiktok/depth-anything), artefato TFLite via **Qualcomm AI Hub** (`quic/ai-hub-models`).
- **LiteRT (TensorFlow Lite)** — Google, Apache-2.0 · **Kotlin stdlib** — JetBrains, Apache-2.0.
- Colormap *turbo* — Google (Anton Mikhailov).
