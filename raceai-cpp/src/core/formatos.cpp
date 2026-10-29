// formatos.cpp — leitor de .pt (zip+pickle), .npz, .safetensors e .json.
#include "formatos.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <map>
#include <cctype>
#include <cstdlib>
#include <sstream>

#include "base.hpp"
#include "zip.hpp"

namespace raceai {
namespace {

// ------------------------------------------------------------ leitura de arquivo
bool ler_arquivo(const std::string& caminho, std::vector<uint8_t>& out, std::string* err) {
    FILE* f = std::fopen(caminho.c_str(), "rb");
    if (!f) {
        if (err) *err = "não abriu o arquivo: " + caminho;
        return false;
    }
    uint8_t buf[65536];
    size_t n;
    out.clear();
    while ((n = std::fread(buf, 1, sizeof(buf), f)) > 0) out.insert(out.end(), buf, buf + n);
    std::fclose(f);
    if (out.empty()) {
        if (err) *err = "arquivo vazio: " + caminho;
        return false;
    }
    return true;
}

// ------------------------------------------------------------ pickle (para .pt)
struct PVal {
    enum T { Nulo, Int, Bool, Str, Bytes, Tupla, Lista, Dict, Global, Pers, Obscuro };
    T t = Nulo;
    long long i = 0;
    bool b = false;
    std::string s;                                   // Str/Bytes/modulo
    std::string nome;                                // Global
    std::vector<PVal> itens;                         // Tupla/Lista/Obscuro
    std::vector<std::pair<PVal, PVal> > pares;        // Dict (ordem preservada)
    int tensor = -1;                                 // >=0: é um tensor (índice)
};

struct StorageRef {
    std::string chave;
    std::string tipo;
    long long offset = 0;
    std::vector<long long> shape;
    std::vector<long long> stride;
    std::string nome;
};

class Pickle {
public:
    Pickle(const uint8_t* p, size_t n, std::vector<StorageRef>& refs, std::string* err)
        : p_(p), n_(n), refs_(refs), err_(err) {}

    bool rodar() {
        while (pos_ < n_) {
            uint8_t op = p_[pos_++];
            if (op == '.') return true;                           // STOP
            if (!passo(op)) return false;
        }
        if (err_ && err_->empty()) *err_ = "pickle terminou sem STOP";
        return false;
    }

private:
    const uint8_t* p_;
    size_t n_, pos_ = 0;
    std::vector<PVal> pilha_;
    std::vector<size_t> marcas_;
    std::vector<PVal> memo_;
    std::vector<StorageRef>& refs_;
    std::string* err_;

    bool falha(const char* msg) {
        if (err_ && err_->empty()) *err_ = msg;
        return false;
    }
    bool precisa(size_t qtd) { return pos_ + qtd <= n_; }
    uint8_t byte() { return precisa(1) ? p_[pos_++] : 0; }
    uint32_t u32_() {
        if (!precisa(4)) return 0;
        uint32_t v = uint32_t(p_[pos_]) | (uint32_t(p_[pos_ + 1]) << 8) |
                     (uint32_t(p_[pos_ + 2]) << 16) | (uint32_t(p_[pos_ + 3]) << 24);
        pos_ += 4;
        return v;
    }
    uint16_t u16_() {
        if (!precisa(2)) return 0;
        uint16_t v = uint16_t(p_[pos_]) | uint16_t(uint16_t(p_[pos_ + 1]) << 8);
        pos_ += 2;
        return v;
    }
    bool linha(std::string& out) {                     // até \n
        out.clear();
        while (pos_ < n_ && p_[pos_] != '\n') out.push_back(char(p_[pos_++]));
        if (pos_ >= n_) return false;
        pos_ += 1;
        return true;
    }

    PVal topo() {
        if (pilha_.empty()) return PVal();
        PVal v = pilha_.back();
        pilha_.pop_back();
        return v;
    }
    void memo_set(size_t i, const PVal& v) {
        if (memo_.size() <= i) memo_.resize(i + 1);
        memo_[i] = v;
    }

