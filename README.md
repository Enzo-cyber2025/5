# FrameNova

Aplicativo nativo para **Windows x64** que cria quadros intermediários entre duas imagens ou em uma sequência de imagens. A interface é simples, em português, e o multiplicador é ajustável entre **2x, 3x e 4x**.

## Download direto

`https://github.com/Enzo-cyber2025/5/raw/arena/01a0698e-5/FrameNova.exe?download=1`

O repositório é privado, portanto a conta usada para baixar precisa ter acesso ao repositório. O link aponta diretamente para o executável publicado nesta branch.

O pacote distribuído contém somente `FrameNova.exe`, sem instalador e sem dependências adicionais. Ele é um binário x64 para Windows 10/11.

## Uso

1. Abra dois quadros consecutivos com **Abrir quadro A** e **Abrir quadro B**, ou escolha uma pasta contendo a sequência de imagens.
2. Escolha o multiplicador: 2x, 3x ou 4x.
3. Use **Gerar preview** para criar um quadro intermediário e depois salvá-lo, ou **Processar sequência** para gerar todos os intermediários.
4. Na sequência, os PNGs são gravados em `FrameNova_Output` dentro da pasta de entrada.

O modo **Rápido** e o **Modo econômico** reduzem a busca de movimento para máquinas com pouca RAM e gráficos integrados. O programa roda localmente e não envia imagens para a internet.

## Limitações importantes

FrameNova é um interpolador local de imagens/quadros. Ele **não injeta código em jogos**, não substitui o renderizador da GPU e não consegue garantir FPS constante em qualquer jogo ou hardware. Em especial, um Pentium N5030 com 4 GB e vídeo integrado pode levar tempo para processar imagens grandes; usar o modo econômico e resoluções menores reduz o custo.

Não é tecnicamente possível prometer “zero queda de FPS” sem controlar o motor do jogo, o driver e a carga do sistema. Este executável foi desenhado para ser leve e previsível, mas não é um substituto universal para tecnologias de frame generation em tempo real.
