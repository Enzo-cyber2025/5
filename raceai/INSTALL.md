# RaceAI 2D — executável Windows

## Instalação

1. Descompacte **toda a pasta** deste ZIP (o `.exe` precisa das DLLs que estão
   ao lado dele — não mova o `RaceAI2D.exe` sozinho).
2. Rode `RaceAI2D\RaceAI2D.exe`.

Requisitos: Windows 10/11 64-bit. Não é necessário instalar Python.

- Para GPU (Intel/AMD/NVIDIA via DirectX 12): nada a instalar — já vem com
  `torch-directml`. O jogo detecta e usa automaticamente (o HUD mostra o
  backend). Verifique com `RaceAI2D-console.exe --bench`.
- Se a GPU não for detectada, ele cai para CPU e continua funcionando.

## Primeiros passos

1. No menu, **3 · Treinar (gerações)** → tecle `F` algumas vezes para acelerar
   (8x/16x) e veja a população evoluir.
2. `G` liga/desliga a evolução. `ESC` volta ao menu.
3. **Modelo .pt** → *Salvar melhor (.pt)* para guardar o que evoluiu.
4. **1 · Dirigir (manual)** para pilotar você mesmo (setas/WASD).
5. **Modelo .pt** → *Carregar e dirigir* para ver o modelo pilotando.

## Problemas

- **Não abriu nada?** Rode `RaceAI2D-console.exe` (mostra os erros) e procure
  `raceai_erro.log` na pasta.
- **Lento?** Diminua a população em Configurações e use pistas curtas.
- **Quer treinar sem janela (mais rápido)?** O executável aceita
  `RaceAI2D-console.exe --headless-train 100 --pop 150 --track kartodromo`.

Pasta `mods\`: coloque JSONs de pistas e carros (veja `MODS.md`).
Pasta `modelos\`: onde os modelos são salvos.
