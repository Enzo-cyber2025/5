// app_state.hpp — estado do jogo (modos, corrida, treino, HUD).
//
// Não depende de janelas: toda a lógica da interface vive aqui, então pode ser
// testada sem abrir nada (tests/test_app.cpp). A camada Win32 só desenha.
#pragma once

#include <memory>
#include <string>
#include <vector>

#include "../core/assets.hpp"
#include "../core/driver.hpp"
#include "../core/py_driver.hpp"
#include "../core/trainer.hpp"

namespace raceai {

enum class Mode { Menu, Corrida, Treinamento };

// ------------------------------------------------------------------ corrida
struct Competitor {
    std::string nome;
    std::string origem;            // "você", "modelo", "python", "piloto automático"
    int carro = 0;                 // índice na lista de carros
    std::shared_ptr<Driver> driver;
    bool manual = false;
    // progresso
    int voltas = 0;
    double s_total = 0.0;
    double tempo = 0.0;
    double velocidade = 0.0;
    double ultima_volta = 0.0;
    double melhor_volta = 1e18;
    double loss = 0.0;
    double erro_pct = 100.0;
    int batidas = 0;
    bool terminou = false;
};

class Race {
public:
    Race() = default;
    void setup(const Track& track, const std::vector<CarSpec>& cars,
               const SimConfig& cfg, const RewardConfig& reward, int seed);
    void add(const Competitor& c);
    void restart();
    void step(int n = 1);
    bool running = false;
    bool finished = false;
    int laps = 3;
    double time_limit = 240.0;
    double elapsed = 0.0;

    std::vector<Competitor> competidores;
    std::unique_ptr<Simulation> sim;
    std::vector<int> ordem;            // classificação (índices em competidores)
    void update_standings();
    std::vector<std::string> hud_lines() const;
};

// controle do carro humano (a camada de janela escreve aqui a cada frame)
void race_set_human(double steer, double drive);
void race_get_human(double* steer, double* drive);

// ------------------------------------------------------------------ treino
// Números em `double` porque cada campo é ligado direto a um slider.
struct TrainSettings {
    double individuals = 60;
    double generations = 200;
    double seconds = 60.0;
    double laps = 0;
    double hidden = 64;
};

struct UiSettings {
    bool mostrar_raios = true;
    bool mostrar_hud = true;
    bool seguir_melhor = true;
    bool pausado = false;
    double zoom = 1.0;
    double velocidade_sim = 4;    // multiplicador de passos por frame
};

// ------------------------------------------------------------------ app
class AppState {
public:
    AppState();

    // assets
    std::vector<AssetItem> pistas;
    std::vector<AssetItem> carros;
    int pista_idx = 0;
    int carro_idx = 0;

    Mode mode = Mode::Menu;
    Track track_cache_;                 // pista atual (a simulação guarda referência)
    CarSpec car_cache_;                 // carro atual
    SimConfig sim_cfg;
    RewardConfig reward;
    GAConfig ga_cfg;
    PolicySpec policy;
    TrainSettings train_cfg;
    UiSettings ui;

    std::unique_ptr<Trainer> trainer;
    Race race;

    // IA em Python colada pelo usuário
    std::string python_code;
    std::string python_runtime_path;   // vazio = procura o python padrão
    bool python_enabled = false;
    std::string python_status;
    std::shared_ptr<PyDriver> py_driver;

    // manual (teclado) — usado na corrida e no treino
    double humano_esterco = 0.0;
    double humano_acelerador = 0.0;
    bool humano_dirigindo = false;

    int geracao = 0;
    bool treinando = false;
    double tempo_treino = 0.0;
    std::vector<double> loss_history;    // curva de loss (melhor de cada geração)
    std::vector<double> erro_history;    // curva de erro %
    std::vector<double> dist_history;
    GenHistory ultima;

    // ---------------------------------------------------------------- setup
    bool carregar_pista(int idx);
    bool carregar_carro(int idx);
    void aplicar_recompensa(const RewardConfig& r);
    void aplicar_treino_cfg(const TrainSettings& t);

    // ---------------------------------------------------------------- treino
    void iniciar_treino(bool novo = true);
    void parar_treino();
    void tick_treino(int passos);        // chamado a cada frame
    bool treino_acabou() const;

    // ---------------------------------------------------------------- python
    bool aplicar_codigo_python(const std::string& codigo);
    bool python_disponivel() const;

    // ---------------------------------------------------------------- corrida
    void iniciar_corrida(const std::vector<std::string>& modelos = {});
    void tick_corrida(int passos);

    // ---------------------------------------------------------------- HUD
    std::vector<std::string> hud_lines() const;
    std::vector<std::string> treino_lines() const;
    std::string titulo() const;

    // modelo
    bool salvar_modelo(const std::string& path, std::string* err) const;
    bool carregar_modelo(const std::string& path, std::string* err);

private:
    void criar_trainer();
};

// texto de ajuda do campo de código Python (índices dos sensores)
std::string ajuda_python();
std::string exemplo_python();

}  // namespace raceai