    bool passo(uint8_t op) {
        switch (op) {
            case 0x80: pos_ += 1; return true;                        // PROTO
            case 0x95: pos_ += 8; return true;                        // FRAME
            case 'N': { PVal v; v.t = PVal::Nulo; pilha_.push_back(v); return true; }
            case 0x88: { PVal v; v.t = PVal::Bool; v.b = true; pilha_.push_back(v); return true; }
            case 0x89: { PVal v; v.t = PVal::Bool; v.b = false; pilha_.push_back(v); return true; }
            case ')': { PVal v; v.t = PVal::Tupla; pilha_.push_back(v); return true; }
            case ']': { PVal v; v.t = PVal::Lista; pilha_.push_back(v); return true; }
            case '}': { PVal v; v.t = PVal::Dict; pilha_.push_back(v); return true; }
            case '(': marcas_.push_back(pilha_.size()); return true;
            case 't': return fecha_tupla();
            case 'l': return fecha_lista();
            case 'd': return fecha_dict();
            case 's': return setitem();
            case 'a': return append();
            case 'R': return reduce();
            case 'b': { topo(); return true; }                        // BUILD (ignora estado)
            case '0': topo(); return true;                            // POP
            case '1': {                                               // POP_MARK
                if (marcas_.empty()) return falha("POP_MARK sem marca");
                size_t m = marcas_.back();
                marcas_.pop_back();
                pilha_.resize(m);
                return true;
            }
            case 'c': {                                               // GLOBAL
                PVal v; v.t = PVal::Global;
                if (!linha(v.s) || !linha(v.nome)) return falha("GLOBAL cortado");
                pilha_.push_back(v);
                return true;
            }
            case 0x93: {                                              // STACK_GLOBAL
                PVal nome = topo(), modulo = topo();
                PVal v; v.t = PVal::Global; v.s = modulo.s; v.nome = nome.s;
                pilha_.push_back(v);
                return true;
            }
            case 'K': { PVal v; v.t = PVal::Int; v.i = byte(); pilha_.push_back(v); return true; }
            case 'M': { PVal v; v.t = PVal::Int; v.i = u16_(); pilha_.push_back(v); return true; }
            case 'J': {
                PVal v; v.t = PVal::Int; v.i = int32_t(u32_()); pilha_.push_back(v); return true;
            }
            case 0x8a: {                                              // LONG1
                uint8_t k = byte();
                long long v = 0;
                for (uint8_t i = 0; i < k; ++i) v |= static_cast<long long>(byte()) << (8 * i);
                PVal p; p.t = PVal::Int; p.i = v; pilha_.push_back(p);
                return true;
            }
            case 0x8b: {                                              // LONG4
                uint32_t k = u32_();
                long long v = 0;
                for (uint32_t i = 0; i < k; ++i) v |= static_cast<long long>(byte()) << (8 * i);
                PVal p; p.t = PVal::Int; p.i = v; pilha_.push_back(p);
                return true;
            }
            case 'X': return texto(u32_(), false);
            case 0x8c: return texto(byte(), false);                   // SHORT_BINUNICODE
            case 0x8d: {                                              // BINUNICODE8
                if (!precisa(8)) return falha("BINUNICODE8 cortado");
                uint64_t tam = 0;
                for (int i = 0; i < 8; ++i) tam |= uint64_t(p_[pos_ + i]) << (8 * i);
                pos_ += 8;
                return texto(static_cast<size_t>(tam), false);
            }
            case 'B': return texto(u32_(), true);
            case 'C': return texto(byte(), true);
            case 'q': memo_set(byte(), pilha_.empty() ? PVal() : pilha_.back()); return true;
            case 'r': memo_set(u32_(), pilha_.empty() ? PVal() : pilha_.back()); return true;
            case 'h': {                                               // BINGET
                size_t i = byte();
                pilha_.push_back(i < memo_.size() ? memo_[i] : PVal());
                return true;
            }
            case 'j': {                                               // LONG_BINGET
                size_t i = u32_();
                pilha_.push_back(i < memo_.size() ? memo_[i] : PVal());
                return true;
            }
            case 'Q': {                                               // BINPERSID
                PVal v = topo();
                PVal p; p.t = PVal::Pers; p.itens.push_back(v);
                pilha_.push_back(p);
                return true;
            }
            case 0x92: {                                              // NEWOBJ
                PVal args = topo(), cls = topo();
                PVal v; v.t = PVal::Obscuro; v.itens.push_back(cls); v.itens.push_back(args);
                pilha_.push_back(v);
                return true;
            }
            default:
                return falha("opcode de pickle não suportado");
        }
    }

    bool texto(size_t tam, bool bytes) {
        if (!precisa(tam)) return falha("texto cortado no pickle");
        PVal v;
        v.t = bytes ? PVal::Bytes : PVal::Str;
        v.s.assign((const char*)(p_ + pos_), tam);
        pos_ += tam;
        pilha_.push_back(v);
        return true;
    }

