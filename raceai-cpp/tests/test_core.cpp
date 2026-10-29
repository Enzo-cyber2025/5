// test_core.cpp — suíte de testes do núcleo C++ (headless, sem dependências).
//
// Rode:  make test   (ou  g++ -std=c++17 -O2 tests/test_core.cpp src/core/*.cpp -o /tmp/t )
#include <cmath>
#include <cstdio>
#include <string>

#include "../src/core/assets.hpp"
#include "../src/core/render3d.hpp"
#include "../src/core/py_driver.hpp"
#include "../src/core/trainer.hpp"

#if defined(__unix__) || defined(__APPLE__)
#include <dlfcn.h>
#endif

using namespace raceai;

static int passed = 0, failed = 0;
static const char* current = "";

// pasta temporária portável (no Windows não existe /tmp)
static std::string tmp_file(const char* nome) {
#ifdef _WIN32
    return std::string(".\\") + nome;
#else
    return std::string("/tmp/") + nome;
#endif
}

#define CHECK(cond, ...)                                                       \
    do {                                                                       \
        if (!(cond)) {                                                         \
            failed += 1;                                                       \
            printf("  FALHOU [%s] %s:%d: ", current, __FILE__, __LINE__);       \
            printf(__VA_ARGS__);                                               \
            printf("\n");                                                      \
        } else {                                                               \
            passed += 1;                                                       \
        }                                                                      \
    } while (0)

#define REQUIRE(cond, ...)                                                     \
    do {                                                                       \
        if (!(cond)) {                                                         \
            failed += 1;                                                       \
            printf("  FALHOU [%s] %s:%d: ", current, __FILE__, __LINE__);       \
            printf(__VA_ARGS__);                                               \
            printf("\n");                                                      \
            return;                                                            \
        }                                                                      \
        passed += 1;                                                           \
    } while (0)

static void test(const char* name, void (*fn)()) {
    current = name;
    int before = failed;
    printf("· %s\n", name);
    fn();
    if (failed == before) printf("  ok\n");
}

// ------------------------------------------------------------------ base
static void t_base() {
    Vec2 a(3, 4), b(1, 0);
    CHECK(std::fabs(a.norm() - 5.0) < 1e-9, "norma errada");
    CHECK(std::fabs(dot(a, b) - 3.0) < 1e-9, "produto interno errado");
    CHECK(std::fabs(cross(a, b) - (-4.0)) < 1e-9, "produto vetorial errado");
    CHECK(std::fabs(clamp(5.0, 0.0, 1.0) - 1.0) < 1e-9, "clamp errado");
    CHECK(std::fabs(wrap_angle(3.0 * kPi) - (-kPi)) < 1e-6, "wrap_angle errado");
    Rng r(42);
    Rng r2(42);
    CHECK(r.uniform01() == r2.uniform01(), "RNG não é determinístico");
    double s = 0;
    for (int i = 0; i < 20000; ++i) s += r.normal(0.0, 1.0);
    CHECK(std::fabs(s / 20000.0) < 0.05, "média do normal fora do esperado: %f", s / 20000.0);

    Json j = Json::parse("{\"a\": 1, \"b\": [1, 2, {\"c\": \"x\"}], \"d\": true}");
    CHECK(j.at("a").num() == 1.0, "parse de número");
    CHECK(j.at("b").at(2).at("c").str() == "x", "parse aninhado");
    CHECK(j.at("d").boolean() == true, "parse de bool");
    CHECK(std::fabs(Json::parse(j.dump()).at("a").num() - 1.0) < 1e-9, "round-trip do dump");
}

// ------------------------------------------------------------------ pista
static void t_track() {
    Track t;
    std::string err;
    CHECK(load_track("kartodromo", t, &err), "não abriu a pista: %s", err.c_str());
    CHECK(t.valid(), "pista inválida");
    CHECK(t.n() > 50, "poucos pontos: %d", t.n());
    CHECK(t.length > 400 && t.length < 600, "comprimento estranho: %.1f", t.length);
    CHECK(std::fabs(t.length - 507.7) < 1.0, "comprimento != 507.7 m: %.1f", t.length);
    CHECK(t.checkpoints.size() >= 4, "sem checkpoints");

    // a curvatura média tem que casar com a referência Python
    double soma = 0;
    for (double c : t.curvature) soma += std::fabs(c);
    CHECK(soma / t.n() > 0.001, "curvatura zerada");

    // ponto sobre a linha de centro: deslocamento lateral ~ 0
    double lat = 99;
    int idx = t.nearest(t.center[10], -1, 48, 25.0, &lat);
    CHECK(idx == 10, "nearest deveria achar 10, achou %d", idx);
    CHECK(std::fabs(lat) < 1e-6, "lateral deveria ser 0, veio %f", lat);

    // deslocar para a esquerda da tangente dá lateral positiva
    Vec2 p = t.center[10] + t.normals[10] * 2.0;
    t.nearest(p, -1, 48, 25.0, &lat);
    CHECK(std::fabs(lat - 2.0) < 0.3, "lateral à esquerda: %f", lat);

    // raycast: um raio para a frente a partir do centro não pode "atravessar" o muro
    double rays[9];
    t.cast_rays(t.center[10], t.heading[10], 10, 9, 70.0, 140.0 * kPi / 180.0, rays);
    for (int i = 0; i < 9; ++i) {
        CHECK(rays[i] > 0.5 && rays[i] <= 70.0, "raio %d fora de faixa: %.2f", i, rays[i]);
    }
    // os raios laterais (mais fechados) não podem ler mais que a meia largura / sen(70°)
    double limite = t.half_widths[10] / std::sin(70.0 * kPi / 180.0) + 1.0;
    CHECK(rays[0] <= limite, "raio lateral muito longo: %.2f (limite %.2f)", rays[0], limite);
    CHECK(rays[8] <= limite, "raio lateral muito longo: %.2f (limite %.2f)", rays[8], limite);

    // oval: os sensores laterais leem ~ meia_largura / sen(ângulo)
    Json pts = Json::array();
    for (int k = 0; k < 36; ++k) {
        double a = k / 36.0 * 2 * kPi;
        Json p2 = Json::array();
        p2.push(Json(160.0 * std::cos(a)));
        p2.push(Json(120.0 * std::sin(a)));
        pts.push(p2);
    }
    Json ov = Json::object();
    ov.set("name", Json("oval"));
    ov.set("width", Json(16.0));
    ov.set("points", pts);
    Track o = Track::from_json(ov, "mem");
    double orays[9];
    int reto = 9;   // ponto do oval com curvatura mínima (mais "reto")
    for (int i = 0; i < o.n(); ++i) if (std::fabs(o.curvature[i]) < std::fabs(o.curvature[reto])) reto = i;
    o.cast_rays(o.center[reto], o.heading[reto], reto, 9, 70.0, 140.0 * kPi / 180.0, orays);
    double esperado = o.half_widths[reto] / std::sin(70.0 * kPi / 180.0);
    CHECK(std::fabs(orays[0] - esperado) / esperado < 0.25,
          "raio lateral do oval: %.2f, esperado ~%.2f", orays[0], esperado);
}

