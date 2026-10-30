// train_cli.cpp — treinador/evaluador de linha de comando (headless).
//
// Roda gerações inteiras o mais rápido possível (vários núcleos) e imprime a
// curva de perda (loss) e a porcentagem de erro — as mesmas métricas que a
// interface mostra, porque o núcleo é o mesmo.
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

#include "../src/core/assets.hpp"
#include "../src/core/trainer.hpp"
#include "../src/core/cli.hpp"

using namespace raceai;

static void usage() {
    printf(
        "RaceAI 2D — treinador de linha de comando (C++)\n"
        "\n"
        "Uso: raceai_train [opções]\n"
        "\n"
        "  --track <id|caminho>   pista (padrão: kartodromo)\n"
        "  --car <id|caminho>     carro (padrão: kart)\n"
        "  -g, --generations N    quantidade de gerações/épocas (padrão: 50)\n"
        "  -p, --individuals N    indivíduos por geração (padrão: 120)\n"
        "  --seconds N            duração de cada episódio em segundos (padrão: 60)\n"
        "  --laps N               voltas alvo (0 = contra o relógio)\n"
        "  --threads N            threads de simulação (padrão: automático)\n"
        "  --seed N               semente aleatória (padrão: 1)\n"
        "  --hidden N            neurônios da 1a camada oculta (a 2a é a metade)\n"
        "  --out <arquivo>        salva o melhor modelo no fim\n"
        "  --load <arquivo>       continua o treino a partir de um modelo\n"
        "  --save-every N         salva o melhor a cada N gerações\n"
        "  --eval                 apenas avalia (não evolui)\n"
        "  --list                 lista pistas e carros disponíveis\n"
        "  --quiet                só imprime o resumo final\n"
        "\n"
        "Recompensa (os mesmos sliders da interface):\n"
        "  --reward-progress N  --reward-speed N  --reward-precision N  --reward-smooth N\n"
        "  --penalty-offtrack N --penalty-crash N --penalty-wrongway N  --penalty-idle N\n"
        "  --finish-bonus N     --ref-speed N (fração da velocidade máx usada como meta)\n");
}

static std::string arg(int argc, char** argv, int& i, const char* flag) {
    if (i + 1 < argc) return argv[++i];
    fprintf(stderr, "faltou o valor de %s\n", flag);
    exit(2);
}

// A mesma função é usada por dois executáveis: o raceai_train (só terminal) e
// o jogo (RaceAI2D.exe), que entra em modo terminal quando recebe argumentos.
namespace raceai {
int rodar_cli(int argc, char** argv) {
    std::string track_id = "kartodromo", car_id = "kart";
    std::string out_path, load_path;
    int generations = 50, individuals = 120, threads = 0, seed = 1, save_every = 0;
    int hidden = 64;
    double seconds = 60.0;
    int laps = 0;
    bool eval_only = false, quiet = false, list_only = false;
    RewardConfig reward;

    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        auto num = [&](const char* f) { return std::atof(arg(argc, argv, i, f).c_str()); };
        if (a == "--help" || a == "-h") { usage(); return 0; }
        else if (a == "--track") track_id = arg(argc, argv, i, "--track");
        else if (a == "--car") car_id = arg(argc, argv, i, "--car");
        else if (a == "-g" || a == "--generations" || a == "--epochs") generations = int(num("-g"));
        else if (a == "-p" || a == "--individuals" || a == "--pop") individuals = int(num("-p"));
        else if (a == "--seconds") seconds = num("--seconds");
        else if (a == "--laps") laps = int(num("--laps"));
        else if (a == "--threads") threads = int(num("--threads"));
        else if (a == "--seed") seed = int(num("--seed"));
        else if (a == "--out") out_path = arg(argc, argv, i, "--out");
        else if (a == "--load") load_path = arg(argc, argv, i, "--load");
                else if (a == "--hidden") hidden = std::max(8, int(num("--hidden")));
else if (a == "--save-every") save_every = int(num("--save-every"));
        else if (a == "--eval") eval_only = true;
        else if (a == "--quiet") quiet = true;
        else if (a == "--list") list_only = true;
        else if (a == "--reward-progress") reward.progress = num("--reward-progress");
        else if (a == "--reward-speed") reward.speed = num("--reward-speed");
        else if (a == "--reward-precision") reward.precision = num("--reward-precision");
        else if (a == "--reward-smooth") reward.smooth = num("--reward-smooth");
        else if (a == "--penalty-offtrack") reward.offtrack = num("--penalty-offtrack");
        else if (a == "--penalty-crash") reward.crash = num("--penalty-crash");
        else if (a == "--penalty-wrongway") reward.wrongway = num("--penalty-wrongway");
        else if (a == "--penalty-idle") reward.idle = num("--penalty-idle");
        else if (a == "--finish-bonus") reward.finish_bonus = num("--finish-bonus");
        else if (a == "--ref-speed") reward.ref_speed_factor = num("--ref-speed");
        else {
            fprintf(stderr, "opção desconhecida: %s (use --help)\n", a.c_str());
            return 2;
        }
    }

    if (list_only) {
        printf("Pistas:\n");
        for (const AssetItem& it : list_tracks())
            printf("  %-16s %-24s %s%s\n", it.id.c_str(), it.name.c_str(), it.detail.c_str(),
                   it.error.empty() ? "" : (" ERRO: " + it.error).c_str());
        printf("Carros:\n");
        for (const AssetItem& it : list_cars())
            printf("  %-16s %s%s\n", it.id.c_str(), it.detail.c_str(),
                   it.error.empty() ? "" : (" ERRO: " + it.error).c_str());
        return 0;
    }

