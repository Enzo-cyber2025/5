// cli.hpp — o treinador de linha de comando também mora dentro do jogo.
//
// O RaceAI2D.exe é UM arquivo só: sem argumentos abre a janela; com
// argumentos (ex.: -g 50 -p 60) roda o treino no terminal, igual ao
// raceai_train.exe.
#pragma once

namespace raceai {

// devolve o código de saída (0 = ok)
int rodar_cli(int argc, char** argv);

}  // namespace raceai
