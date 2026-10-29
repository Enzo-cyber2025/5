#include "track.hpp"

#include <numeric>

namespace raceai {

// ---------------------------------------------------------------- geometria
std::vector<Vec2> resample_polyline(const std::vector<Vec2>& pts, double spacing, bool closed) {
    const int n = int(pts.size());
    if (n < 2) return pts;
    const int n_seg = closed ? n : n - 1;
    std::vector<double> lengths(n_seg + 1, 0.0);
    for (int i = 0; i < n_seg; ++i) {
        lengths[i + 1] = lengths[i] + (pts[(i + 1) % n] - pts[i]).norm();
    }
    const double total = lengths[n_seg];
    spacing = std::max(spacing, 1e-3);
    int n_out = int(std::round(total / spacing));
    if (closed) n_out = std::max(8, n_out);
    else n_out = std::max(2, n_out);

    std::vector<Vec2> out;
    out.reserve(n_out);
    int j = 0;
    for (int i = 0; i < n_out; ++i) {
        double target = total * double(i) / double(closed ? n_out : n_out - 1);
        while (j < n_seg - 1 && lengths[j + 1] <= target) ++j;
        double seg_len = lengths[j + 1] - lengths[j];
        double t = seg_len <= 1e-9 ? 0.0 : clamp((target - lengths[j]) / seg_len, 0.0, 1.0);
        const Vec2& a = pts[j % n];
        const Vec2& b = pts[(j + 1) % n];
        out.push_back(a + (b - a) * t);
    }
    return out;
}

std::vector<Vec2> catmull_rom(const std::vector<Vec2>& pts, int samples, bool closed,
                              double tension) {
    const int n = int(pts.size());
    std::vector<Vec2> out;
    if (n < 2) return pts;
    auto get = [&](int i) -> Vec2 {
        if (closed) return pts[((i % n) + n) % n];
        return pts[std::max(0, std::min(n - 1, i))];
    };
    const int segs = closed ? n : n - 1;
    out.reserve(size_t(segs) * size_t(samples));
    for (int i = 0; i < segs; ++i) {
        Vec2 p0 = get(i - 1), p1 = get(i), p2 = get(i + 1), p3 = get(i + 2);
        for (int k = 0; k < samples; ++k) {
            double t = double(k) / double(samples);
            double t2 = t * t, t3 = t2 * t;
            double c0 = -tension * t3 + 2 * tension * t2 - tension * t;
            double c1 = (2 - tension) * t3 + (tension - 3) * t2 + 1;
            double c2 = (tension - 2) * t3 + (3 - 2 * tension) * t2 + tension * t;
            double c3 = tension * t3 - tension * t2;
            out.push_back(p0 * c0 + p1 * c1 + p2 * c2 + p3 * c3);
        }
    }
    return out;
}

// ---------------------------------------------------------------- construção
void Track::rebuild() {
    const int n = int(center.size());
    if (n < 4) return;
    tangents.assign(n, Vec2());
    for (int i = 0; i < n; ++i) {
        const Vec2& prev = center[closed ? (i - 1 + n) % n : std::max(0, i - 1)];
        const Vec2& next = center[closed ? (i + 1) % n : std::min(n - 1, i + 1)];
        Vec2 d = next - prev;
        double len = d.norm();
        tangents[i] = len > 1e-9 ? d / len : Vec2(1.0, 0.0);
    }
    normals.resize(n);
    heading.resize(n);
    for (int i = 0; i < n; ++i) {
        normals[i] = Vec2(-tangents[i].y, tangents[i].x);   // à esquerda
        heading[i] = std::atan2(tangents[i].y, tangents[i].x);
    }
    curvature.assign(n, 0.0);
    for (int i = 0; i < n; ++i) {
        int a = i;
        int b = closed ? (i + 1) % n : std::min(n - 1, i + 1);
        double ds = std::max((center[b] - center[a]).norm(), 1e-6);
        curvature[i] = wrap_angle(heading[b] - heading[a]) / ds;
    }
    arc.assign(n, 0.0);
    for (int i = 1; i < n; ++i) {
        arc[i] = arc[i - 1] + (center[i] - center[i - 1]).norm();
    }
    length = arc[n - 1] + (closed ? (center[0] - center[n - 1]).norm() : 0.0);

    edge_l.resize(n);
    edge_r.resize(n);
    for (int i = 0; i < n; ++i) {
        edge_l[i] = center[i] + normals[i] * half_widths[i];
        edge_r[i] = center[i] - normals[i] * half_widths[i];
    }
    int m = std::max(4, std::min(60, int(length / 25.0)));
    checkpoints.resize(m);
    for (int k = 0; k < m; ++k) checkpoints[k] = int(double(k) * double(n) / double(m)) % n;

    if (grip.size() != size_t(n)) grip.assign(n, 1.0);
    build_walls();
}

void Track::build_walls() {
    const int n = int(center.size());
    wall_p.assign(2 * n, Vec2());
    wall_q.assign(2 * n, Vec2());
    for (int i = 0; i < n; ++i) {
        int j = closed ? (i + 1) % n : std::min(n - 1, i + 1);
        wall_p[i] = edge_l[i];
        wall_q[i] = edge_l[j];
        wall_p[n + i] = edge_r[i];
        wall_q[n + i] = edge_r[j];
    }
    ray_window = 64;
}

Track Track::from_json(const Json& data, const std::string& src) {
    Track t;
    t.name = data.has("name") ? data.at("name").str() : data.at("id").str("pista");
    t.description = data.at("description").str();
    t.closed = data.has("closed") ? data.at("closed").boolean(true) : true;
    t.spacing = data.has("spacing") ? data.at("spacing").num(3.0) : 3.0;
    std::vector<Vec2> pts;
    for (const Json& p : data.at("points").items()) {
        if (p.size() >= 2) pts.emplace_back(p.at(0).num(), p.at(1).num());
    }
    if (pts.size() < 4) throw std::runtime_error("pista '" + t.name + "': menos de 4 pontos");

    // uniformiza os pontos de controle antes do spline (evita overshoot)
    double step = std::max(8.0, t.spacing * 2.0);
    std::vector<Vec2> ctrl = pts.size() > 4 ? resample_polyline(pts, step, t.closed) : pts;
    std::vector<Vec2> smooth = catmull_rom(ctrl, 24, t.closed);
    t.center = resample_polyline(smooth, t.spacing, t.closed);

    const int n = t.n();
    const Json& w = data.at("width");
    t.half_widths.assign(n, 7.0);
    if (w.type() == Json::Arr && w.size() >= 2) {
        std::vector<double> wa;
        for (const Json& v : w.items()) wa.push_back(v.num());
        std::vector<double> ta = wa;
        for (size_t i = 0; i < wa.size(); ++i) ta[i] = double(i) / double(wa.size() - 1);
        for (int i = 0; i < n; ++i) {
            double u = double(i) / double(n);
            size_t k = 0;
            while (k + 2 < ta.size() && ta[k + 1] < u) ++k;
            double span = std::max(1e-9, ta[k + 1] - ta[k]);
            double f = clamp((u - ta[k]) / span, 0.0, 1.0);
            t.half_widths[i] = lerp(wa[k], wa[k + 1], f) * 0.5;
        }
    } else {
        double base = w.num(14.0);
        for (int i = 0; i < n; ++i) t.half_widths[i] = base * 0.5;
    }
    for (int i = 0; i < n; ++i) t.half_widths[i] = std::max(3.0, t.half_widths[i]);

    t.rebuild();
    t.grip.assign(n, 1.0);
    for (const Json& z : data.at("zones").items()) {
        double zs = z.at("start").num(0.0), ze = z.at("end").num(0.0);
        double g = z.at("grip").num(1.0);
        int i0 = int(zs * n) % n;
        int i1 = int(ze * n) % n;
        if (i1 >= i0) for (int i = i0; i < i1 && i < n; ++i) t.grip[i] = g;
        else { for (int i = i0; i < n; ++i) t.grip[i] = g; for (int i = 0; i < i1; ++i) t.grip[i] = g; }
    }
    t.start_index = 0;
    t.source = src;
    return t;
}

bool Track::load(const std::string& path, Track& out, std::string* err) {
    Json j;
    if (!Json::load_file(path, j, err)) return false;
    try {
        out = from_json(j, path);
        return true;
    } catch (const std::exception& e) {
        if (err) *err = e.what();
        return false;
    }
}

// ---------------------------------------------------------------- consultas
int Track::nearest(Vec2 pos, int hint, int window, double guard, double* lateral) const {
    const int n = int(center.size());
    int best = -1;
    double best_d = 1e18;
    auto scan = [&](int from, int count) {
        for (int k = 0; k < count; ++k) {
            int i = ((from + k) % n + n) % n;
            double d = (center[i] - pos).norm2();
            if (d < best_d) { best_d = d; best = i; }
        }
    };
    if (hint >= 0 && n > 0) {
        scan(hint - 6, window);
        double lim = half_widths[best] + guard;
        if (best_d > lim * lim) { best_d = 1e18; best = -1; scan(0, n); }
    } else {
        scan(0, n);
    }
    // mesmo critério do Python: se a projeção cai à frente do ponto, assume o próximo
    if (best >= 0) {
        Vec2 rel0 = pos - center[best];
        if (dot(rel0, tangents[best]) > 0.0) best = (best + 1) % n;
    }
    if (lateral && best >= 0) {
        Vec2 rel = pos - center[best];
        *lateral = cross(tangents[best], rel);   // + = esquerda
    }
    return best;
}

// Interseção raio x segmento: resolve o + t*d = p + u*(q-p) e devolve t (>=0,
// u em [0,1]) ou -1.  Observação: a versão Python (mathutil.ray_segment_distance)
// inverte o sinal do denominador e acaba aceitando acertos *atrás* do carro
// (um raio com um muro 5 m à frente devolve "sem acerto").  Aqui fazemos o
// cálculo correto — os sensores do C++ enxergam de verdade à frente.
// interseção raio/segmento: devolve a distância ao longo do raio ou -1
static double ray_segment(Vec2 o, Vec2 d, Vec2 p, Vec2 q) {
    Vec2 s = q - p;
    double den = cross(d, s);
    if (std::fabs(den) < 1e-12) return -1.0;
    Vec2 op = p - o;
    double t = cross(op, s) / den;      // ao longo do raio
    double u = cross(op, d) / den;      // ao longo do segmento
    if (t >= 0.0 && u >= 0.0 && u <= 1.0) return t;
    return -1.0;
}

void Track::cast_rays(Vec2 pos, double ang0, int idx, int n_rays, double max_range,
                      double fov_rad, double* out) const {
    const int n = int(center.size());
    const int walls = int(wall_p.size());
    for (int r = 0; r < n_rays; ++r) {
        double off = (n_rays == 1) ? 0.0 : (-fov_rad * 0.5 + fov_rad * double(r) / double(n_rays - 1));
        double a = ang0 + off;
        Vec2 d(std::cos(a), std::sin(a));
        double best = max_range;
        int base = (idx - 4 + n) % n;
        for (int k = 0; k < ray_window; ++k) {
            int i0 = (base + k) % n;
            int i1 = i0 + n;
            if (i1 >= walls) i1 = walls - 1;
            if (i0 >= walls) continue;
            double t = ray_segment(pos, d, wall_p[i0], wall_q[i0]);
            if (t >= 0.0 && t < best) best = t;
            t = ray_segment(pos, d, wall_p[i1], wall_q[i1]);
            if (t >= 0.0 && t < best) best = t;
        }
        out[r] = best;
    }
}

void Track::lookahead(int idx, const std::vector<double>& distances,
                      double* out_dheading, double* out_curvature) const {
    const int n = int(center.size());
    for (size_t k = 0; k < distances.size(); ++k) {
        int st = int(std::round(distances[k] / std::max(spacing, 1e-6)));
        int j = ((idx + st) % n + n) % n;
        out_dheading[k] = wrap_angle(heading[j] - heading[idx]);
        if (st > 1) {
            double acc = 0.0;
            for (int s = 0; s < st; ++s) acc += curvature[(idx + s) % n];
            out_curvature[k] = acc / double(st);
        } else {
            out_curvature[k] = curvature[idx];
        }
    }
}

}  // namespace raceai