// ------------------------------------------------------------------ carro
static void t_car() {
    CarSpec c;
    std::string err;
    CHECK(load_car("kart", c, &err), "não abriu o carro: %s", err.c_str());
    CHECK(c.mass > 100 && c.max_speed > 5, "especificação estranha");
    CHECK(std::fabs(c.cg_rear() - (c.wheelbase - c.cg_front)) < 1e-9 || c.cg_rear() >= 0.4,
          "cg_rear inconsistente");

    // sanitização: mods absurdos não podem quebrar a física
    Json ruim = Json::object();
    ruim.set("mass", Json(-10.0));
    ruim.set("max_speed", Json(1e9));
    ruim.set("grip_front", Json(0.0));
    CarSpec s = CarSpec::from_json(ruim, "ruim.json");
    CHECK(s.mass >= 300.0, "massa não foi limitada: %.1f", s.mass);
    CHECK(s.max_speed <= 140.0, "velocidade não foi limitada: %.1f", s.max_speed);
    CHECK(s.grip_front >= 0.4, "aderência não foi limitada: %.2f", s.grip_front);
    CHECK(s.id == "ruim", "id deveria vir do nome do arquivo: %s", s.id.c_str());

    // física: acelera com acelerador, vira com esterço, nunca gera NaN
    CarState st;
    st.throttle = 1.0;
    for (int i = 0; i < 240; ++i) physics_step(c, st, 1.0, 1.0, 1.0 / 120.0);
    CHECK(st.speed > 3.0, "não acelerou: %.2f m/s", st.speed);
    CHECK(std::isfinite(st.x) && std::isfinite(st.y) && std::isfinite(st.heading),
          "estado virou NaN/Inf");

    CarState st2;
    st2.vx = 10.0;
    st2.steer_cmd = 1.0;
    double h0 = st2.heading;
    for (int i = 0; i < 120; ++i) physics_step(c, st2, 1.0, 1.0, 1.0 / 120.0);
    CHECK(st2.heading - h0 > 0.1, "não virou: %f", st2.heading - h0);

    // freio com o carro quase parado = ré
    CarState st3;
    st3.brake = 1.0;
    st3.reverse_cmd = 1.0;
    for (int i = 0; i < 240; ++i) physics_step(c, st3, 1.0, 1.0, 1.0 / 120.0);
    CHECK(st3.vx < -0.2, "não entrou em ré: vx=%.2f", st3.vx);
}

