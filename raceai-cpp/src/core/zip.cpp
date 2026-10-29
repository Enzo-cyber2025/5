// zip.cpp — leitor de ZIP + inflate (ver zip.hpp).
#include "zip.hpp"

#include <algorithm>
#include <cstdio>
#include <cstring>

namespace raceai {
namespace {

uint32_t u32(const uint8_t* p) {
    return uint32_t(p[0]) | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16) |
           (uint32_t(p[3]) << 24);
}
uint64_t u64(const uint8_t* p) {
    uint64_t v = 0;
    for (int i = 7; i >= 0; --i) v = (v << 8) | p[i];
    return v;
}
uint16_t u16(const uint8_t* p) { return uint16_t(p[0]) | (uint16_t(p[1]) << 8); }

// ------------------------------------------------------------------ inflate
struct Bits {
    const uint8_t* p = nullptr;
    size_t n = 0, pos = 0;
    uint32_t acc = 0;
    int bits = 0;
    bool erro = false;

    Bits(const uint8_t* dados, size_t tam) : p(dados), n(tam) {}

    int bit() {
        if (bits == 0) {
            if (pos >= n) { erro = true; return 0; }
            acc = p[pos++];
            bits = 8;
        }
        int b = acc & 1;
        acc >>= 1;
        --bits;
        return b;
    }
    uint32_t ler(int qtd) {          // bits chegam do menos para o mais significativo
        uint32_t v = 0;
        for (int i = 0; i < qtd; ++i) v |= uint32_t(bit()) << i;
        return v;
    }
    void alinhar() { acc = 0; bits = 0; }
};

// Tabela canônica de Huffman: guardamos os símbolos ordenados por
// (comprimento, código) e comparamos bit a bit. Simples e suficiente para
// carregar um modelo — a velocidade aqui não importa.
struct Huffman {
    struct Entrada {
        uint32_t codigo;
        uint8_t len;
        uint16_t simbolo;
    };
    std::vector<Entrada> tabela;
    bool ok = false;

    bool construir(const std::vector<uint8_t>& comprimentos) {
        // contagem por comprimento -> códigos canônicos
        uint16_t contagem[16] = {0};
        for (uint8_t c : comprimentos)
            if (c > 0 && c < 16) contagem[c] += 1;      // comprimento 0 = ausente
        uint16_t codigo = 0, primeiro[16] = {0};
        for (int l = 1; l <= 15; ++l) {
            codigo = uint16_t((codigo + contagem[l - 1]) * 2);
            primeiro[l] = codigo;
        }
        uint16_t usado[16] = {0};
        tabela.clear();
        for (size_t s = 0; s < comprimentos.size(); ++s) {
            uint8_t l = comprimentos[s];
            if (!l) continue;
            uint32_t c = uint32_t(primeiro[l] + usado[l]);
            usado[l] += 1;
            tabela.push_back({c, l, uint16_t(s)});
        }
        std::sort(tabela.begin(), tabela.end(), [](const Entrada& a, const Entrada& b) {
            if (a.len != b.len) return a.len < b.len;
            return a.codigo < b.codigo;
        });
        ok = !tabela.empty();
        return ok;
    }

    int decodifica(Bits& b) const {
        uint32_t codigo = 0;
        for (int l = 1; l <= 15; ++l) {
            codigo = (codigo << 1) | uint32_t(b.bit());
            for (const Entrada& e : tabela) {
                if (e.len != l) continue;
                if (e.codigo == codigo) return e.simbolo;
            }
        }
        return -1;
    }
};

bool montar_huffman(Huffman& h, const std::vector<uint8_t>& comps) {
    return h.construir(comps);
}

const uint16_t kBaseTam[29] = {3,  4,  5,  6,  7,  8,  9,  10, 11,  13,  15,  17,  19,  23, 27,
                               31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258};
const uint8_t kExtraTam[29] = {0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2,
                               2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0};
const uint16_t kBaseDist[30] = {1,    2,    3,    4,    5,    7,    9,    13,   17,   25,
                                33,   49,   65,   97,   129,  193,  257,  385,  513,  769,
                                1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577};
const uint8_t kExtraDist[30] = {0, 0, 0, 0, 1, 1, 2, 2,  3,  3,  4,  4,  5,  5,  6,
                                6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13};

const uint8_t kOrdemComprimentos[19] = {16, 17, 18, 0, 8,  7, 9,  6, 10, 5,
                                        11, 4,  12, 3, 13, 2, 14, 1, 15};

}  // namespace

