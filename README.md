# MegaCode

Envio de arquivos por **código visual** (formato próprio, de alta densidade),
lido pela **câmera do celular**. Suporta **qualquer tipo de arquivo**.

## Binários

| Arquivo | Plataforma |
|---------|-----------|
| [`dist/MegaCode.apk`](dist/MegaCode.apk) | Android (câmera + gerador) |
| [`dist/MegaCode.exe`](dist/MegaCode.exe) | Windows |

> Apenas os **binários compilados** são publicados neste repositório.
> O código-fonte não é distribuído.

## Uso rápido

- **Android:** instale o `MegaCode.apk` e conceda a permissão de câmera.
- **Windows:** dê dois cliques em `MegaCode.exe` (abre o app no navegador).
- **Transmitir:** escolha o arquivo; a tela exibe a sequência de quadros.
- **Receber:** aponte a câmera para a tela até completar.

## Capacidade

Um único símbolo visível pela câmera não comporta 1 GB (limite físico da
câmera). Arquivos grandes são enviados como **sequência animada de quadros**,
com correção de erro e retomada por quadro. Arquivos pequenos (até ~1–3 MB)
usam o modo de imagem única.

Instruções completas em [`LEIA-ME.txt`](LEIA-ME.txt).
