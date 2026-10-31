# Memória da sessão (atualizada em 2026-10-30 20:10)

Branch: `arena/5d450bd0-5`. Último commit: `31d91a9` (CI 41127078994 success).
Release: só `RaceAI2D.exe`, 25.501.452 bytes, exe estático verificado em
máquina limpa (PATH sem MinGW).

## CORREÇÃO CRÍTICA: DLL do MinGW

O usuário mandou um print com `RaceAI2D.exe - System Error: The code execution
cannot proceed because libgcc_s_seh-1.dll was not found`. Causa: o executável
era ligado dinamicamente às DLLs do compilador (libgcc_s_seh-1.dll,
libstdc++-6.dll, libwinpthread-1.dll), que não existem no PC dele — **o bug
também afetava o zip antigo**.

Correção: `STATIC := -static -static-libgcc -static-libstdc++` na regra do
`raceai.exe` no Makefile. O .exe passou de 22,8 MB para 25,5 MB.
Passo novo no CI lista as DLLs importadas e falha se aparecer
libgcc/libstdc++/libwinpthread.

**Sempre distribuir binário MinGW com ligação estática.**

O teste antigo (`make test` no shell msys2) NÃO provava nada: o MSYS2 tem
`/mingw64/bin` no PATH, então um .exe dinâmico rodaria lá mesmo assim. Teste
de verdade = passo **pwsh** que limpa o PATH (`mingw|msys|clang|gcc`), copia o
.exe para uma pasta vazia em $env:TEMP e roda com `Start-Process -PassThru`
conferindo `$p.ExitCode`. Resultado atual: `mingw_no_path=NAO exit=0`, e o
`objdump -p | grep "DLL Name"` só lista USER32/SHELL32/msvcrt/KERNEL32/GDI32/
comdlg32/COMCTL32.

**Como ler a saída do CI sem baixar o log** (host results-receiver bloqueado):
emita `Write-Host "::notice ::..."` e leia com
`gh api repos/Enzo-cyber2025/5/check-runs/<id>/annotations`.
O `<id>` vem de `gh api repos/.../commits/<sha>/check-runs`.

`gh release create` só roda na 1ª vez: para atualizar as notas em todo build é
preciso `gh release edit exe-cpp-windows --notes $notas` depois do upload.

## Como ler imagem enviada pelo usuário (sem visão)

O tool não mostra a imagem, mas dá para fazer OCR:
```
cp /tmp/arena-coding-uploads/image-N.png /home/user/5/.arena_uploads/
pip install --break-system-packages rapidocr-onnxruntime
pip install --break-system-packages --force-reinstall opencv-python-headless
convert image.png -resize 300% -colorspace Gray -sharpen 0x1 grande.png
python3 -c "from rapidocr_onnxruntime import RapidOCR; print(RapidOCR()('grande.png')[0])"
```
(rapidocr precisa do opencv-headless: o normal exige libGL.so.1, ausente.)

## Entrega: UM arquivo só

- Release `exe-cpp-windows` agora tem **um único asset**: `RaceAI2D.exe`
  (22.806.065 B). URL: https://github.com/Enzo-cyber2025/5/releases/download/exe-cpp-windows/RaceAI2D.exe
- O zip antigo (`RaceAI2D-C++-windows.zip`) foi removido da release pelo próprio
  workflow (`gh release delete-asset ... -y`).
- `raceai_train.exe` **não é mais distribuído** (continua sendo compilado para os
  testes de CI). O mesmo `RaceAI2D.exe` treina no terminal quando recebe
  argumentos.

## Como o "um .exe" funciona

- `tools/empacotar.cpp` (wrapper fino) → `raceai::criar_pacote()` em
  `src/app/conteudo.cpp`: anexa `assets/`, `modelos/` e `python/` ao FIM do .exe
  + trailer de 24 bytes (`RACEAIPAKEND` + u64 tamanho). Windows ignora dados
  depois da imagem PE.
- `src/app/conteudo.cpp` → `extrair_pacote()` / `garantir_conteudo()`: lê o
  trailer, extrai só o que não existe (nunca sobrescreve mod) para
  `%LOCALAPPDATA%\RaceAI2D` (fallback `USERPROFILE\AppData\Local`).
