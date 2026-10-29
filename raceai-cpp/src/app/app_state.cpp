#include "app_state.hpp"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <chrono>
#include <sstream>

namespace raceai {

// ------------------------------------------------------------------ ajuda
std::string ajuda_python() {
    return
        "A IA é uma função Python. Ela recebe a leitura dos sensores e devolve "
        "dois números (esterço, acelerador), ambos entre -1 e 1.\n\n"
        "    def dirigir(sensores):\n"
        "        ...\n"
        "        return esterco, acelerador\n\n"
        "Índices de `sensores` (24 valores, todos normalizados):\n"
        "   0..8    nove raios do para-choque, da esquerda para a direita\n"
        "           (1.0 = 70 m livre, 0.0 = colado no muro)\n"
        "   9       velocidade / velocidade máxima do carro\n"
        "   10      velocidade longitudinal (m/s, normalizada)\n"
        "   11      velocidade lateral\n"
        "   12      taxa de guinada\n"
        "   13      esterço atual\n"
        "   14      deslocamento lateral na pista (+ esquerda, - direita)\n"
        "   15      erro de direção em relação à pista\n"
        "   16..19  diferença de direção a 15, 30, 50 e 80 m à frente\n"
        "   20      aderência do piso (1 = asfalto, menor = terra/gelo)\n"
        "   21      uso dos pneus (1 = no limite da aderência)\n"
        "   22      último esterço aplicado\n"
        "   23      último acelerador aplicado\n\n"
        "Dicas: esterço positivo vira para a esquerda; acelerador negativo é "
        "freio. O código é recompilado quando você clica em APLICAR.";
}

std::string exemplo_python() {
    return
        "def dirigir(sensores):\n"
        "    # diferença entre os raios das pontas: para que lado há mais espaço\n"
        "    espaco = sensores[8] - sensores[0]\n"
        "    # olha também os raios mais ao centro para não bater de frente\n"
        "    frente = min(sensores[3], sensores[4], sensores[5])\n"
        "    esterco = (espaco * 2.0 + (sensores[8] - sensores[0])) * 1.5\n"
        "    esterco = max(-1.0, min(1.0, esterco))\n"
        "    # reduz onde a pista fecha (pouca distância à frente)\n"
        "    acelerador = 0.35 + 0.65 * frente\n"
        "    if frente < 0.12:\n"
        "        acelerador = 0.18          # só reduz: dar ré mata a volta\n"
        "    if sensores[14] > 0.85 or sensores[14] < -0.85:\n"
        "        acelerador *= 0.8          # está no limite da pista\n"
        "    return esterco, acelerador\n";
}

// ------------------------------------------------------------------ corrida
void Race::setup(const Track& track, const std::vector<CarSpec>& cars,
                 const SimConfig& cfg, const RewardConfig& rw, int seed) {
    const int n = std::max(1, int(competidores.size()));
    sim = std::make_unique<Simulation>(track, cars.empty() ? CarSpec() : cars[0], cfg, n,
                                       uint32_t(seed));
    if (!cars.empty()) {
        std::vector<CarSpec> specs;
        for (const Competitor& c : competidores) specs.push_back(cars[c.carro % cars.size()]);
        sim->set_specs(specs);
    }
    sim->reward = rw;
    sim->cfg.target_laps = laps;
    sim->cfg.max_seconds = time_limit;
    sim->max_steps = int(time_limit / cfg.dt);
    sim->reset(0);
    for (int i = 0; i < sim->n(); ++i) {
        sim->agents[i].agent_id = i;
        competidores[i].voltas = 0;
        competidores[i].terminou = false;
    }
    elapsed = 0.0;
    finished = false;
    update_standings();
}

void Race::add(const Competitor& c) { competidores.push_back(c); }

void Race::restart() {
    if (!sim) return;
    sim->cfg.target_laps = laps;
    sim->cfg.max_seconds = time_limit;
    sim->max_steps = int(time_limit / sim->cfg.dt);
    sim->reset(0);
    for (size_t i = 0; i < competidores.size() && i < size_t(sim->n()); ++i) {
        competidores[i].voltas = 0;
        competidores[i].terminou = false;
        competidores[i].melhor_volta = 1e18;
        competidores[i].batidas = 0;
    }
    elapsed = 0.0;
    finished = false;
    update_standings();
}

static double humano_steer = 0.0, humano_drive = 0.0;

void Race::step(int n) {
    if (!sim || finished) return;
    const int dim = sim->obs_dim;
    std::vector<float> obs(size_t(std::max(1, dim)));
    float act[2] = {0.0f, 0.0f};
    for (int k = 0; k < n; ++k) {
        if (sim->should_decide()) {
            for (int row : sim->active()) {
                if (row >= int(competidores.size())) continue;
                sim->observe(row, obs.data());
                Competitor& c = competidores[row];
                if (c.manual) {
                    act[0] = float(humano_steer);
                    act[1] = float(humano_drive);
                } else if (c.driver) {
                    c.driver->act(obs.data(), dim, act);
                }
                sim->set_action(row, act[0], act[1]);
            }
        }
        sim->step();
        elapsed += sim->cfg.dt;
        if (elapsed >= time_limit || sim->all_dead()) break;
    }
    for (size_t i = 0; i < competidores.size() && i < size_t(sim->n()); ++i) {
        const Agent& a = sim->agents[i];
        Competitor& c = competidores[i];
        c.voltas = a.laps;
        c.s_total = a.max_s;
        c.tempo = a.time;
        c.velocidade = a.car.speed;
        c.ultima_volta = a.last_lap;
        c.melhor_volta = a.best_lap;
        c.batidas = a.crashes;
        c.terminou = a.finished;
        Metrics m = sim->metrics(int(i));
        c.loss = m.loss;
        c.erro_pct = m.error_pct;
    }
    grava_fantasma();
    update_standings();
    bool todos_terminaram = true;
    for (const Competitor& c : competidores) {
        if (!c.terminou && (c.voltas < laps || laps <= 0)) todos_terminaram = false;
    }
    if ((laps > 0 && todos_terminaram) || elapsed >= time_limit || sim->all_dead()) {
        finished = true;
    }
}

void Race::update_standings() {
    ordem.resize(competidores.size());
    for (size_t i = 0; i < ordem.size(); ++i) ordem[i] = int(i);
    std::sort(ordem.begin(), ordem.end(), [&](int a, int b) {
        const Competitor& ca = competidores[a];
        const Competitor& cb = competidores[b];
        if (ca.terminou != cb.terminou) return ca.terminou && !cb.terminou;
        if (ca.voltas != cb.voltas) return ca.voltas > cb.voltas;
        return ca.s_total > cb.s_total;
    });
}

// Telemetria da corrida: setores, delta e "fantasma" (traçado da melhor volta).
// O fantasma é gravado só do carro em foco, a 30 Hz — custo irrelevante e
// permite comparar a volta atual com a melhor desenhada na pista.
int Race::indice_foco() const {
    if (competidores.empty()) return 0;
    for (size_t i = 0; i < competidores.size(); ++i)
        if (competidores[i].manual) return int(i);
    return ordem.empty() ? 0 : ordem.front();
}

void Race::grava_fantasma() {
    if (!sim) return;
    foco = indice_foco();
    if (foco < 0 || foco >= int(competidores.size()) || foco >= sim->n()) return;
    const Agent& a = sim->agents[foco];
    if (!a.car.alive) return;
    if (melhor_setor.size() != size_t(setores)) melhor_setor.assign(size_t(setores), 1e18);

    // amostra a 30 Hz (a simulação roda a 120 Hz)
    gravando.emplace_back(float(a.car.x), float(a.car.y));

    if (a.laps > volta_gravada) {
        // fechou a volta: se foi a melhor, vira o fantasma
        if (a.last_lap < melhor_volta_geral && gravando.size() > 30) {
            melhor_volta_geral = a.last_lap;
            fantasma.swap(gravando);
            fantasma_valido = true;
        }
        gravando.clear();
        volta_gravada = a.laps;
        for (size_t k = 0; k < melhor_setor.size() && k < a.melhor_setor.size(); ++k)
            melhor_setor[k] = std::min(melhor_setor[k], a.melhor_setor[k]);
    }
    if (gravando.size() > 20000) gravando.clear();   // segurança
}

static std::string fmt_tempo(double t) {
    if (t >= 1e17) return "--.--";
    char b[32];
    std::snprintf(b, sizeof(b), "%.2f", t);
    return b;
}

std::vector<std::string> Race::hud_lines() const {
    std::vector<std::string> out;
    char buf[160];
    const int fi = indice_foco();

    out.push_back("VOLTA " + std::to_string(laps > 0 ? laps : 0) +
                  (laps > 0 ? "" : "  (tempo livre)"));
    std::snprintf(buf, sizeof(buf), "tempo %6.1f s", elapsed);
    out.push_back(buf);

    if (sim && fi < sim->n() && fi < int(competidores.size())) {
        const Agent& a = sim->agents[fi];
        std::snprintf(buf, sizeof(buf), "volta %d  parcial %s s", a.laps + 1,
                      fmt_tempo(a.time - a.lap_start).c_str());
        out.push_back(buf);

        std::string linha = "setores ";
        for (int k = 0; k < setores; ++k) {
            double ms = (size_t(k) < melhor_setor.size()) ? melhor_setor[size_t(k)] : 1e18;
            linha += (k == a.setor ? ">" : " ") + fmt_tempo(ms) + " ";
        }
        out.push_back(linha);
        std::snprintf(buf, sizeof(buf), "última %s  melhor %s", fmt_tempo(a.last_lap).c_str(),
                      fmt_tempo(a.best_lap).c_str());
        out.push_back(buf);
        std::snprintf(buf, sizeof(buf), "delta %+.2f s   setor %d", a.delta, a.setor + 1);
        out.push_back(buf);

        out.push_back("--- carro ---");
        std::snprintf(buf, sizeof(buf), "marcha %d    %5.0f rpm", a.car.gear, a.car.rpm);
        out.push_back(buf);
        std::snprintf(buf, sizeof(buf), "%5.1f m/s  (%3.0f km/h)", a.car.speed,
                      a.car.speed * 3.6);
        out.push_back(buf);
        std::snprintf(buf, sizeof(buf), "pneu %3.0f C  desgaste %2.0f%%", a.car.tire_temp,
                      a.car.tire_wear * 100.0);
        out.push_back(buf);
        std::snprintf(buf, sizeof(buf), "dano %2.0f%%  tanque %3.0f%%", a.car.damage * 100.0,
                      a.car.fuel * 100.0);
        out.push_back(buf);
        std::snprintf(buf, sizeof(buf), "aderência %3.0f%%  patina %2.0f%%",
                      std::min(a.car.grip_use, 2.0) * 100.0, a.car.wheelspin * 100.0);
        out.push_back(buf);
        if (fantasma_valido) {
            std::snprintf(buf, sizeof(buf), "fantasma %s s (%zu pts)",
                          fmt_tempo(melhor_volta_geral).c_str(), fantasma.size());
            out.push_back(buf);
        }
    }

    out.push_back("--- classificação ---");
    for (size_t k = 0; k < ordem.size() && k < 8; ++k) {
        const Competitor& c = competidores[ordem[k]];
        std::snprintf(buf, sizeof(buf), "%zu. %-15s %2d v %5.1f m/s %4.1f%%", k + 1,
                      c.nome.c_str(), c.voltas, c.velocidade, c.erro_pct);
        out.push_back(buf);
    }
    return out;
}

// expõe o controle manual para a camada de janela
void race_set_human(double steer, double drive) {
    humano_steer = steer;
    humano_drive = drive;
}
void race_get_human(double* steer, double* drive) {
    if (steer) *steer = humano_steer;
    if (drive) *drive = humano_drive;
}

// ------------------------------------------------------------------ app
AppState::AppState() {
    pistas = list_tracks();
    carros = list_cars();
    // kartódromo e kart são o padrão (os mais fáceis de aprender)
    for (size_t i = 0; i < pistas.size(); ++i) if (pistas[i].id == "kartodromo") pista_idx = int(i);
    for (size_t i = 0; i < carros.size(); ++i) if (carros[i].id == "kart") carro_idx = int(i);
    std::string err;
    if (!pistas.empty()) load_track(pistas[pista_idx].id, track_cache_, &err);
    if (!carros.empty()) load_car(carros[carro_idx].id, car_cache_, &err);
    policy.obs_dim = sim_cfg.n_rays + 15;
    policy.hidden = {64, 64};
    python_code = exemplo_python();
    // preferências do jogador ficam num JSON ao lado do executável
    controles_path = assets_root() + "/controles.json";
    carregar_controles();
}

bool AppState::carregar_pista(int idx) {
    if (idx < 0 || idx >= int(pistas.size())) return false;
    std::string err;
    if (!load_track(pistas[idx].id, track_cache_, &err)) return false;
    pista_idx = idx;
    return true;
}

bool AppState::carregar_carro(int idx) {
    if (idx < 0 || idx >= int(carros.size())) return false;
    std::string err;
    if (!load_car(carros[idx].id, car_cache_, &err)) return false;
    carro_idx = idx;
    if (trainer) trainer->set_car(car_cache_);
    return true;
}

void AppState::aplicar_recompensa(const RewardConfig& r) {
    reward = r;
    if (trainer) trainer->set_reward(r);
    if (race.sim) race.sim->reward = r;
}

void AppState::aplicar_treino_cfg(const TrainSettings& t) {
    train_cfg = t;
    ga_cfg.population = std::max(2, int(t.individuals));
    sim_cfg.max_seconds = t.seconds;
    sim_cfg.target_laps = t.laps;
    int h1 = std::max(8, int(t.hidden));
    policy.hidden = {h1, std::max(8, h1 / 2)};
    ga_cfg.genes_mutados = std::max(0, int(t.genes_mutados));
    if (trainer) {
        trainer->sim_cfg = sim_cfg;
        trainer->policy = policy;
        trainer->pop.spec = policy;
        for (auto& s : trainer->shards) {
            s->cfg = sim_cfg;
            s->max_steps = int(sim_cfg.max_seconds / sim_cfg.dt);
        }
        if (trainer->pop.n() != int(t.individuals)) trainer->set_population(int(t.individuals));
    }
}

// ------------------------------------------------------------- controles
// As assistências são uma escolha do jogador, não do carro: o que vale é o
// que está marcado na interface (e fica salvo).
void AppState::aplicar_assistencias() {
    if (!race.sim) return;
    const int fi = race.indice_foco();
    if (fi < 0 || fi >= race.sim->n()) return;
    CarSpec& sp = race.sim->specs[size_t(fi)];
    sp.abs_level = controles.abs ? 0.9 : 0.0;
    sp.traction_control = controles.controle_tracao ? 0.6 : 0.0;
}

bool AppState::salvar_controles() const {
    if (controles_path.empty()) return false;
    std::string err;
    if (!controles.save(controles_path, &err)) {
        fprintf(stderr, "controles: %s\n", err.c_str());
        return false;
    }
    return true;
}

bool AppState::carregar_controles() {
    if (controles_path.empty()) return false;
    std::string err;
    ControlSettings c;
    if (!ControlSettings::load(controles_path, c, &err)) return false;
    controles = c;
    return true;
}

// ------------------------------------------------------------- relógio/ETA
double AppState::agora_segundos() {
    return double(std::chrono::steady_clock::now().time_since_epoch().count()) *
           double(std::chrono::steady_clock::period::num) /
           double(std::chrono::steady_clock::period::den);
}

// ------------------------------------------------------------- controles
Json ControlSettings::to_json() const {
    Json j = Json::object();
    j.set("sensibilidade", Json(sensibilidade));
    j.set("zona_morta", Json(zona_morta));
    j.set("gamma", Json(gamma));
    j.set("retorno", Json(retorno));
    j.set("suavizar", Json(suavizar ? 1.0 : 0.0));
    j.set("abs", Json(abs ? 1.0 : 0.0));
    j.set("controle_tracao", Json(controle_tracao ? 1.0 : 0.0));
    return j;
}

ControlSettings ControlSettings::from_json(const Json& j) {
    ControlSettings c;
    if (j.has("sensibilidade")) c.sensibilidade = clamp(j.at("sensibilidade").num(1.0), 0.2, 2.5);
    if (j.has("zona_morta")) c.zona_morta = clamp(j.at("zona_morta").num(0.02), 0.0, 0.3);
    if (j.has("gamma")) c.gamma = clamp(j.at("gamma").num(1.0), 0.5, 2.5);
    if (j.has("retorno")) c.retorno = clamp(j.at("retorno").num(1.0), 0.3, 3.0);
    if (j.has("suavizar")) c.suavizar = j.at("suavizar").num(1.0) > 0.5;
    if (j.has("abs")) c.abs = j.at("abs").num(0.0) > 0.5;
    if (j.has("controle_tracao")) c.controle_tracao = j.at("controle_tracao").num(0.0) > 0.5;
    return c;
}

bool ControlSettings::save(const std::string& path, std::string* err) const {
    if (!Json::save_file(path, to_json())) {
        if (err) *err = "não foi possível gravar: " + path;
        return false;
    }
    return true;
}

bool ControlSettings::load(const std::string& path, ControlSettings& out, std::string* err) {
    Json j;
    if (!Json::load_file(path, j, err)) return false;
    out = from_json(j);
    return true;
}

// ------------------------------------------------------------- chave de modo
void AppState::alternar_modo() {
    if (mode == Mode::Corrida) {
        if (!trainer) criar_trainer();
        mode = Mode::Treinamento;
        return;
    }
    // indo para a corrida: monta o grid só se ainda nao existir, assim a
    // corrida continua de onde parou quando voce volta
    if (!race.sim) {
        iniciar_corrida({});
        return;
    }
    mode = Mode::Corrida;
}

void AppState::criar_trainer() {
    TrainerConfig tc;
    tc.seed = 12345;
    tc.threads = 0;
    ga_cfg.population = std::max(2, int(train_cfg.individuals));
    sim_cfg.max_seconds = train_cfg.seconds;
    sim_cfg.target_laps = int(train_cfg.laps);
    trainer = std::make_unique<Trainer>(track_cache_, car_cache_, sim_cfg, ga_cfg, policy, tc);
    trainer->set_reward(reward);
    trainer->generation = 0;
    geracao = 0;
}

// Tempo estimado para terminar todas as gerações: média do que já rodou.
void AppState::marca_geracao() {
    const double agora = agora_segundos();
    if (t0_geracao > 0.0) {
        const double dt = agora - t0_geracao;
        if (dt > 0.0 && dt < 600.0) {
            tempos_geracao.push_back(dt);
            if (tempos_geracao.size() > 30) tempos_geracao.erase(tempos_geracao.begin());
        }
    }
    t0_geracao = agora;
}

double AppState::eta_segundos() const {
    if (!treinando || geracao <= 0 || tempos_geracao.empty()) return -1.0;
    double soma = 0.0;
    for (double t : tempos_geracao) soma += t;
    const double media = soma / double(tempos_geracao.size());
    const int faltam = std::max(0, int(train_cfg.generations) - geracao);
    return media * double(faltam);
}

void AppState::iniciar_treino(bool novo) {
    if (pistas.empty() || carros.empty()) return;
    if (!trainer || novo) criar_trainer();
    if (python_enabled && py_driver) trainer->set_driver(py_driver);
    else trainer->set_driver(nullptr);
    loss_history.clear();
    erro_history.clear();
    dist_history.clear();
    tempo_treino = 0.0;
    treinando = true;
    ui.pausado = false;
    trainer->generations_enabled = true;
    trainer->start_episode();
}

void AppState::parar_treino() { treinando = false; }

bool AppState::treino_acabou() const {
    return geracao >= int(train_cfg.generations);
}

void AppState::tick_treino(int passos) {
    if (!trainer || !treinando || ui.pausado) return;
    for (int k = 0; k < passos; ++k) {
        trainer->step(1);
        if (trainer->episode_done()) {
            GenHistory h = trainer->finish_episode(true);
            ultima = h;
            geracao = h.generation + 1;
            marca_geracao();
            loss_history.push_back(h.best_loss);
            erro_history.push_back(h.best_error_pct);
            dist_history.push_back(h.best_distance);
            if (geracao >= int(train_cfg.generations)) { treinando = false; }
            break;
        }
    }
    tempo_treino += passos * sim_cfg.dt;
}

bool AppState::salvar_modelo(const std::string& path, std::string* err) const {
    if (!trainer) {
        if (err) *err = "treine ou carregue um modelo primeiro";
        return false;
    }
    return trainer->save_best(path, err);
}

bool AppState::carregar_modelo(const std::string& path, std::string* err) {
    if (!trainer) criar_trainer();
    bool ok = trainer->load_model(path, err);
    if (ok) geracao = 0;
    return ok;
}

// ------------------------------------------------------------------ python
bool AppState::python_disponivel() const {
    return py_driver && py_driver->runtime_loaded();
}

bool AppState::aplicar_codigo_python(const std::string& codigo) {
    python_code = codigo;
    if (!py_driver) {
        py_driver = std::make_shared<PyDriver>();
        std::string err;
        if (!py_driver->load_runtime(python_runtime_path, &err)) {
            python_status = "Python não encontrado: " + err;
            python_enabled = false;
            return false;
        }
    }
    std::string err;
    if (!py_driver->set_code(codigo, &err)) {
        python_status = err;
        python_enabled = false;
        return false;
    }
    python_status = "código aplicado (" + std::to_string(py_driver->call_count()) + " chamadas)";
    python_enabled = true;
    if (trainer) trainer->set_driver(py_driver);
    return true;
}

// ----------------------------------------------------- importar/salvar .py
bool AppState::importar_python(const std::string& path, std::string* err) {
    std::ifstream in(path.c_str(), std::ios::binary);
    if (!in) {
        if (err) *err = "não foi possível abrir: " + path;
        python_status = err ? *err : std::string("não foi possível abrir o arquivo");
        return false;
    }
    std::ostringstream ss;
    ss << in.rdbuf();
    std::string codigo = ss.str();
    if (codigo.empty()) {
        if (err) *err = "o arquivo está vazio: " + path;
        python_status = "o arquivo .py está vazio";
        return false;
    }
    // aceita tanto \n quanto \r\n (arquivo feito no Bloco de Notas)
    std::string limpo;
    limpo.reserve(codigo.size());
    for (char c : codigo) {
        if (c == '\r') continue;
        limpo.push_back(c);
    }
    python_code = limpo;
    if (!aplicar_codigo_python(limpo)) {
        if (err) *err = python_status;
        return false;
    }
    return true;
}

bool AppState::salvar_python(const std::string& path, std::string* err) const {
    std::ofstream out(path.c_str(), std::ios::binary);
    if (!out) {
        if (err) *err = "não foi possível gravar: " + path;
        return false;
    }
    const std::string& c = python_code.empty() ? exemplo_python() : python_code;
    out << c;
    if (!out) {
        if (err) *err = "falha ao gravar: " + path;
        return false;
    }
    return true;
}

// ------------------------------------------------------------------ corrida
void AppState::iniciar_corrida(const std::vector<std::string>& modelos_in) {
    if (pistas.empty() || carros.empty()) return;
    // sem modelo escolhido, usamos os que estiverem prontos na pasta modelos/
    std::vector<std::string> modelos = modelos_in;
    if (modelos.empty()) modelos = list_models();
    if (modelos.size() > 4) modelos.resize(4);      // deixa espaço no grid
    race.competidores.clear();
    race.laps = 3;
    race.time_limit = 300.0;

    Competitor voce;
    voce.nome = "Você";
    voce.origem = "teclado";
    voce.manual = true;
    voce.carro = carro_idx;
    race.add(voce);

    for (size_t i = 0; i < modelos.size(); ++i) {
        Competitor c;
        c.nome = base_name(modelos[i]);
        c.origem = "modelo";
        c.carro = int(i + 1) % std::max<size_t>(1, carros.size());
        auto d = std::make_shared<PolicyDriver>();
        Model m;
        std::string err;
        if (Model::load(modelos[i], m, &err)) {
            d = std::make_shared<PolicyDriver>(m.spec, m.weights);
            c.nome = m.meta.has("car") ? m.meta.at("car").str() : c.nome;
        }
        c.driver = d;
        race.add(c);
    }
    if (python_enabled && py_driver) {
        Competitor c;
        c.nome = "Sua IA";
        c.origem = "python";
        c.carro = carro_idx;
        c.driver = py_driver;
        race.add(c);
    }
    // completa o grid com o melhor indivíduo da evolução atual
    if (trainer && race.competidores.size() < 6) {
        Competitor c;
        c.nome = "Evolução";
        c.origem = "evolução";
        c.carro = carro_idx;
        c.driver = std::make_shared<PolicyDriver>(trainer->policy, trainer->best_weights());
        race.add(c);
    }

    std::vector<CarSpec> specs;
    for (const Competitor& c : race.competidores) {
        CarSpec sp = car_cache_;
        if (c.carro != carro_idx) {
            std::string err;
            load_car(carros[c.carro % carros.size()].id, sp, &err);
        }
        specs.push_back(sp);
    }
    race.setup(track_cache_, specs, sim_cfg, reward, 4242);
    aplicar_assistencias();          // ABS/controle de tração escolhidos pelo jogador
    race.restart();
    mode = Mode::Corrida;
}

void AppState::tick_corrida(int passos) {
    if (race.finished) return;
    race.step(passos);
}

// ------------------------------------------------------------------ HUD
std::vector<std::string> AppState::hud_lines() const {
    std::vector<std::string> out;
    out.push_back("Pista: " + (pistas.empty() ? "-" : pistas[pista_idx].name));
    out.push_back("Carro: " + (carros.empty() ? "-" : carros[carro_idx].name));
    return out;
}

std::vector<std::string> AppState::treino_lines() const {
    std::vector<std::string> out;
    char buf[192];
    if (!trainer) {
        out.push_back("treino parado");
        return out;
    }
    Simulation::Stats st;
    int vivos = 0, total = 0;
    for (const auto& s : trainer->shards) {
        Simulation::Stats x = s->stats();
        vivos += x.alive;
        total += s->n();
        st.best_distance = std::max(st.best_distance, x.best_distance);
        st.best_laps = std::max(st.best_laps, x.best_laps);
        st.avg_speed = std::max(st.avg_speed, x.avg_speed);
    }
    std::snprintf(buf, sizeof(buf), "geração %d / %d   vivos %d/%d", geracao,
                  int(train_cfg.generations), vivos, total);
    out.push_back(buf);
    {
        const double eta = eta_segundos();
        if (eta >= 0.0) {
            int m = int(eta) / 60, s2 = int(eta) % 60;
            std::snprintf(buf, sizeof(buf), "ETA %dm %02ds  (faltam %d gerações)", m, s2,
                          std::max(0, int(train_cfg.generations) - geracao));
        } else {
            std::snprintf(buf, sizeof(buf), "ETA -- (ainda sem histórico)");
        }
        out.push_back(buf);
    }
    out.push_back("--- métricas do melhor (agora) ---");
    int best_row = -1;
    double best_fit = -1e18;
    for (const auto& s : trainer->shards) {
        for (int r = 0; r < s->n(); ++r) {
            if (s->agents[r].fitness > best_fit) { best_fit = s->agents[r].fitness; best_row = r; }
        }
    }
    if (best_row >= 0) {
        const Simulation* s = nullptr;
        for (const auto& sh : trainer->shards) {
            if (best_row < sh->n()) { s = sh.get(); break; }
        }
        if (s) {
            Metrics m = s->metrics(best_row);
            std::snprintf(buf, sizeof(buf), "loss        %.4f", m.loss);
            out.push_back(buf);
            std::snprintf(buf, sizeof(buf), "erro        %.1f %%", m.error_pct);
            out.push_back(buf);
            std::snprintf(buf, sizeof(buf), "velocidade  %.1f m/s  (%.0f km/h)",
                          m.mean_speed, m.mean_speed * 3.6);
            out.push_back(buf);
            std::snprintf(buf, sizeof(buf), "distância   %.0f m  (%.2f voltas)", m.distance,
                          m.distance / std::max(1.0, track_cache_.length));
            out.push_back(buf);
            std::snprintf(buf, sizeof(buf), "progresso   %3.0f %%   precisão %3.0f %%",
                          m.progress_score * 100.0, m.precision_score * 100.0);
            out.push_back(buf);
            std::snprintf(buf, sizeof(buf), "vel. suavidade %3.0f %%", m.smooth_score * 100.0);
            out.push_back(buf);
        }
    }
    if (!loss_history.empty()) {
        std::snprintf(buf, sizeof(buf), "melhor loss %.4f | melhor erro %.1f %%",
                      ultima.best_loss, ultima.best_error_pct);
        out.push_back("--- última geração ---");
        out.push_back(buf);
        std::snprintf(buf, sizeof(buf), "distância %.0f m | %.2f voltas | %.1f m/s",
                      ultima.best_distance, ultima.best_laps, ultima.best_speed);
        out.push_back(buf);
    }
    if (python_enabled) {
        out.push_back("IA em Python ativa" +
                      (py_driver ? " (" + std::to_string(py_driver->call_count()) + " chamadas, " +
                                       std::to_string(int(py_driver->last_call_ms() * 100) / 100.0) + " ms)" : ""));
    }
    return out;
}

std::string AppState::titulo() const {
    switch (mode) {
        case Mode::Menu: return "menu";
        case Mode::Corrida: return "corrida";
        case Mode::Treinamento: return "treinamento";
    }
    return "";
}

}  // namespace raceai
