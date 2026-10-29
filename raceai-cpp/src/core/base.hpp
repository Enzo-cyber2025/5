// base.hpp — matemática, núcleo determinístico e JSON mínimo (sem dependências).
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <map>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace raceai {

// ---------------------------------------------------------------- vetores
struct Vec2 {
    double x = 0.0;
    double y = 0.0;
    Vec2() = default;
    Vec2(double x_, double y_) : x(x_), y(y_) {}
    Vec2 operator+(const Vec2& o) const { return Vec2(x + o.x, y + o.y); }
    Vec2 operator-(const Vec2& o) const { return Vec2(x - o.x, y - o.y); }
    Vec2 operator*(double s) const { return Vec2(x * s, y * s); }
    Vec2 operator/(double s) const { return Vec2(x / s, y / s); }
    Vec2& operator+=(const Vec2& o) { x += o.x; y += o.y; return *this; }
    double norm() const { return std::sqrt(x * x + y * y); }
    double norm2() const { return x * x + y * y; }
};

inline Vec2 operator*(double s, const Vec2& v) { return v * s; }
inline double dot(const Vec2& a, const Vec2& b) { return a.x * b.x + a.y * b.y; }
inline double cross(const Vec2& a, const Vec2& b) { return a.x * b.y - a.y * b.x; }

inline double clamp(double v, double lo, double hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}
inline double lerp(double a, double b, double t) { return a + (b - a) * t; }
// M_PI não existe em todo compilador (MinGW com -std=c++17 não define): usa os
// nossos, para o núcleo compilar igual em qualquer lugar.
constexpr double kPi = 3.14159265358979323846;
constexpr double kTau = 6.28318530717958647692;

inline double wrap_angle(double a) {
    const double k = 6.28318530717958647692;
    a = std::fmod(a + kPi, k);
    if (a < 0.0) a += k;
    return a - kPi;
}

// ---------------------------------------------------------------- RNG (PCG32)
// determinístico: mesma semente -> mesmo treino, em qualquer máquina/plataforma.
class Rng {
public:
    explicit Rng(uint64_t seed = 0x853c49e6748fea9bULL) { seed_with(seed); }

    void seed_with(uint64_t seed) {
        state = 0;
        inc = (seed << 1) | 1ULL;
        next_u32();
        state += seed;
        next_u32();
        spare = 0.0;
        has_spare = false;
    }

    uint32_t next_u32() {
        uint64_t old = state;
        state = old * 6364136223846793005ULL + inc;
        uint32_t xorshifted = uint32_t(((old >> 18u) ^ old) >> 27u);
        uint32_t rot = uint32_t(old >> 59u);
        return (xorshifted >> rot) | (xorshifted << ((0u - rot) & 31u));
    }

    double uniform01() {           // [0, 1)
        return double(next_u32()) * (1.0 / 4294967296.0);
    }
    double range(double a, double b) { return a + (b - a) * uniform01(); }
    int irange(int a, int b) {      // [a, b]
        if (b <= a) return a;
        return a + int(next_u32() % uint32_t(b - a + 1));
    }
    double normal(double mean, double sd) {   // Box-Muller com cache
        if (has_spare) {
            has_spare = false;
            return mean + sd * spare;
        }
        double u, v, s;
        do {
            u = uniform01() * 2.0 - 1.0;
            v = uniform01() * 2.0 - 1.0;
            s = u * u + v * v;
        } while (s >= 1.0 || s == 0.0);
        double mul = std::sqrt(-2.0 * std::log(s) / s);
        spare = v * mul;
        has_spare = true;
        return mean + sd * (u * mul);
    }

private:
    uint64_t state = 0;
    uint64_t inc = 1;
    double spare = 0.0;
    bool has_spare = false;
};

// ---------------------------------------------------------------- JSON
class Json {
public:
    enum Type { Null, Bool, Num, Str, Arr, Obj };

    Json() : type_(Null) {}
    Json(bool v) : type_(Bool), b_(v) {}
    Json(double v) : type_(Num), num_(v) {}
    Json(const std::string& v) : type_(Str), str_(v) {}
    Json(const char* v) : type_(Str), str_(v ? v : "") {}

    static Json array() { Json j; j.type_ = Arr; return j; }
    static Json object() { Json j; j.type_ = Obj; return j; }

    Type type() const { return type_; }
    bool is_null() const { return type_ == Null; }

    // --- leitura
    bool has(const std::string& key) const {
        return type_ == Obj && obj_.find(key) != obj_.end();
    }
    const Json& at(const std::string& key) const {
        static const Json null_json;
        auto it = obj_.find(key);
        return it == obj_.end() ? null_json : it->second;
    }
    const Json& at(size_t i) const {
        static const Json null_json;
        return i < arr_.size() ? arr_[i] : null_json;
    }
    size_t size() const { return type_ == Arr ? arr_.size() : (type_ == Obj ? obj_.size() : 0); }

    double num(double fallback = 0.0) const {
        if (type_ == Num) return num_;
        if (type_ == Str) { try { return std::stod(str_); } catch (...) { return fallback; } }
        if (type_ == Bool) return b_ ? 1.0 : 0.0;
        return fallback;
    }
    std::string str(const std::string& fallback = "") const {
        return type_ == Str ? str_ : fallback;
    }
    bool boolean(bool fallback = false) const {
        if (type_ == Bool) return b_;
        if (type_ == Num) return num_ != 0.0;
        return fallback;
    }
    const std::vector<Json>& items() const { return arr_; }
    const std::map<std::string, Json>& fields() const { return obj_; }

    // --- escrita
    void push(const Json& v) { type_ = Arr; arr_.push_back(v); }
    void set(const std::string& k, const Json& v) { type_ = Obj; obj_[k] = v; }

    std::string dump(int indent = 0) const {
        std::ostringstream os;
        write(os, indent, 0);
        return os.str();
    }

    // --- parser
    static Json parse(const std::string& text) {
        size_t pos = 0;
        Json v = parse_value(text, pos);
        return v;
    }
    static bool load_file(const std::string& path, Json& out, std::string* err = nullptr) {
        std::ifstream f(path, std::ios::binary);
        if (!f) {
            if (err) *err = "não foi possível abrir: " + path;
            return false;
        }
        std::ostringstream ss;
        ss << f.rdbuf();
        try {
            out = parse(ss.str());
            return true;
        } catch (const std::exception& e) {
            if (err) *err = std::string("JSON inválido em ") + path + ": " + e.what();
            return false;
        }
    }
    static bool save_file(const std::string& path, const Json& v) {
        std::ofstream f(path, std::ios::binary);
        if (!f) return false;
        f << v.dump(2);
        return true;
    }

private:
    void write(std::ostringstream& os, int indent, int level) const {
        const std::string pad(indent > 0 ? std::string(size_t(level + 1) * size_t(indent), ' ') : "");
        const std::string pad0(indent > 0 ? std::string(size_t(level) * size_t(indent), ' ') : "");
        const std::string nl = indent > 0 ? "\n" : "";
        switch (type_) {
            case Null: os << "null"; break;
            case Bool: os << (b_ ? "true" : "false"); break;
            case Num: {
                os.setf(std::ostringstream::fixed);
                os.precision(6);
                os << num_;
                break;
            }
            case Str: {
                os << '"';
                for (char c : str_) {
                    switch (c) {
                        case '"': os << "\\\""; break;
                        case '\\': os << "\\\\"; break;
                        case '\n': os << "\\n"; break;
                        case '\r': os << "\\r"; break;
                        case '\t': os << "\\t"; break;
                        default: os << c;
                    }
                }
                os << '"';
                break;
            }
            case Arr: {
                if (arr_.empty()) { os << "[]"; break; }
                os << "[" << nl;
                for (size_t i = 0; i < arr_.size(); ++i) {
                    os << pad;
                    arr_[i].write(os, indent, level + 1);
                    if (i + 1 < arr_.size()) os << "," << nl;
                }
                os << nl << pad0 << "]";
                break;
            }
            case Obj: {
                if (obj_.empty()) { os << "{}"; break; }
                os << "{" << nl;
                size_t i = 0;
                for (const auto& kv : obj_) {
                    os << pad << '"' << kv.first << "\":" << (indent > 0 ? " " : "");
                    kv.second.write(os, indent, level + 1);
                    if (++i < obj_.size()) os << "," << nl;
                }
                os << nl << pad0 << "}";
                break;
            }
        }
    }

    static void skip_ws(const std::string& s, size_t& p) {
        while (p < s.size() && (s[p] == ' ' || s[p] == '\t' || s[p] == '\n' || s[p] == '\r')) ++p;
    }
    static Json parse_value(const std::string& s, size_t& p) {
        skip_ws(s, p);
        if (p >= s.size()) throw std::runtime_error("JSON vazio");
        char c = s[p];
        if (c == '{') return parse_object(s, p);
        if (c == '[') return parse_array(s, p);
        if (c == '"') return Json(parse_string(s, p));
        if (c == 't' || c == 'f') {
            if (s.compare(p, 4, "true") == 0) { p += 4; return Json(true); }
            if (s.compare(p, 5, "false") == 0) { p += 5; return Json(false); }
            throw std::runtime_error("booleano inválido");
        }
        if (c == 'n') {
            if (s.compare(p, 4, "null") == 0) { p += 4; return Json(); }
            throw std::runtime_error("null inválido");
        }
        return Json(parse_number(s, p));
    }
    static Json parse_object(const std::string& s, size_t& p) {
        Json o = Json::object();
        ++p;  // '{'
        skip_ws(s, p);
        if (p < s.size() && s[p] == '}') { ++p; return o; }
        while (p < s.size()) {
            skip_ws(s, p);
            if (s[p] != '"') throw std::runtime_error("chave esperada");
            std::string key = parse_string(s, p);
            skip_ws(s, p);
            if (s[p] != ':') throw std::runtime_error("':' esperado");
            ++p;
            o.set(key, parse_value(s, p));
            skip_ws(s, p);
            if (p < s.size() && s[p] == ',') { ++p; continue; }
            if (p < s.size() && s[p] == '}') { ++p; break; }
            throw std::runtime_error("',' ou '}' esperado");
        }
        return o;
    }
    static Json parse_array(const std::string& s, size_t& p) {
        Json a = Json::array();
        ++p;  // '['
        skip_ws(s, p);
        if (p < s.size() && s[p] == ']') { ++p; return a; }
        while (p < s.size()) {
            a.push(parse_value(s, p));
            skip_ws(s, p);
            if (p < s.size() && s[p] == ',') { ++p; continue; }
            if (p < s.size() && s[p] == ']') { ++p; break; }
            throw std::runtime_error("',' ou ']' esperado");
        }
        return a;
    }
    static std::string parse_string(const std::string& s, size_t& p) {
        ++p;  // '"'
        std::string out;
        while (p < s.size() && s[p] != '"') {
            if (s[p] == '\\' && p + 1 < s.size()) {
                ++p;
                char e = s[p++];
                switch (e) {
                    case 'n': out += '\n'; break;
                    case 't': out += '\t'; break;
                    case 'r': out += '\r'; break;
                    case 'b': out += '\b'; break;
                    case 'f': out += '\f'; break;
                    case 'u': {
                        if (p + 4 <= s.size()) {
                            out += '?';  // caracteres unicode escapados viram '?'
                            p += 4;
                        }
                        break;
                    }
                    default: out += e;
                }
            } else {
                out += s[p++];
            }
        }
        ++p;  // fecha '"'
        return out;
    }
    static double parse_number(const std::string& s, size_t& p) {
        size_t start = p;
        while (p < s.size() && (std::isdigit((unsigned char)s[p]) || s[p] == '-' || s[p] == '+' ||
                                s[p] == '.' || s[p] == 'e' || s[p] == 'E')) {
            ++p;
        }
        return std::stod(s.substr(start, p - start));
    }

    Type type_ = Null;
    bool b_ = false;
    double num_ = 0.0;
    std::string str_;
    std::vector<Json> arr_;
    std::map<std::string, Json> obj_;
};

// ---------------------------------------------------------------- utilidades

// ---------------------------------------------------------------- arquivos
// nome do arquivo sem diretório e sem extensão (id de mods a partir do path)
inline std::string base_name(const std::string& path, bool strip_ext = true) {
    size_t slash = path.find_last_of("/\\");
    std::string name = (slash == std::string::npos) ? path : path.substr(slash + 1);
    if (strip_ext) {
        size_t dot = name.rfind('.');
        if (dot != std::string::npos && dot > 0) name = name.substr(0, dot);
    }
    return name;
}

inline double wrap_pi(double a) {   // atalho: mesmo que wrap_angle
    return wrap_angle(a);
}

inline std::vector<std::string> split_csv(const std::string& s) {
    std::vector<std::string> out;
    std::string cur;
    for (char c : s) {
        if (c == ',') { out.push_back(cur); cur.clear(); }
        else cur += c;
    }
    out.push_back(cur);
    return out;
}

}  // namespace raceai