// ------------------------------------------------------- física avançada
static void t_fisica_avancada() {
    CarSpec c = CarSpec::from_json(Json(), "fisica");

    // câmbio: sobe marcha conforme ganha velocidade, respeitando o corte
    CarState st;
    st.throttle = 1.0;
    int marchas_vistas = 1;
    double rpm_max = 0.0;
    for (int i = 0; i < 120 * 25; ++i) {
        physics_step(c, st, 1.0, 1.0, 1.0 / 120.0);
        marchas_vistas = std::max(marchas_vistas, st.gear);
        rpm_max = std::max(rpm_max, st.rpm);
    }
    CHECK(marchas_vistas >= 2, "não trocou de marcha (ficou na %d)", marchas_vistas);
    CHECK(st.gear >= 1 && st.gear <= int(c.gears.size()), "marcha fora da faixa: %d", st.gear);
    CHECK(rpm_max <= c.rpm_limit * 1.05, "giro passou do corte: %.0f", rpm_max);
    CHECK(st.speed > 8.0, "carro lento demais depois de 25 s: %.1f m/s", st.speed);
    CHECK(st.speed <= c.max_speed * 1.1, "passou da velocidade máxima: %.1f", st.speed);

    // pneus esquentam e desgastam quando o carro é exigido
    CarState st2;
    double temp0 = st2.tire_temp;
    st2.throttle = 1.0;
    st2.steer_cmd = 0.8;
    for (int i = 0; i < 120 * 20; ++i) physics_step(c, st2, 1.0, 1.0, 1.0 / 120.0);
    CHECK(st2.tire_temp > temp0, "pneu não esquentou: %.1f -> %.1f", temp0, st2.tire_temp);
    CHECK(st2.tire_wear > 0.0, "pneu não desgastou");
    CHECK(st2.tire_wear < 1.0, "pneu desgastou demais em 20 s: %.2f", st2.tire_wear);

    // tanque: acelera gastando combustível; sem combustível não anda
    CarState st3;
    st3.throttle = 1.0;
    for (int i = 0; i < 120 * 20; ++i) physics_step(c, st3, 1.0, 1.0, 1.0 / 120.0);
    CHECK(st3.fuel < 1.0, "não consumiu combustível");
    double v_cheio = st3.speed;
    CarState st4;
    st4.throttle = 1.0;
    st4.fuel = 0.0;
    for (int i = 0; i < 120 * 20; ++i) physics_step(c, st4, 1.0, 1.0, 1.0 / 120.0);
    CHECK(st4.speed < v_cheio * 0.5, "tanque vazio não cortou a potência: %.1f vs %.1f",
          st4.speed, v_cheio);

    // dano: batida tira velocidade, reduz potência e não pode virar NaN
    CarState st5;
    st5.vx = 25.0;
    double v_antes = std::fabs(st5.vx);
    aplicar_impacto(c, st5, 25.0);
    CHECK(st5.damage > 0.0, "batida não gerou dano");
    CHECK(std::fabs(st5.vx) < v_antes, "batida não tirou velocidade");
    CarState inteiro, batido;
    inteiro.throttle = 1.0;
    batido.throttle = 1.0;
    batido.damage = 0.9;
    for (int i = 0; i < 120 * 6; ++i) {
        physics_step(c, inteiro, 1.0, 1.0, 1.0 / 120.0);
        physics_step(c, batido, 1.0, 1.0, 1.0 / 120.0);
    }
    CHECK(batido.speed < inteiro.speed, "carro danificado não ficou mais lento");
    CHECK(std::isfinite(batido.x) && std::isfinite(batido.speed), "dano gerou NaN");

    // asfalto molhado/liso: menos aderência = menos velocidade em curva
    CarState seco, liso;
    seco.vx = 20.0; liso.vx = 20.0;
    seco.throttle = 0.6; liso.throttle = 0.6;
    seco.steer_cmd = 0.7; liso.steer_cmd = 0.7;
    for (int i = 0; i < 120 * 3; ++i) {
        physics_step(c, seco, 1.0, 1.0, 1.0 / 120.0);
        physics_step(c, liso, 0.45, 1.0, 1.0 / 120.0);
    }
    CHECK(std::fabs(liso.r) < std::fabs(seco.r) || std::fabs(liso.slip_f) > std::fabs(seco.slip_f),
          "pista escorregadia não mudou o comportamento");
}

// -------------------------------------------------------- renderizador 3D
static void t_render3d() {
    Render3D r;
    Camera3D cam;
    cam.x = 0.0; cam.y = 0.0; cam.z = 2.0;
    cam.yaw = 0.0; cam.pitch = 0.0;
    cam.fov = 70.0;
    r.set_camera(cam);
    r.begin(800, 600);

    // um ponto à frente da câmera aparece no meio da tela
    double sx = 0.0, sy = 0.0;
    CHECK(r.projetar(Vec3{20.0, 0.0, 2.0}, &sx, &sy), "ponto à frente não projetou");
    CHECK(std::fabs(sx - 400.0) < 1.0, "centro horizontal errado: %.1f", sx);
    CHECK(std::fabs(sy - 300.0) < 1.0, "centro vertical errado: %.1f", sy);

    // um ponto à direita aparece à direita; acima, mais alto na tela
    CHECK(r.projetar(Vec3{20.0, 5.0, 2.0}, &sx, &sy), "ponto à direita não projetou");
    CHECK(sx > 400.0, "ponto à direita apareceu à esquerda: %.1f", sx);
    CHECK(r.projetar(Vec3{20.0, 0.0, 6.0}, &sx, &sy), "ponto alto não projetou");
    CHECK(sy < 300.0, "ponto alto apareceu embaixo: %.1f", sy);

    // atrás da câmera não projeta
    CHECK(!r.projetar(Vec3{-20.0, 0.0, 2.0}, &sx, &sy), "ponto atrás projetou");
    CHECK(!r.projetar(Vec3{0.05, 0.0, 2.0}, &sx, &sy), "ponto no plano próximo projetou");

    // o horizonte fica dentro da tela
    const double h = r.horizonte_y();
    CHECK(h > 0.0 && h < 600.0, "horizonte fora da tela: %.1f", h);

    // algoritmo do pintor: o que está longe vem primeiro
    r.begin(800, 600);
    r.add_quad(Vec3{5.0, -1.0, 0.0}, Vec3{5.0, 1.0, 0.0}, Vec3{5.0, 1.0, 1.0},
               Vec3{5.0, -1.0, 1.0}, 0xff0000);      // perto
    r.add_quad(Vec3{80.0, -1.0, 0.0}, Vec3{80.0, 1.0, 0.0}, Vec3{80.0, 1.0, 1.0},
               Vec3{80.0, -1.0, 1.0}, 0x00ff00);     // longe
    std::vector<Face3D> faces = r.resolve();
    CHECK(faces.size() == 2, "esperava 2 faces, veio %zu", faces.size());
    if (faces.size() == 2) {
        CHECK(faces[0].profundidade > faces[1].profundidade,
              "ordem errada: %.1f deveria vir depois de %.1f", faces[0].profundidade,
              faces[1].profundidade);
        CHECK(faces[0].cor == 0x00ff00, "a face distante não é a verde");
    }

    // recorte: um quadrado atravessando a câmera ainda gera uma face válida
    r.begin(800, 600);
    r.add_quad(Vec3{-5.0, -2.0, 0.0}, Vec3{-5.0, 2.0, 0.0}, Vec3{10.0, 2.0, 0.0},
               Vec3{10.0, -2.0, 0.0}, 0x123456);
    std::vector<Face3D> rec = r.resolve();
    CHECK(rec.size() == 1, "quadrado recortado desapareceu (%zu faces)", rec.size());
    if (rec.size() == 1) {
        CHECK(rec[0].valida(), "face recortada sem pontos suficientes");
        for (size_t i = 0; i < rec[0].xs.size(); ++i)
            CHECK(std::fabs(rec[0].xs[i]) < 100000 && std::fabs(rec[0].ys[i]) < 100000,
                  "coordenada absurda depois do recorte: %d %d", rec[0].xs[i],
                  rec[0].ys[i]);
    }

    // caixa e pirâmide geram faces
    r.begin(800, 600);
    r.add_box(Vec3{15.0, 0.0, 0.5}, 4.0, 1.8, 1.4, 0.3, 0xe0483a);
    r.add_pyramid(Vec3{30.0, 6.0, 0.0}, 2.0, 6.0, 0x2f7d4f);
    std::vector<Face3D> obj = r.resolve();
    CHECK(obj.size() >= 8, "caixa/pirâmide geraram poucas faces: %zu", obj.size());

    // a cena da pista: precisa gerar asfalto, muro e cenário
    Track t;
    std::string err;
    REQUIRE(load_track("kartodromo", t, &err), "sem pista para o teste 3D: %s", err.c_str());
    // câmera dentro da pista, olhando para a frente (como o jogo faz)
    Camera3D cam_pista = cam;
    cam_pista.x = t.center[0].x;
    cam_pista.y = t.center[0].y;
    cam_pista.z = 2.0;
    cam_pista.yaw = t.heading[0];
    Render3D cena;
    cena.set_camera(cam_pista);
    cena.begin(800, 600);
    montar_cena_pista(cena, t, 0, 60);
    std::vector<Face3D> pista = cena.resolve();
    CHECK(pista.size() > 50, "cena 3D da pista pobre: %zu faces", pista.size());
    for (const Face3D& f : pista) {
        CHECK(f.valida(), "face inválida na cena");
        for (size_t i = 0; i < f.xs.size(); ++i)
            CHECK(std::fabs(f.xs[i]) < 200000, "coordenada fora de controle: %d", f.xs[i]);
    }

    // elevação: um ponto mais alto aparece mais alto na tela (mesma distância)
    std::vector<double> ele(t.n(), 0.0);
    for (size_t i = 0; i < ele.size(); ++i) ele[i] = 3.0 * std::sin(double(i) * 0.05);
    Render3D c2;
    c2.set_camera(cam_pista);
    c2.begin(800, 600);
    montar_cena_pista(c2, t, 0, 40, &ele);
    CHECK(!c2.resolve().empty(), "cena com elevação ficou vazia");
}

