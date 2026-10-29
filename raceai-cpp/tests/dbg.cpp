#include "../src/core/trainer.hpp"
#include "../src/core/assets.hpp"
#include <cstdio>
using namespace raceai;
int main(){
    Track t; std::string e; load_track("kartodromo", t, &e);
    CarSpec c; load_car("kart", c, &e);
    SimConfig sim; sim.max_seconds = 20;
    PolicySpec pol; pol.obs_dim = sim.n_rays + 15;
    GAConfig ga; ga.population = 8;
    TrainerConfig tc; tc.threads = 1; tc.seed = 3;
    Trainer tr(t, c, sim, ga, pol, tc);
    tr.start_episode();
    tr.run_episode();
    for (int i = 0; i < 8; ++i)
        printf("ag %d: fitness membro %.4f | loss %.4f | dist %.0f | vivo %d | motivo '%s'\n",
               i, tr.fitness[i], tr.last_metrics[i].loss, tr.last_metrics[i].distance,
               tr.shards[0]->agents[i].car.alive, tr.shards[0]->agents[i].death_reason.c_str());
    GenHistory h = tr.finish_episode(true);
    printf("hist: best %.4f mean %.4f best_ever %.4f | best_loss %.4f\n", h.best, h.mean, h.best_ever, h.best_loss);
    printf("pop.best_fitness %.4f | pop.fitness:", tr.pop.best_fitness);
    for (int i=0;i<4;i++) printf(" %.3f", tr.pop.fitness[i]);
    printf("\n");
    return 0;
}
