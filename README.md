# FrameNova

Aplicativo nativo para **Windows x64** que cria quadros intermediários entre duas imagens, em uma sequência de imagens ou a partir da captura ao vivo do monitor. A interface é simples, em português, e o multiplicador é ajustável entre **2x, 3x e 4x**.

## Download direto

[Baixar FrameNova.exe](https://github.com/Enzo-cyber2025/5/raw/arena/01a0698e-5/FrameNova.exe?download=1)

O repositório é privado, portanto a conta usada para baixar precisa ter acesso ao repositório. O pacote distribuído contém somente `FrameNova.exe`, sem instalador e sem dependências adicionais.

## Modos

- **Dois quadros:** abra A e B, escolha o multiplicador e gere um preview.
- **Sequência:** selecione uma pasta com imagens numeradas. Os PNGs intermediários são gravados em `FrameNova_Output`.
- **Capturar tela ao vivo:** usa a API nativa **DXGI Desktop Duplication** para copiar o monitor e exibir, nesta janela, o ponto intermediário entre os quadros capturados.

Para o Pentium N5030 com 4 GB, use **Rápido + Modo econômico** e, se possível, capture em uma resolução menor. O caminho ao vivo limita a imagem capturada a 960 px de largura no modo econômico e a 1280 px no modo normal, evitando criar uma fila de processamento escondida.

## Limitações importantes

Este é um interpolador local com uma captura ao vivo de demonstração. Ele **não injeta código em jogos**, não intercepta o swap chain do processo, não substitui o renderizador da GPU e não funciona como um driver de frame generation. O resultado da captura aparece na janela do FrameNova; ele não é desenhado por cima do jogo nem transforma automaticamente 30 FPS do jogo em 60 FPS na tela.

Toda captura e interpolação adiciona trabalho de CPU, cópia de memória e latência. Portanto, não é tecnicamente possível prometer “zero queda de FPS” em qualquer jogo, especialmente em um Pentium N5030 com vídeo integrado. A API de captura reduz a necessidade de integração por jogo, mas não elimina o custo do processamento.

Também não seria honesto chamar o motor de uma rede neural treinada do zero: uma IA nova com pesos realmente treinados exige dataset, treinamento, métricas e validação reproduzíveis. Para manter este binário pequeno, offline e funcional, ele usa um algoritmo original de busca de movimento em blocos e síntese adaptativa, sem modelo externo ou telemetria.
