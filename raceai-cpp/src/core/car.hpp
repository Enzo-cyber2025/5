// car.hpp — especificação de carro (mods em JSON) e modelo de física.
//
// Modelo: bicicleta dinâmica com pneus Pacejka-lite, transferência de carga
// longitudinal, downforce opcional e círculo de atrito por eixo. Integração
// semi-implícita a passo fixo (1/120 s) para ser determinística — requisito
// para comparar gerações de forma justa.
//
// Unidades: SI (m, s, kg, N, rad).  Portado de raceai/src/raceai/car.py.
#pragma once

#include <string>

#include "base.hpp"

namespace raceai {

constexpr double G = 9.81;

struct CarSpec {
    std::string id = "car";
    std::string name = "Carro";
    double mass = 1200.0;
    double length = 4.2;
    double width = 1.9;
    double wheelbase = 2.60;
    double cg_front = 1.25;
    double cg_height = 0.55;
    double engine_force = 9000.0;
    double max_power = 120000.0;
    double brake_force = 13000.0;
    double max_speed = 72.0;
    double reverse_ratio = 0.30;
    double max_steer = 0.60;
    double steer_rate = 4.0;
    double steer_falloff = 0.55;
    double grip_front = 1.45;
    double grip_rear = 1.45;
    double tire_stiffness = 9.0;
    double tire_shape = 1.45;
    double drag = 0.42;
    double rolling = 26.0;
    double downforce = 0.0;
    double drive_front = 0.5;
    double brake_front = 0.62;
    double yaw_inertia = 1.05;
    std::string body_color = "#e0483a";
    std::string accent_color = "#f5f5f5";
    std::string sprite;
    std::string source;

    double cg_rear() const { return std::max(0.4, wheelbase - cg_front); }
    double iz() const {
        return mass * (length * length + width * width) / 12.0 * yaw_inertia;
    }
    double power_to_weight() const { return max_power / std::max(mass, 1.0); }

    std::string summary() const;
    Json to_json() const;

    // Carrega validando/sanitizando: um mod não pode quebrar a física.
    static CarSpec from_json(const Json& data, const std::string& source = "");
    static bool load(const std::string& path, CarSpec& out, std::string* err = nullptr);
};

// ---------------------------------------------------------------- física
struct CarState {
    double x = 0.0, y = 0.0, heading = 0.0;
    double vx = 0.0, vy = 0.0;      // referencial do carro
    double r = 0.0;                 // taxa de guinada
    double steer = 0.0;             // esterço atual (rad)
    double steer_cmd = 0.0;         // comando [-1,1]
    double throttle = 0.0, brake = 0.0;
    double reverse_cmd = 1.0;       // freio com carro parado = ré
    bool alive = true, frozen = false;

    // saídas (sensores / HUD)
    double slip_f = 0.0, slip_r = 0.0, grip_use = 0.0;
    double ax = 0.0, ay = 0.0, speed = 0.0;
};

// Pneus Pacejka-lite: satura suavemente e permite derrapagem controlada.
inline double tire_lateral_force(double slip, double fz, double mu,
                                 double stiffness, double shape) {
    fz = std::max(fz, 0.0);
    return mu * fz * std::sin(shape * std::atan(stiffness * slip));
}

// Avança um passo de física (in-place).
void physics_step(const CarSpec& sp, CarState& st, double surface_grip,
                  double surface_roll, double dt);

}  // namespace raceai
