// test_integrado.cpp — teste de ponta a ponta da interface + IA em Python.
//
// Cobre o caminho inteiro que o usuário faz:
//   colar um código Python  ·  importar um arquivo .py  ·  salvar o .py
//   a IA assumir o carro na corrida e no treino  ·  salvar/carregar modelo
//   sliders de recompensa  ·  HUD com loss e erro %
//
// Roda de três formas:
//   ./raceai_integrado                       sem Python (pula a parte de IA)
//   RACEAI_STUB_PYTHON=./build/libstubpython.so ./raceai_integrado
//   ./raceai_integrado python/python311.dll  com o CPython de verdade (CI)
#include <cmath>
#include <cstdio>
#include <cstdlib>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <dlfcn.h>
#endif
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "../src/app/app_state.hpp"

using namespace raceai;

static int ok = 0, falhas = 0;
static int g_secao = 0;            // seção em execução
static int g_foco = 0;             // 0 = roda tudo; N = roda só a seção N
static int g_nesta_secao = 0;      // verificações já feitas na seção
static int g_primeira_falha = 0;   // 1-based; 0 = nenhuma

// O CI roda uma seção por vez: assim o passo que falhar já diz onde foi.
static bool secao(int n) {
    g_secao = n;
    g_nesta_secao = 0;
    return g_foco == 0 || g_foco == n;
}

static std::string tmp_file(const char* nome) {
#ifdef _WIN32
    return std::string(".\\") + nome;
#else
    return std::string("/tmp/") + nome;
#endif
}

#define CHECK(c, ...)                                                          \
    do {                                                                       \
        g_nesta_secao += 1;                                                    \
        if (!(c)) {                                                            \
            falhas += 1;                                                       \
            if (!g_primeira_falha) g_primeira_falha = g_nesta_secao;           \
            printf("  FALHOU %s:%d: ", __FILE__, __LINE__);                    \
            printf(__VA_ARGS__);                                               \
            printf("\n");                                                      \
        } else {                                                               \
            ok += 1;                                                           \
        }                                                                      \
    } while (0)

// ------------------------------------------------------------ arquivos
static bool escrever(const std::string& path, const std::string& txt) {
    std::ofstream out(path.c_str(), std::ios::binary);
    if (!out) return false;
    out << txt;
    return bool(out);
}