- Modo portátil: se existir `assets/` ao lado do .exe, usa ele e não extrai nada.
- `assets.cpp`: `definir_raiz_dados()` faz `assets_root()` e `list_models()`
  preferirem a pasta de dados.
- Makefile: `$(BIN)/empacotar` é pré-requisito de `raceai.exe`; a regra compila
  com `-DRACEAI_SEM_MAIN` (tira o `main` do train_cli) e roda o empacotador
  depois de linkar. `APP` inclui `src/app/conteudo.cpp`.
- `tools/train_cli.cpp`: `main` → `raceai::rodar_cli()` (declarado em
  `src/core/cli.hpp`); `#ifndef RACEAI_SEM_MAIN` mantém o executável CLI.
- `WinMain`: se `__argc > 1` → `AttachConsole(ATTACH_PARENT_PROCESS)` +
  `freopen("CONOUT$")` → `rodar_cli(__argc, __argv)`.
- Shim Win32 (`tests/winshim/windows.h`): adicionados `AttachConsole`,
  `ATTACH_PARENT_PROCESS`, `GetEnvironmentVariableW`, `CreateDirectoryW` e
  `#define __argc/__argv` para o `make check-win` continuar valendo.

## Estado dos testes (local, Linux)

`raceai_tests` 2017/0 · `raceai_tests_app` 179/0 · `raceai_integrado` 121/0
(era 125 antes; o número varia conforme os modelos/seções disponíveis) ·
`make check-win` ok. Rodar ASan: `g++ -fsanitize=address -Isrc tests/test_app.cpp
src/core/*.cpp src/app/app_state.cpp` (já limpo).

## Armadilhas desta sessão

- **O repo local volta para o commit base sozinho** (HEAD = `cdf1151`, tudo
  untracked). Consertar com:
  `git fetch origin arena/5d450bd0-5 && git reset --mixed origin/arena/5d450bd0-5`
  (o trabalho em disco fica intacto), conferir `git status --short | grep '^D'`
  e só então `git add -A raceai-cpp .github/workflows/raceai-cpp-windows.yml`.
- `unsigned char(x)` é inválido como cast funcional → usar
  `static_cast<unsigned char>(x)`.
- `std::vector<unsigned char> v(size_t(n));` = most vexing parse → declarar
  `const size_t n = ...` antes.
- `criar_dirs_()` precisa criar o ÚLTIMO componente depois do loop.
- `le_trailer`: o limite certo é `tam_pacote + 24 > tam_total` (com `-32` um
  .exe pequeno era rejeitado).
- `raceai::rodar_cli` precisa ser definido dentro de `namespace raceai {}`.
- O Makefile novo: a regra do empacotar precisa compilar
  `tools/empacotar.cpp src/app/conteudo.cpp -Isrc` (senão link quebra).
- Não há mais zig no sandbox: não dá para compilar para Windows localmente;
  a validação é o CI + `make check-win`.

## Interface: fim do pisca-pisca + cara nova (2026-10-30)

- **Causa do pisca**: `WM_PAINT` desenhava direto no HDC da janela e o
  `WM_TIMER` chamava `InvalidateRect(hwnd, nullptr)` a cada ~15 ms → cada
  quadro aparecia sendo "riscado" na tela. Só devolver 1 no `WM_ERASEBKGND`
  não resolve.
- **Consertado com 4 coisas** (todas em `src/app/main.cpp`):
  1. **duplo-buffer**: `WM_PAINT` desenha num bitmap e dá um único `BitBlt`.
     O bitmap é **cacheado** (`g_mem_dc/g_mem_bmp`) e só recriado quando o
     tamanho muda — alocar um bitmap do tamanho da tela 60×/s pesa muito no
     Pentium N5030. Liberado no `WM_DESTROY`.
  2. `WM_TIMER` invalida **só a área da pista** (`x >= kPainelW + 2`), o
     painel inteiro parou de repintar.
  3. `atualiza_textos()` só chama `SetWindowTextW` quando o texto **mudou**
     de verdade (cache em `g_txt_metricas/g_txt_corrida`).
  4. `WS_CLIPCHILDREN` na janela: nada pinta por cima dos controles.
