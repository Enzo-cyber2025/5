#include "trainer.hpp"

#include <algorithm>
#include <cmath>

namespace raceai {

Trainer::Trainer(const Track& t, const CarSpec& c, const SimConfig& sim, const GAConfig& g,
                 const PolicySpec& pol, const TrainerConfig& tc)
    : track(t), car(c), sim_cfg(sim), ga_cfg(g), policy(pol), tcfg(tc),
      pop(pol, g, tc.seed) {
    threads = tcfg.threads > 0 ? tcfg.threads
                               : std::max(1, int(std::thread::hardware_concurrency()));
    build();
}

void Trainer::build(int n_agents) {
    const int n = n_agents > 0 ? n_agents : ga_cfg.population;
    ga_cfg.population = n;
    if (pop.n() != n) pop.resize(n);
    threads = std::max(1, std::min(threads, n));
    shards.clear();
    fitness.assign(n, 0.0);
    last_metrics.assign(n, Metrics());
    // divide a população em blocos (um por thread); cada bloco é uma simulação
    const int base = n / threads;
    int extra = n % threads;
    int start = 0;
    for (int t = 0; t < threads; ++t) {
        int count = base + (extra > 0 ? 1 : 0);
        if (extra > 0) --extra;
        if (count <= 0) continue;
        auto sim = std::make_unique<Simulation>(track, car, sim_cfg, count,
                                                uint32_t(tcfg.seed + 7919u * size_t(t + 1)));
        sim->id_offset = start;          // reset() numera os agentes a partir daqui
        sim->reset(0);
        shards.push_back(std::move(sim));
        start += count;
    }
    apply_reward();
}

void Trainer::apply_reward() {
    for (auto& s : shards) s->reward = reward;
}

void Trainer::set_reward(const RewardConfig& r) {
    reward = r;
    apply_reward();
}

void Trainer::set_track(const Track& t) {
    track = t;
    shards.clear();          // a simulação guarda referência da pista: reconstrói
    build();
}

void Trainer::set_car(const CarSpec& c) {
    car = c;
    for (auto& s : shards) s->set_car(c);
}

void Trainer::set_sim_cfg(const SimConfig& c) {
    sim_cfg = c;
    for (auto& s : shards) {
        s->cfg = c;
        s->max_steps = int(c.max_seconds / c.dt);
    }
}

void Trainer::set_population(int n) {
    n = std::max(2, n);
    ga_cfg.population = n;
    pop.resize(n);
    build(n);
}

void Trainer::reset_training() {
    pop.random_population();
    generation = 0;
    build();
    start_episode();
}

bool Trainer::load_model(const std::string& path, std::string* err) {
    Model m;
    if (!Model::load(path, m, err)) return false;
    if (m.spec.obs_dim != policy.obs_dim) {
        if (err) {
            char buf[160];
            std::snprintf(buf, sizeof(buf),
                          "modelo esperava %d sensores, a configuração usa %d",
                          m.spec.obs_dim, policy.obs_dim);
            *err = buf;
        }
        return false;
    }
    policy = m.spec;
    pop.spec = m.spec;
    pop.seed_from(m.weights);
    generation = 0;
    start_episode();
    return true;
}

std::vector<float> Trainer::best_weights() const {
    return pop.best_genome.empty() ? pop.genomes[pop.best_index()] : pop.best_genome;
}

bool Trainer::save_best(const std::string& path, std::string* err) const {
    Model m;
    m.spec = policy;
    m.weights = best_weights();
    Json meta = Json::object();
    meta.set("track", Json(track.name));
    meta.set("car", Json(car.name));
    meta.set("generation", Json(double(pop.generation)));
    meta.set("fitness", Json(double(pop.best_fitness)));
    meta.set("population", Json(double(ga_cfg.population)));
    meta.set("obs_dim", Json(double(policy.obs_dim)));
    GenHistory h = pop.last();
    meta.set("best_loss", Json(h.best_loss));
    meta.set("best_error_pct", Json(h.best_error_pct));
    meta.set("best_distance", Json(h.best_distance));
    m.meta = meta;
    return m.save(path, err);
}

// ---------------------------------------------------------------- episódio
void Trainer::start_episode() {
    for (auto& s : shards) s->reset(pop.generation);
    apply_reward();
}

void Trainer::worker(int shard) {
    Simulation& sim = *shards[shard];
    const int dim = policy.obs_dim;
    std::vector<float> obs(size_t(std::max(1, dim)));
    float act[2] = {0.0f, 0.0f};
    const bool use_driver = external_driver_ != nullptr;
    while (!sim.all_dead() && sim.step_count < sim.max_steps) {
        if (sim.should_decide()) {
            for (int row : sim.active()) {
                sim.observe(row, obs.data());
                const int id = sim.agents[row].agent_id;
                if (use_driver && id == 0) {
                    external_driver_->act(obs.data(), dim, act);
                } else if (id < int(pop.genomes.size())) {
                    forward(policy, pop.genomes[id].data(), obs.data(), act);
                } else {
                    act[0] = 0.0f; act[1] = 0.0f;
                }
                sim.set_action(row, act[0], act[1]);
            }
        }
        sim.step();
    }
    sim.update_fitness();
    for (int row = 0; row < sim.n(); ++row) {
        const int id = sim.agents[row].agent_id;
        if (id < 0 || id >= int(fitness.size())) continue;
        fitness[id] = sim.agents[row].fitness;
        last_metrics[id] = sim.metrics(row);
    }
}

void Trainer::step(int n) {
    // modo interface: um (ou poucos) passos por frame, sem threads
    for (auto& s : shards) {
        const int dim = policy.obs_dim;
        std::vector<float> obs(size_t(std::max(1, dim)));
        float act[2] = {0.0f, 0.0f};
        for (int k = 0; k < n; ++k) {
            if (s->should_decide()) {
                for (int row : s->active()) {
                    s->observe(row, obs.data());
                    int id = s->agents[row].agent_id;
                    if (external_driver_ && id == 0) external_driver_->act(obs.data(), dim, act);
                    else if (id < int(pop.genomes.size()))
                        forward(policy, pop.genomes[id].data(), obs.data(), act);
                    s->set_action(row, act[0], act[1]);
                }
            }
            s->step();
        }
    }
}

bool Trainer::episode_done() const {
    for (const auto& s : shards) {
        if (!s->all_dead() && s->step_count < s->max_steps) return false;
    }
    return true;
}

GenHistory Trainer::finish_episode(bool evolve) {
    // coleta o resultado de todos os blocos (com ou sem threads)
    std::vector<EpisodeResult> episodes(fitness.size());
    for (auto& s : shards) {
        s->update_fitness();
        for (int row = 0; row < s->n(); ++row) {
            const int id = s->agents[row].agent_id;
            if (id < 0 || id >= int(fitness.size())) continue;
            fitness[id] = s->agents[row].fitness;
            last_metrics[id] = s->metrics(row);
            EpisodeResult er;
            er.agent_id = id;
            er.fitness = s->agents[row].fitness;
            er.metrics = last_metrics[id];
            er.crashes = s->agents[row].crashes;
            er.laps = s->agents[row].laps;
            er.death_reason = s->agents[row].death_reason;
            episodes[id] = er;
        }
    }
    last_episodes = episodes;

    // estatísticas da geração (junta todos os blocos)
    Simulation::Stats acc;
    double best_f = -1e18, mean_f = 0.0, best_l = 1e18, mean_l = 0.0;
    double best_e = 1e18, mean_e = 0.0, best_d = 0.0, mean_d = 0.0, best_laps = 0.0;
    double sum_v = 0.0, sum_c = 0.0;
    int alive = 0, n = 0;
    double best_speed = 0.0;
    for (const auto& s : shards) {
        Simulation::Stats st = s->stats();
        best_f = std::max(best_f, st.best_fitness);
        mean_f += st.mean_fitness * s->n();
        best_l = std::min(best_l, st.best_loss);
        mean_l += st.mean_loss * s->n();
        best_e = std::min(best_e, st.best_error_pct);
        mean_e += st.mean_error_pct * s->n();
        best_d = std::max(best_d, st.best_distance);
        mean_d += st.distance * s->n();
        best_laps = std::max(best_laps, st.best_laps);
        sum_c += st.crashes * s->n();
        alive += st.alive;
        n += s->n();
    }
    // velocidade média do melhor indivíduo da geração
    {
        double bf = -1e18;
        for (size_t i = 0; i < fitness.size(); ++i) {
            if (fitness[i] > bf) { bf = fitness[i]; best_speed = last_metrics[i].mean_speed; }
        }
    }
    acc.alive = alive;
    for (size_t i = 0; i < last_metrics.size(); ++i) sum_v += last_metrics[i].mean_speed;
    if (n > 0) {
        mean_f /= n; mean_l /= n; mean_e /= n; mean_d /= n;
        sum_c /= n;
        sum_v /= double(last_metrics.size());
    }

    pop.record(fitness);
    GenHistory h = pop.last();
    h.best_loss = best_l;
    h.mean_loss = mean_l;
    h.best_error_pct = best_e;
    h.mean_error_pct = mean_e;
    h.best_distance = best_d;
    h.mean_distance = mean_d;
    h.best_laps = best_laps;
    h.mean_speed = sum_v;
    h.best_speed = best_speed;
    h.crashes = sum_c;
    if (!pop.history.empty()) pop.history.back() = h;

    if (evolve && generations_enabled) pop.evolve();
    generation = pop.generation;
    start_episode();
    return h;
}

void Trainer::run_episode() {
    std::vector<std::thread> th;
    th.reserve(shards.size());
    for (size_t t = 0; t < shards.size(); ++t) {
        if (shards.size() == 1) {
            worker(0);
        } else {
            th.emplace_back([this, t]() { this->worker(int(t)); });
        }
    }
    for (auto& x : th) x.join();
}

void Trainer::run(int generations, std::function<bool(const GenHistory&)> callback) {
    for (int g = 0; g < generations; ++g) {
        start_episode();
        run_episode();
        GenHistory h = finish_episode(true);
        if (callback && !callback(h)) break;
    }
}

}  // namespace raceai
