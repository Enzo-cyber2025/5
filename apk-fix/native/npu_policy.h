#pragma once
// NPU do aparelho: existe? existe backend compatível NESTE binário? Quando não
// existe, a resposta honesta é "não", e é isso que este cabeçalho entrega.
//
// Por que não é possível usar a NPU hoje:
//  * llama.cpp (a versão fixada neste repositório) não tem backend de NPU;
//  * o runtime da Samsung (ENN/NeuroPilot) é fechado e exige registro de parceiro;
//  * NNAPI foi removido do llama.cpp e o QNN/HTP é do Hexagon (Qualcomm), não do
//    Exynos 1480 do Galaxy A55;
//  * o emulador do CI não tem NPU nenhuma, então nem a aceleração nem a recusa
//    poderiam ser medidas lá.
// Sem backend, o aplicativo detecta, registra e declara a ausência — jamais
// promete aceleração por NPU.
#include <cctype>
#include <cstring>
#include <string>

#define GGUF_NPU_BACKEND_AVAILABLE 0
#define GGUF_NPU_BACKEND_REASON "nenhum backend de NPU embarcado"

struct NpuAssessment {
    const char *soc;   // nome curto do SoC reconhecido ("" quando desconhecido)
    bool npu_present;  // o SoC reconhecido tem NPU
    const char *backend; // backend de NPU embarcado compatível ("" quando nenhum)
};

// Tabela de identificação (não de promessa): o SoC é reconhecido pelo texto que o
// Android expõe (ro.soc.model, ro.board.platform, ro.hardware). O NPU do Galaxy
// A55 é o do Exynos 1480 (s5e8845); os outros entram para que a detecção não
// dependa de um único aparelho.
inline NpuAssessment npu_assess(const char *identity) {
    static const struct Soc { const char *label; const char *needles[3]; } SOCS[] = {
        {"Exynos 1480", {"exynos1480", "s5e8845", nullptr}},
        {"Exynos 2400", {"exynos2400", "s5e9945", nullptr}},
        {"Snapdragon 8 Gen 2", {"sm8550", "kalama", nullptr}},
        {"Snapdragon 7 Gen 3", {"sm7550", "crow", nullptr}},
        {"Tensor G3", {"zuma", "tensor g3", nullptr}},
    };
    NpuAssessment result{"", false, ""};
    if (!identity) return result;
    std::string folded(identity);
    for (char &c : folded) c = (char)std::tolower((unsigned char)c);
    for (const Soc &soc : SOCS) {
        for (const char *needle : soc.needles) {
            if (!needle) break;
            if (folded.find(needle) != std::string::npos) {
                result.soc = soc.label;
                result.npu_present = true;
                result.backend = GGUF_NPU_BACKEND_AVAILABLE ? "embarcado" : "";
                return result;
            }
        }
    }
    return result;
}
