# Sound Transfer — Transferência de Arquivos por Som

Aplicativo que transfere arquivos usando **som** (FSK: **12.000 Hz = bit 0**, **15.000 Hz = bit 1**).
O arquivo volta sempre com o **mesmo nome e extensão** original (`.exe`, `.obj`, `.txt`, etc.) —
**nunca** vira um `.bin`.

## Downloads

| Plataforma | Arquivo | Link |
|---|---|---|
| Windows (10/11 64-bit) | `SoundTransfer-Windows.exe` | `https://github.com/Enzo-cyber2025/5/raw/v1.0.5/SoundTransfer-Windows.exe` |
| Android | `SoundTransfer-Android.apk` | `https://github.com/Enzo-cyber2025/5/raw/v1.0.5/SoundTransfer-Android.apk` |

> **v1.0.5:** seletor de velocidade com **espaçamento reduzido** — agora são **9 opções**
> em passos menores (48→16 amostras/símbolo), em vez de 4 opções fixas. Mantém o FSK
> **12.000 Hz / 15.000 Hz** e o Windows tocando o som direto da memória (sem arquivo temporário).
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

Velocidades no seletor (valores reais, passos menores para maior controle):
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
| 0,00034 MB/s | 16 — mais rápida e *menos confiável* no ar |

> **Limite físico:** o teto real dessa técnica por **som** é **0,00034 MB/s** (16 amostras/símbolo).
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