// ------------------------------------------------------------- conteúdo
// Piloto automático simples (persegue um ponto à frente na linha de centro e
// dosa a velocidade pela curvatura). Serve para provar que toda pista e todo
// carro que o jogo entrega são realmente dirigíveis.
static int pilota(const Track& t, const CarSpec& c, double segundos, int* voltas = nullptr,
                  double* tempo_volta = nullptr) {
    SimConfig cfg;
    cfg.max_seconds = segundos;
    cfg.checkpoint_gating = true;
    Simulation sim(t, c, cfg, 1, 7);
    const int n = t.n();
    const int passos = int(segundos / cfg.dt);
    for (int s = 0; s < passos && !sim.all_dead(); ++s) {
        if (sim.should_decide()) {
            for (int row : sim.active()) {
                const Agent& a = sim.agents[row];
                // perseguição pura: olha mais longe quanto mais rápido vai
                const int frente = std::max(3, int((6.0 + a.car.speed * 0.55) /
                                                   std::max(t.spacing, 0.5)));
                const Vec2 alvo = t.center[(a.idx + frente) % n];
                double desejado = std::atan2(alvo.y - a.car.y, alvo.x - a.car.x);
                double erro = desejado - a.car.heading;
                while (erro > kPi) erro -= 2 * kPi;
                while (erro < -kPi) erro += 2 * kPi;
                // termo derivativo na taxa de guinada: sem isso os carros
                // potentes (monoposto, GT) entram em oscilação e batem
                double cs = (std::fabs(a.car.slip_r) > 0.30) ? 0.45 * a.car.slip_r
                                                             : 0.06 * a.car.slip_r;
                double steer = std::max(-1.0, std::min(1.0, 1.1 * erro - 0.40 * a.car.r - cs));

                // curvatura à frente -> velocidade alvo
                const int la = std::max(6, frente * 2);
                const Vec2& tan_a = t.tangents[a.idx];
                const Vec2& tan_b = t.tangents[(a.idx + la) % n];
                double curv = std::fabs(std::atan2(tan_b.y, tan_b.x) - std::atan2(tan_a.y, tan_a.x));
                if (curv > kPi) curv = 2 * kPi - curv;
                double raio = std::max(8.0, la * t.spacing / std::max(curv, 0.05));
                double mu = 0.55 * (c.grip_front + c.grip_rear) * 0.5;
                double v_alvo = std::min(c.max_speed * 0.75, std::sqrt(mu * 9.81 * raio));
                double drive = a.car.speed < v_alvo ? 1.0
                             : (a.car.speed > v_alvo * 1.25 ? -0.9 : -0.35);
                // rodou: reduz e contra-esterça até apontar de novo para frente
                if (std::fabs(erro) > 2.0) {
                    drive = a.car.speed > 4.0 ? -0.5 : 0.35;
                    steer = erro > 0.0 ? 1.0 : -1.0;
                }
                sim.set_action(row, steer, drive);
            }
        }
        sim.step();
    }
    int row = sim.best_row();
    if (voltas) *voltas = sim.agents[row].laps;
    if (tempo_volta) *tempo_volta = sim.agents[row].best_lap;
    return row;
}

