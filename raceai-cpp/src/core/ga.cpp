#include "ga.hpp"

#include <algorithm>
#include <cmath>

namespace raceai {

Json GAConfig::to_json() const {
    Json j = Json::object();
    j.set("population", Json(double(population)));
    j.set("elitism", Json(elitism));
    j.set("tournament", Json(double(tournament)));
    j.set("crossover", Json(crossover));
    j.set("crossover_rate", Json(crossover_rate));
    j.set("mutation_rate", Json(mutation_rate));
    j.set("mutation_sigma", Json(mutation_sigma));
    j.set("sigma_decay", Json(sigma_decay));
    j.set("sigma_min", Json(sigma_min));
    j.set("fresh_blood", Json(fresh_blood));
    j.set("stagnation_limit", Json(double(stagnation_limit)));
    j.set("reset_mutation_chance", Json(reset_mutation_chance));
    return j;
}

GAConfig GAConfig::from_json(const Json& j) {
    GAConfig c;
    if (j.is_null()) return c;
    c.population = std::max(2, int(j.at("population").num(c.population)));
    c.elitism = clamp(j.at("elitism").num(c.elitism), 0.0, 0.6);
    c.tournament = clamp(int(j.at("tournament").num(c.tournament)), 2, 20);
    c.crossover = j.at("crossover").str(c.crossover);
    c.crossover_rate = clamp(j.at("crossover_rate").num(c.crossover_rate), 0.0, 1.0);
    c.mutation_rate = clamp(j.at("mutation_rate").num(c.mutation_rate), 0.0, 1.0);
    c.mutation_sigma = clamp(j.at("mutation_sigma").num(c.mutation_sigma), 0.001, 2.0);
    c.sigma_decay = clamp(j.at("sigma_decay").num(c.sigma_decay), 0.5, 1.0);
    c.sigma_min = clamp(j.at("sigma_min").num(c.sigma_min), 0.001, 1.0);
    c.fresh_blood = clamp(j.at("fresh_blood").num(c.fresh_blood), 0.0, 0.5);
    c.stagnation_limit = std::max(1, int(j.at("stagnation_limit").num(c.stagnation_limit)));
    c.reset_mutation_chance = clamp(j.at("reset_mutation_chance").num(c.reset_mutation_chance), 0.0, 0.2);
    return c;
}

// ------------------------------------------------------------------ população
Population::Population(const PolicySpec& sp, const GAConfig& c, uint32_t seed)
    : spec(sp), cfg(c), rng(seed) {
    sigma = cfg.mutation_sigma;
    size_t pos = 0;
    for (size_t s : spec.shapes()) {
        slices_.emplace_back(pos, pos + s);
        pos += s;
    }
    random_population();
}

void Population::random_population() {
    const int n = std::max(2, cfg.population);
    genomes.clear();
    genomes.reserve(n);
    for (int i = 0; i < n; ++i) genomes.push_back(init_genome(spec, rng));
    fitness.assign(n, 0.0);
    generation = 0;
    best_fitness = -1e18;
    best_genome.clear();
    best_generation = 0;
    stagnation = 0;
    sigma = cfg.mutation_sigma;
    history.clear();
}

void Population::seed_from(const std::vector<float>& genome) {
    const int n = std::max(2, cfg.population);
    genomes.clear();
    for (int i = 0; i < n; ++i) genomes.push_back(mutate(genome, 1.0));
    genomes[0] = genome;
    fitness.assign(n, 0.0);
    generation = 0;
    best_fitness = -1e18;
    best_genome = genome;
    best_generation = 0;
    stagnation = 0;
    sigma = cfg.mutation_sigma * 0.6;
}

void Population::resize(int n) {
    n = std::max(2, n);
    cfg.population = n;
    if (best_genome.empty() || genomes.empty()) {
        random_population();
        return;
    }
    std::vector<float> base = best_genome;
    genomes.clear();
    for (int i = 0; i < n; ++i) genomes.push_back(mutate(base, 1.0));
    genomes[0] = base;
    fitness.assign(n, 0.0);
}

void Population::record(const std::vector<double>& fit) {
    fitness = fit;
    if (fitness.size() != genomes.size()) fitness.assign(genomes.size(), 0.0);
    int bi = best_index();
    GenHistory h;
    h.generation = generation;
    if (!fitness.empty()) {
        double sum = 0.0;
        double best = -1e18, worst = 1e18;
        for (double f : fitness) { sum += f; best = std::max(best, f); worst = std::min(worst, f); }
        double mean = sum / double(fitness.size());
        double var = 0.0;
        for (double f : fitness) var += (f - mean) * (f - mean);
        h.best = best;
        h.mean = mean;
        h.worst = worst;
        h.std = std::sqrt(var / double(fitness.size()));
        if (best > best_fitness) {
            best_fitness = best;
            best_genome = genomes[bi];
            best_generation = generation;
            stagnation = 0;
        } else {
            stagnation += 1;
        }
        h.best_ever = best_fitness;
    }
    double div = 0.0;
    for (const auto& g : genomes) {
        double m = 0.0;
        for (float v : g) m += v;
        m /= double(std::max<size_t>(1, g.size()));
        double v = 0.0;
        for (float f : g) v += double(f - m) * double(f - m);
        div += std::sqrt(v / double(std::max<size_t>(1, g.size())));
    }
    h.diversity = genomes.empty() ? 0.0 : div / double(genomes.size());
    h.sigma = sigma;
    history.push_back(h);
}

int Population::best_index() const {
    int bi = 0;
    double bf = -1e18;
    for (size_t i = 0; i < fitness.size(); ++i) {
        if (fitness[i] > bf) { bf = fitness[i]; bi = int(i); }
    }
    return bi;
}

int Population::tournament() {
    const int n = int(genomes.size());
    const int k = std::max(2, cfg.tournament);
    int best = rng.irange(0, n - 1);
    double bf = fitness[best];
    for (int i = 1; i < k; ++i) {
        int c = rng.irange(0, n - 1);
        if (fitness[c] > bf) { bf = fitness[c]; best = c; }
    }
    return best;
}

std::vector<float> Population::crossover(const std::vector<float>& a, const std::vector<float>& b) {
    if (rng.uniform01() > cfg.crossover_rate) return a;
    std::vector<float> c(a.size());
    for (size_t i = 0; i < a.size(); ++i) {
        if (cfg.crossover == "uniform") {
            c[i] = (rng.uniform01() < 0.5) ? a[i] : b[i];
        } else {
            double alpha = rng.uniform01();
            c[i] = float(a[i] * alpha + b[i] * (1.0 - alpha));
        }
    }
    return c;
}

std::vector<float> Population::mutate(const std::vector<float>& genome, double boost) {
    std::vector<float> g = genome;
    const double rate = clamp(cfg.mutation_rate, 0.0, 1.0);
    // desvio global (piso para camadas colapsadas, ex.: bias zerado)
    double gm = 0.0;
    for (float v : g) gm += v;
    gm /= double(std::max<size_t>(1, g.size()));
    double gvar = 0.0;
    for (float v : g) gvar += (double(v) - gm) * (double(v) - gm);
    double global_std = std::max(std::sqrt(gvar / double(std::max<size_t>(1, g.size()))), 1e-3);

    for (const auto& sl : slices_) {
        const size_t i0 = sl.first, i1 = std::min(sl.second, g.size());
        if (i1 <= i0) continue;
        double m = 0.0;
        for (size_t i = i0; i < i1; ++i) m += g[i];
        m /= double(i1 - i0);
        double v = 0.0;
        for (size_t i = i0; i < i1; ++i) v += (double(g[i]) - m) * (double(g[i]) - m);
        double layer_std = std::sqrt(v / double(i1 - i0));
        double scale = sigma * boost * (layer_std + 0.15 * global_std);
        for (size_t i = i0; i < i1; ++i) {
            if (rng.uniform01() < rate) g[i] += float(rng.normal(0.0, scale));
        }
    }
    if (cfg.reset_mutation_chance > 0.0) {
        for (size_t i = 0; i < g.size(); ++i) {
            if (rng.uniform01() < cfg.reset_mutation_chance) {
                g[i] = float(rng.normal(0.0, global_std));
            }
        }
    }
    for (float& v : g) v = float(clamp(double(v), -8.0, 8.0));
    return g;
}

void Population::evolve() {
    const int n = std::max(2, cfg.population);
    std::vector<int> order(genomes.size());
    for (size_t i = 0; i < order.size(); ++i) order[i] = int(i);
    std::sort(order.begin(), order.end(),
              [&](int a, int b) { return fitness[a] > fitness[b]; });
    int n_elite = std::max(1, int(std::round(n * clamp(cfg.elitism, 0.0, 0.6))));
    int n_fresh = int(std::round(n * clamp(cfg.fresh_blood, 0.0, 0.5)));

    std::vector<std::vector<float>> next;
    next.reserve(n);
    if (!best_genome.empty()) next.push_back(best_genome);          // campeão
    for (int i = 0; i < n_elite && i < int(order.size()); ++i) {
        next.push_back(genomes[order[i]]);                            // elitismo
    }
    for (int i = 0; i < n_fresh; ++i) next.push_back(init_genome(spec, rng));
    while (int(next.size()) < n) {
        const std::vector<float>& pa = genomes[tournament()];
        const std::vector<float>& pb = genomes[tournament()];
        next.push_back(mutate(crossover(pa, pb)));
    }
    genomes = std::move(next);
    if (int(genomes.size()) > n) genomes.resize(n);
    fitness.assign(genomes.size(), 0.0);
    generation += 1;

    if (stagnation >= std::max(1, cfg.stagnation_limit)) {
        sigma = std::min(0.35, sigma * 1.5);
        stagnation = 0;
    } else {
        sigma = std::max(cfg.sigma_min, sigma * cfg.sigma_decay);
    }
}

}  // namespace raceai