bool inflate_bytes(const uint8_t* entrada, size_t n, std::vector<uint8_t>& saida,
                   std::string* err) {
    Bits b(entrada, n);
    for (;;) {
        int final = b.bit();
        int tipo = b.ler(2);
        if (b.erro) {
            if (err) *err = "dados comprimidos cortados no meio";
            return false;
        }
        if (tipo == 0) {                                    // guardado
            b.alinhar();
            // LEN e NLEN são de 16 bits (o NLEN é o complemento do LEN)
            if (b.pos + 4 > b.n) {
                if (err) *err = "bloco guardado sem tamanho";
                return false;
            }
            uint32_t len = u16(b.p + b.pos);
            uint32_t nlen = u16(b.p + b.pos + 2);
            b.pos += 4;
            if ((len ^ 0xFFFFu) != nlen) {
                if (err) *err = "bloco guardado corrompido";
                return false;
            }
            if (b.pos + len > b.n) {
                if (err) *err = "bloco guardado maior que o arquivo";
                return false;
            }
            saida.insert(saida.end(), b.p + b.pos, b.p + b.pos + len);
            b.pos += len;
            b.alinhar();
        } else if (tipo == 1 || tipo == 2) {                // huffman fixo/dinâmico
            std::vector<uint8_t> comp_lit(288, 0), comp_dist(30, 0);
            if (tipo == 1) {
                for (int i = 0; i < 144; ++i) comp_lit[i] = 8;
                for (int i = 144; i < 256; ++i) comp_lit[i] = 9;
                for (int i = 256; i < 280; ++i) comp_lit[i] = 7;
                for (int i = 280; i < 288; ++i) comp_lit[i] = 8;
                for (int i = 0; i < 30; ++i) comp_dist[i] = 5;
            } else {
                uint32_t nlit = b.ler(5) + 257;
                uint32_t ndist = b.ler(5) + 1;
                uint32_t ncod = b.ler(4) + 4;
                std::vector<uint8_t> comps_cod(19, 0);
                for (uint32_t i = 0; i < ncod; ++i) comps_cod[kOrdemComprimentos[i]] = uint8_t(b.ler(3));
                Huffman h_cod;
                if (!montar_huffman(h_cod, comps_cod)) {
                    if (err) *err = "tabela huffman dos comprimentos inválida";
                    return false;
                }
                std::vector<uint8_t> comps;
                comps.reserve(nlit + ndist);
                while (comps.size() < nlit + ndist) {
                    int s = h_cod.decodifica(b);
                    if (s < 0) {
                        if (err) *err = "huffman corrompido";
                        return false;
                    }
                    if (s < 16) {
                        comps.push_back(uint8_t(s));
                    } else if (s == 16) {                    // repete o anterior
                        if (comps.empty()) {
                            if (err) *err = "huffman com repetição vazia";
                            return false;
                        }
                        uint32_t vezes = 3 + b.ler(2);
                        uint8_t ultimo = comps.back();
                        for (uint32_t i = 0; i < vezes; ++i) comps.push_back(ultimo);
                    } else if (s == 17) {
                        uint32_t vezes = 3 + b.ler(3);
                        for (uint32_t i = 0; i < vezes; ++i) comps.push_back(0);
                    } else {
                        uint32_t vezes = 11 + b.ler(7);
                        for (uint32_t i = 0; i < vezes; ++i) comps.push_back(0);
                    }
                }
                comp_lit.assign(comps.begin(), comps.begin() + nlit);
                comp_lit.resize(288, 0);
                comp_dist.assign(comps.begin() + nlit, comps.begin() + nlit + ndist);
                comp_dist.resize(30, 0);
            }
            Huffman h_lit, h_dist;
            if (!montar_huffman(h_lit, comp_lit) || !montar_huffman(h_dist, comp_dist)) {
                if (err) *err = "tabelas huffman inválidas";
                return false;
            }
            for (;;) {
                int s = h_lit.decodifica(b);
                if (b.erro) {
                    if (err) *err = "dados comprimidos cortados";
                    return false;
                }
                if (s < 0) {
                    if (err) *err = "símbolo inválido";
                    return false;
                }
                if (s < 256) {
                    saida.push_back(uint8_t(s));
                } else if (s == 256) {
                    break;
                } else {
                    int idx = s - 257;
                    if (idx >= 29) {
                        if (err) *err = "comprimento inválido";
                        return false;
                    }
                    uint32_t tam = kBaseTam[idx] + b.ler(kExtraTam[idx]);
                    int ds = h_dist.decodifica(b);
                    if (ds < 0 || ds >= 30) {
                        if (err) *err = "distância inválida";
                        return false;
                    }
                    uint32_t dist = kBaseDist[ds] + b.ler(kExtraDist[ds]);
                    if (dist > saida.size()) {
                        if (err) *err = "distância aponta antes do começo";
                        return false;
                    }
                    size_t de = saida.size() - dist;
                    for (uint32_t i = 0; i < tam; ++i) saida.push_back(saida[de + i]);
                }
            }
        } else {
            if (err) *err = "bloco comprimido com tipo desconhecido";
            return false;
        }
        if (final) break;
    }
    return true;
}

