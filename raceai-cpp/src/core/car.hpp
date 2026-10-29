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
#include <vector>

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

    // ---- trem de forca (motor a combustao com cambio) ----
    std::vector<double> gears = {3.40, 2.20, 1.60, 1.24, 1.00, 0.82};
    double final_drive = 3.60;
    double wheel_radius = 0.33;
    double drivetrain_eff = 0.92;
    double peak_torque = 0.0;       // 0 = deriva de engine_force
    double rpm_idle = 950.0;
    double rpm_peak = 5200.0;
    double rpm_limit = 6900.0;
    double torque_shape = 1.15;     // largura da curva de torque
    double shift_up = 0.94;         // fracao do corte para subir marcha
    double shift_down = 0.52;       // fracao do corte para reduzir
    double shift_time = 0.22;       // s sem tracao na troca

    // ---- aerodinamica ----
    double cd_a = 0.72;             // Cd * area frontal (m^2)
    double cl_a = 0.0;              // Cl * area (downforce)
    double downforce_front = 0.45;  // fracao do downforce na dianteira

    // ---- pneus ----
    double track_width = 1.62;
    double roll_front = 0.55;       // rigidez anti-rolagem dianteira
    double load_sens = 0.12;        // perda de mu por carga extra
    double tire_opt_temp = 90.0;    // graus C de grip máximo
    double tire_temp_rate = 0.020;
    double tire_cool_rate = 0.012;
    double tire_wear_rate = 0.00018;

    // ---- rodas, diferencial e freios (modelo de simulador) ----
    double wheel_inertia = 3.2;     // kg*m^2 por eixo (duas rodas)
    double engine_inertia = 0.22;   // kg*m^2 do virabrequim (refletido pela marcha)
    double diff_lock = 0.25;        // 0 = diferencial aberto, 1 = travado (LSD)
    double brake_heat = 0.20;       // graus C por kJ de trabalho de freio
    double brake_cool = 0.020;      // resfriamento (1/s)
    double brake_fade = 0.35;       // perda de força com o disco quente

    // ---- suspensão, cambagem e atitude ----
    double roll_grad = 0.055;       // rad de rolagem por g lateral
    double pitch_grad = 0.025;      // rad de pitch por g longitudinal
    double susp_tau = 0.12;         // s: a carroceria não responde na hora
    double camber_static = -0.020;  // rad (negativo = cambagem negativa)
    double camber_gain = 0.55;      // ganho de cambagem com a rolagem
    double camber_loss = 0.55;      // perda de aderência por rad de cambagem
    double aero_pitch = 0.35;       // quanto o pitch muda o downforce

    // ---- sistemas ----
    double abs_level = 0.0;         // 0 = sem ABS, 1 = ABS perfeito
    double traction_control = 0.0;
    double fuel_capacity = 100.0;   // litros (0 = sem combustivel)
    double fuel_burn = 0.055;       // litros/s em aceleração plena
    double damage_rate = 0.045;     // dano por impacto (por m/s de choque)

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

    // trem de força
    double rpm = 0.0;
    int gear = 1;
    double shift_cd = 0.0;          // tempo restante de troca
    double wheelspin = 0.0;         // 0..1 (patinação do eixo de tração)
    double lockup = 0.0;            // 0..1 (roda travada no freio)
    double omega_f = 0.0, omega_r = 0.0;  // rotação das rodas (rad/s) por eixo
    double sr_f = 0.0, sr_r = 0.0;        // escorregamento longitudinal (+ = patina)

    // pneus e sistemas
    double tire_temp = 70.0;
    double tire_wear = 0.0;
    double damage = 0.0;            // 0..1
    double fuel = 1.0;              // fração do tanque
    double brake_temp = 60.0;       // graus C do disco
    double susp_roll = 0.0;         // rad (rolagem da carroceria)
    double susp_pitch = 0.0;        // rad (pitch da carroceria)

    void reset_systems() {
        rpm = 0.0; gear = 1; shift_cd = 0.0; wheelspin = 0.0; lockup = 0.0;
        omega_f = 0.0; omega_r = 0.0; sr_f = 0.0; sr_r = 0.0;
        tire_temp = 70.0; tire_wear = 0.0; damage = 0.0; fuel = 1.0;
        brake_temp = 60.0; susp_roll = 0.0; susp_pitch = 0.0;
    }
};

// Pneus Pacejka-lite: satura suavemente e permite derrapagem controlada.
inline double tire_lateral_force(double slip, double fz, double mu,
                                 double stiffness, double shape) {
    fz = std::max(fz, 0.0);
    return mu * fz * std::sin(shape * std::atan(stiffness * slip));
}

// Pneu com escorregamento COMBINADO (elipse de atrito de verdade): pedir força
// longitudinal come a aderência lateral, e vice-versa. É o que faz o carro
// sair de frente numa freada forte ou de traseira ao acelerar em cima da zebra.
struct Pneu {
    double fx = 0.0, fy = 0.0, mag = 0.0;
};

inline Pneu pneu_combinado(double slip_x, double slip_y, double fz, double mu,
                           double b_lat, double b_long, double shape) {
    Pneu p;
    if (fz <= 0.0 || mu <= 0.0) return p;
    const double sx = b_long * slip_x;      // escorregamento longitudinal normalizado
    const double sy = b_lat * slip_y;       // escorregamento lateral normalizado
    const double s = std::sqrt(sx * sx + sy * sy);
    if (s < 1e-6) return p;
    p.mag = mu * fz * std::sin(shape * std::atan(s));
    p.fx = p.mag * sx / s;
    p.fy = p.mag * sy / s;
    return p;
}

// Avança um passo de física (in-place).
// `draft` (0..1) é o vácuo: quanto do ar do carro da frente você está
// aproveitando — reduz arrasto e um pouco do downforce.
void physics_step(const CarSpec& sp, CarState& st, double surface_grip,
                  double surface_roll, double dt, double draft = 0.0);

// Registra uma batida: gera dano (perda de potência/aderência) e tira velocidade.
void aplicar_impacto(const CarSpec& sp, CarState& st, double vel_impacto);

}  // namespace raceai