static std::string ler(const std::string& path) {
    std::ifstream in(path.c_str(), std::ios::binary);
    if (!in) return std::string();
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

#ifdef RACEAI_WITH_PYTHON
// acesso ao interpretador falso (quando houver) para decidir a ação devolvida
static int stub_gil(const char* stub) {
#if defined(_WIN32)
    HMODULE h = LoadLibraryA(stub);
    if (!h) return 0;
    typedef int (*Fn)();
    Fn f = (Fn)GetProcAddress(h, "stubpython_gil_balance");
#else
    void* h = dlopen(stub, RTLD_NOW);
    if (!h) return 0;
    typedef int (*Fn)();
    Fn f = (Fn)dlsym(h, "stubpython_gil_balance");
#endif
    return f ? f() : 0;
}

static void stub_responder(const char* stub, double steer, double drive) {
#if defined(_WIN32)
    HMODULE h = LoadLibraryA(stub);
    if (!h) return;
    typedef void (*Fn)(double, double);
    Fn f = (Fn)GetProcAddress(h, "stubpython_set_response");
#else
    void* h = dlopen(stub, RTLD_NOW);
    if (!h) return;
    typedef void (*Fn)(double, double);
    Fn f = (Fn)dlsym(h, "stubpython_set_response");
#endif
    if (f) f(steer, drive);
}
#endif

// um piloto simples, usado para provar que o código colado realmente dirige
static const char* kPilotoSimples =
    "def dirigir(sensores):\n"
    "    # segue o meio da pista: s[14] deslocamento lateral, s[15] erro de direcao\n"
    "    esterco = -(sensores[14] * 0.9 + sensores[15] * 1.6)\n"
    "    esterco = max(-1.0, min(1.0, esterco))\n"
    "    frente = min(sensores[3], sensores[4], sensores[5])\n"
    "    acelerador = 0.35 + 0.65 * frente\n"
    "    if frente < 0.15:\n"
    "        acelerador = -0.4\n"
    "    return esterco, acelerador\n";

int main(int argc, char** argv) {
    printf("RaceAI 2D (C++) — teste de integração ponta a ponta\n\n");

    std::string runtime;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "--secao" && i + 1 < argc) g_foco = std::atoi(argv[++i]);
        else if (a.rfind("--secao=", 0) == 0) g_foco = std::atoi(a.c_str() + 8);
        else if (!a.empty() && a[0] != '-') runtime = a;   // caminho do interpretador
    }
    if (g_foco) printf("rodando só a seção %d\n\n", g_foco);

    const char* stub = std::getenv("RACEAI_STUB_PYTHON");
    const bool tem_python = !runtime.empty() || (stub && *stub);
    if (runtime.empty() && stub && *stub) runtime = stub;

    AppState app;
    if (tem_python) app.python_runtime_path = runtime;
    std::string err;

    if (secao(1)) {
    printf("1. pistas, carros e mods\n");
    CHECK(!app.pistas.empty(), "nenhuma pista");
    CHECK(!app.carros.empty(), "nenhum carro");
    for (size_t i = 0; i < app.carros.size(); ++i)
        CHECK(app.carregar_carro(int(i)), "não carregou o carro %zu", i);
    // uma pista larga, para o piloto simples ter espaço
    int idx_oval = 0;
    for (size_t i = 0; i < app.pistas.size(); ++i)
        if (app.pistas[i].id.find("oval") != std::string::npos) idx_oval = int(i);
    CHECK(app.carregar_pista(idx_oval), "não carregou a pista oval");
    CHECK(app.carregar_carro(0), "não voltou ao carro 0");

    }

    // ------------------------------------------------- 2. colar o código
    if (secao(2)) {
    printf("2. colar um código Python\n");
    if (tem_python) {
#ifdef RACEAI_WITH_PYTHON
        if (stub && *stub) stub_responder(stub, 0.0, 0.8);
        CHECK(app.aplicar_codigo_python(kPilotoSimples),
              "não aplicou o código colado: %s", app.python_status.c_str());
        CHECK(app.python_enabled, "a IA em Python deveria estar ativa");
        CHECK(app.python_code == kPilotoSimples, "o código colado não foi guardado");
        float obs[24] = {0};
        float out[2] = {9, 9};
        if (app.py_driver) {
            app.py_driver->act(obs, 24, out);
            CHECK(out[0] >= -1.0f && out[0] <= 1.0f, "esterço fora de faixa: %.3f", out[0]);
            CHECK(out[1] >= -1.0f && out[1] <= 1.0f, "acelerador fora de faixa: %.3f", out[1]);
        }
        // o exemplo que vem com o jogo também precisa compilar
        CHECK(app.aplicar_codigo_python(exemplo_python()),
              "o exemplo do jogo não compilou: %s", app.python_status.c_str());
#endif
    } else {
        printf("   (pulando: nenhum interpretador informado)\n");
    }

    }

    // ------------------------------------------------ 3. salvar e importar .py
    if (secao(3)) {
    printf("3. salvar e importar arquivo .py\n");
    if (tem_python) {
#ifdef RACEAI_WITH_PYTHON
        if (stub && *stub) stub_responder(stub, 0.0, 0.8);
        const std::string arq = tmp_file("raceai_minha_ia.py");
        CHECK(app.aplicar_codigo_python(kPilotoSimples), "não aplicou antes de salvar");
        CHECK(app.salvar_python(arq, &err), "não salvou o .py: %s", err.c_str());
        CHECK(ler(arq) == kPilotoSimples, "o .py salvo não bate com o código");

        // importar de volta (com quebras de linha do Windows, de brinde)
        std::string crlf;
        for (char c : std::string(kPilotoSimples)) {
            if (c == '\n') crlf += "\r\n";
            else crlf += c;
        }
        const std::string arq_crlf = tmp_file("raceai_minha_ia_crlf.py");
        CHECK(escrever(arq_crlf, crlf), "não gravou o .py com CRLF");
        CHECK(app.importar_python(arq_crlf, &err), "não importou o .py: %s", err.c_str());
        CHECK(app.python_enabled, "importar deveria deixar a IA ativa");
        CHECK(app.python_code.find("\r") == std::string::npos,
              "as quebras \\r deveriam ser removidas");
        CHECK(app.python_code == kPilotoSimples, "o código importado foi alterado");

        // arquivo com erro de sintaxe: recusado, com explicação, sem derrubar nada
        const std::string ruim = tmp_file("raceai_ia_ruim.py");
        CHECK(escrever(ruim, "def dirigir(sensores)\n    return 1, 1\n"), "não gravou");
        CHECK(!app.importar_python(ruim, &err), "código quebrado foi aceito");
        CHECK(!err.empty(), "deveria explicar o erro");
        CHECK(!app.python_enabled, "a IA deveria ser desligada depois do erro");
        printf("   erro reportado: %s\n", err.substr(0, 60).c_str());

        // arquivo sem a função dirigir(): recusado
        const std::string sem = tmp_file("raceai_sem_dirigir.py");
        CHECK(escrever(sem, "x = 1 + 1\n"), "não gravou");
        CHECK(!app.importar_python(sem, &err), "arquivo sem dirigir() foi aceito");
        CHECK(!err.empty(), "deveria avisar que falta dirigir()");

        // arquivo que não existe
        CHECK(!app.importar_python(tmp_file("nao_existe_12345.py"), &err),
              "arquivo inexistente foi aceito");

        // volta para o piloto simples para os testes de pista
        CHECK(app.importar_python(arq, &err), "não voltou ao piloto simples: %s", err.c_str());
#endif
    } else {
        printf("   (pulando: nenhum interpretador informado)\n");
    }

    }

    // --------------------------------- 4. a IA colada dirige na simulação
    if (secao(4)) {
    printf("4. a IA colada dirige de verdade\n");
    if (tem_python) app.aplicar_codigo_python(kPilotoSimples);
    if (tem_python && app.py_driver) {
#ifdef RACEAI_WITH_PYTHON
        if (stub && *stub) stub_responder(stub, 0.0, 0.9);
        SimConfig cfg = app.sim_cfg;
        cfg.max_seconds = 40.0;
        Simulation sim(app.track_cache_, app.car_cache_, cfg, 1, 7u);
        sim.reward = app.reward;
        std::vector<float> obs(size_t(sim.obs_dim));
        float at[2] = {0, 0};
        int chamadas = 0;
        bool faixa_ok = true;
        const int passos = int(20.0 / cfg.dt);          // 20 s de simulação
        for (int k = 0; k < passos; ++k) {
            if (sim.should_decide()) {
                for (int row : sim.active()) {
                    sim.observe(row, obs.data());
                    app.py_driver->act(obs.data(), sim.obs_dim, at);
                    chamadas += 1;
                    if (!(at[0] >= -1.0f && at[0] <= 1.0f && at[1] >= -1.0f && at[1] <= 1.0f))
                        faixa_ok = false;
                    sim.set_action(row, at[0], at[1]);
                }
            }
            sim.step();
        }
        CHECK(chamadas > 50, "a IA foi chamada poucas vezes: %d", chamadas);
        CHECK(faixa_ok, "a IA devolveu ação fora de [-1, 1]");
        double dist = sim.agents[0].max_s;
        CHECK(dist > 15.0, "o carro andou pouco: %.1f m em 20 s", dist);
        CHECK(sim.agents[0].crashes < 20, "bateu demais: %d", sim.agents[0].crashes);
        Metrics m = sim.metrics(0);
        CHECK(m.error_pct >= 0.0 && m.error_pct <= 100.0, "erro%% fora de faixa: %.1f", m.error_pct);
        CHECK(std::isfinite(m.loss), "loss inválida: %.3f", m.loss);
        printf("   andou %.1f m, %d batidas, erro %.1f%%, %d chamadas\n",
               dist, sim.agents[0].crashes, m.error_pct, chamadas);
#endif
    } else {
        printf("   (pulando: nenhum interpretador informado)\n");
    }

    }

    // ------------------------------------------- 5. corrida com a IA no grid
    if (secao(5)) {
    printf("5. corrida com a IA em Python no grid\n");
    {
        if (tem_python) {
#ifdef RACEAI_WITH_PYTHON
            if (stub && *stub) stub_responder(stub, 0.0, 0.9);
            app.aplicar_codigo_python(kPilotoSimples);
#endif
        }
        app.iniciar_corrida({});
        CHECK(app.mode == Mode::Corrida, "não entrou na corrida");
        CHECK(app.race.sim != nullptr, "sem simulação");
        race_set_human(0.0, 0.6);
        int ia = -1;
        for (size_t i = 0; i < app.race.competidores.size(); ++i)
            if (app.race.competidores[i].origem == "python") ia = int(i);
        if (tem_python) {
            CHECK(ia >= 0, "a IA em Python não entrou no grid");
        }
        const int antes = tem_python && ia >= 0
                              ? 0
                              : 0;
        (void)antes;
        for (int i = 0; i < 1500; ++i) app.tick_corrida(4);
        if (ia >= 0) {
            CHECK(app.race.competidores[size_t(ia)].s_total > 3.0,
                  "a IA não saiu do lugar: %.1f m", app.race.competidores[size_t(ia)].s_total);
            CHECK(app.py_driver->call_count() > 10,
                  "a IA foi chamada poucas vezes na corrida: %d", app.py_driver->call_count());
            printf("   IA na corrida: %.1f m, %d chamadas\n",
                   app.race.competidores[size_t(ia)].s_total, app.py_driver->call_count());
        }
        CHECK(!app.race.hud_lines().empty(), "HUD da corrida vazio");
        std::string classificacao;
        for (const std::string& l : app.race.hud_lines()) classificacao += l + "\n";
        CHECK(classificacao.find("m") != std::string::npos, "HUD sem distância");
    }

    }

    // ------------------------------------------ 6. treino comandado pela IA
    if (secao(6)) {
    printf("6. treino com a IA em Python no carro de foco\n");
    {
        app.train_cfg.individuals = 12;
        app.train_cfg.generations = 2;
        app.train_cfg.seconds = 6.0;
        app.aplicar_treino_cfg(app.train_cfg);
        app.iniciar_treino(true);
        CHECK(app.treino_acabou() == false || app.geracao >= 2, "estado inicial estranho");
        int guarda = 0;
        while (app.treinando && guarda < 200000) { app.tick_treino(30); guarda += 1; }
        CHECK(app.geracao >= 2, "o treino não avançou 2 gerações (ficou em %d)", app.geracao);
        CHECK(app.loss_history.size() == size_t(app.geracao), "histórico de loss desalinhado");
        CHECK(app.erro_history.size() == app.loss_history.size(), "histórico de erro desalinhado");
        CHECK(!app.loss_history.empty(), "sem loss registrada");
        std::string hud;
        for (const std::string& l : app.treino_lines()) hud += l + "\n";
        CHECK(hud.find("loss") != std::string::npos, "HUD do treino sem loss");
        CHECK(hud.find("erro") != std::string::npos, "HUD do treino sem erro %%");
        // a IA em Python continuou sendo chamada durante o treino?
        if (tem_python && app.py_driver) {
            CHECK(app.py_driver->call_count() > 10,
                  "a IA não foi usada no treino: %d chamadas", app.py_driver->call_count());
        }
    }

    }

    // ---------------------------------------------- 7. modelo e recompensa
    if (secao(7)) {
    printf("7. salvar/carregar modelo e sliders de recompensa\n");
    {
        if (!app.trainer) app.iniciar_treino(true);
        const std::string arq = tmp_file("raceai_integrado_modelo.json");
        CHECK(app.salvar_modelo(arq, &err), "não salvou o modelo: %s", err.c_str());
        CHECK(!ler(arq).empty(), "arquivo do modelo vazio");
        CHECK(app.carregar_modelo(arq, &err), "não carregou o modelo: %s", err.c_str());

        RewardConfig r = app.reward;
        r.crash = 2.5;
        r.speed = 1.2;
        app.aplicar_recompensa(r);
        CHECK(app.reward.crash == 2.5 && app.reward.speed == 1.2, "recompensa não aplicada");
        if (app.trainer && !app.trainer->shards.empty())
            CHECK(app.trainer->shards[0]->reward.crash == 2.5,
                  "a recompensa não chegou na simulação");
    }
    }

    // ------------------------- 8. modelos prontos na pasta modelos/ entram no grid
    if (secao(8)) {
    printf("8. modelos prontos entram na corrida\n");
    {
        std::vector<std::string> prontos = list_models();
        if (prontos.empty()) {
            printf("   (pulando: nenhum modelo em modelos/ — rode o treinador)\n");
        } else {
            CHECK(prontos.size() <= 4, "mais de 4 modelos: %zu", prontos.size());
            app.iniciar_corrida({});
            int n_modelo = 0;
            for (const Competitor& c : app.race.competidores)
                if (c.origem == "modelo") n_modelo += 1;
            CHECK(n_modelo > 0, "os modelos prontos não entraram no grid");
            CHECK(size_t(n_modelo) == prontos.size(),
                  "entraram %d modelos, a pasta tem %zu", n_modelo, prontos.size());
            race_set_human(0.0, 0.0);
            for (int i = 0; i < 1200; ++i) app.tick_corrida(4);
            double melhor = 0.0;
            for (const Competitor& c : app.race.competidores)
                if (c.origem == "modelo") melhor = std::max(melhor, c.s_total);
            CHECK(melhor > 30.0, "o modelo treinado andou pouco: %.1f m", melhor);
            printf("   %d modelo(s) no grid, melhor %.1f m\n", n_modelo, melhor);
        }
    }
    }

    // o GIL (real ou falso) precisa estar equilibrado no fim: sem vazamento
    if (stub && *stub) {
        int pendente = stub_gil(stub);
        CHECK(pendente == 0, "chaves do GIL desequilibradas: %d pendente(s)", pendente);
    }

    printf("\n%d verificações passaram, %d falharam\n", ok, falhas);
    if (!tem_python)
        printf("(parte de Python pulada: rode com RACEAI_STUB_PYTHON ou passe o caminho da dll)\n");
    if (!falhas) return 0;
    // Devolve qual verificação falhou: o CI mostra "exit code N" e, com
    // --secao, N-200 é a contagem da verificação dentro daquela seção.
    if (g_foco) return 200 + (g_primeira_falha > 50 ? 50 : g_primeira_falha);
    return 1;
}