// ------------------------------------------------------------------ zip
bool zip_list(const std::string& caminho, std::vector<ZipEntry>& out, std::string* err) {
    FILE* f = std::fopen(caminho.c_str(), "rb");
    if (!f) {
        if (err) *err = "não abriu o arquivo: " + caminho;
        return false;
    }
    if (std::fseek(f, 0, SEEK_END) != 0) { std::fclose(f); return false; }
    long long tam = std::ftell(f);
    if (tam < 22) {
        std::fclose(f);
        if (err) *err = "arquivo pequeno demais para ser zip";
        return false;
    }
    // procura o fim do diretório central nos últimos 64 KB + 22 bytes
    size_t janela = size_t(tam < 65557 ? tam : 65557);
    std::vector<uint8_t> fim(janela);
    if (std::fseek(f, static_cast<long>(tam) - static_cast<long>(janela), SEEK_SET) != 0 ||
        std::fread(fim.data(), 1, janela, f) != janela) {
        std::fclose(f);
        if (err) *err = "não consegui ler o fim do arquivo";
        return false;
    }
    long long pos_eocd = -1;
    for (long long i = static_cast<long long>(janela) - 22; i >= 0; --i) {
        if (u32(fim.data() + i) == 0x06054b50u) { pos_eocd = i; break; }
    }
    if (pos_eocd < 0) {
        std::fclose(f);
        if (err) *err = "não é um zip (sem diretório central)";
        return false;
    }
    const uint8_t* e = fim.data() + pos_eocd;
    uint64_t n_entradas = u16(e + 10);
    uint64_t dir_offset = u32(e + 16);
    // ZIP64: usado por arquivos enormes (modelos de muitos GB)
    if (n_entradas == 0xFFFFu || dir_offset == 0xFFFFFFFFu) {
        long long base = tam - static_cast<long long>(janela) + pos_eocd;
        long long pos_loc = base - 20;
        if (pos_loc >= 0) {
            std::vector<uint8_t> loc(20);
            if (std::fseek(f, pos_loc, SEEK_SET) == 0 && std::fread(loc.data(), 1, 20, f) == 20 &&
                u32(loc.data()) == 0x07064b50u) {
                uint64_t off64 = u64(loc.data() + 8);
                std::vector<uint8_t> e64(56);
                if (std::fseek(f, static_cast<long>(off64), SEEK_SET) == 0 &&
                    std::fread(e64.data(), 1, 56, f) == 56 && u32(e64.data()) == 0x06064b50u) {
                    n_entradas = u64(e64.data() + 32);
                    dir_offset = u64(e64.data() + 48);
                }
            }
        }
    }

    std::vector<uint8_t> dir;
    dir.resize(size_t(std::min<uint64_t>(n_entradas * 46 + 1024, 64u * 1024u * 1024u)));
    size_t lido = 0;
    {
        // lê o diretório inteiro: pode ser grande se houver muitas entradas
        size_t quer = dir.size();
        std::vector<uint8_t> bruto(quer);
        if (std::fseek(f, static_cast<long>(dir_offset), SEEK_SET) != 0) {
            std::fclose(f);
            if (err) *err = "diretório central fora do arquivo";
            return false;
        }
        lido = std::fread(bruto.data(), 1, quer, f);
        dir = bruto;
    }
    out.clear();
    size_t p = 0;
    for (uint64_t i = 0; i < n_entradas; ++i) {
        if (p + 46 > lido || u32(dir.data() + p) != 0x02014b50u) break;
        const uint8_t* c = dir.data() + p;
        uint32_t metodo = u16(c + 10);
        uint64_t comprimido = u32(c + 20);
        uint64_t tamanho = u32(c + 24);
        uint16_t nome_len = u16(c + 28);
        uint16_t extra_len = u16(c + 30);
        uint16_t coment_len = u16(c + 32);
        uint64_t offset_local = u32(c + 42);
        ZipEntry z;
        z.nome.assign((const char*)(c + 46), nome_len);
        // campo extra do ZIP64 sobrescreve os tamanhos de 32 bits
        const uint8_t* ex = c + 46 + nome_len;
        size_t ex_pos = 0;
        while (ex_pos + 4 <= extra_len) {
            uint16_t id = u16(ex + ex_pos);
            uint16_t tam_ex = u16(ex + ex_pos + 2);
            const uint8_t* corpo = ex + ex_pos + 4;
            if (id == 0x0001 && tam_ex >= 16) {
                size_t k = 0;
                if (tamanho == 0xFFFFFFFFu && k + 8 <= tam_ex) { tamanho = u64(corpo + k); k += 8; }
                if (comprimido == 0xFFFFFFFFu && k + 8 <= tam_ex) { comprimido = u64(corpo + k); k += 8; }
                if (offset_local == 0xFFFFFFFFu && k + 8 <= tam_ex) { offset_local = u64(corpo + k); k += 8; }
            }
            ex_pos += 4 + tam_ex;
        }
        z.metodo = metodo;
        z.comprimido = comprimido;
        z.tamanho = tamanho;
        // pula o cabeçalho local para achar os dados
        std::vector<uint8_t> local(30);
        if (std::fseek(f, static_cast<long>(offset_local), SEEK_SET) != 0 ||
            std::fread(local.data(), 1, 30, f) != 30) {
            break;
        }
        z.offset = offset_local + 30 + u16(local.data() + 26) + u16(local.data() + 28);
        out.push_back(z);
        p += 46 + nome_len + extra_len + coment_len;
    }
    std::fclose(f);
    if (out.empty()) {
        if (err) *err = "zip sem entradas";
        return false;
    }
    return true;
}

bool zip_read(const std::string& caminho, const ZipEntry& e, std::vector<uint8_t>& out,
              std::string* err) {
    FILE* f = std::fopen(caminho.c_str(), "rb");
    if (!f) {
        if (err) *err = "não abriu o arquivo";
        return false;
    }
    if (std::fseek(f, static_cast<long>(e.offset), SEEK_SET) != 0) {
        std::fclose(f);
        if (err) *err = "entrada fora do arquivo";
        return false;
    }
    std::vector<uint8_t> bruto(size_t(e.comprimido));
    if (e.comprimido && std::fread(bruto.data(), 1, bruto.size(), f) != bruto.size()) {
        std::fclose(f);
        if (err) *err = "entrada cortada";
        return false;
    }
    std::fclose(f);
    if (e.metodo == 0) {
        out = bruto;
        return true;
    }
    if (e.metodo != 8) {
        if (err) *err = "compactação desconhecida neste zip";
        return false;
    }
    out.clear();
    out.reserve(size_t(e.tamanho));
    return inflate_bytes(bruto.data(), bruto.size(), out, err);
}

}  // namespace raceai
