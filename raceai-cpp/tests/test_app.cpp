// test_app.cpp — testes da camada de interface (sem abrir janela).
#include <cmath>
#include <cstdio>
#include <string>

#include "../src/app/app_state.hpp"

using namespace raceai;

static int ok = 0, falhas = 0;

// pasta temporária portável (no Windows não existe /tmp)
static std::string tmp_file(const char* nome) {
#ifdef _WIN32
    return std::string(".\\") + nome;
#else
    return std::string("/tmp/") + nome;
#endif
}
#define CHECK(c, ...)                                                          \
    do {                                                                       \
        if (!(c)) {                                                            \
            falhas += 1;                                                       \
            printf("  FALHOU %s:%d: ", __FILE__, __LINE__);                     \
            printf(__VA_ARGS__);                                               \
            printf("\n");                                                      \
        } else {                                                               \
            ok += 1;                                                           \
        }                                                                      \
    } while (0)

int main() {
    printf("RaceAI 2D (C++) — testes da interface\n\n");
    AppState app;

    // ---------------------------------------------------------- assets
    CHECK(!app.pistas.empty(), "nenhuma pista encontrada");
    CHECK(!app.carros.empty(), "nenhum carro encontrado");
    for (size_t i = 0; i < app.pistas.size(); ++i) {
        CHECK(app.carregar_pista(int(i)), "não carregou a pista %zu", i);
    }
    for (size_t i = 0; i < app.carros.size(); ++i) {
        CHECK(app.carregar_carro(int(i)), "não carregou o carro %zu", i);
    }
    CHECK(app.carregar_pista(0), "voltar para a pista 0");
    CHECK(app.carregar_carro(0), "voltar para o carro 0");

    // ---------------------------------------------------------- treino
    app.train_cfg.individuals = 12;
    app.train_cfg.generations = 3;
    app.train_cfg.seconds = 6.0;
    app.iniciar_treino(true);
    CHECK(app.trainer != nullptr, "trainer não foi criado");
    CHECK(app.treinando, "deveria estar treinando");
    int guarda = 0;
    while (app.treinando && guarda < 200000) {
        app.tick_treino(8);
        guarda += 8;
    }
    CHECK(guarda < 200000, "o treino não terminou (travou?)");
    CHECK(app.geracao >= 1, "nenhuma geração concluída: %d", app.geracao);
    CHECK(!app.treinando, "deveria ter parado no limite de gerações");
    CHECK(app.loss_history.size() == size_t(app.geracao),
          "histórico de loss: %zu (gerações %d)", app.loss_history.size(), app.geracao);
    CHECK(app.erro_history.size() == app.loss_history.size(), "histórico de erro desalinhado");
    for (double v : app.loss_history) {
        CHECK(std::isfinite(v) && v >= 0.0 && v < 20.0, "loss fora de faixa: %.3f", v);
    }
    for (double v : app.erro_history) {
        CHECK(std::isfinite(v) && v >= 0.0 && v <= 100.0, "erro fora de faixa: %.1f", v);
    }

    // o HUD precisa trazer perda e erro (pedido do usuário)
    std::vector<std::string> linhas = app.treino_lines();
    std::string tudo;
    for (const std::string& s : linhas) tudo += s + "\n";
    CHECK(tudo.find("loss") != std::string::npos, "HUD sem loss:\n%s", tudo.c_str());
    CHECK(tudo.find("erro") != std::string::npos, "HUD sem erro:\n%s", tudo.c_str());
    CHECK(tudo.find("velocidade") != std::string::npos, "HUD sem velocidade");

    // ---------------------------------------------------------- recompensa
    RewardConfig pesada;
    pesada.crash = 3.0;
    pesada.offtrack = 3.0;
    pesada.idle = 3.0;
    app.aplicar_recompensa(pesada);
    CHECK(app.trainer->shards[0]->reward.crash == 3.0, "recompensa não chegou na simulação");
    app.aplicar_recompensa(RewardConfig());
    CHECK(app.trainer->shards[0]->reward.crash == 0.5, "não voltou ao padrão");

    // ---------------------------------------------------------- modelo
    std::string err;
    CHECK(app.salvar_modelo(tmp_file("raceai_app_modelo.json"), &err), "não salvou: %s", err.c_str());
    CHECK(app.carregar_modelo(tmp_file("raceai_app_modelo.json"), &err), "não carregou: %s",
          err.c_str());
    CHECK(app.geracao == 0, "geração deveria zerar ao carregar modelo");

    // ---------------------------------------------------------- python
    const char* stub = std::getenv("RACEAI_STUB_PYTHON");
    if (stub) {
        app.python_runtime_path = stub;
        // carrega o interpretador "falso" usando o caminho do stub
        PyDriver tmp;
        CHECK(tmp.load_runtime(stub, &err), "não carregou o interpretador: %s", err.c_str());
    }
    bool aplicou = app.aplicar_codigo_python(exemplo_python());
    if (stub) {
        CHECK(aplicou, "não aplicou o código: %s", app.python_status.c_str());
        CHECK(app.python_enabled, "IA em Python deveria estar ativa");
        CHECK(app.python_disponivel(), "runtime deveria estar disponível");
        // o driver devolve uma ação válida
        float obs[24] = {0};
        float out[2] = {9, 9};
        if (app.py_driver) {
            app.py_driver->act(obs, 24, out);
            CHECK(std::isfinite(out[0]) && std::isfinite(out[1]), "ação inválida");
        }
        // código quebrado é recusado e mostra o erro
        CHECK(!app.aplicar_codigo_python("isto nao é python <<<"), "código inválido aceito");
        CHECK(!app.python_status.empty(), "deveria explicar o erro");
    } else {
        printf("  (pulando testes do python: stub não informado)\n");
    }

    // ---------------------------------------------------------- corrida
    app.iniciar_corrida({});
    CHECK(app.mode == Mode::Corrida, "não entrou no modo corrida");
    CHECK(app.race.sim != nullptr, "simulação da corrida não foi criada");
    CHECK(app.race.competidores.size() >= 1, "grid vazio");
    CHECK(app.race.competidores[0].manual, "o primeiro competidor deveria ser o jogador");
    race_set_human(0.0, 1.0);
    double s = 0, d = 0;
    race_get_human(&s, &d);
    CHECK(std::fabs(d - 1.0) < 1e-9, "controle manual não foi registrado");

    double antes = app.race.elapsed;
    for (int i = 0; i < 600; ++i) app.tick_corrida(4);
    CHECK(app.race.elapsed > antes, "o tempo da corrida não avançou");
    CHECK(!app.race.hud_lines().empty(), "HUD da corrida vazio");
    std::string classificacao;
    for (const std::string& l : app.race.hud_lines()) classificacao += l + "\n";
    CHECK(classificacao.find("Você") != std::string::npos, "classificação sem o jogador:\n%s",
          classificacao.c_str());
    CHECK(app.race.ordem.size() == app.race.competidores.size(), "classificação incompleta");
    // reiniciar zera as voltas
    app.race.restart();
    CHECK(app.race.competidores[0].voltas == 0, "voltas não zeraram");
    CHECK(!app.race.finished, "corrida deveria estar ativa após reiniciar");

    printf("\n%d testes passaram, %d falharam\n", ok, falhas);
    return falhas ? 1 : 0;
}
