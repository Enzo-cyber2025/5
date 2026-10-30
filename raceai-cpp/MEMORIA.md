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
