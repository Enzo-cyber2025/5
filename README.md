# Sound Transfer — Transferência de Arquivos por Som

Aplicativo que transfere arquivos usando **som** (FSK: **12.000 Hz = bit 0**, **15.000 Hz = bit 1**).
O arquivo volta sempre com o **mesmo nome e extensão** original (`.exe`, `.obj`, `.txt`, etc.) —
**nunca** vira um `.bin`.

## Downloads

| Plataforma | Arquivo | Link |
|---|---|---|
| Windows (10/11 64-bit) | `SoundTransfer-Windows.exe` | `https://github.com/Enzo-cyber2025/5/raw/v1.0.7/SoundTransfer-Windows.exe` |
| Android | `SoundTransfer-Android.apk` | `https://github.com/Enzo-cyber2025/5/raw/v1.0.7/SoundTransfer-Android.apk` |

> **v1.0.7:** **Android com as APIs de captura mais rápidas** — a recepção agora usa
> **amostras cruas em tempo real** (`ScriptProcessorNode`, com fallback `MediaRecorder`), o que
> elimina a reamostragem/atraso do gravador. O detector ficou **ciente da taxa de amostragem**
> (44,1 kHz e **48 kHz** — comum no Android), reamostrando para 44,1 kHz antes de decodificar.
> Isso permitiu **baixar o espaçamento**: novas velocidades **12 / 10 / 8 amostras por símbolo**
> (0,00046 / 0,00055 / 0,00069 MB/s) para som limpo / MP4.
> Isso permite símbolos mais curtos → **transferência mais rápida** (~3× mais que antes).
> O Windows foi corrigido para tocar o som **direto da memória** (sem arquivo temporário,
> eliminando a mensagem "Falha ao gravar o WAV temporário").

> **Nota importante sobre o `.apk`:** ele **instala e roda** o motor FSK completo, mas é um
> empacotador **WebView**. O template usa apenas `WebViewClient`/`shouldInterceptRequest` e
> **não inclui** os hooks nativos de `onShowFileChooser` (seletor de arquivos),
> `onPermissionRequest` (microfone) e `DownloadListener` (downloads). Por isso, dentro do APK
> os recursos dependentes do Android (escolher arquivo, gravar do microfone, salvar o resultado)
> podem não abrir. **A versão completa no Android é o app Web (PWA)** instalado pelo Chrome,
> onde tudo funciona. O código nativo para um APK 100% funcional está disponível sob demanda.

## Funcionalidades (motor, idênticas em todas as plataformas)
- **Enviar arquivo via som** — codifica o arquivo em tons (FSK) e toca no alto-falante.
- **Receber do microfone** — capta pelo microfone e decodifica de volta em um arquivo.
- **Exportar .mp4** — grava o sinal sonoro em um arquivo de mídia (MP4/WEBM).
- **Ler .mp4** — abre o arquivo exportado e restaura o arquivo original.
- **Velocidade de transferência ajustável** — seletor no app.
- **Preserva o tipo original** — `.obj` volta como `.obj`, `.exe` como `.exe`, etc.

## Como usar (Windows `.exe`)
1. Abra o `SoundTransfer-Windows.exe`.
2. **Enviar**: "Enviar arquivo via som" → escolha o arquivo → o app toca o som.
3. **Receber**: no outro aparelho, "Receber do microfone" → toque o som → "Parar recepção".
4. **Exportar .mp4** gera o arquivo; **Ler .mp4** restaura o original.

## Como usar (Android — PWA, funcional)
1. No Chrome do celular, abra o app Web (link do preview).
2. Menu ⋮ → **"Instalar aplicativo" / "Adicionar à tela inicial"**.
3. Use normalmente (microfone, escolher arquivo e downloads funcionam).

## Nota sobre a velocidade (valores reais)
FSK com **12.000 Hz / 15.000 Hz**: a taxa de bytes é `44100 / (8·N)` bytes/s, onde N é o
número de amostras por símbolo. Como a separação entre os tons é de 3 kHz, dá para usar
símbolos mais curtos (N menor) → mais rápido.

Velocidades no seletor (valores reais, passos menores; as últimas 3 são só para som limpo/MP4):
| Opção | Fator (amostras/símbolo) |
|---|---|
| 0,00011 MB/s | 48 — mais lenta e *mais confiável* no microfone |
| 0,00012 MB/s | 44 |
| 0,00014 MB/s | 40 |
| 0,00015 MB/s | 36 |
| 0,00017 MB/s | 32 |
| 0,00020 MB/s | 28 |
| 0,00023 MB/s | 24 |
| 0,00028 MB/s | 20 |
| 0,00034 MB/s | 16 — mais rápida confiável no ar |
| 0,00046 MB/s | 12 — extra rápida (só som limpo / MP4) |
| 0,00055 MB/s | 10 (só som limpo / MP4) |
| 0,00069 MB/s | 8 — ultra rápida (só som limpo / MP4) |

> **Limite físico:** o teto confiável por **ar** é 0,00034 MB/s (16 spp). As opções 0,00046–0,00069 MB/s exigem som limpo/MP4 (o teto por ar continua ~0,00034 MB/s).
> É fisicamente **impossível** chegar a **1 MB/s ou 1 GB/s** por áudio a 12–15 kHz — não existe
> software que contorne isso (é limitação do meio acústico, não do app). Por isso **não** foi
> adicionada uma opção "1 GB/s" que não transferiria de verdade. Para máxima confiabilidade, use
> a opção mais lenta e aproxime os aparelhos. **Dica extra:** 12–15 kHz é pouco audível / mais
> agudo — reduz o incômodo, mas exige aparelhos que reproduzam bem essas frequências (nem todo
> alto-falante pequeno toca 15 kHz).

## Build / origem
- **Windows**: compilado em C (Win32) com prefixador **Zig**, sem dependências externas.
- **Android**: app Web (HTML/JS) + `.apk` (WebView) assinado com **APK Signature v1+v2+v3**.
- O **código-fonte não acompanha** este repositório (conforme solicitado).
