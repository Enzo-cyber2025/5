# ⏱️ Passo de 1 minuto (só o dono da conta consegue — o GitHub proíbe bots de criar arquivos em `.github/workflows/`)

> **Use o navegador do celular ou do PC** (o app do GitHub no celular não tem o botão de editar/renomear).

## Caminho A — renomear (mais fácil, nada de copiar)

1. Abra: **https://github.com/Enzo-cyber2025/5/blob/arena/01a073f1-5/GGUF-Studio-build-apk.yml.example**
2. Toque no **lápis ✏️** (canto superior direito, "Editar este arquivo")
3. No campo do **nome do arquivo**, apague o texto e digite: `.github/workflows/build-apk.yml`
4. Toque em **Commit changes…** → **Commit changes** (mantendo o branch `arena/01a073f1-5`)

Pronto. O build **dispara sozinho** e o agente publica os links diretos do APK.

## Caminho B — criar do zero (se o A falhar)

1. Abra o conteúdo em: **https://github.com/Enzo-cyber2025/5/raw/arena/01a073f1-5/GGUF-Studio-build-apk.yml.example**
   → selecione tudo → copie (ou use o botão "Raw" e copie).
2. Abra: **https://github.com/Enzo-cyber2025/5/new/arena/01a073f1-5/.github/workflows**
3. No campo do nome, digite `build-apk.yml`, cole o conteúdo copiado.
4. **Commit changes…** → **Commit changes**.

## Como saber que funcionou

Abra **https://github.com/Enzo-cyber2025/5/actions** → deve aparecer o workflow **"GGUF Studio APK"** rodando (~1–3 h). O agente acompanha e entrega o link de download da Release.
