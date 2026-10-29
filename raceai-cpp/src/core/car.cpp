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
    j.set("body_color", Json(body_color));
    j.set("accent_color", Json(accent_color));
    if (!sprite.empty()) j.set("sprite", Json(sprite));
    return j;
}

// ---------------------------------------------------------------- física
void physics_step(const CarSpec& sp, CarState& st, double surface_grip,
                  double surface_roll, double dt) {
    const double m = sp.mass;
    const double a_ax = sp.cg_front;
    const double b_ax = sp.cg_rear();
    const double l_wb = a_ax + b_ax;
    const double iz = sp.iz();
    const double max_speed = std::max(sp.max_speed, 1e-6);

    double vx = st.vx, vy = st.vy, yaw_rate = st.r;
    double speed = std::sqrt(vx * vx + vy * vy);
    double vx_ref = std::max(std::fabs(vx), 1.2);

    // ---------------- direção (comando -> esterço real) -------------------
    double falloff = 1.0 - sp.steer_falloff * clamp(speed / max_speed, 0.0, 1.0);
    double steer_max = sp.max_steer * falloff;
    double target = clamp(st.steer_cmd, -1.0, 1.0) * steer_max;
    double max_delta = sp.steer_rate * dt;
    double steer = st.steer + clamp(target - st.steer, -max_delta, max_delta);

    // ---------------- ângulos de deriva ----------------------------------
    double slip_f = steer - std::atan2(vy + a_ax * yaw_rate, vx_ref);
    double slip_r = -std::atan2(vy - b_ax * yaw_rate, vx_ref);

    // ---------------- cargas verticais -----------------------------------
    double throttle = clamp(st.throttle, 0.0, 1.0);
    double brake = clamp(st.brake, 0.0, 1.0);
    double v_ref = std::max(speed, 5.0);
    double traction = std::min(sp.engine_force, sp.max_power / v_ref);
    double power_curve = clamp(1.0 - std::pow(speed / max_speed, 1.6), 0.0, 1.0);
    double f_drive_demand = throttle * traction * power_curve;

    double reverse = (brake > 0.0 && speed < 0.6 && st.reverse_cmd > 0.5) ? brake : 0.0;
    double f_reverse = reverse * sp.engine_force * sp.reverse_ratio;
    double f_drive = f_drive_demand - f_reverse;

    double f_brake_demand = (speed >= 0.6) ? brake * sp.brake_force : 0.0;
    double drag_f = sp.drag * speed * speed;
    double roll_f = sp.rolling * surface_roll * speed;
    double resist = drag_f + roll_f;

    double long_demand = f_drive - f_brake_demand - resist;
    double ax_est = long_demand / m;

    double weight = m * G + sp.downforce * speed * speed;
    double fz_front = weight * (b_ax / l_wb) - m * ax_est * sp.cg_height / l_wb;
    double fz_rear = weight * (a_ax / l_wb) + m * ax_est * sp.cg_height / l_wb;
    fz_front = std::max(fz_front, weight * 0.05);
    fz_rear = std::max(fz_rear, weight * 0.05);

    // ---------------- forças longitudinais por eixo -----------------------
    double fx_front = f_drive * sp.drive_front - f_brake_demand * sp.brake_front - resist * 0.5;
    double fx_rear = f_drive * (1.0 - sp.drive_front) -
                     f_brake_demand * (1.0 - sp.brake_front) - resist * 0.5;

    // ---------------- laterais + círculo de atrito ------------------------
    double grip = clamp(surface_grip, 0.15, 2.0);
    double mu_f = sp.grip_front * grip;
    double mu_r = sp.grip_rear * grip;
    double fy_front = tire_lateral_force(slip_f, fz_front, mu_f, sp.tire_stiffness, sp.tire_shape);
    double fy_rear = tire_lateral_force(slip_r, fz_rear, mu_r, sp.tire_stiffness, sp.tire_shape);

    double cap_front = mu_f * fz_front;
    double cap_rear = mu_r * fz_rear;
    double mag_front = std::sqrt(fx_front * fx_front + fy_front * fy_front);
    double mag_rear = std::sqrt(fx_rear * fx_rear + fy_rear * fy_rear);
    double scale_f = mag_front > cap_front ? cap_front / std::max(mag_front, 1e-6) : 1.0;
    double scale_r = mag_rear > cap_rear ? cap_rear / std::max(mag_rear, 1e-6) : 1.0;
    fx_front *= scale_f; fy_front *= scale_f;
    fx_rear *= scale_r;  fy_rear *= scale_r;

    // ---------------- dinâmica no referencial do carro --------------------
    double cos_d = std::cos(steer), sin_d = std::sin(steer);
    double fx_body = fx_front * cos_d - fy_front * sin_d + fx_rear;
    double fy_body = fy_front * cos_d + fx_front * sin_d + fy_rear;
    double mz = a_ax * (fy_front * cos_d + fx_front * sin_d) - b_ax * fy_rear;

    double ax_body = fx_body / m + yaw_rate * vy;
    double ay_body = fy_body / m - yaw_rate * vx;
    double dr = mz / iz;

    double new_vx = vx + ax_body * dt;
    double new_vy = vy + ay_body * dt;
    double new_r = yaw_rate + dr * dt;

    // ---------------- limites e estabilidade ------------------------------
    bool idle = (throttle < 0.02) && (brake < 0.02) && (speed < 0.8);
    if (idle) { new_vx *= 0.85; new_vy *= 0.80; new_r *= 0.85; }
    bool stopped = idle && (speed < 0.25);
    if (stopped) { new_vx = 0.0; new_vy = 0.0; new_r = 0.0; }

    new_vx = clamp(new_vx, -max_speed * 0.4, max_speed * 1.05);
    new_vy = clamp(new_vy, -45.0, 45.0);
    new_r = clamp(new_r, -6.0, 6.0);

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

    st.slip_f = slip_f;
    st.slip_r = slip_r;
    st.grip_use = std::max(mag_front / std::max(cap_front, 1e-6),
                           mag_rear / std::max(cap_rear, 1e-6));
    st.ax = ax_body;
    st.ay = ay_body;
    st.speed = std::sqrt(st.vx * st.vx + st.vy * st.vy);
}

}  // namespace raceai
