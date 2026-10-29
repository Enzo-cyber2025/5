// ga.hpp — algoritmo genético: seleção, cruzamento, mutação e elitismo.
//
// Mesma receita do treinador Python (para manter a qualidade de convergência):
//   * elitismo mantém os melhores intactos (passam os pesos adiante);
//   * o melhor de todos os tempos nunca se perde;
//   * torneio escolhe os pais;
//   * cruzamento blend/uniforme mistura os pesos;
//   * mutação gaussiana **relativa à escala de cada camada** (ruído absoluto
//     destrói camadas com pesos pequenos);
//   * sigma adaptativo: encolhe por geração e dispara quando estagna.
#pragma once

#include <vector>

#include "base.hpp"
#include "policy.hpp"

namespace raceai {

struct GAConfig {
    int population = 120;
    double elitism = 0.10;          // fração preservada sem alteração
    int tournament = 3;
    std::string crossover = "blend";  // blend | uniform
    double crossover_rate = 0.90;
    double mutation_rate = 0.08;    // probabilidade por gene
    // quantos pesos são alterados por mutação. 0 (ou maior que o total) =
    // todos os genes passam pelo sorteio de `mutation_rate`; N = exatamente N
    // posições sorteadas são mutadas (ignorando a probabilidade).
    int genes_mutados = 0;
    double mutation_sigma = 0.25;
    double sigma_decay = 0.995;
    double sigma_min = 0.03;
    double fresh_blood = 0.04;      // fração de indivíduos novos por geração
    int stagnation_limit = 15;
    double reset_mutation_chance = 0.01;

    Json to_json() const;
    static GAConfig from_json(const Json& j);
};

struct GenHistory {
    int generation = 0;
    double best = 0.0, mean = 0.0, worst = 0.0, std = 0.0;
    double diversity = 0.0, sigma = 0.0, best_ever = 0.0;
    // métricas da simulação (pedidas na interface)
    double best_loss = 0.0, mean_loss = 0.0;
    double best_error_pct = 0.0, mean_error_pct = 0.0;
    double best_distance = 0.0, mean_distance = 0.0;
    double best_laps = 0.0, mean_speed = 0.0, best_speed = 0.0, crashes = 0.0;
};

class Population {
public:
    Population(const PolicySpec& spec, const GAConfig& cfg, uint32_t seed = 0);

    PolicySpec spec;
    GAConfig cfg;
    Rng rng;
    int generation = 0;
    std::vector<std::vector<float>> genomes;
    std::vector<double> fitness;
    std::vector<GenHistory> history;
    double best_fitness = -1e18;
    std::vector<float> best_genome;
    int best_generation = 0;
    int stagnation = 0;
    double sigma = 0.25;

    void random_population();
    void seed_from(const std::vector<float>& genome);   // ajuste fino de um modelo
    void resize(int n);
    void record(const std::vector<double>& fit);
    void evolve();

    int best_index() const;
    int n() const { return int(genomes.size()); }
    GenHistory last() const { return history.empty() ? GenHistory() : history.back(); }

    // núcleo usado pela evolução (exposto para testes)
    std::vector<float> mutate(const std::vector<float>& g, double boost = 1.0);
    std::vector<float> crossover(const std::vector<float>& a, const std::vector<float>& b);
    int tournament();

private:
    std::vector<std::pair<size_t, size_t>> slices_;
};

}  // namespace raceai
