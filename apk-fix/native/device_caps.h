#pragma once
// O que o driver Vulkan OFERECE, lido da linha que o PRÓPRIO backend do llama.cpp
// imprime ao enumerar os dispositivos:
//
//   ggml_vulkan: 0 = llvmpipe (LLVM 21.0.0, 256 bits) | uma: 1 | fp16: 0 |
//   bf16: 0 | warp size: 32 | shared memory: 32768 | int dot: 0 | matrix cores: none
//
// Isto é declaração, não promessa: o valor que interessa no Galaxy A55 (Exynos
// 1480, GPU Xclipse 530, AMD RDNA) é `matrix cores:` — as matrizes cooperativas
// são o caminho rápido do pré-preenchimento em GPU AMD; no emulador do CI o valor
// é `none`. Nada aqui escolhe caminho de execução: quem escolhe é o backend, em
// tempo de execução, pelo que o driver expõe. O aplicativo só MOSTRA o que foi
// encontrado, para o usuário conferir no aparelho em vez de acreditar.
#include <cstring>
#include <string>

struct DeviceCaps {
    std::string device;        // nome do dispositivo, como o driver o reporta
    std::string uma;           // memória unificada (1) ou dedicada (0)
    std::string fp16;          // aritmética FP16 no hardware
    std::string int_dot;       // produto escalar inteiro
    std::string warp_size;     // tamanho do subgrupo (warp/subgroup)
    std::string shared_memory; // memória compartilhada por grupo de trabalho
    std::string matrix_cores;  // none | KHR | NV | ... (matrizes cooperativas)
};

static inline std::string device_caps_trim(const std::string &value) {
    // Espaço E quebra de linha: o backend escreve a linha com \n no fim, e o valor
    // de cada campo não pode carregá-la para dentro do aviso da tela.
    const size_t first = value.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) return "";
    const size_t last = value.find_last_not_of(" \t\r\n");
    return value.substr(first, last - first + 1);
}

static inline std::string device_caps_field(const std::string &line, const char *key) {
    const size_t at = line.find(key);
    if (at == std::string::npos) return "";
    const size_t start = at + std::strlen(key);
    const size_t end = line.find('|', start);
    return device_caps_trim(line.substr(start, end == std::string::npos ? std::string::npos : end - start));
}

// Devolve `matrix_cores` vazio quando a linha não é a de enumeração de
// dispositivos (é assim que quem chama sabe que não há o que declarar).
static inline DeviceCaps device_caps_parse(const char *text) {
    DeviceCaps caps;
    if (!text) return caps;
    const std::string line = text;
    if (line.find("matrix cores:") == std::string::npos) return caps;
    const size_t marker = line.find(" = ");
    const size_t pipe = line.find(" | ");
    if (marker != std::string::npos && pipe != std::string::npos && pipe > marker + 3)
        caps.device = device_caps_trim(line.substr(marker + 3, pipe - marker - 3));
    caps.uma = device_caps_field(line, "uma:");
    caps.fp16 = device_caps_field(line, "fp16:");
    caps.int_dot = device_caps_field(line, "int dot:");
    caps.warp_size = device_caps_field(line, "warp size:");
    caps.shared_memory = device_caps_field(line, "shared memory:");
    caps.matrix_cores = device_caps_field(line, "matrix cores:");
    return caps;
}

// Resumo curto para o aviso da tela: "coopmat KHR" quando o driver oferece
// matrizes cooperativas, "coopmat nenhum" quando não oferece, "" quando nem a
// linha de dispositivos foi vista.
static inline std::string device_caps_summary(const DeviceCaps &caps) {
    if (caps.matrix_cores.empty()) return "";
    if (caps.matrix_cores == "none") return "coopmat nenhum";
    return "coopmat " + caps.matrix_cores;
}