- **Cara nova**: paleta única (`kCorPainel/kCorFundo/kCorDestaque/...`),
  botões `BS_OWNERDRAW` desenhados como pílula (`desenha_botao`, com estado
  pressionado/desabilitado), fontes com `CLEARTYPE_QUALITY` (`criar_fonte`),
  `WM_CTLCOLORSTATIC/EDIT/BTN/LISTBOX` para os controles nativos ficarem
  escuros, HUD dentro de um cartão arredondado com títulos `--- x ---` em
  verde, grade discreta no fundo da pista e faixa do título na cor de
  destaque (`g_hwnd_titulo` + `g_pincel_titulo`).
- **Ordem obrigatória no `WM_DRAWITEM`**: os `if` das chaves
  (`ID_CHAVE_MODO`, `ID_CHAVE_TIPO_IA`, `ID_CHAVE_3D`) vêm **antes** do ramo
  genérico `di->CtlType == ODT_BUTTON`. Se o genérico vier primeiro, as
  chaves são desenhadas como botão comum e deixam de ser chave.

## Listas de pista/carro vazias + gerador por digitação (2026-10-30)

- **Bug grave (e a causa do "escolher pista está vazio")**: `g_app` é um
  **global**, então `AppState()` roda antes do `WinMain`. Ele chamava
  `list_tracks()`/`list_cars()` quando a pasta de dados ainda não era
  conhecida (`definir_raiz_dados()` só acontece depois de extrair o pacote
  embutido) → as listas nasciam vazias e os combos ficavam em branco.
  Consertado com `AppState::reler_ativos()`, chamada em `rodar()` logo
  depois de `definir_raiz_dados()` (e reaproveitada por `recarregar_mods()`).
- **Segundo bug**: em `WM_COMMAND` existia um `if (HIWORD(wp) ==
  CBN_SELCHANGE) { ... return 0; }` genérico, que engolia a seleção de
  pista/carro (os `if (id == ID_PISTA ...)` abaixo nunca rodavam). Escolher
  pista/carro não fazia nada. O bloco foi removido.
- **Gerador de IA agora é tudo digitado**: `camadas` e `ativação` são caixas
  de texto (helper `cria_edit`, `ativacao_digitada()` aceita maiúscula,
  espaço e apelidos). Os menus suspensos `ID_GER_ATIV`/`ID_GER_FORMATO`
  saíram. `EN_CHANGE` atualiza o resumo enquanto o usuário digita.
- **Combos escuros**: `combo()` agora usa `CBS_OWNERDRAWFIXED` e
  `desenha_combo()` desenha a caixa e os itens (precisa de `WM_MEASUREITEM`
  com `itemHeight`, senão as linhas ficam com altura 0).
- **Guarda no CI**: o job `verificar` (windows-2022, máquina limpa) agora
  roda `RaceAI2D.exe --conteudo`; o flag imprime `conteudo: pistas=N
  carros=N` e sai com 1 se vier 0. Assim "lista vazia" nunca mais passa.

## Slider e caixas de marcação próprios (2026-10-30)

- O **trackbar do Windows não dá para redesenhar por dentro** (sempre fica
  cinza claro, destoando do painel escuro). Troquei por um controle próprio:
  classe `RaceAISlider` (`SliderProc`), registrada em `rodar()` antes da
  janela principal. Mensagens próprias `kSlSetPos/kSlGetPos/kSlSetRange`
  (WM_USER+1..3) no lugar de `TBM_SETPOS/TBM_GETPOS/TBM_SETRANGE`.
- O slider avisa o pai com `WM_HSCROLL` e `wp=1` enquanto o usuário arrasta:
  o pai atualiza o valor, mas **só salva em disco quando o arrasto termina**
  (`wp=0`), senão gravaria o JSON a cada pixel.
- Caixas de marcação (ABS, tração, colisões, boxe) viraram `BS_AUTOCHECKBOX |
  BS_OWNERDRAW` + `desenha_check()`. No `WM_DRAWITEM`, o ramo `ODT_BUTTON`
  olha `GetWindowLongPtrW(GWL_STYLE) & (BS_CHECKBOX | BS_3STATE)` para
  decidir entre `desenha_check` e `desenha_botao`.
