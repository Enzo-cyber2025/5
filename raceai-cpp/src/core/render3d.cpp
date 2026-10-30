// render3d.cpp — implementação do mini renderizador (ver comentários no .hpp).
#include "render3d.hpp"

#include <algorithm>
#include <cmath>

namespace raceai {
namespace {

inline double rad(double graus) { return graus * kPi / 180.0; }

// clareia/escurece uma cor 0x00RRGGBB (fator 1.0 = igual)
inline uint32_t sombrear(uint32_t cor, double fator) {
    if (fator < 0.15) fator = 0.15;
    if (fator > 1.6) fator = 1.6;
    auto canal = [&](int shift) {
        int v = int((cor >> shift) & 0xFF);
        v = int(double(v) * fator);
        return uint32_t(v > 255 ? 255 : v);
    };
    return (canal(16) << 16) | (canal(8) << 8) | canal(0);
}

}  // namespace

bool Render3D::projetar(Vec3 p, double* sx, double* sy) const {
    // translada para a câmera e gira em z
    const double dx = p.x - cam_.x, dy = p.y - cam_.y, dz = p.z - cam_.z;
    const double cy = std::cos(-cam_.yaw), sy2 = std::sin(-cam_.yaw);
    double fx = dx * cy - dy * sy2;      // para a frente (profundidade)
    double rx = dx * sy2 + dy * cy;      // para a direita
    // pitch: inclina o olhar
    const double cp = std::cos(-cam_.pitch), sp = std::sin(-cam_.pitch);
    double fy = fx * cp - dz * sp;
    double rz = fx * sp + dz * cp;       // para cima
    if (fy <= cam_.perto) return false;

    const double f = (double(alt_) * 0.5) / std::tan(rad(cam_.fov) * 0.5);
    *sx = double(larg_) * 0.5 + f * rx / fy;
    *sy = double(alt_) * 0.5 - f * rz / fy;
    return true;
}

double Render3D::horizonte_y() const {
    // linha do infinito: com pitch 0 fica no meio da tela
    const double f = (double(alt_) * 0.5) / std::tan(rad(cam_.fov) * 0.5);
    return double(alt_) * 0.5 + f * std::tan(cam_.pitch);
}

void Render3D::begin(int largura, int altura) {
    larg_ = std::max(1, largura);
    alt_ = std::max(1, altura);
    faces_.clear();
}

void Render3D::add_quad(Vec3 a, Vec3 b, Vec3 c, Vec3 d, uint32_t cor) {
    FaceBruta f;
    f.pontos = {a, b, c, d};
    f.cor = cor;
    faces_.push_back(f);
}

void Render3D::add_tri(Vec3 a, Vec3 b, Vec3 c, uint32_t cor) {
    FaceBruta f;
    f.pontos = {a, b, c};
    f.cor = cor;
    faces_.push_back(f);
}

void Render3D::add_box(Vec3 centro, double comp, double larg, double alt, double yaw,
                       uint32_t cor, uint32_t cor_topo) {
    const double c = std::cos(yaw), s = std::sin(yaw);
    const double hx = comp * 0.5, hy = larg * 0.5, hz = alt * 0.5;
    // oito cantos no referencial do objeto
    Vec3 local[8];
    int k = 0;
    for (int sz = 0; sz < 2; ++sz)
        for (int sy = 0; sy < 2; ++sy)
            for (int sx = 0; sx < 2; ++sx) {
                double lx = (sx ? hx : -hx), ly = (sy ? hy : -hy), lz = (sz ? alt : 0.0);
                local[k].x = centro.x + lx * c - ly * s;
                local[k].y = centro.y + lx * s + ly * c;
                local[k].z = centro.z - hz + lz;
                ++k;
            }
    // índices: 0..3 base (z baixo), 4..7 topo
    const int base[4] = {0, 1, 3, 2};
    const int topo[4] = {4, 5, 7, 6};
    // laterais
    for (int i = 0; i < 4; ++i) {
        int j = (i + 1) % 4;
        add_quad(local[base[i]], local[base[j]], local[topo[j]], local[topo[i]],
                 sombrear(cor, 0.82 + 0.10 * (i % 2)));
    }
    add_quad(local[topo[0]], local[topo[1]], local[topo[2]], local[topo[3]],
             cor_topo ? cor_topo : sombrear(cor, 1.18));
}

void Render3D::add_pyramid(Vec3 base, double raio, double altura, uint32_t cor) {
    const int lados = 4;
    for (int i = 0; i < lados; ++i) {
        const double a0 = 2.0 * kPi * double(i) / double(lados);
        const double a1 = 2.0 * kPi * double(i + 1) / double(lados);
        Vec3 p0{base.x + std::cos(a0) * raio, base.y + std::sin(a0) * raio, base.z};
        Vec3 p1{base.x + std::cos(a1) * raio, base.y + std::sin(a1) * raio, base.z};
        Vec3 topo{base.x, base.y, base.z + altura};
        add_tri(p0, p1, topo, sombrear(cor, 0.85 + 0.12 * (i % 2)));
    }
}

std::vector<Face3D> Render3D::resolve() const {
    std::vector<Face3D> saida;
    saida.reserve(faces_.size());
    const double cx = cam_.x, cy = cam_.y, cz = cam_.z;

    for (const FaceBruta& f : faces_) {
        if (f.pontos.size() < 3) continue;
        // distância do centroide (para o algoritmo do pintor)
        double mx = 0.0, my = 0.0, mz = 0.0;
        for (const Vec3& p : f.pontos) { mx += p.x; my += p.y; mz += p.z; }
        const double n = double(f.pontos.size());
        mx /= n; my /= n; mz /= n;
        const double dist = std::sqrt((mx - cx) * (mx - cx) + (my - cy) * (my - cy) +
                                      (mz - cz) * (mz - cz));
        if (dist > cam_.longe) continue;

        // recorte no plano próximo (Sutherland-Hodgman com 1 plano)
        std::vector<Vec3> recorte;
        {
            // depth = projeção no eixo de visão (positivo = na frente)
            auto depth = [&](const Vec3& p) {
                const double dx = p.x - cx, dy = p.y - cy;
                const double fw = dx * std::cos(-cam_.yaw) - dy * std::sin(-cam_.yaw);
                return fw;
            };
            // corta um pouco à frente do plano próximo: cortar exatamente em
            // cima dele deixa o vértice na berlinda do "fy <= perto" (e a face
            // inteira desaparecia por causa de 1e-16)
            const double alvo = cam_.perto * 1.05;
            const size_t m = f.pontos.size();
            for (size_t i = 0; i < m; ++i) {
                const Vec3& a = f.pontos[i];
                const Vec3& b = f.pontos[(i + 1) % m];
                const double da = depth(a), db = depth(b);
                const bool fa = da > alvo, fb = db > alvo;
                if (fa) recorte.push_back(a);
                if (fa != fb) {
                    const double t = (alvo - da) / (db - da);
                    recorte.push_back(Vec3{a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t,
                                           a.z + (b.z - a.z) * t});
                }
            }
        }
        if (recorte.size() < 3) continue;

        Face3D face;
        face.cor = f.cor;
        face.profundidade = dist;
        bool fora = false;
        for (const Vec3& p : recorte) {
            double sx = 0.0, sy = 0.0;
            if (!projetar(p, &sx, &sy)) { fora = true; break; }
            face.xs.push_back(int(std::lround(sx)));
            face.ys.push_back(int(std::lround(sy)));
            // desencoraja polígonos absurdos (perto demais da câmera)
            if (std::fabs(sx) > 1e6 || std::fabs(sy) > 1e6) fora = true;
        }
        if (fora || !face.valida()) continue;
        saida.push_back(std::move(face));
    }

    // algoritmo do pintor: desenha o que está longe primeiro
    std::sort(saida.begin(), saida.end(), [](const Face3D& a, const Face3D& b) {
        return a.profundidade > b.profundidade;
    });
    return saida;
}

// ------------------------------------------------------------------ cenário
// Monta a pista: asfalto em tiras, zebrada nas bordas, muro e árvores.
// `centro` é o índice do ponto onde o carro está; `alcance` quantos pontos à
// frente (e alguns atrás) entrar na cena.
void montar_cena_pista(Render3D& r, const Track& t, int centro, int alcance,
                       const std::vector<double>* elev) {
    const int n = t.n();
    if (n < 4) return;
    const int atras = 8;
    auto z_de = [&](int i) {
        int k = ((i % n) + n) % n;
        return (elev && k < int(elev->size())) ? (*elev)[size_t(k)] : 0.0;
    };

    const uint32_t asfalto = 0x3A3F47;
    const uint32_t zebrada1 = 0xD8452F;
    const uint32_t zebrada2 = 0xEDEDED;
    const uint32_t muro = 0x6B7280;
    const uint32_t grama = 0x2C4130;

    for (int passo = -atras; passo < alcance; ++passo) {
        const int i = ((centro + passo) % n + n) % n;
        const int j = (i + 1) % n;
        const Vec3 el_i{t.edge_l[i].x, t.edge_l[i].y, z_de(i)};
        const Vec3 er_i{t.edge_r[i].x, t.edge_r[i].y, z_de(i)};
        const Vec3 el_j{t.edge_l[j].x, t.edge_l[j].y, z_de(j)};
        const Vec3 er_j{t.edge_r[j].x, t.edge_r[j].y, z_de(j)};
        // asfalto (duas metades: dá um fio de diferença de tom)
        const Vec3 c_i{(el_i.x + er_i.x) * 0.5, (el_i.y + er_i.y) * 0.5, z_de(i)};
        const Vec3 c_j{(el_j.x + er_j.x) * 0.5, (el_j.y + er_j.y) * 0.5, z_de(j)};
        const bool xadrez = ((i / 3) % 2) == 0;
        r.add_quad(el_i, c_i, c_j, el_j, sombrear(asfalto, xadrez ? 1.0 : 0.93));
        r.add_quad(c_i, er_i, er_j, c_j, sombrear(asfalto, xadrez ? 0.93 : 1.0));

        // zebrada (faixa de 1,2 m nas duas bordas, alternada a cada 3 pontos)
        if ((i % 6) < 3) {
            auto beira = [&](const Vec3& a, const Vec3& b, bool lado_esq) {
                const Vec2& na = t.normals[i];
                const Vec2& nb = t.normals[j];
                const double s = 1.2 * (lado_esq ? 1.0 : -1.0);
                Vec3 a2{a.x + na.x * s, a.y + na.y * s, a.z + 0.02};
                Vec3 b2{b.x + nb.x * s, b.y + nb.y * s, b.z + 0.02};
                r.add_quad(a, a2, b2, b, (i % 2) ? zebrada1 : zebrada2);
            };
            beira(el_i, el_j, true);
            beira(er_i, er_j, false);
        }

        // muro (1,1 m de altura) só de vez em quando: economiza polígonos
        if ((i % 2) == 0) {
            auto muro_lado = [&](const Vec3& a, const Vec3& b, bool lado_esq) {
                const Vec2& na = t.normals[i];
                const Vec2& nb = t.normals[j];
                const double s = 1.1 * (lado_esq ? 1.0 : -1.0);
                Vec3 a2{a.x + na.x * s, a.y + na.y * s, a.z};
                Vec3 b2{b.x + nb.x * s, b.y + nb.y * s, b.z};
                Vec3 a3{a2.x, a2.y, a2.z + 1.1};
                Vec3 b3{b2.x, b2.y, b2.z + 1.1};
                r.add_quad(a2, b2, b3, a3, sombrear(muro, 0.9));
            };
            muro_lado(el_i, el_j, true);
            muro_lado(er_i, er_j, false);
        }

        // grama: uma faixa larga para fora do muro (só a cada 3 pontos)
        if ((i % 3) == 0) {
            auto grama_lado = [&](const Vec3& a, const Vec3& b, bool lado_esq) {
                const Vec2& na = t.normals[i];
                const Vec2& nb = t.normals[j];
                const double s0 = 1.1 * (lado_esq ? 1.0 : -1.0);
                const double s1 = 26.0 * (lado_esq ? 1.0 : -1.0);
                Vec3 a0{a.x + na.x * s0, a.y + na.y * s0, a.z - 0.05};
                Vec3 b0{b.x + nb.x * s0, b.y + nb.y * s0, b.z - 0.05};
                Vec3 a1{a.x + na.x * s1, a.y + na.y * s1, a.z - 0.05};
                Vec3 b1{b.x + nb.x * s1, b.y + nb.y * s1, b.z - 0.05};
                r.add_quad(a0, a1, b1, b0, grama);
            };
            grama_lado(el_i, el_j, true);
            grama_lado(er_i, er_j, false);
        }

        // árvores/pilares de cenário: a cada 12 pontos, um de cada lado
        if ((i % 12) == 0) {
            const Vec2& na = t.normals[i];
            for (int lado = 0; lado < 2; ++lado) {
                const double s = (lado == 0 ? 1.0 : -1.0) * 12.0;
                Vec3 base{el_i.x + na.x * s, el_i.y + na.y * s, z_de(i) - 0.05};
                if (lado == 1) {
                    base.x = er_i.x + na.x * s;
                    base.y = er_i.y + na.y * s;
                }
                r.add_pyramid(base, 2.2, 6.0 + 3.0 * ((i / 12) % 3), 0x2F7D4F);
            }
        }
    }
}


// ------------------------------------------------------- carros pré-modelados
// Cada estilo é uma receita de sólidos (chassi, cabine, asas, rodas, santo
// antônio...) montada com as proporções REAIS do carro (comprimento, largura,
// altura, entre-eixos e raio de roda do JSON). Nada de caixa genérica: no
// espelho/3D dá para reconhecer o carro pelo desenho.
namespace {

inline Vec3 vsoma(const Vec3& a, const Vec3& b) { return Vec3{a.x + b.x, a.y + b.y, a.z + b.z}; }
inline Vec3 vescala(const Vec3& a, double k) { return Vec3{a.x * k, a.y * k, a.z * k}; }
inline double vnorma(const Vec3& a) { return std::sqrt(a.x * a.x + a.y * a.y + a.z * a.z); }
inline Vec3 vcruz(const Vec3& a, const Vec3& b) {
    return Vec3{a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x};
}

struct Moldura {
    // referencial do carro: +x para frente, +y para a esquerda, +z para cima
    double x = 0.0, y = 0.0, z = 0.0, h = 0.0;   // h = heading
    double ch = 1.0, sh = 0.0;

