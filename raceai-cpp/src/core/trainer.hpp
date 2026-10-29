// trainer.hpp — evolução: população + simulação (com ou sem threads).
//
// É o mesmo objeto usado pela interface visual (um passo por frame) e pelo
// treinador de linha de comando (gerações inteiras o mais rápido possível).
#pragma once

#include <functional>
#include <memory>
#include <string>
#include <thread>
#include <vector>

#include "driver.hpp"
#include "ga.hpp"
#include "sim.hpp"

namespace raceai {

struct TrainerConfig {
    int threads = 0;        // 0 = automático (núcleos da máquina)
    uint32_t seed = 1;
};

// Um episódio (geração) completo de um agente — usado no relatório final.
struct EpisodeResult {
    int agent_id = 0;
    double fitness = 0.0;
    Metrics metrics;
    int crashes = 0;
    int laps = 0;
    std::string death_reason;
};

class Trainer {
public:
    Trainer(const Track& track, const CarSpec& car, const SimConfig& sim,
            const GAConfig& ga, const PolicySpec& policy, const TrainerConfig& tcfg = {});

    Track track;
    CarSpec car;
    SimConfig sim_cfg;
    RewardConfig reward;
    GAConfig ga_cfg;
    PolicySpec policy;
    TrainerConfig tcfg;
    Population pop;
    int threads = 1;

    std::vector<std::unique_ptr<Simulation>> shards;     // um por thread
    std::vector<double> fitness;                          // por indivíduo
    std::vector<Metrics> last_metrics;                    // por indivíduo
    std::vector<EpisodeResult> last_episodes;
    bool generations_enabled = true;
    int generation = 0;

    // ---------------------------------------------------------------- setup
    void build(int n_agents = -1);
    void set_track(const Track& t);
    void set_car(const CarSpec& c);
    void set_reward(const RewardConfig& r);
    void set_sim_cfg(const SimConfig& c);
    void set_population(int n);
    void reset_training();
    bool load_model(const std::string& path, std::string* err = nullptr);
    bool save_best(const std::string& path, std::string* err = nullptr) const;
    std::vector<float> best_weights() const;

    // ---------------------------------------------------------------- loop
    void start_episode();                 // reseta os carros (rotação do grid)
    void step(int n = 1);                 // alguns passos de física (interface)
    bool episode_done() const;
    GenHistory finish_episode(bool evolve = true);   // fecha + evolui
    void run_episode();                   // episódio inteiro (vários threads)
    void run(int generations, std::function<bool(const GenHistory&)> callback = nullptr);

    // driver externo substitui a rede (código Python do usuário, piloto manual)
    void set_driver(std::shared_ptr<Driver> d) { external_driver_ = d; }
    std::shared_ptr<Driver> driver() const { return external_driver_; }

    GenHistory last_history() const { return pop.last(); }
    const std::vector<GenHistory>& history() const { return pop.history; }

private:
    std::shared_ptr<Driver> external_driver_;
    void worker(int shard);
    void apply_reward();
};

}  // namespace raceai
