// render3d.hpp — mini renderizador 3D por software (sem GPU, sem dependências).
//
// O jogo é 2D (Win32 + GDI), mas dá para desenhar a mesma pista em 3D com um
// rasterizador de polígonos bem simples:
//
//   1. cada pedaço do mundo (pista, carro, árvore) vira uma lista de faces;
//   2. as faces são transformadas para o referencial da câmera e projetadas
//      com uma projeção perspectiva (pinhole);
//   3. o que fica atrás da câmera é recortado no plano próximo;
//   4. as faces são ordenadas da mais longe para a mais perto (algoritmo do
//      pintor) e devolvidas em coordenadas de tela.
//
// Não há z-buffer: para uma pista (uma superfície só, vista de dentro do
// carro) o algoritmo do pintor é suficiente e custa quase nada — roda a 60 Hz
// num Pentium N5030 sem esforço.
//
// Este arquivo é só matemática: nada de Win32. main.cpp pega as faces e
// desenha com Polygon(); os testes verificam a projeção no Linux.
#pragma once

#include <cstdint>
#include <vector>

#include "base.hpp"
#include "track.hpp"

namespace raceai {

struct Vec3 {
    double x = 0.0, y = 0.0, z = 0.0;
};

// Uma face pronta para desenhar: polígono em pixels + cor.
struct Face3D {
    std::vector<int> xs;          // coordenadas em pixels
    std::vector<int> ys;
    uint32_t cor = 0;             // 0x00RRGGBB
    double profundidade = 0.0;    // distância do centroide até a câmera
    bool valida() const { return xs.size() >= 3; }
};

// Câmera: posição no mundo, para onde olha e campo de visão.
struct Camera3D {
    double x = 0.0, y = 0.0, z = 2.2;   // z = altura do olho (m)
    double yaw = 0.0;                   // para onde a câmera aponta (rad)
    double pitch = -0.06;               // positivo = olhando para cima
    double fov = 68.0;                  // campo de visão vertical (graus)
    double perto = 0.35;                // plano de recorte próximo (m)
    double longe = 900.0;               // nada além disso é desenhado
};

class Render3D {
public:
    void set_camera(const Camera3D& c) { cam_ = c; }
    const Camera3D& camera() const { return cam_; }

    // tamanho da área de desenho (pixels)
    void begin(int largura, int altura);

    // adiciona geometria (coordenadas de mundo, em metros; z = altura)
    void add_quad(Vec3 a, Vec3 b, Vec3 c, Vec3 d, uint32_t cor);
    void add_tri(Vec3 a, Vec3 b, Vec3 c, uint32_t cor);
    // caixa (carro, árvore, prédio): centro, tamanho e rotação em z
    void add_box(Vec3 centro, double comp, double larg, double alt, double yaw,
                 uint32_t cor, uint32_t cor_topo = 0);
    // cone/pirâmide simples (árvore, cone de pista)
    void add_pyramid(Vec3 base, double raio, double altura, uint32_t cor);

    // projeta e devolve as faces em ordem de desenho (longe -> perto)
    std::vector<Face3D> resolve() const;

    // altura do horizonte em pixels (para desenhar céu e chão)
    double horizonte_y() const;

    int largura() const { return larg_; }
    int altura() const { return alt_; }

    // projetor usado pelos testes
    bool projetar(Vec3 p, double* sx, double* sy) const;

private:
    Camera3D cam_;
    int larg_ = 1, alt_ = 1;

    struct FaceBruta {
        std::vector<Vec3> pontos;   // no mundo
        uint32_t cor = 0;
    };
    std::vector<FaceBruta> faces_;
};

// Monta a pista em 3D: asfalto, zebradas, muros e o cenário em volta.
// `elev` é opcional (altura de cada ponto da linha de centro).
void montar_cena_pista(Render3D& r, const Track& t, int centro, int alcance,
                       const std::vector<double>* elev = nullptr);

}  // namespace raceai