    Track track;
    CarSpec car;
    std::string err;
    if (!load_track(track_id, track, &err)) {
        fprintf(stderr, "não consegui abrir a pista '%s': %s\n", track_id.c_str(), err.c_str());
        if (err.empty() || track_id == "kartodromo") {
            fprintf(stderr, "dica: rode a partir da pasta raceai-cpp (ou use --track <caminho>)\n");
        }
        return 1;
    }
    if (!load_car(car_id, car, &err)) {
        fprintf(stderr, "não consegui abrir o carro '%s': %s\n", car_id.c_str(), err.c_str());
        return 1;
    }

    SimConfig sim;
    sim.max_seconds = seconds;
    sim.target_laps = laps;
    PolicySpec pol;
    pol.hidden = {hidden, std::max(8, hidden / 2)};
    pol.obs_dim = sim.n_rays + 15;
    GAConfig ga;
    ga.population = std::max(2, individuals);
    TrainerConfig tc;
    tc.threads = threads;
    tc.seed = uint32_t(seed);

    Trainer trainer(track, car, sim, ga, pol, tc);
    trainer.set_reward(reward);
    if (!load_path.empty()) {
        if (!trainer.load_model(load_path, &err)) {
            fprintf(stderr, "não consegui carregar '%s': %s\n", load_path.c_str(), err.c_str());
            return 1;
        }
        printf("modelo carregado: %s (%zu pesos)\n", load_path.c_str(),
               trainer.best_weights().size());
    }
    if (eval_only) {
        trainer.generations_enabled = false;
        generations = 1;
    }

    printf("pista: %s (%.0f m) | carro: %s\n", track.name.c_str(), track.length,
           car.summary().c_str());
    printf("população %d | %d thread(s) | %.0f s por episódio%s\n\n", ga.population,
           trainer.threads, seconds, eval_only ? " | MODO AVALIAÇÃO" : "");
    printf("%4s %10s %8s %8s %9s %7s %8s %8s %7s\n", "ger", "fitness", "loss", "erro%",
           "dist(m)", "voltas", "v(m/s)", "batidas", "sigma");
    printf("-------------------------------------------------------------------------------\n");

    double t0 = double(clock()) / CLOCKS_PER_SEC;
    GenHistory last;
    double ever_loss = 1e18, ever_error = 1e18, ever_dist = 0.0, ever_fit = -1e18;
    for (int g = 0; g < generations; ++g) {
        trainer.start_episode();
        trainer.run_episode();
        last = trainer.finish_episode(!eval_only);
        if (!quiet || g == generations - 1 || (g + 1) % 10 == 0) {
            printf("%4d %10.3f %8.3f %7.1f%% %9.0f %7.1f %8.1f %8.1f %7.3f\n",
                   last.generation, last.best, last.best_loss, last.best_error_pct,
                   last.best_distance, last.best_laps, last.best_speed, last.crashes,
                   last.sigma);
            fflush(stdout);
        }
        ever_loss = std::min(ever_loss, last.best_loss);
        ever_error = std::min(ever_error, last.best_error_pct);
        ever_dist = std::max(ever_dist, last.best_distance);
        ever_fit = std::max(ever_fit, last.best);
        // estimativa: quanto falta para terminar todas as épocas
        if (!quiet || g == generations - 1 || (g + 1) % 10 == 0) {
            const double decorrido = double(clock()) / CLOCKS_PER_SEC - t0;
            const double media = decorrido / double(g + 1);
            const int faltam = generations - (g + 1);
            const double eta = media * double(faltam);
            if (faltam > 0) {
                const int em = int(eta) / 60, es = int(eta) % 60;
                const int dm = int(decorrido) / 60, ds = int(decorrido) % 60;
                printf("      ETA %dm %02ds para %s %d época%s restante%s "
                       "(%.2fs por época • %dm %02ds rodados)\n",
                       em, es, faltam > 1 ? "as" : "a", faltam,
                       faltam > 1 ? "s" : "", faltam > 1 ? "s" : "", media, dm, ds);
                fflush(stdout);
            }
        }
        if (save_every && !out_path.empty() && (last.generation % save_every == 0)) {
            std::string e2;
            trainer.save_best(out_path, &e2);
        }
    }
    double elapsed = double(clock()) / CLOCKS_PER_SEC - t0;

    if (!out_path.empty()) {
        if (!trainer.save_best(out_path, &err)) {
            fprintf(stderr, "não consegui salvar '%s': %s\n", out_path.c_str(), err.c_str());
            return 1;
        }
        printf("\nmodelo salvo em %s\n", out_path.c_str());
    }
    printf("\nresumo: %d gerações em %.1f s\n  melhor fitness de todas: %.3f\n"
           "  menor loss:               %.3f\n  menor erro:               %.1f%%\n"
           "  maior distância:          %.0f m (%.2f voltas)\n",
           generations, elapsed, ever_fit, ever_loss, ever_error, ever_dist,
           ever_dist / std::max(1.0, track.length));
    return 0;
}
}  // namespace raceai

#ifndef RACEAI_SEM_MAIN
int main(int argc, char** argv) { return raceai::rodar_cli(argc, argv); }
#endif
