// track.hpp — pista: spline, arco, paredes, sensores (raycast) e checkpoints.
#pragma once

#include <string>
#include <vector>

#include "base.hpp"

namespace raceai {

class Track {
public:
    std::string name = "sem nome";
    std::string description;
    std::string source;
    bool closed = true;
    double spacing = 3.0;

    std::vector<Vec2> center;        // linha de centro reamostrada
    std::vector<double> half_widths; // metade da largura em cada ponto
    std::vector<Vec2> tangents;      // unitário
    std::vector<Vec2> normals;       // à esquerda da tangente
    std::vector<double> heading;     // rad
    std::vector<double> curvature;   // 1/m (com sinal)
    std::vector<double> arc;         // comprimento acumulado até cada ponto
    std::vector<double> grip;        // aderência por ponto (zonas)
    std::vector<Vec2> edge_l, edge_r;
    std::vector<Vec2> wall_p, wall_q;  // 2N segmentos de parede
    std::vector<int> checkpoints;
    double length = 0.0;
    int start_index = 0;
    int ray_window = 64;

    int n() const { return int(center.size()); }

    // --- construção
    void rebuild();
    static Track from_json(const Json& data, const std::string& source = "");
    static bool load(const std::string& path, Track& out, std::string* err = nullptr);
    bool valid() const { return center.size() >= 8; }

    // --- consultas
    // índice do ponto mais perto e deslocamento lateral com sinal (+ = esquerda)
    int nearest(Vec2 pos, int hint = -1, int window = 48, double guard = 25.0,
                double* lateral = nullptr) const;
    // sensores: distância até a parede para cada raio
    void cast_rays(Vec2 pos, double heading_rad, int idx, int n_rays, double max_range,
                   double fov_rad, double* out) const;
    // diferença de heading e curvatura média para pontos à frente
    void lookahead(int idx, const std::vector<double>& distances,
                   double* out_dheading, double* out_curvature) const;

    double grip_at(int idx) const { return grip.empty() ? 1.0 : grip[idx]; }
    double half_width_at(int idx) const { return half_widths[idx]; }

private:
    void build_walls();
};

// --- geometria auxiliar (exportada para os testes)
std::vector<Vec2> resample_polyline(const std::vector<Vec2>& pts, double spacing, bool closed);
std::vector<Vec2> catmull_rom(const std::vector<Vec2>& pts, int samples_per_seg, bool closed,
                              double tension = 0.5);

}  // namespace raceai
