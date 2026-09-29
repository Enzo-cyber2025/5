# Winlator otimizado para Galaxy A55 (Exynos 1480 / Xclipse 530)

Build baseada no Winlator 8.0.1-mod (brunovalads) com um patch que liga o
**Box64 dynarec persistente em disco** — o equivalente a "pré-traduzir" as
instruções x86 em blocos ARM64 que ficam reutilizáveis entre execuções: na
primeira abertura do jogo o Box64 traduz o que é preciso, nas próximas ele
carrega os blocos já traduzidos (menos trabalho em tempo real, FPS maior).

## O que foi ajustado para o A55

- `BOX64_DYNAREC_BIGBLOCK=3`, `SAFEFLAGS=1`, `STRONGMEM=2` (blocos maiores de ARM64)
- `BOX64_DYNAREC_PERSISTENT=1` com diretório em `/data/data/.../.cache/box64/`
- DXVK forçado por `WINEDLLOVERRIDES`, caches persistentes de shader DXVK/Mesa
- Tuning de afinidade para todos os cores (incluindo os A720 grandes do A55)
- Drivers Turnip+DXVK como padrão dos novos containers
- Mono/VCRun2019 continuam como na build oficial.

## Instalando seus arquivos do BeamNG

1. Instale o APK.
2. Extraia o .7z do seu BeamNG.drive no PC.
3. Copie a pasta com `BeamNG.drive.x64.exe` para `Download/BeamNG.drive/` no celular.
4. Abra Winlator-A55, crie um container (o padrão já vem com Turnip/DXVK) e adicione
   um atalho para o `.exe`.
5. A PRIMEIRA execução ainda traduz blocos frios e compila shaders (3-6 min); a
   SEGUNDA em diante usa o cache pré-traduzido e entra mais rápido, com FPS mais estável.

## FPS esperado

Em cenários simples, algo entre 5–14 FPS. Em cenários pesados com muitos carros,
espera 3–8. O Galaxy A55 tem GPU de entrada e o BeamNG é extremamente CPU-pesado;
mesmo com o pre-AOT ele vai ficar aquém de um PC. É o máximo que se consegue sem
código-fonte do jogo.

## Licença

Derivado de Winlator (MIT), Box64 (MIT), Wine (LGPL), DXVK (zlib), Mesa Turnip
(MIT). Nenhum arquivo da BeamNG GmbH é redistribuído aqui.
