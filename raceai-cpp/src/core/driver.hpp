// driver.hpp — "quem dirige": rede neural, piloto automático clássico ou
// código Python colado pelo usuário.
//
// A interface é mínima de propósito: o mesmo núcleo de simulação roda com
// qualquer driver, e o interpretador Python embutido (opcional,macro
// RACEAI_WITH_PYTHON) implementa exatamente esta interface.
#pragma once

#include <string>
#include <vector>

#include "policy.hpp"

namespace raceai {

// obs (obs_dim floats) -> out[0] = esterço [-1,1], out[1] = acelerador [-1,1]
class Driver {
public:
    virtual ~Driver() = default;
    virtual void act(const float* obs, int obs_dim, float* out) = 0;
    virtual std::string name() const { return "driver"; }
    virtual bool valid() const { return true; }
    virtual std::string error() const { return ""; }
    // quantas saídas o piloto produz: 3 = esterço, acelerador e pedido de boxe
    virtual int out_dim() const { return 2; }
};

// Rede neural (pesos = genoma da evolução ou modelo carregado).
class PolicyDriver : public Driver {
public:
    PolicyDriver() = default;
    PolicyDriver(const PolicySpec& spec, const std::vector<float>& weights)
        : spec_(spec), w_(weights) {}

    void set_weights(const std::vector<float>& w) { w_ = w; }
    const PolicySpec& spec() const { return spec_; }
    void act(const float* obs, int obs_dim, float* out) override {
        // tolera observação maior que a da rede (ex.: boxe ligado numa rede
        // treinada sem boxe): usa os primeiros spec_.obs_dim valores
        if (w_.size() != spec_.n_params() || obs_dim < spec_.obs_dim) {
            out[0] = 0.0f; out[1] = 0.0f;
            return;
        }
        forward(spec_, w_.data(), obs, out);
    }
    int out_dim() const override { return spec_.act_dim; }
    std::string name() const override { return "rede neural"; }

private:
    PolicySpec spec_;
    std::vector<float> w_;
};

}  // namespace raceai