    std::vector<PVal> corta() {
        if (marcas_.empty()) { std::vector<PVal> v; v.push_back(topo()); return v; }
        size_t m = marcas_.back();
        marcas_.pop_back();
        std::vector<PVal> v(pilha_.begin() + long(m), pilha_.end());
        pilha_.resize(m);
        return v;
    }

    bool fecha_tupla() {
        PVal v; v.t = PVal::Tupla; v.itens = corta(); pilha_.push_back(v); return true;
    }
    bool fecha_lista() {
        PVal v; v.t = PVal::Lista; v.itens = corta(); pilha_.push_back(v); return true;
    }
    bool fecha_dict() {
        std::vector<PVal> v = corta();
        PVal d; d.t = PVal::Dict;
        for (size_t i = 0; i + 1 < v.size(); i += 2) d.pares.push_back({v[i], v[i + 1]});
        pilha_.push_back(d);
        return true;
    }
    bool setitem() {
        PVal valor = topo(), chave = topo();
        if (valor.t == PVal::Obscuro && !valor.itens.empty() && valor.itens[0].tensor >= 0 &&
            chave.t == PVal::Str) {
            int idx = valor.itens[0].tensor;
            if (idx >= 0 && idx < static_cast<int>(refs_.size())) refs_[static_cast<size_t>(idx)].nome = chave.s;
        }
        if (pilha_.empty() || pilha_.back().t != PVal::Dict) {
            PVal d; d.t = PVal::Dict;
            pilha_.push_back(d);
        }
        pilha_.back().pares.push_back({chave, valor});
        return true;
    }
    bool append() {
        PVal valor = topo();
        if (!pilha_.empty() && pilha_.back().t == PVal::Lista) pilha_.back().itens.push_back(valor);
        return true;
    }

