// policy.hpp — política (rede neural) e genoma para evolução.
//
// Topologia padrão: MLP  obs -> [64, 64] -> 2  com tanh.
// Saída: [esterço, acelerador] em [-1, 1] (acelerador negativo = freio).
//
// O genoma é o vetor de pesos achatado (float); mutação e crossover operam
// nele. A inferência é feita em C++ puro (sem dependências), o que permite
// avaliar populações inteiras em paralelo na CPU.
#pragma once

#include <string>
#include <vector>

#include "base.hpp"

namespace raceai {

struct PolicySpec {
    int obs_dim = 24;
    std::vector<int> hidden = {64, 64};
    int act_dim = 2;
    // ativação das camadas escondidas: tanh | relu | sigmoid | leaky
    // (a saída é sempre tanh, porque está em [-1, 1] de propósito)
    std::string activation = "tanh";

    std::vector<int> dims() const;
    std::vector<size_t> shapes() const;   // tamanho de cada bloco (W e b)
    size_t n_params() const;
    Json to_json() const;
    static PolicySpec from_json(const Json& j);
};

// Aplica a ativação escolhida (usada pela inferência e pelos testes).
inline float ativar(const std::string& nome, float v) {
    if (nome == "relu") return v > 0.0f ? v : 0.0f;
    if (nome == "leaky") return v > 0.0f ? v : 0.05f * v;
    if (nome == "sigmoid") return 1.0f / (1.0f + std::exp(-v));
    return std::tanh(v);                      // tanh é o padrão
}

// Inicialização Xavier uniforme — saída pequena para não sair derrapando.
std::vector<float> init_genome(const PolicySpec& spec, Rng& rng, double scale = 0.9);

// Inferência de um indivíduo: obs (obs_dim) -> ação (act_dim).
void forward(const PolicySpec& spec, const float* w, const float* obs, float* out);

// ------------------------------------------------------------------ modelo
struct Model {
    PolicySpec spec;
    std::vector<float> weights;
    Json meta = Json::object();

    bool save(const std::string& path, std::string* err = nullptr) const;
    static bool load(const std::string& path, Model& out, std::string* err = nullptr);
};

}  // namespace raceai
