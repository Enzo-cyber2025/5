// sim.hpp — simulação headless: frota, sensores, colisão, recompensa e métricas.
//
// É o mesmo núcleo usado pelo jogo (visual), pelo treinador de linha de comando
// e pelo modo de corrida: a física e a recompensa são únicas, então o que o
// usuário vê na tela é exatamente o que o treinador otimiza.
//
// Recompensa (fitness) e perda (loss) são duas faces da mesma moeda:
//   fitness = -loss  (+ bônus de conclusão)
// Todos os termos da loss são **taxas normalizadas em [0,1]** (fraçoão do tempo
// ou do percurso) — ver `Metrics` e os comentários em compute_metrics().
#pragma once

#include <string>
#include <vector>

#include "base.hpp"
#include "car.hpp"
#include "track.hpp"

namespace raceai {

// ------------------------------------------------------------------ config
struct SimConfig {
    double dt = 1.0 / 120.0;
    int decision_interval = 4;      // passos de física entre decisões (~30 Hz)
    int n_rays = 9;
    double ray_range = 70.0;
    double fov_deg = 140.0;
    double max_seconds = 60.0;
    int target_laps = 0;            // 0 = ilimitado (contra o relógio)
    double grass_grip = 0.62;
    double grass_roll = 4.0;
    double runoff = 3.5;            // faixa de escape antes do muro (m)
    double stall_seconds = 2.0;
    double wrong_way_seconds = 2.5;
    int max_crashes = 40;
    int spawn_rows = 0;             // 0 = automático
    bool checkpoint_gating = true;  // volta só vale se passar por todos os postos
    int sectors = 3;                 // setores por volta (HUD/telemetria)
};

// Pesos da recompensa — **cada campo vira um slider na interface**.
//   w_*_reward  : o quanto aquele aspecto vale (positivo)
//   w_*_penalty : o quanto aquele erro custa (negativo)
struct RewardConfig {
    double progress = 1.00;     // distância avançada (termo dominante)
    double speed = 0.60;        // velocidade média de avanço
    double precision = 0.30;    // ficar perto da linha de corrida
    double smooth = 0.15;       // dirigir sem esterço/freio bruscos
    double offtrack = 0.50;     // penalidade: tempo fora da pista
    double crash = 0.50;        // penalidade: batidas
    double wrongway = 0.80;     // penalidade: tempo contra-mão
    double idle = 0.50;         // penalidade: tempo parado / muito lento
    double finish_bonus = 30.0; // bônus por concluir as voltas
    double ref_speed_factor = 0.45;  // meta = ref_speed_factor * velocidade máx do carro

    Json to_json() const;
    static RewardConfig from_json(const Json& j);
};

// ------------------------------------------------------------------ agente
struct Agent {
    int agent_id = 0;           // posição na população (imune à compactação)
    CarState car;

    bool finished = false;
    int idx = 0;                // índice do ponto mais próximo na pista
    double s_prev = 0.0, s_total = 0.0, max_s = 0.0;
    int laps = 0;               // voltas válidas (com checkpoint gating)
    int raw_laps = 0;           // voltas pelo arco (sem gate)
    int lap_count = 0;
    double lap_start = 0.0, last_lap = 0.0, best_lap = 1e18;
    double time = 0.0;
    double offtrack_time = 0.0, wrong_way_time = 0.0, idle_time = 0.0, crash_time = 0.0;
    int crashes = 0;
    double crash_cd = 0.0;
    double stall_time = 0.0;
    std::string death_reason;
    double fitness = 0.0;
    double surface_grip = 1.0, surface_roll = 1.0;
    double draft = 0.0;             // 0..1: vácuo (aspiração) do carro da frente
    double lateral = 0.0;
    double last_steer = 0.0, last_drive = 0.0;

    // acumuladores das métricas (integrados por passo, nunca por "instante")
    double fwd_dist = 0.0;      // metros avançados (só progresso positivo)
    double speed_int = 0.0;     // ∫ v_tangencial dt
    double precision_int = 0.0; // ∫ (1 - |lat|/meia_largura) * ds
    double jerk_int = 0.0;      // ∫ |Δação| * ds  (por metro, não por segundo)

    // checkpoints em ordem (fecha o atalho "cortar o infield")
    int cp_next = 0, cp_passed = 0;

    // ---- setores, melhor volta e delta (HUD estilo telemetria) ----
    int setor = 0;                    // setor atual (0..setores-1)
    double setor_inicio = 0.0;        // tempo em que o setor atual começou
    std::vector<double> melhor_setor;      // melhor tempo de cada setor
    std::vector<double> parcial_volta;     // parciais da volta em andamento
    std::vector<double> melhor_parcial;    // parciais da melhor volta
    double delta = 0.0;               // +/- contra a própria melhor volta
    double ultimo_setor = 0.0;        // tempo do setor que acabou de fechar
};

// Métricas de um agente — tudo em [0,1] (exceto os campos em metros/segundos).
struct Metrics {
    double loss = 1.0;          // 0 = perfeito; menor é melhor
    double error_pct = 100.0;   // % do tempo em erro (fora, contra-mão, batido, parado)
    double offtrack_pct = 0.0, wrongway_pct = 0.0, idle_pct = 0.0, crash_pct = 0.0;
    double progress_score = 0.0;
    double speed_score = 0.0;
    double precision_score = 0.0;
    double smooth_score = 0.0;
    double crash_score = 0.0;
    double giveup_pct = 0.0;    // tempo que o agente abriu mão (morreu cedo)
    double mean_speed = 0.0;
    double distance = 0.0;
    double target_distance = 1.0;
    double ref_speed = 20.0;
};

// ------------------------------------------------------------------ sim
class Simulation {
public:
    Simulation(const Track& track, const CarSpec& car, const SimConfig& cfg,
               int n_agents, uint32_t seed = 0);

    const Track& track;
    SimConfig cfg;
    RewardConfig reward;
    std::vector<Agent> agents;
    std::vector<CarSpec> specs;
    Rng rng;
    int obs_dim = 24;
    int step_count = 0;
    int max_steps = 7200;
    int id_offset = 0;          // primeiro índice da população neste bloco

    int n() const { return int(agents.size()); }
    bool should_decide() const { return step_count % std::max(1, cfg.decision_interval) == 0; }
    bool all_dead() const { return active_.empty(); }
    const std::vector<int>& active() const { return active_; }

    void reset(int rotation = 0);
    void set_car(const CarSpec& car);                 // frota inteira
    void set_specs(const std::vector<CarSpec>& specs);  // um carro por linha

    void set_action(int agent_row, double steer, double drive);
    void step();

    // observação (tamanho obs_dim) para uma linha da frota
    void observe(int agent_row, float* out) const;

    Metrics metrics(int row) const;
    double fitness(int row) const;             // = -loss (+bônus de conclusão)
    void update_fitness();                     // recalcula o de todos

    // resumo da geração (HUD / treinador)
    struct Stats {
        int alive = 0;
        double best_fitness = 0.0, mean_fitness = 0.0;
        double best_loss = 0.0, mean_loss = 0.0;
        double mean_error_pct = 0.0, best_error_pct = 0.0;
        double distance = 0.0, best_distance = 0.0;
        double avg_speed = 0.0;
        double laps = 0.0, best_laps = 0.0;
        double crashes = 0.0;
    };
    Stats stats() const;
    int best_row() const;

private:
    std::vector<int> active_;
    void sync_track_state();
    void handle_walls();
    void kill(int row, const std::string& reason);
    double target_distance(const CarSpec& sp) const;
    double ref_speed(const CarSpec& sp) const;
};

}  // namespace raceai
