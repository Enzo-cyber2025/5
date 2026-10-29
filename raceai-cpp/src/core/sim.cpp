#include "sim.hpp"

#include <algorithm>
#include <cmath>

namespace raceai {


// ------------------------------------------------------------------ reward
Json RewardConfig::to_json() const {
    Json j = Json::object();
    j.set("progress", Json(progress));
    j.set("speed", Json(speed));
    j.set("precision", Json(precision));
    j.set("smooth", Json(smooth));
    j.set("offtrack", Json(offtrack));
    j.set("crash", Json(crash));
    j.set("wrongway", Json(wrongway));
    j.set("idle", Json(idle));
    j.set("finish_bonus", Json(finish_bonus));
    j.set("ref_speed_factor", Json(ref_speed_factor));
    return j;
}

RewardConfig RewardConfig::from_json(const Json& j) {
    RewardConfig r;
    if (j.is_null()) return r;
    r.progress = j.at("progress").num(r.progress);
    r.speed = j.at("speed").num(r.speed);
    r.precision = j.at("precision").num(r.precision);
    r.smooth = j.at("smooth").num(r.smooth);
    r.offtrack = j.at("offtrack").num(r.offtrack);
    r.crash = j.at("crash").num(r.crash);
    r.wrongway = j.at("wrongway").num(r.wrongway);
    r.idle = j.at("idle").num(r.idle);
    r.finish_bonus = j.at("finish_bonus").num(r.finish_bonus);
    r.ref_speed_factor = j.at("ref_speed_factor").num(r.ref_speed_factor);
    r.progress = std::max(0.0, r.progress);
    r.finish_bonus = clamp(r.finish_bonus, 0.0, 200.0);
    r.ref_speed_factor = clamp(r.ref_speed_factor, 0.1, 1.0);
    return r;
}

// ------------------------------------------------------------------ ctor
Simulation::Simulation(const Track& t, const CarSpec& car, const SimConfig& c,
                       int n_agents, uint32_t seed)
    : track(t), cfg(c), rng(seed) {
    agents.assign(std::max(1, n_agents), Agent());
    specs.assign(agents.size(), car);
    obs_dim = cfg.n_rays + 15;
    max_steps = int(cfg.max_seconds / cfg.dt);
    reset(0);
}

void Simulation::set_car(const CarSpec& car) {
    specs.assign(agents.size(), car);
}

void Simulation::set_specs(const std::vector<CarSpec>& s) {
    specs = s;
    if (specs.size() < agents.size()) {
        size_t k = specs.size();
        while (specs.size() < agents.size()) specs.push_back(specs[specs.size() % std::max<size_t>(1, k)]);
    }
    specs.resize(agents.size());
}

// ------------------------------------------------------------------ reset
void Simulation::reset(int rotation) {
    const int n = int(agents.size());
    const int tn = track.n();
    agents.assign(n, Agent());
    for (int i = 0; i < n; ++i) agents[i].agent_id = id_offset + i;
    step_count = 0;
    active_.clear();
    active_.reserve(n);

    const int start = track.start_index % std::max(1, tn);
    double half0 = track.half_widths[start];
    int per_row = std::max(1, int((half0 * 2.0 - 3.0) / 3.2));
    int rows = cfg.spawn_rows > 0 ? cfg.spawn_rows : int(std::ceil(double(n) / double(per_row)));
    (void)rows;
    for (int k = 0; k < n; ++k) {
        // o lugar no grid gira a cada geração: ninguém fica sempre com a mesma
        // posição (boa ou ruim) na largada
        int slot = (k + rotation) % n;
        int row = slot / per_row;
        int col = slot % per_row;
        int back = int(std::round((6.0 + row * 9.0) / std::max(track.spacing, 1e-6)));
        int i = ((start - back) % tn + tn) % tn;
        double half = track.half_widths[i];
        double lat = 0.0;
        if (per_row > 1) {
            double span = std::max(0.0, half - 1.6);
            lat = -span + 2.0 * span * double(col) / double(per_row - 1);
        }
        Agent& a = agents[k];
        a.car.x = track.center[i].x + track.normals[i].x * lat;
        a.car.y = track.center[i].y + track.normals[i].y * lat;
        a.car.heading = track.heading[i];
        a.car.vx = 0.0; a.car.vy = 0.0; a.car.r = 0.0; a.car.steer = 0.0;
        a.car.alive = true; a.car.frozen = false;
        a.idx = i;
        a.s_prev = 0.0;
        a.cp_next = 0;
        a.cp_passed = 0;
        active_.push_back(k);
    }
    sync_track_state();
    for (int k = 0; k < n; ++k) {
        // a linha de centro no ponto de largada define s = 0
        agents[k].s_prev = 0.0;
    }
}

// ------------------------------------------------------------------ estado
void Simulation::sync_track_state() {
    for (int row : active_) {
        Agent& a = agents[row];
        Vec2 pos(a.car.x, a.car.y);
        double lat = 0.0;
        int idx = track.nearest(pos, a.idx, 48, 25.0, &lat);
        a.idx = idx;
        a.lateral = lat;
        double half = track.half_widths[idx];
        bool on = std::fabs(lat) <= half;
        a.surface_grip = on ? track.grip[idx] : track.grip[idx] * cfg.grass_grip;
        a.surface_roll = on ? 1.0 : cfg.grass_roll;
    }
}

void Simulation::handle_walls() {
    for (int row : active_) {
        Agent& a = agents[row];
        const double half = track.half_widths[a.idx];
        const double limit = half + cfg.runoff;
        if (std::fabs(a.lateral) <= limit) continue;
        const double sign = a.lateral >= 0.0 ? 1.0 : -1.0;
        const Vec2& c = track.center[a.idx];
        const Vec2& nrm = track.normals[a.idx];
        const Vec2& tang = track.tangents[a.idx];
        a.car.x = c.x + nrm.x * (sign * limit);
        a.car.y = c.y + nrm.y * (sign * limit);

        double cos_h = std::cos(a.car.heading), sin_h = std::sin(a.car.heading);
        double wvx = a.car.vx * cos_h - a.car.vy * sin_h;
        double wvy = a.car.vx * sin_h + a.car.vy * cos_h;
        double v_t = wvx * tang.x + wvy * tang.y;
        double v_n = wvx * nrm.x + wvy * nrm.y;
        double speed = std::sqrt(v_t * v_t + v_n * v_n) + 1e-6;
        double v_n_out = (std::signbit(v_n) == std::signbit(sign)) ? v_n : 0.0;
        double v_n2 = v_n - 1.25 * v_n_out;                 // restituição 0.25
        double impact = clamp(std::fabs(v_n_out) / speed, 0.0, 1.0);
        double v_t2 = v_t * (1.0 - 0.45 * impact);
        double wvx2 = tang.x * v_t2 + nrm.x * v_n2;
        double wvy2 = tang.y * v_t2 + nrm.y * v_n2;
        a.car.vx = wvx2 * cos_h + wvy2 * sin_h;
        a.car.vy = -wvx2 * sin_h + wvy2 * cos_h;
        a.car.r *= 0.55;
        if (a.crash_cd <= 0.0) {
            a.crashes += 1;
            a.crash_cd = 0.4;
        }
    }
}

void Simulation::kill(int row, const std::string& reason) {
    Agent& a = agents[row];
    if (!a.car.alive) return;
    a.car.alive = false;
    if (a.death_reason.empty()) a.death_reason = reason;
    a.car.throttle = 0.0;
    a.car.brake = 0.0;
    auto it = std::find(active_.begin(), active_.end(), row);
    if (it != active_.end()) {
        *it = active_.back();
        active_.pop_back();
    }
}

void Simulation::set_action(int row, double steer, double drive) {
    if (row < 0 || row >= int(agents.size())) return;
    Agent& a = agents[row];
    double s = clamp(steer, -1.0, 1.0);
    double d = clamp(drive, -1.0, 1.0);
    // variação da ação entra na métrica de suavidade (peso por metro rodado)
    a.jerk_int += (std::fabs(s - a.last_steer) + std::fabs(d - a.last_drive)) * 0.5 *
                  std::max(0.0, a.car.speed) * cfg.dt;
    a.last_steer = s;
    a.last_drive = d;
    a.car.steer_cmd = s;
    a.car.throttle = clamp(d, 0.0, 1.0);
    a.car.brake = clamp(-d, 0.0, 1.0);
}

// ------------------------------------------------------------------ passo
void Simulation::step() {
    const double dt = cfg.dt;
    const int tn = track.n();
    const double length = std::max(track.length, 1e-6);
    const int m = std::max(1, int(track.checkpoints.size()));

    std::vector<int> rows = active_;   // cópia: kill() altera active_
    for (int row : rows) {
        Agent& a = agents[row];
        physics_step(specs[row], a.car, a.surface_grip, a.surface_roll, dt);
    }
    sync_track_state();
    handle_walls();

    for (int row : rows) {
        Agent& a = agents[row];
        if (!a.car.alive) continue;
        const double half = track.half_widths[a.idx];
        const Vec2& tang = track.tangents[a.idx];

        a.time += dt;

        // ---- progressão ao longo do arco (com volta)
        Vec2 rel(a.car.x - track.center[a.idx].x, a.car.y - track.center[a.idx].y);
        double along = clamp(dot(rel, tang), -track.spacing, track.spacing);
        double s = track.arc[a.idx] + along;
        double ds = s - a.s_prev;
        double half_len = length * 0.5;
        if (ds > half_len) ds -= length;
        if (ds < -half_len) ds += length;
        // nenhum carro anda mais do que alguns metros por passo: corta saltos.
        double max_ds = std::max(a.car.speed * dt * 3.0 + 1.0, 2.0);
        ds = clamp(ds, -max_ds, max_ds);
        a.s_total += ds;
        a.s_prev = s;
        a.max_s = std::max(a.max_s, a.s_total);
        a.raw_laps = int(std::floor(a.s_total / length));

        // ---- checkpoints em ordem: fecha o atalho de cortar o infield
        if (cfg.checkpoint_gating) {
            int cp_index = int(double(a.idx) * double(m) / double(tn)) % m;
            if (cp_index == a.cp_next || cp_index == (a.cp_next + 1) % m) {
                a.cp_next = (a.cp_next + 1) % m;
                a.cp_passed += 1;
                if (a.cp_next == 0) {
                    a.laps += 1;
                    double lt = a.time - a.lap_start;
                    a.last_lap = lt;
                    a.best_lap = std::min(a.best_lap, lt);
                    a.lap_start = a.time;
                }
            }
        } else {
            a.laps = a.raw_laps;
        }

        // ---- métricas integradas (por metro / por segundo)
        double fwd = std::max(ds, 0.0);
        a.fwd_dist += fwd;
        double v_along = ds / dt;                       // m/s de avanço real
        a.speed_int += std::max(v_along, 0.0) * dt;
        double lat_ratio = clamp(std::fabs(a.lateral) / std::max(half, 1e-6), 0.0, 1.0);
        a.precision_int += (1.0 - lat_ratio) * fwd;

        // ---- estados de erro
        if (std::fabs(a.lateral) > half) a.offtrack_time += dt;
        if (a.crash_cd > 0.0) a.crash_time += dt;
        if (a.car.speed < 1.2) a.idle_time += dt;
        a.crash_cd = std::max(a.crash_cd - dt, 0.0);

        // ---- sentido da pista
        double aligned = std::cos(a.car.heading) * tang.x + std::sin(a.car.heading) * tang.y;
        bool wrong = (aligned < -0.15) && (a.car.speed > 2.0);
        a.wrong_way_time = wrong ? a.wrong_way_time + dt : 0.0;

        // ---- término
        bool slow = a.car.speed < 1.2;
        a.stall_time = slow ? a.stall_time + dt : 0.0;
        const char* reason = nullptr;
        if (a.stall_time > cfg.stall_seconds) reason = "parado";
        else if (a.s_total < a.max_s - 30.0) reason = "voltou";
        else if (a.wrong_way_time > cfg.wrong_way_seconds) reason = "contra-mão";
        else if (a.time >= cfg.max_seconds) reason = "tempo";
        else if (cfg.target_laps > 0 && a.laps >= cfg.target_laps) reason = "concluiu";
        else if (a.crashes >= cfg.max_crashes) reason = "batidas";
        if (reason) {
            a.finished = (std::string(reason) == "concluiu");
            kill(row, reason);
        }
    }

    step_count += 1;
    update_fitness();
}

// ------------------------------------------------------------------ métricas
double Simulation::target_distance(const CarSpec& sp) const {
    if (cfg.target_laps > 0) return track.length * double(cfg.target_laps);
    return std::max(50.0, ref_speed(sp) * cfg.max_seconds);
}

double Simulation::ref_speed(const CarSpec& sp) const {
    return clamp(reward.ref_speed_factor * sp.max_speed, 6.0, 60.0);
}

Metrics Simulation::metrics(int row) const {
    const Agent& a = agents[row];
    const CarSpec& sp = specs[row];
    Metrics mt;
    const double T = std::max(cfg.max_seconds, 1e-6);
    const double used = clamp(a.time, 0.0, T);
    // as frações de erro são medidas sobre o tempo **dirigido** (é o que o HUD
    // mostra ao vivo); o tempo que o agente abriu mão (morreu antes da hora)
    // entra separado, em `giveup_pct` — desistir nunca pode sair de graça.
    const double denom = std::max(used, 0.5);

    mt.target_distance = target_distance(sp);
    mt.ref_speed = ref_speed(sp);
    mt.distance = a.max_s;
    mt.progress_score = clamp(a.max_s / std::max(mt.target_distance, 1e-6), 0.0, 1.0);
    mt.mean_speed = a.speed_int / std::max(used, 0.5);
    mt.speed_score = clamp(mt.mean_speed / mt.ref_speed, 0.0, 1.0);
    // precisão e suavidade são médias **por metro**: parado em cima da linha de
    // centro não rende nada (fecha o "farm" de precisão sem andar)
    mt.precision_score = a.fwd_dist > 5.0 ? clamp(a.precision_int / a.fwd_dist, 0.0, 1.0) : 0.0;
    double jerk_per_m = a.fwd_dist > 5.0 ? a.jerk_int / a.fwd_dist : 10.0;
    mt.smooth_score = clamp(1.0 - jerk_per_m / 1.5, 0.0, 1.0);

    mt.offtrack_pct = clamp(a.offtrack_time / denom, 0.0, 1.0);
    mt.wrongway_pct = clamp(a.wrong_way_time / denom, 0.0, 1.0);
    mt.idle_pct = clamp(a.idle_time / denom, 0.0, 1.0);
    mt.crash_pct = clamp(a.crash_time / denom, 0.0, 1.0);
    const double exempt = a.finished ? std::max(0.0, T - used) : 0.0;
    mt.giveup_pct = a.car.alive ? 0.0
                                : clamp(std::max(0.0, T - used - exempt) / T, 0.0, 1.0);
    double crash_budget = std::max(3.0, used / 8.0);
    mt.crash_score = clamp(double(a.crashes) / crash_budget, 0.0, 1.0);

    mt.error_pct = 100.0 * clamp(mt.offtrack_pct + mt.wrongway_pct + mt.idle_pct +
                                 mt.crash_pct, 0.0, 1.0);

    const RewardConfig& w = reward;
    mt.loss = w.progress * (1.0 - mt.progress_score)
            + w.speed * (1.0 - mt.speed_score)
            + w.precision * (1.0 - mt.precision_score)
            + w.smooth * (1.0 - mt.smooth_score)
            + w.offtrack * mt.offtrack_pct
            + w.wrongway * mt.wrongway_pct
            + w.idle * clamp(mt.idle_pct + mt.giveup_pct, 0.0, 1.0)
            + w.crash * mt.crash_score;
    return mt;
}

double Simulation::fitness(int row) const {
    const Agent& a = agents[row];
    Metrics mt = metrics(row);
    double f = -mt.loss;
    if (a.finished) {
        double remaining = std::max(0.0, cfg.max_seconds - a.time);
        f += reward.finish_bonus * clamp(remaining / std::max(cfg.max_seconds, 1e-6), 0.0, 1.0);
    }
    return f;
}

void Simulation::update_fitness() {
    for (size_t i = 0; i < agents.size(); ++i) {
        agents[i].fitness = fitness(int(i));
    }
}

Simulation::Stats Simulation::stats() const {
    Stats st;
    if (agents.empty()) return st;
    double sum_f = 0.0, sum_l = 0.0, sum_e = 0.0, sum_d = 0.0, sum_v = 0.0, sum_c = 0.0, sum_laps = 0.0;
    double best_f = -1e18, best_l = 1e18, best_e = 1e18, best_d = 0.0, best_laps = 0.0;
    int alive_n = 0;
    for (size_t i = 0; i < agents.size(); ++i) {
        const Agent& a = agents[i];
        Metrics m = metrics(int(i));
        double f = a.fitness;
        sum_f += f; sum_l += m.loss; sum_e += m.error_pct; sum_d += a.max_s;
        sum_c += a.crashes; sum_laps += a.laps;
        if (a.car.alive) { sum_v += a.car.speed; alive_n += 1; }
        best_f = std::max(best_f, f);
        best_l = std::min(best_l, m.loss);
        best_e = std::min(best_e, m.error_pct);
        best_d = std::max(best_d, a.max_s);
        best_laps = std::max(best_laps, double(a.laps));
    }
    const double n = double(agents.size());
    st.alive = alive_n;
    st.best_fitness = best_f;
    st.mean_fitness = sum_f / n;
    st.best_loss = best_l;
    st.mean_loss = sum_l / n;
    st.best_error_pct = best_e;
    st.mean_error_pct = sum_e / n;
    st.distance = sum_d / n;
    st.best_distance = best_d;
    st.avg_speed = alive_n ? sum_v / alive_n : 0.0;
    st.crashes = sum_c / n;
    st.laps = sum_laps / n;
    st.best_laps = best_laps;
    return st;
}

int Simulation::best_row() const {
    int best = 0;
    double bf = -1e18;
    for (size_t i = 0; i < agents.size(); ++i) {
        if (agents[i].fitness > bf) { bf = agents[i].fitness; best = int(i); }
    }
    return best;
}

// ------------------------------------------------------------------ sensores
void Simulation::observe(int row, float* out) const {
    const Agent& a = agents[row];
    const CarSpec& sp = specs[row];
    const int nr = std::max(1, cfg.n_rays);
    std::vector<double> rays(nr);
    track.cast_rays(Vec2(a.car.x, a.car.y), a.car.heading, a.idx, nr, cfg.ray_range,
                    cfg.fov_deg * kPi / 180.0, rays.data());
    int o = 0;
    for (int i = 0; i < nr; ++i) out[o++] = float(clamp(rays[i] / cfg.ray_range, 0.0, 1.0));

    const double max_speed = std::max(sp.max_speed, 1e-6);
    const double steer_norm = std::max(sp.max_steer, 1e-6);
    const double half = std::max(track.half_widths[a.idx], 1e-6);
    out[o++] = float(a.car.speed / max_speed);
    out[o++] = float(a.car.vx / max_speed);
    out[o++] = float(a.car.vy / 12.0);
    out[o++] = float(a.car.r / 3.0);
    out[o++] = float(a.car.steer / steer_norm);
    out[o++] = float(clamp(a.lateral / half, -1.5, 1.5) / 1.5);
    out[o++] = float(wrap_angle(a.car.heading - track.heading[a.idx]) / kPi);

    const double dists[4] = {15.0, 30.0, 50.0, 80.0};
    double dh[4], kk[4];
    track.lookahead(a.idx, std::vector<double>(dists, dists + 4), dh, kk);
    for (int i = 0; i < 4; ++i) out[o++] = float(clamp(dh[i] / 1.2, -1.0, 1.0));

    out[o++] = float(clamp(a.surface_grip, 0.0, 2.0));
    out[o++] = float(clamp(a.car.grip_use, 0.0, 1.5));
    out[o++] = float(a.last_steer);
    out[o++] = float(a.last_drive);
    // zera o resto (configurações com menos raios usam obs_dim menor)
    for (; o < obs_dim; ++o) out[o] = 0.0f;
}

}  // namespace raceai
