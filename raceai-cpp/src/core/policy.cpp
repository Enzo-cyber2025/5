#include "policy.hpp"

#include <cmath>
#include <fstream>

namespace raceai {

std::vector<int> PolicySpec::dims() const {
    std::vector<int> d;
    d.push_back(obs_dim);
    for (int h : hidden) d.push_back(h);
    d.push_back(act_dim);
    return d;
}

std::vector<size_t> PolicySpec::shapes() const {
    std::vector<int> d = dims();
    std::vector<size_t> out;
    for (size_t i = 0; i + 1 < d.size(); ++i) {
        out.push_back(size_t(d[i + 1]) * size_t(d[i]));   // pesos
        out.push_back(size_t(d[i + 1]));                  // bias
    }
    return out;
}

size_t PolicySpec::n_params() const {
    size_t total = 0;
    for (size_t s : shapes()) total += s;
    return total;
}

Json PolicySpec::to_json() const {
    Json j = Json::object();
    j.set("obs_dim", Json(double(obs_dim)));
    j.set("act_dim", Json(double(act_dim)));
    Json h = Json::array();
    for (int v : hidden) h.push(Json(double(v)));
    j.set("hidden", h);
    return j;
}

PolicySpec PolicySpec::from_json(const Json& j) {
    PolicySpec s;
    if (j.is_null()) return s;
    s.obs_dim = std::max(1, int(j.at("obs_dim").num(24)));
    s.act_dim = std::max(1, int(j.at("act_dim").num(2)));
    std::vector<int> h;
    for (const Json& v : j.at("hidden").items()) h.push_back(std::max(1, int(v.num(64))));
    if (!h.empty()) s.hidden = h;
    return s;
}

std::vector<float> init_genome(const PolicySpec& spec, Rng& rng, double scale) {
    std::vector<int> d = spec.dims();
    std::vector<float> g;
    for (size_t i = 0; i + 1 < d.size(); ++i) {
        int fan_in = d[i], fan_out = d[i + 1];
        double lim = scale * std::sqrt(6.0 / double(fan_in + fan_out));
        size_t nw = size_t(fan_in) * size_t(fan_out);
        for (size_t k = 0; k < nw; ++k) g.push_back(float(rng.range(-lim, lim)));
        for (int k = 0; k < fan_out; ++k) g.push_back(0.0f);   // bias zero
    }
    return g;
}

// Layout do genoma, igual ao do treinador Python: para cada camada, primeiro
// a matriz de pesos (linhas = neurônios de saída) e depois o vetor de bias.
void forward(const PolicySpec& spec, const float* w, const float* obs, float* out) {
    std::vector<int> d = spec.dims();
    const int layers = int(d.size()) - 1;
    // buffers: até 256 neurônios por camada (suficiente para estas MLPs)
    float a[256], b[256];
    int cur = d[0];
    for (int i = 0; i < cur; ++i) a[i] = obs[i];
    const float* p = w;
    for (int l = 0; l < layers; ++l) {
        const int n_in = d[l], n_out = d[l + 1];
        const size_t nw = size_t(n_in) * size_t(n_out);
        for (int o = 0; o < n_out; ++o) {
            const float* row = p + size_t(o) * size_t(n_in);
            float acc = p[nw + size_t(o)];            // bias
            for (int i = 0; i < n_in; ++i) acc += row[i] * a[i];
            b[o] = std::tanh(acc);
        }
        p += nw + size_t(n_out);
        cur = n_out;
        for (int i = 0; i < cur; ++i) a[i] = b[i];
    }
    for (int i = 0; i < d.back(); ++i) out[i] = a[i];
}

// ------------------------------------------------------------------ modelo
bool Model::save(const std::string& path, std::string* err) const {
    Json j = spec.to_json();
    Json w = Json::array();
    for (float v : weights) w.push(Json(double(v)));
    j.set("weights", w);
    j.set("meta", meta);
    if (!Json::save_file(path, j)) {
        if (err) *err = "não foi possível salvar: " + path;
        return false;
    }
    return true;
}

bool Model::load(const std::string& path, Model& out, std::string* err) {
    Json j;
    if (!Json::load_file(path, j, err)) return false;
    PolicySpec sp = PolicySpec::from_json(j);
    std::vector<float> w;
    for (const Json& v : j.at("weights").items()) w.push_back(float(v.num()));
    if (w.size() != sp.n_params()) {
        if (err) {
            char buf[160];
            std::snprintf(buf, sizeof(buf),
                          "modelo com %zu pesos, a topologia espera %zu",
                          w.size(), sp.n_params());
            *err = buf;
        }
        return false;
    }
    out.spec = sp;
    out.weights = w;
    out.meta = j.has("meta") ? j.at("meta") : Json::object();
    return true;
}

}  // namespace raceai
