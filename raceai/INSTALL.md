# RaceAI 2D — executável Windows

## Download

**Release `exe-windows`:** https://github.com/Enzo-cyber2025/5/releases/tag/exe-windows
→ baixe `RaceAI2D-windows.zip`, descompacte **a pasta inteira** e rode
`RaceAI2D\RaceAI2D.exe`.

## Instalação

1. Descompacte **toda a pasta** deste ZIP (o `.exe` precisa das DLLs que estão
   ao lado dele — não mova o `RaceAI2D.exe` sozinho).
2. Rode `RaceAI2D\RaceAI2D.exe`.

Dois executáveis vêm no pacote:

| arquivo | para que serve |
| --- | --- |
| `RaceAI2D.exe` | o jogo (abre a janela; o console dele fica escondido) |
| `RaceAI2D-console.exe` | o mesmo jogo com console visível — use para ver erros, `--bench`, `--selftest` e treino headless |

Requisitos: Windows 10/11 64-bit. Não é necessário instalar Python.

- Para GPU (Intel/AMD/NVIDIA via DirectX 12): nada a instalar — já vem com
  `torch-directml`. O jogo detecta e usa automaticamente (o HUD mostra o
  backend). Verifique com `RaceAI2D-console.exe --bench`.
- Se a GPU não for detectada, ele cai para CPU e continua funcionando.
- O teste da GPU roda num processo separado (para um driver problemático não
  derrubar o jogo). O resultado fica em `.dml_status.json`, ao lado do `.exe`.
  Em Configurações há um botão **Retestar GPU** para refazer o teste.
- Para desligar a GPU de vez: crie a variável de ambiente `RACEAI_NO_DML=1`.

## Primeiros passos

1. **1 · CORRIDA** — monte um grid com vários carros e modelos (tecla `M`) e
   corra contra eles. `C` troca a câmera, `R` recomeça.
2. **2 · TREINAMENTO** — defina **indivíduos** e **épocas**, aperte
   *INICIAR TREINO* e espere: no fim o jogo salva o `.pt` e pergunta se você
   quer **testar na corrida**.
3. `F` acelera a simulação (até 32x) e `G` liga/desliga a evolução.
   `ESC` volta ao menu.
4. **3 · Dirigir (manual)** para pilotar você mesmo (setas/WASD) e
   **4 · Assistir IA** para ver um modelo pilotando.
5. Tela **Modelo .pt** → *Salvar melhor (.pt)* guarda o que evoluiu;
   *Carregar* coloca qualquer `.pt`/`.npz` no carro ou no grid da corrida.

## Problemas

- **Não abriu nada?** Rode `RaceAI2D-console.exe` (mostra os erros) e procure
  `raceai_erro.log` na pasta. Se quiser ver a saída do `RaceAI2D.exe` mesmo
  assim: `set RACEAI_DIAG_LOG=diag.log` antes de abrir, num terminal.
- **Apareceu uma janela preta por um instante?** É o console do jogo; ele se
  esconde sozinho quando foi aberto com duplo clique.
- **Mods/modelos não aparecem?** Se o jogo estiver em *Arquivos de Programas*,
  os arquivos ficam em `%LOCALAPPDATA%\RaceAI2D` (mods, modelos e config).
- **Lento?** Diminua a população em Configurações e use pistas curtas.
- **Quer treinar sem janela (mais rápido)?** O executável aceita
  `RaceAI2D-console.exe --headless-train 100 --pop 150 --track kartodromo`.

Pasta `mods\`: coloque JSONs de pistas e carros (veja `MODS.md`).
Pasta `modelos\`: onde os modelos são salvos.
