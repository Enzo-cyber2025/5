// formatos.hpp — carregador universal de modelos.
//
// O jogo lê rede neural de onde ela vier:
//   .pt / .pth     PyTorch (zip + pickle + storages) — sem precisar do torch
//   .npz           NumPy
//   .safetensors   safetensors (cabeçalho JSON + dados crus)
//   .json          formato do próprio jogo
//
// Não há limite de tamanho nem de topologia: entra qualquer rede totalmente
// conectada. Só é recusado o que não for rede neural (ou não couber na memória).
#pragma once

#include <string>
#include <vector>

#include "policy.hpp"

namespace raceai {

struct Tensor {
    std::string nome;
    std::vector<long long> shape;
    std::vector<float> dados;          // sempre convertido para float
};

// Detecta o formato pelo conteúdo (não pela extensão) e lê os tensores.
bool ler_tensores(const std::string& caminho, std::vector<Tensor>& out,
                  std::string* err = nullptr);

// Monta um modelo a partir dos tensores, aceitando qualquer topologia.
// A rede é adaptada às entradas/saídas do jogo (24 sensores -> 2 controles):
//   · entrada com mais de 24: usa as 24 primeiras colunas
//   · entrada com menos de 24: completa com zero
//   · saída diferente de 2: pega as primeiras (ou completa com zero)
bool montar_modelo(const std::vector<Tensor>& tensores, Model& out,
                   std::string* err = nullptr);

// Atalho: arquivo -> modelo (qualquer formato da lista acima).
bool carregar_modelo_qualquer_formato(const std::string& caminho, Model& out,
                                      std::string* err = nullptr);

}  // namespace raceai