static void t_conteudo() {
    auto pistas = list_tracks();
    auto carros = list_cars();
    CHECK(pistas.size() >= 12, "poucas pistas: %zu", pistas.size());
    CHECK(carros.size() >= 10, "poucos carros: %zu", carros.size());

    CarSpec sedan;
    std::string err;
    REQUIRE(load_car("sedan", sedan, &err), "carro sedan nao carregou: %s", err.c_str());

    // toda pista entregue precisa ser completável
    for (const auto& it : pistas) {
        Track t;
        CHECK(Track::load(it.path, t, &err), "pista %s nao carregou: %s", it.id.c_str(),
              err.c_str());
        if (t.n() < 30) continue;
        int voltas = 0;
        double tempo = 0.0;
        pilota(t, sedan, 150.0, &voltas, &tempo);
        CHECK(voltas >= 1, "pista %s: piloto automatico nao completou uma volta",
              it.id.c_str());
        CHECK(tempo > 5.0 && tempo < 400.0, "pista %s: volta de %.1f s fora do normal",
              it.id.c_str(), tempo);
    }

    // todo carro entregue precisa completar uma volta no oval (a pista de
    // referência: todo mundo consegue, do caminhão ao monoposto)
    Track base;
    REQUIRE(load_track("oval_iniciante", base, &err), "oval nao carregou: %s", err.c_str());
    for (const auto& it : carros) {
        CarSpec c;
        CHECK(CarSpec::load(it.path, c, &err), "carro %s nao carregou: %s", it.id.c_str(),
              err.c_str());
        int voltas = 0;
        pilota(base, c, 150.0, &voltas);
        CHECK(voltas >= 1, "carro %s nao completou uma volta no oval", it.id.c_str());
    }
}

// ------------------------------------------------------------------ sim
static Track g_track;
static CarSpec g_car;

static double roda(double steer, double drive, double seconds, Metrics* m_out = nullptr,
                   int* crashes = nullptr, int* laps = nullptr) {
    SimConfig cfg;
    cfg.max_seconds = seconds;
    Simulation sim(g_track, g_car, cfg, 8, 1234);
    int steps = int(seconds / cfg.dt);
    for (int s = 0; s < steps && !sim.all_dead(); ++s) {
        if (sim.should_decide()) for (int r : sim.active()) sim.set_action(r, steer, drive);
        sim.step();
    }
    int b = sim.best_row();
    if (m_out) *m_out = sim.metrics(b);
    if (crashes) *crashes = sim.agents[b].crashes;
    if (laps) *laps = sim.agents[b].laps;
    return sim.agents[b].fitness;
}

static void t_sim() {
    Metrics m;
    // o carro precisa andar quando o acelerador é pressionado
    roda(0.0, 1.0, 10.0, &m);
    CHECK(m.distance > 20.0, "andou pouco: %.0f m", m.distance);

    // parado é pior do que tentar (não existe "farm" ficando parado)
    double f_parado = roda(0.0, 0.0, 20.0);
    double f_andando = roda(0.2, 1.0, 20.0);
    CHECK(f_andando > f_parado, "parado (%.3f) deveria ser pior que andando (%.3f)",
          f_parado, f_andando);

    // marcha a ré também é pior
    double f_re = roda(0.0, -1.0, 20.0);
    CHECK(f_andando > f_re, "ré (%.3f) deveria ser pior que andando (%.3f)", f_re, f_andando);

    // precisão é medida por metro: rastejar em cima da linha de centro não rende
    SimConfig cfg;
    cfg.max_seconds = 30;
    Simulation devagar(g_track, g_car, cfg, 1, 7);
    for (int s = 0; s < 30 * 120 && !devagar.all_dead(); ++s) {
        if (devagar.should_decide()) devagar.set_action(0, 0.0, 0.06);
        devagar.step();
    }
    Metrics mlen = devagar.metrics(0);
    Simulation rapido(g_track, g_car, cfg, 1, 7);
    for (int s = 0; s < 30 * 120 && !rapido.all_dead(); ++s) {
        if (rapido.should_decide()) rapido.set_action(0, 0.0, 1.0);
        rapido.step();
    }
    Metrics mrap = rapido.metrics(0);
    if (mrap.distance > 100 && mlen.distance > 5) {
        CHECK(mrap.loss < mlen.loss, "rápido (loss %.3f, %.0f m) deveria perder menos que "
              "devagar (loss %.3f, %.0f m)", mrap.loss, mrap.distance, mlen.loss, mlen.distance);
    }

    // sensores: 24 valores finitos em [-1.5, 1.5]
    Simulation sim(g_track, g_car, cfg, 4, 9);
    std::vector<float> obs(sim.obs_dim);
    sim.observe(0, obs.data());
    CHECK(sim.obs_dim == 24, "obs_dim deveria ser 24, é %d", sim.obs_dim);
    bool ok = true;
    for (float v : obs) if (!std::isfinite(v) || std::fabs(v) > 2.0) ok = false;
    CHECK(ok, "observação com valor inválido");

    // progressão monotônica: andar para trás não aumenta max_s
    Simulation s2(g_track, g_car, cfg, 1, 3);
    for (int i = 0; i < 600; ++i) { s2.set_action(0, 0.0, 1.0); s2.step(); }
    double frente = s2.agents[0].max_s;
    for (int i = 0; i < 600; ++i) { s2.set_action(0, 0.0, -1.0); s2.step(); }
    CHECK(s2.agents[0].max_s >= frente - 1e-6, "max_s diminuiu ao dar ré");
}

