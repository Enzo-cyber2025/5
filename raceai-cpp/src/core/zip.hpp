// zip.hpp — leitor de ZIP mínimo, só o que os formatos de modelo precisam.
//
// Por que não usar uma biblioteca: o jogo não tem dependência nenhuma e não
// vamos ganhar uma só para ler .pt/.npz. O leitor aceita entradas guardadas
// (STORED) e comprimidas (DEFLATE) — o inflate é implementado aqui.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace raceai {

struct ZipEntry {
    std::string nome;
    uint32_t metodo = 0;          // 0 = guardado, 8 = deflate
    uint64_t comprimido = 0;      // tamanho no arquivo
    uint64_t tamanho = 0;         // tamanho depois de descomprimir
    uint64_t offset = 0;          // onde começam os dados (já pulando o cabeçalho local)
};

// Lê o diretório central de um arquivo zip.
bool zip_list(const std::string& caminho, std::vector<ZipEntry>& out, std::string* err = nullptr);

// Lê e descomprime uma entrada.
bool zip_read(const std::string& caminho, const ZipEntry& e,
              std::vector<uint8_t>& out, std::string* err = nullptr);

// Inflate puro (RFC 1951): usado para as entradas comprimidas.
bool inflate_bytes(const uint8_t* entrada, size_t n, std::vector<uint8_t>& saida,
                   std::string* err = nullptr);

}  // namespace raceai
