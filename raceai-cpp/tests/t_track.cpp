#include "../src/core/track.hpp"
#include <cstdio>
using namespace raceai;
int main() {
    Track t;
    std::string err;
    if (!Track::load("../raceai/assets/tracks/kartodromo.json", t, &err)) {
        printf("ERRO: %s\n", err.c_str()); return 1;
    }
    printf("pista %s: %d pontos, %.1f m, largura media %.1f m, checkpoints %d\n",
           t.name.c_str(), t.n(), t.length, 2.0 * t.half_widths[0], (int)t.checkpoints.size());
    double lat = 0;
    int idx = t.nearest(t.center[10], -1, 48, 25.0, &lat);
    printf("nearest(idx esperado ~10): %d lateral %.3f\n", idx, lat);
    double rays[9];
    t.cast_rays(t.center[10], t.heading[10], 10, 9, 70.0, 140.0 * 3.14159265 / 180.0, rays);
    printf("raios:"); for (int i = 0; i < 9; ++i) printf(" %.1f", rays[i]); printf("\n");
    std::vector<double> dists{15, 30, 50, 80};
    double dh[4], kk[4];
    t.lookahead(10, dists, dh, kk);
    printf("lookahead dheading:"); for (int i = 0; i < 4; ++i) printf(" %.2f", dh[i]);
    printf(" | curvatura:"); for (int i = 0; i < 4; ++i) printf(" %.4f", kk[i]); printf("\n");

    Json pts = Json::array();
    for (int k = 0; k < 36; ++k) {
        double a = k / 36.0 * 6.283185307179586;
        Json p = Json::array();
        p.push(Json(160.0 * std::cos(a)));
        p.push(Json(120.0 * std::sin(a)));
        pts.push(p);
    }
    Json ov = Json::object();
    ov.set("name", Json("oval"));
    ov.set("width", Json(16.0));
    ov.set("points", pts);
    Track o = Track::from_json(ov, "mem");
    double orays[9];
    o.cast_rays(o.center[0], o.heading[0], 0, 9, 70.0, 140.0 * 3.14159265 / 180.0, orays);
    printf("oval reta (meia largura %.1f) raios:", o.half_widths[0]);
    for (int i = 0; i < 9; ++i) printf(" %.1f", orays[i]);
    printf("\n");
    printf("esperado ~: ");
    for (int i = 0; i < 9; ++i) {
        double ang = -70.0 + 140.0 * i / 8.0;
        double s = std::sin(std::fabs(ang) * 3.14159265 / 180.0);
        printf(" %.1f", s < 1e-3 ? 70.0 : std::min(70.0, o.half_widths[0] / s));
    }
    printf("\n");
    return 0;
}