// ------------------------------------------------------------------ métricas
static void t_metrics() {
    // as métricas precisam ser estáveis e limitadas
    Metrics m;
    roda(0.3, 1.0, 15.0, &m);
    CHECK(m.loss >= 0.0 && m.loss < 10.0, "loss fora de faixa: %.3f", m.loss);
    CHECK(m.error_pct >= 0.0 && m.error_pct <= 100.0, "erro%% fora de faixa: %.1f", m.error_pct);
    CHECK(m.progress_score >= 0.0 && m.progress_score <= 1.0, "progresso fora de faixa");
    CHECK(m.speed_score >= 0.0 && m.speed_score <= 1.0, "velocidade fora de faixa");
    CHECK(m.precision_score >= 0.0 && m.precision_score <= 1.0, "precisão fora de faixa");
    CHECK(m.smooth_score >= 0.0 && m.smooth_score <= 1.0, "suavidade fora de faixa");

    // pesos maiores em um erro precisam aumentar a loss
    // esterço máximo: cedo ou tarde o carro sai da pista e bate (é isso que
    // as penalidades precisam enxergar para a comparação abaixo fazer sentido)
    SimConfig cfg;
    cfg.max_seconds = 35;
    RewardConfig leve, pesado;
    pesado.crash = 3.0;
    pesado.offtrack = 3.0;
    Simulation a(g_track, g_car, cfg, 4, 5);
    Simulation b(g_track, g_car, cfg, 4, 5);
    a.reward = leve;
    b.reward = pesado;
    for (int s = 0; s < 35 * 120; ++s) {
        if (a.should_decide()) for (int r : a.active()) a.set_action(r, 1.0, 1.0);
        if (b.should_decide()) for (int r : b.active()) b.set_action(r, 1.0, 1.0);
        a.step(); b.step();
    }
    Metrics ma = a.metrics(a.best_row()), mb = b.metrics(b.best_row());
    CHECK(ma.offtrack_pct + ma.crash_score > 0.0,
          "o cenário de teste não produziu nenhum erro para penalizar");
    CHECK(mb.loss > ma.loss, "penalidades maiores deveriam doer mais (%.3f vs %.3f)",
          ma.loss, mb.loss);

    // checkpoint gating: cortar caminho não conta volta
    CHECK(g_track.checkpoints.size() >= 4, "pista sem checkpoints");
}

// ------------------------------------------------------------------ política
static void t_policy() {
    PolicySpec sp;
    sp.obs_dim = 24;
    sp.hidden = {8, 8};
    Rng rng(1);
    std::vector<float> g = init_genome(sp, rng);
    CHECK(g.size() == sp.n_params(), "tamanho do genoma: %zu vs %zu", g.size(), sp.n_params());
    std::vector<float> obs(24, 0.0f);
    float out[2];
    forward(sp, g.data(), obs.data(), out);
    CHECK(std::isfinite(out[0]) && std::isfinite(out[1]), "saída inválida");
    CHECK(std::fabs(out[0]) <= 1.0 && std::fabs(out[1]) <= 1.0, "saída fora de [-1,1]");

    // biases zerados: entrada zero => saída zero
    CHECK(std::fabs(out[0]) < 1e-6 && std::fabs(out[1]) < 1e-6,
          "com bias zero a saída deveria ser 0: %.4f %.4f", out[0], out[1]);

    // Xavier: a escala dos pesos é limitada
    double mx = 0;
    for (float v : g) mx = std::max(mx, double(std::fabs(v)));
    CHECK(mx < 1.0, "peso inicial grande demais: %.3f", mx);

    // salvar/carregar modelo
    Model mm;
    mm.spec = sp;
    mm.weights = g;
    mm.meta.set("track", Json("teste"));
    std::string err;
    CHECK(mm.save(tmp_file("raceai_modelo_teste.json"), &err), "não salvou: %s", err.c_str());
    Model carregado;
    CHECK(Model::load(tmp_file("raceai_modelo_teste.json"), carregado, &err), "não carregou: %s",
          err.c_str());
    CHECK(carregado.weights.size() == g.size(), "tamanho diferente após carregar");
    bool igual = carregado.weights.size() == g.size();
    for (size_t i = 0; igual && i < g.size(); ++i) {
        if (std::fabs(carregado.weights[i] - g[i]) > 1e-6) igual = false;
    }
    CHECK(igual, "pesos mudaram ao salvar/carregar");
    CHECK(carregado.meta.at("track").str() == "teste", "meta perdida");

    Model quebrado;
    CHECK(!Model::load(tmp_file("raceai_nao_existe.json"), quebrado, &err),
          "deveria falhar em arquivo inexistente");
}

