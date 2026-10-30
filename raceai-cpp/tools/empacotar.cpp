// empacotar.cpp — grava pistas, carros, modelos e o Python dentro do .exe.
//
// Uso:  empacotar <arquivo.exe> <pasta1> [pasta2 ...]
//
// O conteúdo é anexado ao FINAL do executável (o Windows ignora o que vem
// depois da imagem PE) e o jogo o extrai na primeira vez — é isso que permite
// entregar UM arquivo só. A lógica mesmo está em src/app/conteudo.cpp.
#include <cstdio>
#include <string>
#include <vector>

#include "../src/app/conteudo.hpp"

int main(int argc, char** argv) {
    if (argc < 3) {
        std::printf("uso: empacotar <arquivo.exe> <pasta1> [pasta2 ...]\n");
        return 2;
    }
    std::vector<std::string> pastas;
    for (int i = 2; i < argc; ++i) pastas.push_back(argv[i]);
    std::string erro;
    if (!raceai::criar_pacote(argv[1], pastas, &erro)) {
        std::printf("empacotar: %s\n", erro.c_str());
        return 1;
    }
    std::printf("empacotar: conteudo gravado em %s\n", argv[1]);
    return 0;
}
