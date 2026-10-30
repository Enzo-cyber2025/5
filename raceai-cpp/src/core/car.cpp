#include "car.hpp"

#include <cmath>

namespace raceai {

static double num_or(const Json& j, const std::string& key, double def) {
    return j.has(key) ? j.at(key).num(def) : def;
}

CarSpec CarSpec::from_json(const Json& data, const std::string& src) {
    CarSpec s;
    s.name = data.has("name") ? data.at("name").str("Carro") : "Carro";
    if (s.name.empty()) s.name = "Carro";
    s.id = data.has("id") && !data.at("id").str().empty()
               ? data.at("id").str()
               : base_name(src);
    if (s.id.empty()) s.id = "car";

    s.mass = num_or(data, "mass", s.mass);
    s.length = num_or(data, "length", s.length);
    s.width = num_or(data, "width", s.width);
    s.wheelbase = num_or(data, "wheelbase", s.wheelbase);
    s.cg_front = num_or(data, "cg_front", s.cg_front);
    s.cg_height = num_or(data, "cg_height", s.cg_height);
    s.engine_force = num_or(data, "engine_force", s.engine_force);
    s.max_power = num_or(data, "max_power", s.max_power);
    s.brake_force = num_or(data, "brake_force", s.brake_force);
    s.max_speed = num_or(data, "max_speed", s.max_speed);
    s.reverse_ratio = num_or(data, "reverse_ratio", s.reverse_ratio);
    s.max_steer = num_or(data, "max_steer", s.max_steer);
    s.steer_rate = num_or(data, "steer_rate", s.steer_rate);
    s.steer_falloff = num_or(data, "steer_falloff", s.steer_falloff);
    s.grip_front = num_or(data, "grip_front", s.grip_front);
    s.grip_rear = num_or(data, "grip_rear", s.grip_rear);
    s.tire_stiffness = num_or(data, "tire_stiffness", s.tire_stiffness);
    s.tire_shape = num_or(data, "tire_shape", s.tire_shape);
    s.drag = num_or(data, "drag", s.drag);
    s.rolling = num_or(data, "rolling", s.rolling);
    s.downforce = num_or(data, "downforce", s.downforce);
    s.drive_front = num_or(data, "drive_front", s.drive_front);
    s.brake_front = num_or(data, "brake_front", s.brake_front);
    s.yaw_inertia = num_or(data, "yaw_inertia", s.yaw_inertia);

    // trem de força
    if (data.has("gears") && data.at("gears").type() == Json::Arr) {
        std::vector<double> g;
        for (const Json& v : data.at("gears").items()) if (v.num(0.0) > 0.05) g.push_back(v.num(0.0));
        if (!g.empty()) s.gears = g;
    }
    s.final_drive = num_or(data, "final_drive", s.final_drive);
    s.wheel_radius = num_or(data, "wheel_radius", s.wheel_radius);
    s.drivetrain_eff = num_or(data, "drivetrain_eff", s.drivetrain_eff);
    s.peak_torque = num_or(data, "peak_torque", s.peak_torque);
    s.rpm_idle = num_or(data, "rpm_idle", s.rpm_idle);
    s.rpm_peak = num_or(data, "rpm_peak", s.rpm_peak);
    s.rpm_limit = num_or(data, "rpm_limit", s.rpm_limit);
    s.torque_shape = num_or(data, "torque_shape", s.torque_shape);
    s.shift_up = num_or(data, "shift_up", s.shift_up);
    s.shift_down = num_or(data, "shift_down", s.shift_down);
    s.shift_time = num_or(data, "shift_time", s.shift_time);
    // aero
    s.cd_a = num_or(data, "cd_a", s.cd_a);
    s.cl_a = num_or(data, "cl_a", s.cl_a);
    s.downforce_front = num_or(data, "downforce_front", s.downforce_front);
    // pneus
    s.track_width = num_or(data, "track_width", s.track_width);
    s.roll_front = num_or(data, "roll_front", s.roll_front);
    s.load_sens = num_or(data, "load_sens", s.load_sens);
    s.tire_opt_temp = num_or(data, "tire_opt_temp", s.tire_opt_temp);
    s.tire_temp_rate = num_or(data, "tire_temp_rate", s.tire_temp_rate);
    s.tire_cool_rate = num_or(data, "tire_cool_rate", s.tire_cool_rate);
    s.tire_wear_rate = num_or(data, "tire_wear_rate", s.tire_wear_rate);
    // sistemas
    s.abs_level = num_or(data, "abs_level", s.abs_level);
    s.traction_control = num_or(data, "traction_control", s.traction_control);
    s.fuel_capacity = num_or(data, "fuel_capacity", s.fuel_capacity);
    s.fuel_burn = num_or(data, "fuel_burn", s.fuel_burn);
    s.damage_rate = num_or(data, "damage_rate", s.damage_rate);
    // simulador: rodas, diferencial, freios, suspensão e aerodinâmica
    s.wheel_inertia = num_or(data, "wheel_inertia", s.wheel_inertia);
    s.engine_inertia = num_or(data, "engine_inertia", s.engine_inertia);
    s.diff_lock = num_or(data, "diff_lock", s.diff_lock);
    s.brake_heat = num_or(data, "brake_heat", s.brake_heat);
    s.brake_cool = num_or(data, "brake_cool", s.brake_cool);
    s.brake_fade = num_or(data, "brake_fade", s.brake_fade);
    s.roll_grad = num_or(data, "roll_grad", s.roll_grad);
    s.pitch_grad = num_or(data, "pitch_grad", s.pitch_grad);
    s.susp_tau = num_or(data, "susp_tau", s.susp_tau);
    s.camber_static = num_or(data, "camber_static", s.camber_static);
    s.camber_gain = num_or(data, "camber_gain", s.camber_gain);
    s.camber_loss = num_or(data, "camber_loss", s.camber_loss);
    s.aero_pitch = num_or(data, "aero_pitch", s.aero_pitch);
    // trem de força: limites que mantêm a simulação estável
    if (s.gears.size() > 9) s.gears.resize(9);
    for (double& g : s.gears) g = clamp(g, 0.25, 8.0);
    s.final_drive = clamp(s.final_drive, 1.0, 8.0);
    s.wheel_radius = clamp(s.wheel_radius, 0.15, 0.75);
    s.drivetrain_eff = clamp(s.drivetrain_eff, 0.5, 1.0);
    s.rpm_idle = clamp(s.rpm_idle, 500.0, 2000.0);
    s.rpm_peak = clamp(s.rpm_peak, 1500.0, 14000.0);
    s.rpm_limit = clamp(std::max(s.rpm_limit, s.rpm_peak * 1.1), 2000.0, 16000.0);
    s.torque_shape = clamp(s.torque_shape, 0.4, 3.0);
    s.shift_up = clamp(s.shift_up, 0.5, 0.999);
    s.shift_down = clamp(s.shift_down, 0.15, 0.95);
    s.shift_time = clamp(s.shift_time, 0.0, 1.0);
    // torque de pico: se o mod não informou, deriva da força de tração
    if (s.peak_torque <= 0.0) {
        s.peak_torque = s.engine_force * s.wheel_radius /
                        std::max(s.gears.front() * s.final_drive * s.drivetrain_eff, 0.1);
    }
    s.peak_torque = clamp(s.peak_torque, 40.0, 3000.0);
    // aero / pneus / sistemas
    s.cd_a = clamp(s.cd_a, 0.15, 4.0);
    s.cl_a = clamp(s.cl_a, 0.0, 8.0);
    s.downforce_front = clamp(s.downforce_front, 0.0, 1.0);
    s.track_width = clamp(s.track_width, 0.8, 3.0);
    s.roll_front = clamp(s.roll_front, 0.1, 0.9);
    s.load_sens = clamp(s.load_sens, 0.0, 0.4);
    s.tire_opt_temp = clamp(s.tire_opt_temp, 40.0, 160.0);
    s.tire_temp_rate = clamp(s.tire_temp_rate, 0.0, 0.2);
    s.tire_cool_rate = clamp(s.tire_cool_rate, 0.0, 0.2);
    s.tire_wear_rate = clamp(s.tire_wear_rate, 0.0, 0.01);
    s.abs_level = clamp(s.abs_level, 0.0, 1.0);
    s.traction_control = clamp(s.traction_control, 0.0, 1.0);
    s.fuel_capacity = clamp(s.fuel_capacity, 0.0, 400.0);
    s.fuel_burn = clamp(s.fuel_burn, 0.0, 2.0);
    s.damage_rate = clamp(s.damage_rate, 0.0, 1.0);

    s.wheel_inertia = clamp(num_or(data, "wheel_inertia", s.wheel_inertia), 0.2, 40.0);
    s.engine_inertia = clamp(num_or(data, "engine_inertia", s.engine_inertia), 0.01, 4.0);
    s.diff_lock = clamp(num_or(data, "diff_lock", s.diff_lock), 0.0, 1.0);
    s.brake_heat = clamp(num_or(data, "brake_heat", s.brake_heat), 0.0, 5.0);
    s.brake_cool = clamp(num_or(data, "brake_cool", s.brake_cool), 0.0, 0.5);
    s.brake_fade = clamp(num_or(data, "brake_fade", s.brake_fade), 0.0, 1.0);
    s.roll_grad = clamp(num_or(data, "roll_grad", s.roll_grad), 0.0, 0.30);
    s.pitch_grad = clamp(num_or(data, "pitch_grad", s.pitch_grad), 0.0, 0.30);
    s.susp_tau = clamp(num_or(data, "susp_tau", s.susp_tau), 0.01, 1.0);
    s.camber_static = clamp(num_or(data, "camber_static", s.camber_static), -0.25, 0.25);
    s.camber_gain = clamp(num_or(data, "camber_gain", s.camber_gain), 0.0, 2.0);
    s.camber_loss = clamp(num_or(data, "camber_loss", s.camber_loss), 0.0, 3.0);
    s.aero_pitch = clamp(num_or(data, "aero_pitch", s.aero_pitch), -3.0, 3.0);

    s.body_style = data.has("body_style") ? data.at("body_style").str() : "";
    s.body_color = data.has("body_color") ? data.at("body_color").str(s.body_color) : s.body_color;
    s.accent_color = data.has("accent_color") ? data.at("accent_color").str(s.accent_color) : s.accent_color;
    s.sprite = data.has("sprite") ? data.at("sprite").str() : "";

    // sanitização: mantém a física estável mesmo com mods escritos à mão
    s.mass = clamp(s.mass, 300.0, 6000.0);
    s.length = clamp(s.length, 1.5, 12.0);
    s.width = clamp(s.width, 0.8, 4.0);
    s.wheelbase = clamp(s.wheelbase, 1.0, 8.0);
    s.engine_force = clamp(s.engine_force, 500.0, 60000.0);
    s.max_power = clamp(s.max_power, 3000.0, 2000000.0);
    s.brake_force = clamp(s.brake_force, 500.0, 80000.0);
    s.max_speed = clamp(s.max_speed, 8.0, 140.0);
    s.reverse_ratio = clamp(s.reverse_ratio, 0.0, 1.0);
    s.max_steer = clamp(s.max_steer, 0.15, 1.2);
    s.steer_rate = clamp(s.steer_rate, 0.5, 12.0);
    s.steer_falloff = clamp(s.steer_falloff, 0.0, 0.9);
    s.grip_front = clamp(s.grip_front, 0.4, 3.0);
    s.grip_rear = clamp(s.grip_rear, 0.4, 3.0);
    s.tire_stiffness = clamp(s.tire_stiffness, 2.0, 25.0);
    s.tire_shape = clamp(s.tire_shape, 1.0, 2.2);
    s.drag = clamp(s.drag, 0.05, 3.0);
    s.rolling = clamp(s.rolling, 0.0, 300.0);
    s.downforce = clamp(s.downforce, -2.0, 20.0);
    s.drive_front = clamp(s.drive_front, 0.0, 1.0);
    s.brake_front = clamp(s.brake_front, 0.2, 0.85);
    s.yaw_inertia = clamp(s.yaw_inertia, 0.5, 2.5);
    s.cg_front = clamp(s.cg_front, 0.6, std::max(0.7, s.wheelbase - 0.6));
    s.cg_height = clamp(s.cg_height, 0.15, 1.5);
    s.source = src;
    return s;
}

bool CarSpec::load(const std::string& path, CarSpec& out, std::string* err) {
    Json j;
    if (!Json::load_file(path, j, err)) return false;
    out = from_json(j, path);
    return true;
}

std::string CarSpec::summary() const {
    char buf[256];
    std::snprintf(buf, sizeof(buf),
                  "%s: %.0f kg, %.0f kW (%.0f W/kg), %.0f km/h, aderência %.2f/%.2f, %s",
                  name.c_str(), mass, max_power / 1000.0, power_to_weight(),
                  max_speed * 3.6, grip_front, grip_rear,
                  drive_front > 0.8 ? "dianteira" : (drive_front < 0.2 ? "traseira" : "integral"));
    return std::string(buf);
}

Json CarSpec::to_json() const {
    Json j = Json::object();
    j.set("id", Json(id));
    j.set("name", Json(name));
    j.set("mass", Json(mass));
    j.set("length", Json(length));
    j.set("width", Json(width));
    j.set("wheelbase", Json(wheelbase));
    j.set("cg_front", Json(cg_front));
    j.set("cg_height", Json(cg_height));
    j.set("engine_force", Json(engine_force));
    j.set("max_power", Json(max_power));
    j.set("brake_force", Json(brake_force));
    j.set("max_speed", Json(max_speed));
    j.set("reverse_ratio", Json(reverse_ratio));
    j.set("max_steer", Json(max_steer));
    j.set("steer_rate", Json(steer_rate));
    j.set("steer_falloff", Json(steer_falloff));
    j.set("grip_front", Json(grip_front));
    j.set("grip_rear", Json(grip_rear));
    j.set("tire_stiffness", Json(tire_stiffness));
    j.set("tire_shape", Json(tire_shape));
    j.set("drag", Json(drag));
    j.set("rolling", Json(rolling));
    j.set("downforce", Json(downforce));
    j.set("drive_front", Json(drive_front));
    j.set("brake_front", Json(brake_front));
    j.set("yaw_inertia", Json(yaw_inertia));
    {
        Json g = Json::array();
        for (double v : gears) g.push(Json(v));
        j.set("gears", g);
    }
    j.set("final_drive", Json(final_drive));
    j.set("wheel_radius", Json(wheel_radius));
    j.set("drivetrain_eff", Json(drivetrain_eff));
    j.set("peak_torque", Json(peak_torque));
    j.set("rpm_idle", Json(rpm_idle));
    j.set("rpm_peak", Json(rpm_peak));
    j.set("rpm_limit", Json(rpm_limit));
    j.set("torque_shape", Json(torque_shape));
    j.set("shift_up", Json(shift_up));
    j.set("shift_down", Json(shift_down));
    j.set("shift_time", Json(shift_time));
    j.set("cd_a", Json(cd_a));
    j.set("cl_a", Json(cl_a));
    j.set("downforce_front", Json(downforce_front));
    j.set("track_width", Json(track_width));
    j.set("roll_front", Json(roll_front));
    j.set("load_sens", Json(load_sens));
    j.set("tire_opt_temp", Json(tire_opt_temp));
    j.set("tire_temp_rate", Json(tire_temp_rate));
    j.set("tire_cool_rate", Json(tire_cool_rate));
    j.set("tire_wear_rate", Json(tire_wear_rate));
    j.set("abs_level", Json(abs_level));
    j.set("traction_control", Json(traction_control));
    j.set("fuel_capacity", Json(fuel_capacity));
    j.set("fuel_burn", Json(fuel_burn));
    j.set("damage_rate", Json(damage_rate));
    j.set("wheel_inertia", Json(wheel_inertia));
    j.set("engine_inertia", Json(engine_inertia));
    j.set("diff_lock", Json(diff_lock));
    j.set("brake_heat", Json(brake_heat));
    j.set("brake_cool", Json(brake_cool));
    j.set("brake_fade", Json(brake_fade));
    j.set("roll_grad", Json(roll_grad));
    j.set("pitch_grad", Json(pitch_grad));
    j.set("susp_tau", Json(susp_tau));
    j.set("camber_static", Json(camber_static));
    j.set("camber_gain", Json(camber_gain));
    j.set("camber_loss", Json(camber_loss));
    j.set("aero_pitch", Json(aero_pitch));
    j.set("body_style", Json(body_style));
    j.set("body_color", Json(body_color));
    j.set("accent_color", Json(accent_color));
    if (!sprite.empty()) j.set("sprite", Json(sprite));
    return j;
}

// ---------------------------------------------------------------- física
// Modelo dinâmico de bicicleta com:
//   * motor com curva de torque, corte de giro e câmbio automático de 6 marchas
//   * pneus Pacejka-lite por eixo, com temperatura, desgaste e sensibilidade
//     à carga vertical (transferência longitudinal E lateral)
//   * círculo de atrito por eixo: acelerar demais come a capacidade de curva
//   * aerodinâmica com arrasto (Cd·A) e downforce (Cl·A) distribuída
//   * dano por impacto e consumo de combustível (o carro fica mais leite...)
// Integração semi-implícita a passo fixo: determinística, requisito do GA.
namespace {

inline double clampd(double v, double lo, double hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

// Estimativa grosseira da força lateral (usada para a transferência de carga
// lateral, que depende da aceleração lateral ANTES do cálculo completo).
inline double fy_estimada(const CarSpec& sp, double slip_f, double slip_r,
                          double fz_front, double fz_rear) {
    double mu = 0.5 * (sp.grip_front + sp.grip_rear);
    double ff = mu * fz_front * std::sin(sp.tire_shape * std::atan(sp.tire_stiffness * slip_f));
    double fr = mu * fz_rear * std::sin(sp.tire_shape * std::atan(sp.tire_stiffness * slip_r));
    return ff + fr;
}

// Curva de torque: sobe até rpm_peak e cai depois, cortada em rpm_limit.
inline double torque_motor(const CarSpec& sp, double rpm) {
    if (rpm < sp.rpm_idle) rpm = sp.rpm_idle;
    if (rpm >= sp.rpm_limit) return 0.0;
    const double u = rpm / std::max(sp.rpm_peak, 1.0);
    const double d = u - 1.0;
    // platô largo perto do pico de torque: cai pouco em baixa (embreagem
    // patinando mantém o motor acima do marcha lenta) e mais depois do pico
    const double q = (u < 1.0) ? 0.55 / std::max(sp.torque_shape, 0.2)
                               : 1.35 * std::max(sp.torque_shape, 0.2);
    const double t = 1.0 - q * d * d;
    return sp.peak_torque * clampd(t, 0.30, 1.05);
}

}  // namespace

// ------------------------------------------------------------------ física
// Modelo de simulador:
//   * cada eixo tem roda com inércia própria (motor refletido pela marcha),
//     então patinação e travamento aparecem sozinhos — nada de "cola";
//   * o pneu usa escorregamento COMBINADO: o círculo de atrito é uma
//     consequência do modelo, não um limitador aplicado depois;
//   * a carga vertical vem do peso + transferência longitudinal + lateral +
//     downforce, com a carroceria rolando/pitchando com atraso;
//   * freio esquenta, perde eficiência (fading) e o ABS/controle de tração
//     trabalham em cima do escorregamento real da roda;
//   * diferencial com trava parcial (LSD) e vácuo (aspiração) opcional.
void physics_step(const CarSpec& sp, CarState& st, double surface_grip,
                  double surface_roll, double dt, double draft) {
    const double m_total = sp.mass;
    const double a_ax = sp.cg_front;
    const double b_ax = sp.cg_rear();
    const double l_wb = std::max(a_ax + b_ax, 0.5);
    const double iz = sp.iz();
    const double max_speed = std::max(sp.max_speed, 1e-6);
    const double rho = 1.225;
    const double R = std::max(sp.wheel_radius, 0.15);
    const double b_lat = sp.tire_stiffness;
    const double b_long = sp.tire_stiffness * 1.55;

    double vx = st.vx, vy = st.vy, yaw_rate = st.r;
    double speed = std::sqrt(vx * vx + vy * vy);
    const double vx_ref = std::max(std::fabs(vx), 1.2);

    const double dano = clampd(st.damage, 0.0, 1.0);
    const double pot_disp = 1.0 - 0.45 * dano;      // dano tira potência
    const bool sem_gasolina = sp.fuel_capacity > 0.0 && st.fuel <= 0.0;
    const double vacuo = clampd(draft, 0.0, 1.0);

    // ---------------- esterço (comando -> ângulo real) ----------------------
    double falloff = 1.0 - sp.steer_falloff * clampd(speed / max_speed, 0.0, 1.0);
    double steer_max = sp.max_steer * falloff * (1.0 - 0.25 * dano);
    double target = clampd(st.steer_cmd, -1.0, 1.0) * steer_max;
    double max_delta = sp.steer_rate * dt;
    double steer = st.steer + clampd(target - st.steer, -max_delta, max_delta);

    // ---------------- suspensão: rolagem e pitch com atraso ----------------
    // A transferência de carga demora: a carroceria rola primeiro, depois o
    // peso passa para as rodas de fora. É o que dá a sensação de "carro vivo"
    // na entrada e na saída de curva.
    const double tau_susp = std::max(sp.susp_tau, 0.02);
    const double k_susp = 1.0 - std::exp(-dt / tau_susp);
    st.susp_roll += (sp.roll_grad * clampd(st.ay / G, -2.5, 2.5) - st.susp_roll) * k_susp;
    st.susp_pitch += (sp.pitch_grad * clampd(-st.ax / G, -2.5, 2.5) - st.susp_pitch) * k_susp;

    // cambagem: roda de fora perde aderência quando a carroceria rola
    const double camb_f = sp.camber_static + sp.camber_gain * st.susp_roll;
    const double camb_r = sp.camber_static - sp.camber_gain * st.susp_roll * 0.25;
    const double perda_camb_f = clampd(1.0 - sp.camber_loss * std::fabs(camb_f), 0.70, 1.0);
    const double perda_camb_r = clampd(1.0 - sp.camber_loss * std::fabs(camb_r), 0.70, 1.0);

    // ---------------- ângulos de deriva e escorregamento --------------------
    const double slip_f = steer - std::atan2(vy + a_ax * yaw_rate, vx_ref);
    const double slip_r = -std::atan2(vy - b_ax * yaw_rate, vx_ref);
    // o escorregamento é limitado: acima de ~150 % o pneu já está saturado e
    // valores gigantes só atrapalham a estabilidade numérica
    double sr_f = clampd((st.omega_f * R - vx) / vx_ref, -1.5, 1.5);   // + = roda patinando
    double sr_r = clampd((st.omega_r * R - vx) / vx_ref, -1.5, 1.5);

    // ---------------- câmbio e motor ---------------------------------------
    const int n_marchas = std::max(1, int(sp.gears.size()));
    if (st.gear < 1) st.gear = 1;
    if (st.gear > n_marchas) st.gear = n_marchas;
    double ratio = sp.gears[st.gear - 1] * sp.final_drive;

    // o giro vem das RODAS: por isso o motor "bate no corte" quando patina
    const double omega_e = sp.drive_front * st.omega_f + (1.0 - sp.drive_front) * st.omega_r;
    double rpm = std::fabs(omega_e) * ratio * 60.0 / (2.0 * kPi);
    if (rpm < sp.rpm_idle) rpm = sp.rpm_idle;
    if (rpm > sp.rpm_limit * 1.03) rpm = sp.rpm_limit * 1.03;
    st.rpm = rpm;

    if (st.shift_cd > 0.0) st.shift_cd = std::max(0.0, st.shift_cd - dt);

    double throttle = clampd(st.throttle, 0.0, 1.0);
    double brake = clampd(st.brake, 0.0, 1.0);
    const bool parado_com_re = (brake > 0.05 && speed < 0.8 && st.reverse_cmd > 0.5);

    if (!parado_com_re && st.shift_cd <= 0.0) {
        const bool pode_subir = st.gear < n_marchas && vx > 1.0;
        if (pode_subir && rpm > sp.rpm_limit * sp.shift_up) {
            double rpm_depois = rpm * sp.gears[st.gear] / std::max(sp.gears[st.gear - 1], 0.05);
            if (rpm_depois > sp.rpm_limit * sp.shift_down * 1.18) {
                st.gear += 1;
                st.shift_cd = sp.shift_time;
                ratio = sp.gears[st.gear - 1] * sp.final_drive;
            }
        } else if (st.gear > 1 && rpm < sp.rpm_limit * sp.shift_down) {
            double rpm_depois = rpm * sp.gears[st.gear - 2] / std::max(sp.gears[st.gear - 1], 0.05);
            if (rpm_depois < sp.rpm_limit * 0.97) {
                st.gear -= 1;
                st.shift_cd = sp.shift_time;
                ratio = sp.gears[st.gear - 1] * sp.final_drive;
            }
        }
    }

    double torque = torque_motor(sp, rpm) * pot_disp;
    if (sem_gasolina) torque = 0.0;
    if (st.shift_cd > 0.0) torque = 0.0;                 // corte na troca
    if (parado_com_re) torque = 0.0;

    // ---------------- freios: temperatura e fading --------------------------
    const double trabalho_freio = brake * sp.brake_force * std::fabs(vx);   // W
    st.brake_temp += (sp.brake_heat * trabalho_freio / 1000.0 -
                      sp.brake_cool * (st.brake_temp - 25.0) * (1.0 + speed * 0.05)) * dt;
    st.brake_temp = clampd(st.brake_temp, 15.0, 950.0);
    const double fade = 1.0 - sp.brake_fade * clampd((st.brake_temp - 380.0) / 420.0, 0.0, 1.0);
    const double brake_cap = sp.brake_force * fade * (1.0 - 0.35 * dano);

    // ---------------- torques nas rodas -------------------------------------
    const double f_potencia = sp.max_power * pot_disp / std::max(speed, 3.0);
    double t_drive_total = std::min(throttle * torque * ratio * sp.drivetrain_eff,
                                    f_potencia * R);
    double t_reverse = 0.0;
    if (parado_com_re) {
        double f_rev = brake * sp.engine_force * sp.reverse_ratio * pot_disp;
        f_rev = std::min(f_rev, sp.max_power * 0.25 / std::max(speed, 2.0));
        t_reverse = -f_rev * R;
    }
    // freio de motor: tirar o pé já desacelera (e estabiliza a entrada de curva)
    const double freio_motor = (1.0 - throttle) * 0.10 * sp.engine_force * R *
                               clampd(rpm / std::max(sp.rpm_limit, 1.0), 0.0, 1.2);

    double t_brake_f = 0.0, t_brake_r = 0.0;
    if (!parado_com_re && brake > 0.0 && vx > 0.25) {
        const double tb = brake * brake_cap * R;
        t_brake_f = tb * sp.brake_front;
        t_brake_r = tb * (1.0 - sp.brake_front);
    }

    // ABS: olha o escorregamento da roda (alvo ~ -13 %) e alivia o disco
    if (sp.abs_level > 0.0) {
        auto abs_mod = [&](double sr, double& t) {
            if (t <= 0.0) return;
            const double alvo = -0.13;
            if (sr > alvo) return;
            t *= 1.0 - sp.abs_level * clampd((alvo - sr) / 0.14, 0.0, 1.0);
        };
        abs_mod(sr_f, t_brake_f);
        abs_mod(sr_r, t_brake_r);
    }
    // controle de tração: corta o motor quando a roda patina
    if (sp.traction_control > 0.0) {
        const double sr_med = sp.drive_front * sr_f + (1.0 - sp.drive_front) * sr_r;
        const double corte = 1.0 - sp.traction_control * clampd((sr_med - 0.10) / 0.25, 0.0, 1.0);
        t_drive_total *= clampd(corte, 0.0, 1.0);
    }

    const double t_drive_f = t_drive_total * sp.drive_front + t_reverse * sp.drive_front;
    const double t_drive_r = t_drive_total * (1.0 - sp.drive_front) +
                             t_reverse * (1.0 - sp.drive_front);
    const double t_motor_f = freio_motor * sp.drive_front;
    const double t_motor_r = freio_motor * (1.0 - sp.drive_front);

    // ---------------- aerodinâmica e resistência ----------------------------
    const double v2 = speed * speed;
    const double fator_pitch = 1.0 + sp.aero_pitch * st.susp_pitch;
    // degradação aerodinâmica: lataria amassada e asa suja perdem eficiência
    const double sujeira = clampd(st.aero_deg, 0.0, 1.0);
    const double ef_aero = clampd(1.0 - 0.50 * dano - 0.40 * sujeira, 0.40, 1.0);
    const double drag_f = 0.5 * rho * sp.cd_a * v2 *
                          (1.0 + 0.35 * dano + 0.45 * sujeira) *
                          (1.0 - 0.30 * vacuo);
    const double roll_f = sp.rolling * surface_roll * speed;
    const double downforce = std::max(0.0, 0.5 * rho * sp.cl_a * v2 * fator_pitch *
                                      ef_aero * (1.0 - 0.5 * vacuo));
    const double resist = drag_f + roll_f;

    // ---------------- cargas verticais por eixo -----------------------------
    const double peso = m_total * G + downforce;
    const double transf_long = m_total * clampd(st.ax, -30.0, 30.0) * sp.cg_height / l_wb;
    double fz_front = peso * (b_ax / l_wb) - transf_long +
                      downforce * (sp.downforce_front - b_ax / l_wb);
    double fz_rear = peso - fz_front;
    fz_front = std::max(fz_front, peso * 0.04);
    fz_rear = std::max(fz_rear, peso * 0.04);
    const double fz_ref_front = peso * (b_ax / l_wb);
    const double fz_ref_rear = peso * (a_ax / l_wb);

    // transferência lateral dividida entre os eixos pela barra estabilizadora
    const double transf_lat = m_total * clampd(st.ay, -40.0, 40.0) * sp.cg_height /
                              std::max(sp.track_width, 0.6);
    const double d_fz_f = transf_lat * sp.roll_front;
    const double d_fz_r = transf_lat * (1.0 - sp.roll_front);
    const double pen_lat_f = clampd(1.0 - sp.load_sens * 0.85 * std::fabs(d_fz_f) /
                                    std::max(fz_front, 1.0), 0.55, 1.0);
    const double pen_lat_r = clampd(1.0 - sp.load_sens * 0.85 * std::fabs(d_fz_r) /
                                    std::max(fz_rear, 1.0), 0.55, 1.0);

    // ---------------- pneus: temperatura, desgaste, superfície --------------
    const double trabalho_pneu = (std::fabs(slip_f) + std::fabs(slip_r)) * speed * 0.5 +
                                 (std::fabs(sr_f) + std::fabs(sr_r)) * speed * 0.35;
    const double alvo_temp = sp.tire_opt_temp * (0.55 + 0.45 * clampd(speed / max_speed, 0.0, 1.0));
    st.tire_temp += (sp.tire_temp_rate * trabalho_pneu * (alvo_temp + 40.0 - st.tire_temp) -
                     sp.tire_cool_rate * (st.tire_temp - 25.0)) * dt * 60.0;
    st.tire_temp = clampd(st.tire_temp, 15.0, 190.0);
    const double desgaste_extra = 1.0 + 6.0 * std::fabs(sr_f > 0 ? sr_f : 0.0) +
                                  6.0 * std::fabs(sr_r > 0 ? sr_r : 0.0) +
                                  3.0 * clampd(-std::min(sr_f, sr_r), 0.0, 1.0);
    st.tire_wear = clampd(st.tire_wear + sp.tire_wear_rate * desgaste_extra *
                          (0.25 + trabalho_pneu * 0.02) * dt * 60.0, 0.0, 1.0);

    double fator_temp = 1.0 - 0.00042 * std::pow(st.tire_temp - sp.tire_opt_temp, 2.0);
    fator_temp = clampd(fator_temp, 0.62, 1.03);
    const double fator_desgaste = 1.0 - 0.30 * st.tire_wear;

    const double grip = clampd(surface_grip, 0.12, 2.0);
    const double lsd = clampd(sp.diff_lock, 0.0, 1.0);

    // ---------------- forças dos pneus (escorregamento combinado) -----------
    auto mu_por_carga = [&](double mu0, double fz, double fz_ref) {
        return mu0 * (1.0 - sp.load_sens * (fz / std::max(fz_ref, 1.0) - 1.0));
    };
    double mu_f_eff = std::max(mu_por_carga(sp.grip_front, fz_front, fz_ref_front),
                               sp.grip_front * 0.35);
    double mu_r_eff = std::max(mu_por_carga(sp.grip_rear, fz_rear, fz_ref_rear),
                               sp.grip_rear * 0.35);
    mu_f_eff *= grip * fator_temp * fator_desgaste * perda_camb_f * pen_lat_f;
    mu_r_eff *= grip * fator_temp * fator_desgaste * perda_camb_r * pen_lat_r;
    // LSD: mais tração na saída de curva (as duas rodas trabalham juntas)
    if (lsd > 0.0 && throttle > 0.05) mu_r_eff *= 1.0 + 0.06 * lsd;

    // estado do pneu dado o giro atual das rodas (escorregamento combinado)
    struct EstadoPneu {
        double sr_f = 0.0, sr_r = 0.0, s_f = 0.0, s_r = 0.0;
        Pneu f, r;
    };
    auto estado_pneu = [&](double wf, double wr) {
        EstadoPneu e;
        e.sr_f = clampd((wf * R - vx) / vx_ref, -1.5, 1.5);
        e.sr_r = clampd((wr * R - vx) / vx_ref, -1.5, 1.5);
        e.s_f = std::sqrt(std::pow(b_long * e.sr_f, 2.0) + std::pow(b_lat * slip_f, 2.0));
        e.s_r = std::sqrt(std::pow(b_long * e.sr_r, 2.0) + std::pow(b_lat * slip_r, 2.0));
        e.f = pneu_combinado(e.sr_f, slip_f, fz_front, mu_f_eff, b_lat, b_long, sp.tire_shape);
        e.r = pneu_combinado(e.sr_r, slip_r, fz_rear, mu_r_eff, b_lat, b_long, sp.tire_shape);
        return e;
    };

    // I*domega = T - Fx*R, resolvido com o declive do pneu no denominador:
    // estável mesmo com pneu muito rígido (e sem "bater" a roda).
    auto passo_roda = [&](double omega, double torque_ext, double fx, double s,
                          double mu, double fz, double inercia_extra, double h) {
        const double dFds = mu * fz * sp.tire_shape /
                            (1.0 + sp.tire_shape * sp.tire_shape * s * s);
        const double dFx_dsr = std::max(dFds * b_long, 1.0);
        const double iw = sp.wheel_inertia + inercia_extra;
        const double denom = iw + h * R * R * dFx_dsr / vx_ref;
        return omega + (torque_ext - fx * R) * h / std::max(denom, 1e-4);
    };

    // ---------------- integração das rodas (sub-passos + semi-implícita) -----
    // O pneu é MUITO rígido: com um passo só a roda "bate" (patina e trava
    // em ziguezague). Subdividindo o passo a patinação sai suave, e usar a
    // força do FINAL do passo (em vez do começo) tira a oscilação do corpo.
    const double i_extra = sp.engine_inertia * ratio * ratio;
    const int sub = 4;
    const double dts = dt / sub;
    double wf = st.omega_f, wr = st.omega_r;
    EstadoPneu e = estado_pneu(wf, wr);
    for (int k = 0; k < sub; ++k) {
        wf = passo_roda(wf, t_drive_f - t_brake_f - t_motor_f, e.f.fx, e.s_f, mu_f_eff,
                        fz_front, i_extra * sp.drive_front, dts);
        wr = passo_roda(wr, t_drive_r - t_brake_r - t_motor_r, e.r.fx, e.s_r, mu_r_eff,
                        fz_rear, i_extra * (1.0 - sp.drive_front), dts);
        e = estado_pneu(wf, wr);
    }
    if (!std::isfinite(wf)) wf = vx / R;
    if (!std::isfinite(wr)) wr = vx / R;
    // parado (ou quase) e SEM torque: a roda acompanha o chão, sem vibrar.
    // (com torque não pode travar, senão o carro nunca sai da largada)
    const double torque_total = std::fabs(t_drive_f) + std::fabs(t_drive_r) +
                                std::fabs(t_reverse);
    if (speed < 1.2 && torque_total < 1.0) { wf = vx / R; wr = vx / R; }
    st.omega_f = clampd(wf, -300.0, 600.0);
    st.omega_r = clampd(wr, -300.0, 600.0);
    st.sr_f = e.sr_f;
    st.sr_r = e.sr_r;

    // forças que o corpo sente = as do fim do passo (já acomodadas)
    const Pneu pf = e.f, pr = e.r;

    // ---------------- dinâmica no referencial do carro ----------------------
    const double cos_d = std::cos(steer), sin_d = std::sin(steer);
    const double sinal_v = clampd(vx / 1.5, -1.0, 1.0);   // evita empurrar parado
    double fx_body = pf.fx * cos_d - pf.fy * sin_d + pr.fx - resist * sinal_v;
    double fy_body = pf.fy * cos_d + pf.fx * sin_d + pr.fy;
    double mz = a_ax * (pf.fy * cos_d + pf.fx * sin_d) - b_ax * pr.fy;

    // diferencial travado: mais estável na saída (e um pouco subesterçante)
    mz -= lsd * 0.05 * m_total * std::fabs(vx) * yaw_rate * throttle;

    double ax_body = fx_body / m_total + yaw_rate * vy;
    double ay_body = fy_body / m_total - yaw_rate * vx;
    double dr = mz / iz;

    // amortecimento natural de guinada (estabiliza a baixa velocidade)
    dr -= yaw_rate * clampd(1.2 - speed * 0.05, 0.15, 1.2);

    double new_vx = vx + ax_body * dt;
    double new_vy = vy + ay_body * dt;
    double new_r = yaw_rate + dr * dt;

    // ---------------- limites e estabilidade --------------------------------
    bool idle = (throttle < 0.02) && (brake < 0.02) && (speed < 0.8);
    if (idle) { new_vx *= 0.85; new_vy *= 0.80; new_r *= 0.85; }
    bool stopped = idle && (speed < 0.25);
    if (stopped) {
        new_vx = 0.0; new_vy = 0.0; new_r = 0.0;
        st.omega_f = 0.0; st.omega_r = 0.0;
    }

    new_vx = clampd(new_vx, -max_speed * 0.4, max_speed * 1.05);
    new_vy = clampd(new_vy, -45.0, 45.0);
    new_r = clampd(new_r, -6.0, 6.0);
    if (!std::isfinite(new_vx) || !std::isfinite(new_vy) || !std::isfinite(new_r)) {
        new_vx = 0.0; new_vy = 0.0; new_r = 0.0;
    }

    // ---------------- degradação aerodinâmica -------------------------------
    // rodar na grama/sujeira entope a asa; em pista limpa a perda é bem lenta
    {
        const bool sujo = surface_grip < 0.985 || surface_roll > 1.03;
        const double uso = clampd(std::fabs(speed) / 12.0, 0.0, 1.0);
        const double taxa = (sujo ? 0.22 * uso : 0.0) + 0.006 * std::fabs(speed) / 30.0;
        st.aero_deg = clampd(st.aero_deg + taxa * dt, 0.0, 1.0);
    }

    // ---------------- combustível -------------------------------------------
    if (sp.fuel_capacity > 0.0) {
        double consumo = sp.fuel_burn * (0.06 + 0.94 * throttle) * dt;
        st.fuel = clampd(st.fuel - consumo / std::max(sp.fuel_capacity, 1.0), 0.0, 1.0);
    }

    // integração da pose
    double cos_h = std::cos(st.heading), sin_h = std::sin(st.heading);
    double world_vx = new_vx * cos_h - new_vy * sin_h;
    double world_vy = new_vx * sin_h + new_vy * cos_h;

    if (st.alive && !st.frozen) {
        st.x += world_vx * dt;
        st.y += world_vy * dt;
        st.heading += new_r * dt;
        st.vx = new_vx; st.vy = new_vy; st.r = new_r; st.steer = steer;
    }

    // ---------------- saídas (sensores / HUD) --------------------------------
    st.slip_f = slip_f;
    st.slip_r = slip_r;
    st.grip_use = std::max(pf.mag / std::max(mu_f_eff * fz_front, 1e-6),
                           pr.mag / std::max(mu_r_eff * fz_rear, 1e-6));
    st.ax = ax_body;
    st.ay = ay_body;
    st.speed = std::sqrt(st.vx * st.vx + st.vy * st.vy);
    const double sr_tracao = sp.drive_front * sr_f + (1.0 - sp.drive_front) * sr_r;
    st.wheelspin = (throttle > 0.05) ? clampd((std::fabs(sr_tracao) - 0.10) / 0.45, 0.0, 1.0)
                                     : 0.0;
    st.lockup = clampd((-std::min(sr_f, sr_r) - 0.15) / 0.35, 0.0, 1.0);
}

void aplicar_impacto(const CarSpec& sp, CarState& st, double vel_impacto) {
    st.damage = clampd(st.damage + sp.damage_rate * clampd(vel_impacto, 0.0, 60.0) / 30.0, 0.0, 1.0);
    // a lataria amassada estraga o fluxo de ar: perde downforce e ganha arrasto
    st.aero_deg = clampd(st.aero_deg + clampd(vel_impacto, 0.0, 60.0) * 0.012, 0.0, 1.0);
    // perda instantânea de velocidade proporcional à gravidade da batida
    double fator = clampd(1.0 - 0.020 * vel_impacto, 0.55, 1.0);
    st.vx *= fator;
    st.vy *= fator;
    st.r = clampd(st.r * 0.6, -3.0, 3.0);
}

}  // namespace raceai