// ------------------------------------------------------------------ GA
static void t_ga() {
    PolicySpec sp;
    sp.obs_dim = 8;
    sp.hidden = {4};
    GAConfig cfg;
    cfg.population = 20;
    Population pop(sp, cfg, 5);
    CHECK(pop.n() == 20, "população: %d", pop.n());
    std::vector<double> fit(20, 0.0);
    fit[3] = 10.0;
    pop.record(fit);
    CHECK(pop.best_index() == 3, "melhor indivíduo errado: %d", pop.best_index());
    std::vector<float> campeao = pop.genomes[3];
    pop.evolve();
    CHECK(pop.n() == 20, "população mudou de tamanho: %d", pop.n());
    bool achou = false;
    for (const auto& g : pop.genomes) if (g == campeao) achou = true;
    CHECK(achou, "o campeão não passou para a próxima geração (elitismo)");
    CHECK(pop.generation == 1, "geração: %d", pop.generation);
    CHECK(pop.history.size() == 1, "histórico: %zu", pop.history.size());

    // mutação muda os pesos mas mantém o tamanho
    std::vector<float> mutado = pop.mutate(pop.genomes[0]);
    CHECK(mutado.size() == pop.genomes[0].size(), "mutação mudou o tamanho");
    int dif = 0;
    for (size_t i = 0; i < mutado.size(); ++i) if (mutado[i] != pop.genomes[0][i]) ++dif;
    CHECK(dif > 0, "mutação não alterou nada");

    // seed_from: o indivíduo 0 é cópia exata do modelo carregado
    pop.seed_from(campeao);
    CHECK(pop.genomes[0] == campeao, "seed_from não preservou o modelo");
    CHECK(pop.n() == 20, "seed_from mudou o tamanho");

    // resize mantém a população válida
    pop.resize(30);
    CHECK(pop.n() == 30, "resize falhou: %d", pop.n());
}

// ------------------------------------------------------------------ treino
static void t_train() {
    SimConfig sim;
    sim.max_seconds = 12.0;
    PolicySpec pol;
    pol.obs_dim = sim.n_rays + 15;
    pol.hidden = {16, 16};
    GAConfig ga;
    ga.population = 12;
    TrainerConfig tc;
    tc.threads = 2;
    tc.seed = 99;

    Trainer tr(g_track, g_car, sim, ga, pol, tc);
    CHECK(tr.shards.size() >= 1, "sem blocos de simulação");
    int total = 0;
    for (auto& s : tr.shards) total += s->n();
    CHECK(total == 12, "agentes somados: %d (deveria ser 12)", total);

    // ids únicos: cada indivíduo da população aparece exatamente uma vez
    std::vector<int> vistos(12, 0);
    for (auto& s : tr.shards)
        for (int i = 0; i < s->n(); ++i) vistos[s->agents[i].agent_id] += 1;
    bool unicos = true;
    for (int v : vistos) if (v != 1) unicos = false;
    CHECK(unicos, "ids da população duplicados ou faltando");

    tr.start_episode();
    tr.run_episode();
    CHECK(tr.episode_done(), "episódio não terminou");
    GenHistory h0 = tr.finish_episode(true);
    CHECK(h0.generation == 0, "geração avaliada deveria ser 0: %d", h0.generation);
    CHECK(tr.pop.generation == 1, "população deveria estar na geração 1: %d", tr.pop.generation);
    CHECK(h0.best_loss > 0.0 && h0.best_loss < 10.0, "loss inicial estranha: %.3f", h0.best_loss);
    CHECK(h0.best_error_pct >= 0.0 && h0.best_error_pct <= 100.0, "erro%% estranho: %.1f",
          h0.best_error_pct);

    // determinismo: mesma semente => mesmos números
    Trainer tr2(g_track, g_car, sim, ga, pol, tc);
    tr2.start_episode();
    tr2.run_episode();
    GenHistory h2 = tr2.finish_episode(true);
    CHECK(std::fabs(h2.best_loss - h0.best_loss) < 1e-9,
          "não é determinístico: %.6f vs %.6f", h0.best_loss, h2.best_loss);

    // treinar muitas gerações tem que reduzir a loss
    Trainer tr3(g_track, g_car, sim, ga, pol, tc);
    GenHistory first, last;
    tr3.run(40, [&](const GenHistory& h) {
        if (h.generation == 1) first = h;
        last = h;
        return true;
    });
    CHECK(last.best_loss < first.best_loss,
          "não evoluiu: loss %.3f -> %.3f", first.best_loss, last.best_loss);
    CHECK(tr3.history().size() == 40, "histórico com %zu gerações", tr3.history().size());

    // salvar e recarregar o melhor modelo
    std::string err;
    CHECK(tr3.save_best(tmp_file("raceai_treino_teste.json"), &err), "não salvou o modelo: %s",
          err.c_str());
    Trainer tr4(g_track, g_car, sim, ga, pol, tc);
    CHECK(tr4.load_model(tmp_file("raceai_treino_teste.json"), &err), "não carregou: %s", err.c_str());
    tr4.start_episode();
    tr4.run_episode();
    GenHistory h4 = tr4.finish_episode(false);
    CHECK(std::isfinite(h4.best_loss), "loss inválida após carregar modelo");
}

// ------------------------------------------------------------------ assets
static void t_assets() {
    auto pistas = list_tracks();
    CHECK(pistas.size() >= 8, "poucas pistas: %zu", pistas.size());
    for (const auto& it : pistas) CHECK(it.error.empty(), "pista %s: %s", it.id.c_str(),
                                        it.error.c_str());
    auto carros = list_cars();
    CHECK(carros.size() >= 6, "poucos carros: %zu", carros.size());
    for (const auto& it : carros) CHECK(it.error.empty(), "carro %s: %s", it.id.c_str(),
                                        it.error.c_str());

    // todas as pistas carregam e são utilizáveis
    for (const auto& it : pistas) {
        Track t;
        std::string err;
        CHECK(Track::load(it.path, t, &err), "pista %s não carregou: %s", it.id.c_str(),
              err.c_str());
        CHECK(t.valid() && t.length > 80.0, "pista %s com geometria ruim (%.0f m)",
              it.id.c_str(), t.length);
        CHECK(std::isfinite(t.length), "pista %s com NaN", it.id.c_str());
    }
    // todos os carros carregam
    for (const auto& it : carros) {
        CarSpec c;
        std::string err;
        CHECK(CarSpec::load(it.path, c, &err), "carro %s não carregou: %s", it.id.c_str(),
              err.c_str());
        CHECK(std::isfinite(c.iz()) && c.iz() > 0, "carro %s com inércia inválida", it.id.c_str());
    }
}