    bool reduce() {
        PVal args = topo(), func = topo();
        bool rebuild = func.t == PVal::Global && func.nome.find("_rebuild_tensor") == 0;
        if (!rebuild) {
            PVal v; v.t = PVal::Obscuro; v.itens.push_back(func); v.itens.push_back(args);
            pilha_.push_back(v);
            return true;
        }
        // _rebuild_tensor_v2(storage, offset, size, stride, ...)
        if (args.t != PVal::Tupla || args.itens.size() < 4) return falha("_rebuild_tensor sem argumentos");
        const PVal& st = args.itens[0];
        if (st.t != PVal::Pers || st.itens.empty() || st.itens[0].t != PVal::Tupla)
            return falha("storage do tensor em formato desconhecido");
        const PVal& pid = st.itens[0];
        StorageRef r;
        if (pid.itens.size() >= 3 && pid.itens[2].t == PVal::Str) r.chave = pid.itens[2].s;
        else if (pid.itens.size() >= 2 && pid.itens[1].t == PVal::Str) r.chave = pid.itens[1].s;
        if (pid.itens.size() >= 2 && pid.itens[1].t == PVal::Str) r.tipo = pid.itens[1].s;
        if (args.itens[1].t == PVal::Int) r.offset = args.itens[1].i;
        for (const PVal& v : args.itens[2].itens) r.shape.push_back(v.t == PVal::Int ? v.i : 0);
        for (const PVal& v : args.itens[3].itens) r.stride.push_back(v.t == PVal::Int ? v.i : 0);
        refs_.push_back(r);
        // empilha um valor "tensor" para poder ser nomeado por SETITEM
        PVal marcador; marcador.t = PVal::Obscuro;
        PVal interno; interno.tensor = static_cast<int>(refs_.size()) - 1;
        marcador.itens.push_back(interno);
        pilha_.push_back(marcador);
        return true;
    }
};

// ------------------------------------------------------------ números
float meio_preciso(uint16_t h) {
    uint32_t sinal = uint32_t(h & 0x8000u) << 16;
    uint32_t exp = (h >> 10) & 0x1Fu;
    uint32_t frac = h & 0x3FFu;
    uint32_t bits;
    if (exp == 0) {
        if (frac == 0) { bits = sinal; }
        else {
            exp = 127 - 15;
            while (!(frac & 0x400u)) { frac <<= 1; --exp; }
            frac &= 0x3FFu;
            bits = sinal | (exp << 23) | (frac << 13);
        }
    } else if (exp == 31) {
        bits = sinal | 0x7F800000u | (frac << 13);
    } else {
        bits = sinal | ((exp + 127 - 15) << 23) | (frac << 13);
    }
    float f;
    std::memcpy(&f, &bits, 4);
    return f;
}

float bf16(uint16_t h) {
    uint32_t bits = uint32_t(h) << 16;
    float f;
    std::memcpy(&f, &bits, 4);
    return f;
}

// quantos bytes por elemento e como converter
bool tipo_para_item(const std::string& tipo, int& bytes, int& modo) {
    // modo: 0 float32, 1 float64, 2 float16, 3 bfloat16, 4 int64, 5 int32
    std::string t = tipo;
    for (char& c : t) c = char(::tolower(c));
    if (t.find("double") != std::string::npos || t.find("float64") != std::string::npos) {
        bytes = 8; modo = 1; return true;
    }
    if (t.find("half") != std::string::npos || t.find("float16") != std::string::npos) {
        bytes = 2; modo = 2; return true;
    }
    if (t.find("bfloat16") != std::string::npos) { bytes = 2; modo = 3; return true; }
    if (t.find("long") != std::string::npos && t.find("float") == std::string::npos) {
        bytes = 8; modo = 4; return true;
    }
    if (t.find("int") != std::string::npos) { bytes = 4; modo = 5; return true; }
    bytes = 4; modo = 0;                     // float32 é o padrão
    return true;
}

double ler_item(const uint8_t* p, int modo) {
    switch (modo) {
        case 1: { double d; std::memcpy(&d, p, 8); return d; }
        case 2: { uint16_t h; std::memcpy(&h, p, 2); return meio_preciso(h); }
        case 3: { uint16_t h; std::memcpy(&h, p, 2); return bf16(h); }
        case 4: { int64_t v; std::memcpy(&v, p, 8); return static_cast<double>(v); }
        case 5: { int32_t v; std::memcpy(&v, p, 4); return static_cast<double>(v); }
        default: { float f; std::memcpy(&f, p, 4); return f; }
    }
}

long long produto(const std::vector<long long>& v) {
    long long p = 1;
    for (long long x : v) p *= x;
    return p;
}

// ------------------------------------------------------------ .pt
bool ler_pt(const std::string& caminho, std::vector<Tensor>& out, std::string* err) {
    std::vector<ZipEntry> entradas;
    if (!zip_list(caminho, entradas, err)) return false;
    std::string pkl_nome;
    std::map<std::string, size_t> storages;
    for (size_t i = 0; i < entradas.size(); ++i) {
        const std::string& n = entradas[i].nome;
        if (n.size() >= 8 && n.compare(n.size() - 8, 8, "data.pkl") == 0) pkl_nome = n;
        size_t barra = n.rfind("/data/");
        if (barra != std::string::npos) storages[n.substr(barra + 6)] = i;
    }
    if (pkl_nome.empty()) {
        if (err) *err = "zip sem data.pkl: não é um modelo do PyTorch";
        return false;
    }
    std::vector<uint8_t> pkl;
    for (const ZipEntry& e : entradas) {
        if (e.nome == pkl_nome) {
            if (!zip_read(caminho, e, pkl, err)) return false;
            break;
        }
    }
    std::vector<StorageRef> refs;
    Pickle pk(pkl.data(), pkl.size(), refs, err);
    if (!pk.rodar()) return false;
    if (refs.empty()) {
        if (err) *err = "não achei tensores dentro do .pt (só redes com pesos valem aqui)";
        return false;
    }
    out.clear();
    for (size_t i = 0; i < refs.size(); ++i) {
        const StorageRef& r = refs[i];
        auto it = storages.find(r.chave);
        if (it == storages.end()) {
            if (err) *err = "storage '" + r.chave + "' não está no arquivo";
            return false;
        }
        std::vector<uint8_t> bruto;
        if (!zip_read(caminho, entradas[it->second], bruto, err)) return false;
        int bpi = 4, modo = 0;
        tipo_para_item(r.tipo, bpi, modo);
        long long total = produto(r.shape);
        if (total <= 0) continue;
        Tensor t;
        t.nome = r.nome.empty() ? ("tensor_" + std::to_string(i)) : r.nome;
        t.shape = r.shape;
        t.dados.resize(static_cast<size_t>(total));
        long long ini = r.offset;
        // índice multidimensional com os strides dados (contíguo é o normal)
        std::vector<long long> idx(r.shape.size(), 0);
        for (long long k = 0; k < total; ++k) {
            long long pos = ini;
            for (size_t d = 0; d < idx.size(); ++d)
                pos += idx[d] * (d < r.stride.size() ? r.stride[d] : 0);
            if (pos < 0 || (static_cast<size_t>(pos) + static_cast<size_t>(bpi)) > bruto.size()) {
                if (err) *err = "storage menor do que o tensor pede";
                return false;
            }
            t.dados[static_cast<size_t>(k)] = float(ler_item(bruto.data() + static_cast<size_t>(pos) * static_cast<size_t>(bpi), modo));
            for (size_t d = idx.size(); d-- > 0;) {
                if (++idx[d] < r.shape[d]) break;
                idx[d] = 0;
            }
        }
        out.push_back(t);
    }
    return !out.empty();
}

// ------------------------------------------------------------ .npz
bool ler_npz(const std::string& caminho, std::vector<Tensor>& out, std::string* err) {
    std::vector<ZipEntry> entradas;
    if (!zip_list(caminho, entradas, err)) return false;
    out.clear();
    for (const ZipEntry& e : entradas) {
        bool npy = e.nome.size() > 4 && e.nome.compare(e.nome.size() - 4, 4, ".npy") == 0;
        if (!npy) continue;
        std::vector<uint8_t> bruto;
        if (!zip_read(caminho, e, bruto, err)) return false;
        if (bruto.size() < 12 || std::memcmp(bruto.data(), "\x93NUMPY", 6) != 0) continue;
        uint32_t tam_cab = uint32_t(bruto[8]) | (uint32_t(bruto[9]) << 8);
        size_t ini_dados = 10 + tam_cab;
        std::string cab((const char*)bruto.data() + 10, tam_cab);
        // tamanho do descritor e forma
        std::string desc = "<f4";
        size_t p = cab.find("'descr'");
        if (p != std::string::npos) {
            size_t a = cab.find('\'', p + 7);
            size_t b = cab.find('\'', a + 1);
            if (a != std::string::npos && b != std::string::npos) desc = cab.substr(a + 1, b - a - 1);
        }
        std::vector<long long> shape;
        size_t s = cab.find("'shape'");
        if (s != std::string::npos) {
            size_t a = cab.find('(', s);
            size_t b = cab.find(')', a == std::string::npos ? s : a);
            if (a != std::string::npos && b != std::string::npos) {
                std::string dentro = cab.substr(a + 1, b - a - 1);
                for (char& c : dentro) if (c == ',') c = ' ';
                std::istringstream ss(dentro);
                long long v;
                while (ss >> v) shape.push_back(v);
            }
        }
        if (shape.empty()) continue;
        bool big_endian = !desc.empty() && (desc[0] == '>' || desc[0] == '!');
        char tipo = desc.empty() ? 'f' : desc[desc.size() - 1] == '4' && desc.size() > 1
                                            ? desc[desc.size() - 2] : desc[desc.size() - 1];
        int bpi = 4, modo = 0;
        std::string d = desc;
        if (d.find("f8") != std::string::npos || d.find("d'") != std::string::npos) { bpi = 8; modo = 1; }
        else if (d.find("f2") != std::string::npos) { bpi = 2; modo = 2; }
        else if (d.find("i8") != std::string::npos) { bpi = 8; modo = 4; }
        else if (d.find("i4") != std::string::npos) { bpi = 4; modo = 5; }
        (void)tipo;
        (void)big_endian;
        long long total = produto(shape);
        if (total <= 0 || ini_dados + static_cast<size_t>(total) * static_cast<size_t>(bpi) > bruto.size()) continue;
        Tensor t;
        t.nome = e.nome;
        size_t corta = e.nome.rfind('.');
        if (corta != std::string::npos) t.nome = e.nome.substr(0, corta);
        t.shape = shape;
        t.dados.resize(static_cast<size_t>(total));
        for (long long i = 0; i < total; ++i)
            t.dados[static_cast<size_t>(i)] = float(ler_item(bruto.data() + ini_dados + static_cast<size_t>(i) * static_cast<size_t>(bpi), modo));
        out.push_back(t);
    }
    if (out.empty()) {
        if (err) *err = "npz sem arrays utilizáveis";
        return false;
    }
    return true;
}

// ------------------------------------------------------------ safetensors
bool ler_safetensors(const std::string& caminho, std::vector<Tensor>& out, std::string* err) {
    std::vector<uint8_t> bruto;
    if (!ler_arquivo(caminho, bruto, err)) return false;
    if (bruto.size() < 8) {
        if (err) *err = "arquivo pequeno demais para safetensors";
        return false;
    }
    uint64_t tam = 0;
    for (int i = 0; i < 8; ++i) tam |= uint64_t(bruto[static_cast<size_t>(i)]) << (8 * i);
    if (tam + 8 > bruto.size() || tam == 0) {
        if (err) *err = "cabeçalho safetensors inválido";
        return false;
    }
    std::string cab((const char*)bruto.data() + 8, static_cast<size_t>(tam));
    Json j = Json::parse(cab);
    if (j.type() != Json::Obj) {
        if (err) *err = "cabeçalho safetensors não é um JSON válido";
        return false;
    }
    out.clear();
    const uint8_t* dados = bruto.data() + 8 + static_cast<size_t>(tam);
    size_t disp = bruto.size() - 8 - static_cast<size_t>(tam);
    for (const auto& campo : j.fields()) {
        const std::string& nome = campo.first;
        Json info = campo.second;
        if (!info.has("shape") || !info.has("data_offsets")) continue;
        if (!info.has("dtype")) continue;
        std::string dt = info.at("dtype").str();
        int bpi = 4, modo = 0;
        if (dt == "F64") { bpi = 8; modo = 1; }
        else if (dt == "F16") { bpi = 2; modo = 2; }
        else if (dt == "BF16") { bpi = 2; modo = 3; }
        else if (dt == "I64") { bpi = 8; modo = 4; }
        else if (dt == "I32") { bpi = 4; modo = 5; }
        std::vector<long long> shape;
        for (const Json& v : info.at("shape").items()) shape.push_back(static_cast<long long>(v.num()));
        if (shape.empty()) continue;
        long long ini = static_cast<long long>(info.at("data_offsets").items()[0].num());
        long long total = produto(shape);
        if (total <= 0) continue;
        if (static_cast<size_t>(ini) + static_cast<size_t>(total) * static_cast<size_t>(bpi) > disp) {
            if (err) *err = "safetensors com dados cortados";
            return false;
        }
        Tensor t;
        t.nome = nome;
        t.shape = shape;
        t.dados.resize(static_cast<size_t>(total));
        for (long long i = 0; i < total; ++i)
            t.dados[static_cast<size_t>(i)] = float(ler_item(dados + static_cast<size_t>(ini) + static_cast<size_t>(i) * static_cast<size_t>(bpi), modo));
        out.push_back(t);
    }
    if (out.empty()) {
        if (err) *err = "safetensors sem tensores";
        return false;
    }
    return true;
}

// ------------------------------------------------------------ nomes/ordenação
// comparação "natural": 2 antes de 10, para a ordem das camadas
bool natural_menor(const std::string& a, const std::string& b) {
    size_t i = 0, j = 0;
    while (i < a.size() && j < b.size()) {
        if (::isdigit((unsigned char)a[i]) && ::isdigit((unsigned char)b[j])) {
            size_t i0 = i, j0 = j;
            while (i < a.size() && ::isdigit((unsigned char)a[i])) ++i;
            while (j < b.size() && ::isdigit((unsigned char)b[j])) ++j;
            long long va = std::atoll(a.substr(i0, i - i0).c_str());
            long long vb = std::atoll(b.substr(j0, j - j0).c_str());
            if (va != vb) return va < vb;
            if (i - i0 != j - j0) return (i - i0) < (j - j0);
        } else {
            if (a[i] != b[j]) return (unsigned char)a[i] < (unsigned char)b[j];
            ++i;
            ++j;
        }
    }
    return a.size() < b.size();
}

std::string prefixo_camada(const std::string& nome) {
    std::string p = nome;
    const char* sufixos[] = {".weight", ".bias", ".W", ".b", "_weight", "_bias"};
    for (const char* s : sufixos) {
        size_t pos = p.rfind(s);
        if (pos != std::string::npos && pos + std::strlen(s) == p.size()) {
            p = p.substr(0, pos);
            break;
        }
    }
    return p;
}

[[maybe_unused]] bool e_bias(const std::string& nome) {
    size_t p = nome.rfind('.');
    std::string ultimo = (p == std::string::npos) ? nome : nome.substr(p + 1);
    return ultimo == "bias" || ultimo == "b" || ultimo == "beta";
}

}  // namespace

// ------------------------------------------------------------ montagem do modelo
namespace {

struct Camada {
    const Tensor* w = nullptr;
    const Tensor* b = nullptr;
    long long in = 0, out = 0;
    bool transpor = false;
};

// 24 sensores entram, 2 controles saem (esterço, acelerador)
const int kEntradasJogo = 24;
const int kSaidasJogo = 2;

}  // namespace

bool montar_modelo(const std::vector<Tensor>& tensores, Model& out, std::string* err) {
    std::vector<const Tensor*> matrizes, vetores;
    for (const Tensor& t : tensores) {
        if (t.shape.size() == 2) matrizes.push_back(&t);
        else if (t.shape.size() == 1) vetores.push_back(&t);
    }
    if (matrizes.empty()) {
        if (err) {
            if (tensores.empty())
                *err = "o arquivo não contém tensores";
            else
                *err = "não parece uma rede neural: nenhuma matriz de pesos "
                       "(só tensores de " + std::to_string(tensores[0].shape.size()) +
                       " dimensões — o jogo usa redes totalmente conectadas)";
        }
        return false;
    }

    // ordem das camadas: pelo prefixo do nome ("0.weight"/"0.bias" -> "0"),
    // comparando números como números (2 antes de 10)
    std::vector<const Tensor*> ordem = matrizes;
    std::sort(ordem.begin(), ordem.end(), [](const Tensor* a, const Tensor* b) {
        return natural_menor(prefixo_camada(a->nome), prefixo_camada(b->nome));
    });

    // duas leituras possíveis para a matriz: linha = saída (torch/keras) ou
    // linha = entrada. Escolhemos a que fecha a cadeia de dimensões.
    auto dims_com = [](const Tensor* t, bool transpor, long long& in, long long& out) {
        if (transpor) { in = t->shape[0]; out = t->shape[1]; }
        else { in = t->shape[1]; out = t->shape[0]; }
    };
    int links_a = 0, links_b = 0;
    for (size_t i = 0; i + 1 < ordem.size(); ++i) {
        long long in0, out0, in1, out1;
        dims_com(ordem[i], false, in0, out0);
        dims_com(ordem[i + 1], false, in1, out1);
        if (out0 == in1) links_a += 1;
        dims_com(ordem[i], true, in0, out0);
        dims_com(ordem[i + 1], true, in1, out1);
        if (out0 == in1) links_b += 1;
    }
    const bool transpor = ordem.size() > 1 && links_b > links_a;

    std::vector<Camada> camadas;
    for (const Tensor* w : ordem) {
        Camada c;
        c.w = w;
        c.transpor = transpor;
        dims_com(w, transpor, c.in, c.out);
        // procura o bias desta camada: primeiro pelo prefixo do nome
        // ("0.weight" casa com "0.bias"); se não houver nome, pela ordem
        std::string pre = prefixo_camada(w->nome);
        for (const Tensor* v : vetores) {
            if (prefixo_camada(v->nome) == pre) { c.b = v; break; }
        }
        if (!c.b && camadas.size() < vetores.size() &&
            vetores[camadas.size()]->shape[0] == c.out) {
            c.b = vetores[camadas.size()];
        }
        if (c.in <= 0 || c.out <= 0) {
            if (err) *err = "camada com dimensão zero em " + w->nome;
            return false;
        }
        camadas.push_back(c);
    }

    // topologia do jogo: 24 entradas -> camadas do arquivo -> 2 saídas
    PolicySpec spec;
    spec.obs_dim = kEntradasJogo;
    spec.act_dim = kSaidasJogo;
    spec.hidden.clear();
    // A última matriz é a camada de saída — não inventamos camada nenhuma.
    for (size_t l = 0; l + 1 < camadas.size(); ++l)
        spec.hidden.push_back(int(std::min<long long>(camadas[l].out, 65536)));

    const size_t total = spec.n_params();
    std::vector<float> pesos;
    pesos.assign(total, 0.0f);

    size_t p = 0;
    for (size_t l = 0; l < camadas.size(); ++l) {
        const Camada& c = camadas[l];
        const int n_out = (l + 1 == camadas.size()) ? kSaidasJogo : int(c.out);
        const int n_in = (l == 0) ? kEntradasJogo : int(camadas[l - 1].out);
        const int linhas_arquivo = static_cast<int>(c.out);
        const int colunas_arquivo = static_cast<int>(c.in);
        for (int o = 0; o < n_out; ++o) {
            for (int i = 0; i < n_in; ++i) {
                float v = 0.0f;
                const bool linha_existe = o < linhas_arquivo;
                const bool coluna_existe = i < colunas_arquivo;
                if (linha_existe && coluna_existe) {
                    size_t idx;
                    if (c.transpor)
                        idx = static_cast<size_t>(i) * static_cast<size_t>(linhas_arquivo) + static_cast<size_t>(o);   // [in][out]
                    else
                        idx = static_cast<size_t>(o) * static_cast<size_t>(colunas_arquivo) + static_cast<size_t>(i);   // [out][in]
                    if (idx < c.w->dados.size()) v = c.w->dados[idx];
                }
                if (p < pesos.size()) pesos[p] = v;
                ++p;
            }
        }
        for (int o = 0; o < n_out; ++o) {
            float v = 0.0f;
            if (c.b && o < static_cast<int>(c.b->dados.size())) v = c.b->dados[static_cast<size_t>(o)];
            if (p < pesos.size()) pesos[p] = v;
            ++p;
        }
    }

    out.spec = spec;
    out.weights = pesos;
    Json meta = Json::object();
    meta.set("origem", Json("arquivo externo"));
    meta.set("topologia_original", Json(
        std::to_string(camadas.empty() ? 0 : camadas[0].in) + "->" +
        [&] {
            std::string s;
            for (const Camada& c : camadas) s += (s.empty() ? "" : "x") + std::to_string(c.out);
            return s;
        }()));
    meta.set("pesos_lidos", Json(static_cast<double>(tensores.size())));
    out.meta = meta;
    if (pesos.size() != total) {
        if (err) *err = "inconsistência ao montar a rede";
        return false;
    }
    return true;
}

// ------------------------------------------------------------ despacho
bool ler_tensores(const std::string& caminho, std::vector<Tensor>& out, std::string* err) {
    FILE* f = std::fopen(caminho.c_str(), "rb");
    if (!f) {
        if (err) *err = "não abriu o arquivo: " + caminho;
        return false;
    }
    uint8_t cab[16] = {0};
    size_t lidos = std::fread(cab, 1, sizeof(cab), f);
    long long tam_total = 0;
    if (std::fseek(f, 0, SEEK_END) == 0) tam_total = std::ftell(f);
    std::fclose(f);
    if (lidos < 4) {
        if (err) *err = "arquivo pequeno demais";
        return false;
    }

    // zip (PK) — pode ser .pt ou .npz: decidimos pelas entradas
    if (cab[0] == 'P' && cab[1] == 'K' && cab[2] == 3 && cab[3] == 4) {
        std::vector<ZipEntry> entradas;
        if (!zip_list(caminho, entradas, err)) return false;
        bool pkl = false, npy = false;
        for (const ZipEntry& e : entradas) {
            if (e.nome.size() >= 8 && e.nome.compare(e.nome.size() - 8, 8, "data.pkl") == 0) pkl = true;
            if (e.nome.size() >= 4 && e.nome.compare(e.nome.size() - 4, 4, ".npy") == 0) npy = true;
        }
        if (pkl) return ler_pt(caminho, out, err);
        if (npy) return ler_npz(caminho, out, err);
        if (err) *err = "zip sem tensores conhecidos (esperava data.pkl ou .npy)";
        return false;
    }

    // safetensors: 8 bytes com o tamanho do cabeçalho e um JSON na sequência
    if (lidos >= 9 && cab[8] == '{') {
        uint64_t tam = 0;
        for (int i = 0; i < 8; ++i) tam |= uint64_t(cab[i]) << (8 * i);
        if (tam > 0 && tam + 8 <= uint64_t(tam_total)) return ler_safetensors(caminho, out, err);
    }

    if (err) *err = "formato desconhecido (use .pt, .npz, .safetensors ou .json)";
    return false;
}

bool carregar_modelo_qualquer_formato(const std::string& caminho, Model& out, std::string* err) {
    // o nosso JSON primeiro (é o mais comum por aqui)
    Json j;
    std::string e_json;
    if (Json::load_file(caminho, j, &e_json) && j.type() == Json::Obj && j.has("weights")) {
        Model m;
        std::string e2;
        if (Model::load(caminho, m, &e2)) {
            out = m;
            return true;
        }
    }
    std::vector<Tensor> tensores;
    if (!ler_tensores(caminho, tensores, err)) return false;
    return montar_modelo(tensores, out, err);
}

}  // namespace raceai
