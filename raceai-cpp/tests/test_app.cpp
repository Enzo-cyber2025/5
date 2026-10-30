// test_app.cpp — testes da camada de interface (sem abrir janela).
#include <cmath>
#include <fstream>
#include <cstdio>
#include <string>

#include "../src/app/app_state.hpp"
#include "../src/core/ga.hpp"

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

    // ------------------------------------------- controles do jogador
    {
        ControlSettings c;
        c.sensibilidade = 1.7;
        c.zona_morta = 0.12;
        c.gamma = 1.8;
        c.retorno = 2.2;
        c.abs = true;
        c.controle_tracao = true;
        const std::string arq = tmp_file("raceai_controles.json");
        std::string err;
        CHECK(c.save(arq, &err), "não gravou os controles: %s", err.c_str());
        ControlSettings lido;
        CHECK(ControlSettings::load(arq, lido, &err), "não leu os controles: %s", err.c_str());
        CHECK(std::fabs(lido.sensibilidade - 1.7) < 1e-9, "sensibilidade perdida");
        CHECK(std::fabs(lido.zona_morta - 0.12) < 1e-9, "zona morta perdida");
        CHECK(std::fabs(lido.gamma - 1.8) < 1e-9, "gamma perdido");
        CHECK(std::fabs(lido.retorno - 2.2) < 1e-9, "retorno perdido");
        CHECK(lido.abs && lido.controle_tracao, "assistências perdidas");
        // saneamento: valores absurdos são limitados, não quebram o jogo
        Json ruim = Json::object();
        ruim.set("sensibilidade", Json(99.0));
        ruim.set("zona_morta", Json(-5.0));
        ControlSettings san = ControlSettings::from_json(ruim);
        CHECK(san.sensibilidade <= 2.5, "sensibilidade não foi limitada");
        CHECK(san.zona_morta >= 0.0, "zona morta negativa");
    }

    // ------------------------------------------- mutação por contagem
    {
        GAConfig g;
        g.mutation_rate = 1.0;              // todos os genes sorteados
        g.mutation_sigma = 0.5;
        g.reset_mutation_chance = 0.0;      // sem reset, para contar direito
        // uma "rede" de 500 pesos em uma única fatia, para contar os genes
        PolicySpec sp;
        sp.obs_dim = 500;
        sp.act_dim = 2;
        sp.hidden = {};
        Population pop(sp, g, 12345);
        std::vector<float> base(size_t(sp.n_params()), 0.5f);
        g.genes_mutados = 4;
        pop.cfg = g;
        std::vector<float> m4 = pop.mutate(base, 1.0);
        int diferentes = 0;
        for (size_t i = 0; i < base.size(); ++i)
            if (m4[i] != base[i]) diferentes += 1;
        CHECK(diferentes > 0 && diferentes <= 4,
              "mutação de 4 parâmetros alterou %d", diferentes);

        pop.cfg.genes_mutados = 0;          // 0 = todos entram no sorteio
        std::vector<float> mt = pop.mutate(base, 1.0);
        int dif_todos = 0;
        for (size_t i = 0; i < base.size(); ++i)
            if (mt[i] != base[i]) dif_todos += 1;
        CHECK(dif_todos > 50, "mutação geral alterou pouco: %d", dif_todos);
    }

    // ------------------------------------------- ETA do treino
    {
        AppState t;
        CHECK(t.eta_segundos() < 0.0, "ETA deveria ser desconhecido antes de treinar");
        t.iniciar_treino(true);
        for (int i = 0; i < 60 && t.treinando; ++i) {
            t.tick_treino(8);
            if (t.geracao >= 3) break;
        }
        if (t.geracao >= 3) {
            const double eta = t.eta_segundos();
            CHECK(eta >= 0.0, "ETA ficou negativo depois de 3 gerações: %.1f", eta);
            CHECK(eta < 1e6, "ETA absurdo: %.1f", eta);
        }
    }

    // ------------------------------------------- mods fáceis
    {
        // os exemplos precisam existir (é o que o usuário copia e edita)
        AppState m;
        m.garantir_modelos_mod();
        const std::string dir_c = mods_cars_dir();
        const std::string dir_t = mods_tracks_dir();
        if (!dir_c.empty() && !dir_t.empty()) {
            std::ifstream fc(dir_c + "/meu_carro_exemplo.json");
            std::ifstream ft(dir_t + "/minha_pista_exemplo.json");
            if (fc.good() && ft.good()) {
                CarSpec c;
                std::string err;
                CHECK(CarSpec::load(dir_c + "/meu_carro_exemplo.json", c, &err),
                      "exemplo de carro inválido: %s", err.c_str());
                Track t;
                CHECK(Track::load(dir_t + "/minha_pista_exemplo.json", t, &err),
                      "exemplo de pista inválido: %s", err.c_str());
                CHECK(t.valid() && t.length > 200.0, "pista de exemplo curta: %.0f",
                      t.length);
            }
        }
        // recarregar não pode quebrar nada
        size_t antes = m.pistas.size();
        m.pistas = list_tracks();
        m.carros = list_cars();
        CHECK(m.pistas.size() >= antes, "recarregar perdeu pistas");
        for (const auto& it : m.pistas) CHECK(it.error.empty(), "pista %s: %s", it.id.c_str(),
                                              it.error.c_str());
        for (const auto& it : m.carros) CHECK(it.error.empty(), "carro %s: %s", it.id.c_str(),
                                              it.error.c_str());
    }

    // ------------------------------------- modelos pré-definidos (modelos/)
    {
        const std::vector<std::string> prontos = list_models();
        if (prontos.empty()) {
            printf("  (sem modelos em modelos/: nada para verificar)\n");
        } else {
            const std::vector<AssetItem> pistas = list_tracks();
            const std::vector<AssetItem> carros = list_cars();
            printf("  %zu modelo(s) pronto(s)\n", prontos.size());
            for (const std::string& caminho : prontos) {
                const std::string curto = base_name(caminho);
                Model m;
                std::string err;
                if (!Model::load(caminho, m, &err)) {
                    CHECK(false, "modelo %s nao carregou: %s", curto.c_str(), err.c_str());
                    continue;
                }
                CHECK(int(m.weights.size()) == m.spec.n_params(),
                      "modelo %s: %zu pesos para %d parametros", curto.c_str(),
                      m.weights.size(), m.spec.n_params());
                // a interface usa os metadados para escolher carro e pista
                const std::string nome_pista =
                    m.meta.has("track") ? m.meta.at("track").str() : "";
                const std::string nome_carro = m.meta.has("car") ? m.meta.at("car").str() : "";
                CHECK(!nome_pista.empty() && !nome_carro.empty(),
                      "modelo %s sem metadados (pista/carro)", curto.c_str());
                int ip = -1, ic = -1;
                for (size_t k = 0; k < pistas.size(); ++k)
                    if (pistas[k].name == nome_pista) ip = int(k);
                for (size_t k = 0; k < carros.size(); ++k)
                    if (carros[k].name == nome_carro) ic = int(k);
                CHECK(ip >= 0, "modelo %s: pista '%s' nao existe mais", curto.c_str(),
                      nome_pista.c_str());
                CHECK(ic >= 0, "modelo %s: carro '%s' nao existe mais", curto.c_str(),
                      nome_carro.c_str());
                if (ip < 0 || ic < 0) continue;

                Track t;
                CarSpec c;
                CHECK(Track::load(pistas[ip].path, t, &err), "pista %s: %s",
                      nome_pista.c_str(), err.c_str());
                CHECK(CarSpec::load(carros[ic].path, c, &err), "carro %s: %s",
                      nome_carro.c_str(), err.c_str());

                // e o modelo tem de DIRIGIR na pista em que foi treinado
                SimConfig cfg;
                cfg.max_seconds = 90.0;
                cfg.checkpoint_gating = true;
                Simulation sim(t, c, cfg, 1, 3);
                PolicyDriver drv(m.spec, m.weights);
                const int passos = int(90.0 / cfg.dt);
                std::vector<float> obs(sim.obs_dim, 0.0f);
                float saida[2] = {0.0f, 0.0f};
                for (int k = 0; k < passos && !sim.all_dead(); ++k) {
                    if (sim.should_decide()) {
                        sim.observe(0, obs.data());
                        drv.act(obs.data(), sim.obs_dim, saida);
                        sim.set_action(0, saida[0], saida[1]);
                    }
                    sim.step();
                }
                const Agent& a = sim.agents[0];
                CHECK(a.max_s > 120.0, "modelo %s andou pouco: %.0f m", curto.c_str(),
                      a.max_s);
                CHECK(a.laps >= 1, "modelo %s nao completou uma volta em %s (%.0f m)",
                      curto.c_str(), nome_pista.c_str(), a.max_s);
                printf("     %-34s %-22s %5.0f m  %d volta(s)  %.1f s\n", curto.c_str(),
                       nome_carro.c_str(), a.max_s, a.laps,
                       a.best_lap < 1e17 ? a.best_lap : 0.0);
            }
        }
    }

    // ------------------------------------------ gerador de IA (sem programar)
    {
        AppState m;
        PolicySpec p = m.spec_da_ia();
        CHECK(p.hidden.size() == 2 && p.hidden[0] == 64, "padrao deveria ser 64x2");
        CHECK(m.ai_gen.texto() == "64, 64", "texto do gerador: %s", m.ai_gen.texto().c_str());
        CHECK(p.activation == "tanh", "ativacao padrao deveria ser tanh");
        CHECK(m.resumo_da_ia().find("par") != std::string::npos,
              "resumo sem a contagem de parametros: %s", m.resumo_da_ia().c_str());

        // campo livre: quantas camadas quiser, do tamanho que quiser
        CHECK(m.ai_gen.de_texto("256, 128, 64"), "nao aceitou 3 camadas");
        p = m.spec_da_ia();
        CHECK(p.hidden.size() == 3 && p.hidden[0] == 256 && p.hidden[1] == 128 &&
                  p.hidden[2] == 64,
              "camadas livres erradas: %zu", p.hidden.size());
        CHECK(m.ai_gen.de_texto("8"), "nao aceitou uma camada");
        CHECK(m.spec_da_ia().hidden == std::vector<int>({8}), "uma camada so");
        // a chave "tipo de IA": Estrategia liga o boxe (mais entradas e 3 saidas)
        m.ai_gen.tipo = TipoIA::Corrida;
        CHECK(m.spec_da_ia().act_dim == 2, "piloto puro deveria ter 2 saidas");
        const int obs_corrida = m.spec_da_ia().obs_dim;
        m.ai_gen.tipo = TipoIA::Estrategia;
        CHECK(m.spec_da_ia().act_dim == 3, "estrategista deveria ter 3 saidas");
        CHECK(m.spec_da_ia().obs_dim == obs_corrida + 5,
              "estrategista deveria enxergar 5 coisas a mais");
        m.aplicar_ia_gerada();
        CHECK(m.trainer->policy.act_dim == 3, "o treino nao virou estrategista");
        m.ai_gen.tipo = TipoIA::Corrida;
        m.aplicar_ia_gerada();
        CHECK(m.trainer->policy.act_dim == 2, "o treino nao voltou a ser piloto");
        CHECK(!m.ai_gen.de_texto("abc"), "deveria recusar texto sem numero");
        CHECK(m.ai_gen.de_texto("1,2,3,4,5,6,7,8,9,10"), "10 camadas deveria ser aceito");
        CHECK(m.spec_da_ia().hidden.size() == 8, "limite de 8 camadas nao aplicado");
        CHECK(m.ai_gen.de_texto("64"), "reset para 64");
        m.ai_gen.ativacao = "relu";
        p = m.spec_da_ia();
        CHECK(p.hidden.size() == 1 && p.hidden[0] == 64 && p.activation == "relu",
              "rede simples errada: %zu camadas, %s", p.hidden.size(),
              p.activation.c_str());
        // aplicar: o treino passa a usar a rede escolhida
        m.aplicar_ia_gerada();
        CHECK(m.trainer != nullptr, "o gerador nao criou o treino");
        CHECK(m.trainer->policy.hidden == p.hidden, "o treino nao pegou a rede nova");
        CHECK(m.trainer->policy.activation == "relu", "o treino nao pegou a ativacao");
        CHECK(m.trainer->policy.n_params() == p.n_params(), "parametros divergentes");
        CHECK(m.trainer->pop.spec.n_params() == p.n_params(),
              "a populacao ficou com a rede antiga");

        // a ativação muda mesmo a resposta da rede (e a saída continua em [-1,1])
        PolicySpec s1;
        s1.obs_dim = 4;
        s1.hidden = {8};
        s1.act_dim = 2;
        PolicySpec s2 = s1;
        s2.activation = "relu";
        std::vector<float> w(s1.n_params(), 0.0f);
        Rng rng(7);
        for (size_t i = 0; i < w.size(); ++i) w[i] = float(rng.uniform01() * 2.0 - 1.0);
        float obs[4] = {0.3f, -0.2f, 0.5f, 0.1f};
        float o1[2] = {0, 0}, o2[2] = {0, 0};
        forward(s1, w.data(), obs, o1);
        forward(s2, w.data(), obs, o2);
        CHECK(std::fabs(o1[0] - o2[0]) > 1e-6, "relu e tanh deram a mesma resposta");
        CHECK(std::fabs(o2[0]) <= 1.0001 && std::fabs(o2[1]) <= 1.0001,
              "saida fora de [-1,1]: %.3f/%.3f", o2[0], o2[1]);
        // modelo salvo guarda a ativação (para não virar tanh ao recarregar)
        Model mo;
        mo.spec = s2;
        mo.weights = w;
        std::string err;
        CHECK(mo.save(tmp_file("modelo_relu.json").c_str(), &err), "salvar: %s", err.c_str());
        Model mo2;
        CHECK(Model::load(tmp_file("modelo_relu.json").c_str(), mo2, &err), "ler: %s",
              err.c_str());
        CHECK(mo2.spec.activation == "relu", "ativacao nao voltou do arquivo: %s",
              mo2.spec.activation.c_str());
    }

    printf("\n%d testes passaram, %d falharam\n", ok, falhas);
    return falhas ? 1 : 0;
}