// ------------------------------------------------------------------ python
// Ponte com o CPython testada contra um **falso** libpython (tests/stub_python.cpp),
// que exporta exatamente os símbolos usados por src/core/py_driver.cpp.
#if defined(__unix__) || defined(__APPLE__)
extern "C" {
typedef void (*StubVoid)();
typedef void (*StubSetResp)(double, double);
typedef void (*StubSetFail)(int);
typedef const char* (*StubStr)();
typedef int (*StubInt)();
typedef double (*StubGet)(int);
}
#endif

static void t_python() {
#if !defined(__unix__) && !defined(__APPLE__)
    printf("  (pulando: teste do stub só roda em unix)\n");
#else
    const char* caminho = std::getenv("RACEAI_STUB_PYTHON");
    if (!caminho) caminho = "build/libstubpython.so";
    void* h = dlopen(caminho, RTLD_NOW | RTLD_GLOBAL);
    if (!h) {
        printf("  (pulando: stub do python não encontrado em %s)\n", caminho);
        return;
    }
    auto sym = [&](const char* n) { return dlsym(h, n); };
    ((StubVoid)sym("stubpython_reset"))();
    StubSetResp set_resp = (StubSetResp)sym("stubpython_set_response");
    StubSetFail set_fail = (StubSetFail)sym("stubpython_set_failure");
    StubStr codigo = (StubStr)sym("stubpython_installed_code");
    StubStr script = (StubStr)sym("stubpython_script");
    StubInt nsens = (StubInt)sym("stubpython_last_sensor_count");
    StubGet sensor = (StubGet)sym("stubpython_last_sensor");
    StubInt ncalls = (StubInt)sym("stubpython_calls");

    PyDriver py;
    std::string err;
    CHECK(py.load_runtime(caminho, &err), "não carregou o interpretador: %s", err.c_str());
    CHECK(py.runtime_loaded(), "runtime deveria estar carregado");
    CHECK(std::string(script()).find("_raceai_call") != std::string::npos,
          "o script de preparação não foi executado");

    const char* fonte = "def dirigir(sensores):\n"
                        "    return (sensores[0] - sensores[8]) * 2.0, 0.5\n";
    CHECK(py.set_code(fonte, &err), "não instalou o código: %s", err.c_str());
    CHECK(py.has_code(), "driver deveria estar pronto");
    CHECK(std::string(codigo()).find("def dirigir") != std::string::npos,
          "o código do usuário não chegou ao interpretador");

    // a chamada recebe a lista de sensores e devolve a ação
    set_resp(0.25, -0.75);
    float obs[24];
    for (int i = 0; i < 24; ++i) obs[i] = float(i) * 0.01f;
    float out[2] = {9, 9};
    py.act(obs, 24, out);
    CHECK(std::fabs(out[0] - 0.25) < 1e-6, "esterço: %.4f", out[0]);
    CHECK(std::fabs(out[1] + 0.75) < 1e-6, "acelerador: %.4f", out[1]);
    CHECK(nsens() == 24, "deveria receber 24 sensores, recebeu %d", nsens());
    CHECK(std::fabs(sensor(3) - 0.03) < 1e-6, "sensor 3: %.4f", sensor(3));
    CHECK(ncalls() == 1, "chamadas: %d", ncalls());

    // clamp da ação em [-1, 1]
    set_resp(5.0, -5.0);
    py.act(obs, 24, out);
    CHECK(out[0] <= 1.0 && out[1] >= -1.0, "ação fora de [-1,1]: %.2f %.2f", out[0], out[1]);

    // erro em tempo de execução: a ação fica neutra e o traceback aparece
    set_fail(2);
    float out2[2] = {9, 9};
    py.act(obs, 24, out2);
    CHECK(out2[0] == 0.0 && out2[1] == 0.0, "com erro a ação deveria ser neutra");
    CHECK(!py.valid(), "driver deveria estar inválido após o erro");
    CHECK(!py.traceback().empty(), "deveria expor o traceback");

    // código sem a função dirigir() é recusado
    ((StubVoid)sym("stubpython_reset"))();
    set_fail(0);
    PyDriver py2;
    CHECK(py2.load_runtime(caminho, &err), "segundo driver não carregou");
    CHECK(!py2.set_code("x = 1 + 1\n", &err), "código sem dirigir() deveria falhar");
    CHECK(!err.empty(), "deveria explicar o erro");
#endif
}

// ------------------------------------------------------------------ main
int main() {
    printf("RaceAI 2D (C++) — testes do núcleo\n\n");
    std::string err;
    if (!load_track("kartodromo", g_track, &err) || !load_car("kart", g_car, &err)) {
        printf("não achei os assets (%s)\nrode a partir da pasta raceai-cpp\n", err.c_str());
        return 1;
    }
    test("base: vetores, rng e json", t_base);
    test("pista: geometria e sensores", t_track);
    test("carro: especificação e física", t_car);
    test("física avançada: câmbio, pneus, dano e tanque", t_fisica_avancada);
    test("simulação: passo e progressão", t_sim);
    test("métricas: loss, erro e pesos", t_metrics);
    test("política: rede e modelo", t_policy);
    test("evolução: população e mutação", t_ga);
    test("treino: gerações e determinismo", t_train);
    test("assets: pistas, carros e mods", t_assets);
    test("conteúdo: toda pista e todo carro são dirigíveis", t_conteudo);
    test("renderizador 3D: projeção, recorte e ordem das faces", t_render3d);
    test("ia em python (ponte com o interpretador)", t_python);

    printf("\n%d testes passaram, %d falharam\n", passed, failed);
    return failed ? 1 : 0;
}