- Shim: `HANDLE`, `LONG_PTR`, `GetWindowLongPtrW/SetWindowLongPtrW`,
  `SetCapture/ReleaseCapture/SetFocus/GetParent`, `Ellipse`,
  `WM_NCDESTROY/WM_LBUTTON*/WM_MOUSEMOVE/WM_CAPTURECHANGED`, `ODS_CHECKED`,
  `GWL_STYLE/GWLP_USERDATA`, `BS_CHECKBOX/BS_3STATE`, `GET_X_LPARAM`.

## Três temas trocáveis dentro do app (2026-10-30)

- O usuário disse que "tudo" estava horrível e eu não vejo a tela. Em vez de
  chutar, o app agora tem **3 temas** e um botão `tema: <nome>` no topo do
  painel que cicla entre eles (ID_TEMA → `aplicar_tema(g_tema_idx + 1)`),
  com a escolha salva em `<pasta de dados>\tema.txt`.
- Tema 0 "escuro" (verde-água), 1 "claro" (cara de app comum, texto escuro),
  2 "azul" (azul-marinho com destaque azul claro).
- **Regra**: nenhuma cor de interface fica mais fixa no código. Todas vêm da
  `struct Tema` (painel, fundo, texto, destaque, botão, edit, cartão do HUD,
  grade, asfalto, borda da pista, divisor, slider, minimapa...). As cores do
  **cenário 3D** (céu, grama) e as cores dos carros continuam fixas: são o
  mundo, não a interface.
- `aplicar_tema()` recria os 4 pincéis (`g_pincel_painel/edit/titulo/
  destaque`) e chama `RedrawWindow(..., RDW_ALLCHILDREN|RDW_INVALIDATE|
  RDW_UPDATENOW)` — sem o ALLCHILDREN os controles ficam com a cor antiga.
- Armadilha: `std::wofstream(caminho_largo)` não compila no Linux (só no
  MinGW/MSVC) → use `std::ofstream(narrow(caminho))`. E `salvar_tema()`
  precisou de declaração adianta porque fica depois de `narrow()`.
- Shim: `HRGN`, `RedrawWindow`, `RDW_INVALIDATE/RDW_UPDATENOW/RDW_ALLCHILDREN`.

## Layout: controles sobrepostos e fora da tela (2026-10-30)

- **Bug 1 (sobrepostos de verdade)**: vários botões tinham `x + largura`
  maior que o painel (420 px) e ficavam desenhados **em cima da pista**:
  `ID_SALVAR_PY` ia até 614 px, `ID_MENU` até 438, `ID_RECARR_MODS` até 438.
  Agora uma auditoria automática confere todos: x + w ≤ 420.
- **Bug 2 (metade da tela inalcançável)**: o conteúdo do treino tem ~1360 px
  e a janela cabe ~700 → recompensa, penalidades, Python e métricas ficavam
  fora da janela, sem volta. Resolvido com **rolagem do painel**:
  `g_rolagem` + `g_pos_painel` (posição original de cada controle via
  `EnumChildWindows`) + `SetWindowPos` em `aplicar_rolagem()`.
  - A roda do mouse rola o painel quando o cursor está em cima dele
    (`x < kPainelW`) e dá zoom na câmera quando está sobre a pista.
  - A altura do conteúdo é medida **só dos controles visíveis** (cada modo
    tem a sua), e `mostra_tela()` chama `recalcular_rolagem()`.
  - Barra de rolagem desenhada à mão no WM_PAINT (só aparece se não couber).
- **Agrupamento**: moldura arredondada em volta de cada seção (`g_cartoes`,
  calculada pelos y dos títulos em `g_secoes_y`), só no modo treino.
- Shim: `EnumChildWindows`, `ScreenToClient`, `GetWindowRect`,
  `IsWindowVisible`, `SetWindowPos`, `SWP_*`, `GetStockObject`, `NULL_BRUSH`,
  `WM_SIZE`, `WHEEL_DELTA`.