    explicit Moldura(double px, double py, double pz, double heading)
        : x(px), y(py), z(pz), h(heading),
          ch(std::cos(heading)), sh(std::sin(heading)) {}

    Vec3 p(double lx, double ly, double lz) const {
        return Vec3{x + lx * ch - ly * sh, y + lx * sh + ly * ch, z + lz};
    }
};

}  // namespace

EstiloCarro estilo_carro(const std::string& body_style, const std::string& id) {
    const std::string s = body_style.empty() ? id : body_style;
    auto tem = [&](const char* t) { return s.find(t) != std::string::npos; };
    if (tem("formula") || tem("monoposto") || tem("prototipo")) return EstiloCarro::Formula;
    if (tem("kart")) return EstiloCarro::Kart;
    if (tem("caminhao") || tem("truck") || tem("van")) return EstiloCarro::Caminhao;
    if (tem("buggy")) return EstiloCarro::Buggy;
    if (tem("pickup") || tem("picape")) return EstiloCarro::Picape;
    if (tem("classico")) return EstiloCarro::Classico;
    if (tem("drift") || tem("tuner")) return EstiloCarro::Drift;
    if (tem("gt") || tem("super") || tem("esportivo") || tem("muscle"))
        return EstiloCarro::Esportivo;
    if (tem("hatch")) return EstiloCarro::Hatch;
    return EstiloCarro::Sedan;
}

void add_cilindro(Render3D& r, const Vec3& centro, double raio, double comprimento,
                  const Vec3& eixo, const Vec3& frente, uint32_t cor, int lados) {
    // base ortogonal: eixo (largura do pneu) x frente x cima
    Vec3 e = eixo, f = frente, up = vcruz(e, f);
    const double ne = vnorma(e), nf = vnorma(f), nu = vnorma(up);
    if (ne < 1e-6 || nf < 1e-6 || nu < 1e-6) return;
    e = vescala(e, 1.0 / ne);
    f = vescala(f, 1.0 / nf);
    up = vescala(up, 1.0 / nu);
    const double meio = comprimento * 0.5;
    std::vector<Vec3> a, b;
    for (int i = 0; i < lados; ++i) {
        const double t = 2.0 * kPi * double(i) / double(lados);
        const Vec3 d = vsoma(vescala(f, std::cos(t) * raio), vescala(up, std::sin(t) * raio));
        a.push_back(vsoma(centro, vsoma(d, vescala(e, -meio))));
        b.push_back(vsoma(centro, vsoma(d, vescala(e, meio))));
    }
    for (int i = 0; i < lados; ++i) {
        const int j = (i + 1) % lados;
        r.add_quad(a[i], b[i], b[j], a[j], cor);
    }
    // tampas (só a de fora aparece na prática, mas custa pouco)
    for (int i = 1; i + 1 < lados; ++i) r.add_tri(a[0], a[i], a[i + 1], cor);
    for (int i = 1; i + 1 < lados; ++i) r.add_tri(b[0], b[i + 1], b[i], cor);
}

void montar_carro(Render3D& r, EstiloCarro estilo, double x, double y, double z,
                  double heading, double comprimento, double largura, double altura,
                  double entre_eixos, double raio_roda, uint32_t cor,
                  uint32_t cor_detalhe, double esterco, double giro) {
    const Moldura m(x, y, z, heading);
    const double L = std::max(2.0, comprimento);
    const double W = std::max(1.2, largura);
    const double H = std::max(0.9, altura);
    const double wb = std::max(1.0, entre_eixos);
    const double R = std::max(0.22, raio_roda);
    const double pneu = std::min(0.40, W * 0.24);

    // vetores do carro no mundo
    const Vec3 frente = Vec3{m.ch, m.sh, 0.0};
    const Vec3 lado = Vec3{-m.sh, m.ch, 0.0};

    // sombra no chão (um retângulo escuro: dá o carro "assentado" na pista)
    r.add_quad(m.p(L * 0.5, W * 0.5, 0.01), m.p(L * 0.5, -W * 0.5, 0.01),
               m.p(-L * 0.5, -W * 0.5, 0.01), m.p(-L * 0.5, W * 0.5, 0.01), 0x0a0c10);

    // ------------------------------------------------------------ rodas
    auto roda = [&](double lx, double ly, bool dianteira) {
        const double h_roda = heading + (dianteira ? esterco : 0.0);
        const Vec3 eixo = Vec3{-std::sin(h_roda), std::cos(h_roda), 0.0};
        const Vec3 fr = Vec3{std::cos(h_roda), std::sin(h_roda), 0.0};
        const Vec3 c = m.p(lx, ly, R);
        add_cilindro(r, c, R, pneu, eixo, fr, 0x1a1a1e, 10);
        // miolo da roda (aro claro) — gira junto, então dá para ver a roda andar
        const double t = giro * 0.35;
        const Vec3 cima = Vec3{0.0, 0.0, 1.0};
        const Vec3 raio = vsoma(vescala(fr, std::cos(t) * R * 0.55),
                                vescala(cima, std::sin(t) * R * 0.55));
        r.add_box(vsoma(c, raio), R * 0.22, pneu * 1.05, R * 0.16, h_roda, cor_detalhe);
    };

    // ------------------------------------------------------- por estilo
    switch (estilo) {
        case EstiloCarro::Formula: {
            // bico baixo, cockpit aberto, asas dianteira e traseira, rodas de fora
            r.add_box(m.p(L * 0.10, 0.0, R * 0.75), L * 0.72, W * 0.42, H * 0.34,
                      heading, cor);
            r.add_box(m.p(L * 0.44, 0.0, R * 0.62), L * 0.30, W * 0.30, H * 0.18,
                      heading, cor);                                    // bico
            r.add_box(m.p(-L * 0.10, 0.0, R * 0.95), L * 0.20, W * 0.34, H * 0.30,
                      heading, cor_detalhe);                            // cockpit
            r.add_box(m.p(-L * 0.46, 0.0, R * 1.05), L * 0.14, W * 0.34, H * 0.16,
                      heading, 0x14161a);                               // aerofólio traseiro
            r.add_box(m.p(-L * 0.46, 0.0, R * 1.55), L * 0.16, W * 1.02, H * 0.07,
                      heading, cor);                                    // asa traseira
            r.add_box(m.p(L * 0.48, 0.0, R * 0.55), L * 0.16, W * 1.05, H * 0.06,
                      heading, cor);                                    // asa dianteira
            const double eixo_f = wb * 0.52, eixo_t = -wb * 0.48;
            for (int s = -1; s <= 1; s += 2) {
                roda(eixo_f, double(s) * (W * 0.52), true);
                roda(eixo_t, double(s) * (W * 0.52), false);
            }
            break;
        }
        case EstiloCarro::Kart: {
            r.add_box(m.p(0.0, 0.0, R * 0.70), L * 0.80, W * 0.62, H * 0.26,
                      heading, cor);                                    // chassi
            r.add_box(m.p(-L * 0.06, 0.0, R * 1.05), L * 0.20, W * 0.50, H * 0.34,
                      heading, 0x20242c);                               // banco
            r.add_box(m.p(-L * 0.22, 0.0, R * 1.30), L * 0.06, W * 0.50, H * 0.44,
                      heading, cor_detalhe);                            // santo antônio
            r.add_box(m.p(L * 0.40, 0.0, R * 0.95), L * 0.10, W * 1.00, H * 0.14,
                      heading, cor);                                    // para-choque
            const double eixo_f = wb * 0.50, eixo_t = -wb * 0.50;
            for (int s = -1; s <= 1; s += 2) {
                roda(eixo_f, double(s) * (W * 0.56), true);
                roda(eixo_t, double(s) * (W * 0.56), false);
            }
            break;
        }
        case EstiloCarro::Caminhao: {
            r.add_box(m.p(L * 0.30, 0.0, R * 1.10), L * 0.34, W * 0.96, H * 0.62,
                      heading, cor);                                    // cabine
            r.add_box(m.p(-L * 0.18, 0.0, R * 1.25), L * 0.62, W * 0.98, H * 0.72,
                      heading, cor_detalhe);                            // baú
            r.add_box(m.p(L * 0.48, 0.0, R * 0.70), L * 0.10, W * 0.92, H * 0.22,
                      heading, 0x2a2f38);                               // para-choque
            const double eixo_f = wb * 0.34, eixo_t = -wb * 0.34;
            for (int s = -1; s <= 1; s += 2) {
                roda(eixo_f, double(s) * (W * 0.48), true);
                roda(eixo_t, double(s) * (W * 0.48), false);
                roda(-wb * 0.52, double(s) * (W * 0.48), false);        // eixo extra
            }
            break;
        }
        case EstiloCarro::Buggy: {
            r.add_box(m.p(0.0, 0.0, R * 0.95), L * 0.62, W * 0.60, H * 0.22,
                      heading, cor);                                    // chassi
            r.add_box(m.p(-L * 0.02, 0.0, R * 1.28), L * 0.26, W * 0.54, H * 0.34,
                      heading, 0x1b1e24);                               // banco
            for (int s = -1; s <= 1; s += 2)
                r.add_box(m.p(-L * 0.16, double(s) * W * 0.24, R * 1.75), L * 0.05,
                          W * 0.05, H * 0.70, heading, cor_detalhe);    // gaiola
            r.add_box(m.p(-L * 0.16, 0.0, R * 2.10), L * 0.30, W * 0.60, H * 0.08,
                      heading, cor_detalhe);                            // teto da gaiola
            const double eixo_f = wb * 0.50, eixo_t = -wb * 0.50;
            for (int s = -1; s <= 1; s += 2) {
                roda(eixo_f, double(s) * (W * 0.55), true);
                roda(eixo_t, double(s) * (W * 0.55), false);
            }
            break;
        }
        case EstiloCarro::Picape: {
            r.add_box(m.p(L * 0.06, 0.0, R * 0.95), L * 0.86, W * 0.94, H * 0.38,
                      heading, cor);                                    // chassi
            r.add_box(m.p(L * 0.20, 0.0, R * 1.55), L * 0.36, W * 0.86, H * 0.42,
                      heading, cor);                                    // cabine
            for (int s = -1; s <= 1; s += 2)
                r.add_box(m.p(-L * 0.20, double(s) * W * 0.44, R * 1.35), L * 0.42,
                          W * 0.06, H * 0.30, heading, cor_detalhe);    // laterais
            r.add_box(m.p(-L * 0.40, 0.0, R * 1.35), L * 0.05, W * 0.88, H * 0.30,
                      heading, cor_detalhe);                            // tampa
            const double eixo_f = wb * 0.48, eixo_t = -wb * 0.48;
            for (int s = -1; s <= 1; s += 2) {
                roda(eixo_f, double(s) * (W * 0.50), true);
                roda(eixo_t, double(s) * (W * 0.50), false);
            }
            break;
        }
        case EstiloCarro::Classico: {
            r.add_box(m.p(0.0, 0.0, R * 0.85), L * 0.94, W * 0.92, H * 0.34,
                      heading, cor);                                    // chassi
            r.add_box(m.p(L * 0.26, 0.0, R * 1.05), L * 0.34, W * 0.86, H * 0.18,
                      heading, cor);                                    // capô longo
            r.add_box(m.p(-L * 0.08, 0.0, R * 1.42), L * 0.40, W * 0.80, H * 0.36,
                      heading, cor);                                    // cabine
            r.add_box(m.p(-L * 0.08, 0.0, R * 1.62), L * 0.30, W * 0.72, H * 0.10,
                      heading, cor_detalhe);                            // teto
            const double eixo_f = wb * 0.48, eixo_t = -wb * 0.48;
            for (int s = -1; s <= 1; s += 2) {
                roda(eixo_f, double(s) * (W * 0.46), true);
                roda(eixo_t, double(s) * (W * 0.46), false);
            }
            break;
        }
        case EstiloCarro::Esportivo:
        case EstiloCarro::Drift: {
            const bool drift = (estilo == EstiloCarro::Drift);
            r.add_box(m.p(0.0, 0.0, R * 0.80), L * 0.96, W * 0.94, H * 0.30,
                      heading, cor);
            r.add_box(m.p(L * 0.30, 0.0, R * 0.95), L * 0.28, W * 0.88, H * 0.14,
                      heading, cor);                                    // capô
            r.add_box(m.p(-L * 0.06, 0.0, R * 1.32), L * 0.38, W * 0.82, H * 0.34,
                      heading, cor);                                    // cabine
            r.add_box(m.p(-L * 0.06, 0.0, R * 1.50), L * 0.30, W * 0.74, H * 0.08,
                      heading, cor_detalhe);
            // aerofólio: maior e mais alto no carro de drift
            const double alt_asa = drift ? R * 1.85 : R * 1.55;
            const double tam_asa = drift ? W * 1.02 : W * 0.92;
            r.add_box(m.p(-L * 0.44, 0.0, alt_asa), L * 0.14, tam_asa, H * 0.07,
                      heading, cor);
            for (int s = -1; s <= 1; s += 2)
                r.add_box(m.p(-L * 0.44, double(s) * W * 0.30, (alt_asa + R) * 0.5),
                          L * 0.05, W * 0.05, alt_asa - R * 0.9, heading, cor_detalhe);
            const double eixo_f = wb * 0.48, eixo_t = -wb * 0.48;
            for (int s = -1; s <= 1; s += 2) {
                roda(eixo_f, double(s) * (W * 0.47), true);
                roda(eixo_t, double(s) * (W * 0.47), false);
            }
            break;
        }
        case EstiloCarro::Hatch: {
            r.add_box(m.p(0.0, 0.0, R * 0.85), L * 0.92, W * 0.92, H * 0.38,
                      heading, cor);
            r.add_box(m.p(0.0, 0.0, R * 1.45), L * 0.50, W * 0.84, H * 0.42,
                      heading, cor);                                    // cabine
            r.add_box(m.p(0.0, 0.0, R * 1.68), L * 0.42, W * 0.76, H * 0.08,
                      heading, cor_detalhe);
            const double eixo_f = wb * 0.47, eixo_t = -wb * 0.47;
            for (int s = -1; s <= 1; s += 2) {
                roda(eixo_f, double(s) * (W * 0.46), true);
                roda(eixo_t, double(s) * (W * 0.46), false);
            }
            break;
        }
        case EstiloCarro::Sedan:
        default: {
            r.add_box(m.p(0.0, 0.0, R * 0.85), L * 0.94, W * 0.92, H * 0.36,
                      heading, cor);                                    // chassi
            r.add_box(m.p(L * 0.30, 0.0, R * 1.02), L * 0.30, W * 0.86, H * 0.15,
                      heading, cor);                                    // capô
            r.add_box(m.p(-L * 0.06, 0.0, R * 1.45), L * 0.42, W * 0.82, H * 0.40,
                      heading, cor);                                    // cabine
            r.add_box(m.p(-L * 0.06, 0.0, R * 1.66), L * 0.34, W * 0.74, H * 0.08,
                      heading, cor_detalhe);                            // teto
            r.add_box(m.p(-L * 0.40, 0.0, R * 1.05), L * 0.18, W * 0.86, H * 0.16,
                      heading, cor);                                    // porta-malas
            const double eixo_f = wb * 0.47, eixo_t = -wb * 0.47;
            for (int s = -1; s <= 1; s += 2) {
                roda(eixo_f, double(s) * (W * 0.46), true);
                roda(eixo_t, double(s) * (W * 0.46), false);
            }
            break;
        }
    }
    (void)frente;
    (void)lado;
}

}  // namespace raceai
