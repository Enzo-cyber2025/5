#include "../src/core/sim.hpp"
#include <cstdio>
using namespace raceai;

static void roda(const char* label, double steer, double drive, int seconds) {
    Track t; std::string err;
    if (!Track::load("../raceai/assets/tracks/kartodromo.json", t, &err)) { printf("ERRO %s\n", err.c_str()); return; }
    CarSpec car; car.max_speed = 40; car.engine_force = 4000; car.max_power = 30000;
    SimConfig cfg; cfg.max_seconds = seconds;
    Simulation sim(t, car, cfg, 24, 12345);
    int steps = int(seconds / cfg.dt);
    for (int s = 0; s < steps; ++s) {
        if (sim.should_decide()) {
            for (int r : sim.active()) sim.set_action(r, steer, drive);
        }
        sim.step();
        if (sim.all_dead()) break;
    }
    Simulation::Stats st = sim.stats();
    int b = sim.best_row();
    Metrics m = sim.metrics(b);
    printf("%-22s vivo=%2d | dist %.0f m | voltas %.0f | vmedia %.1f m/s | perdas %.3f | erro %.1f%% "
           "| batidas %.1f | motivo '%s'\n",
           label, st.alive, m.distance, st.best_laps, m.mean_speed, m.loss, m.error_pct,
           st.crashes, sim.agents[b].death_reason.c_str());
    printf("%-22s   scores: prog %.2f vel %.2f prec %.2f suav %.2f | fora %.2f parado %.2f desist %.2f crash %.2f\n",
           "", m.progress_score, m.speed_score, m.precision_score, m.smooth_score,
           m.offtrack_pct, m.idle_pct, m.giveup_pct, m.crash_score);
}

int main() {
    roda("pé embaixo, reto", 0.0, 1.0, 30);
    roda("parado", 0.0, 0.0, 30);
    roda("esterço fixo", 0.5, 1.0, 30);
    roda("freio (ré)", 0.0, -1.0, 30);
    return 0;
}
