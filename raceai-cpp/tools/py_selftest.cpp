// py_selftest.cpp — prova que a ponte com o CPython funciona de verdade.
//
// Uso:  raceai_pytest [caminho/para/python3XX.dll]
//       (no Windows, o normal é  python/python311.dll)
//
// Compila o exemplo de IA, chama dirigir(sensores) e mostra a ação devolvida;
// depois provoca um erro de propósito para conferir que o traceback aparece.
#include <cstdio>
#include <string>

#include "../src/app/app_state.hpp"

using namespace raceai;

int main(int argc, char** argv) {
    printf("RaceAI 2D — teste da IA em Python\n");
    const char* caminho = argc > 1 ? argv[1] : "";
    PyDriver py;
    std::string err;
    if (!py.load_runtime(caminho, &err)) {
        printf("FALHOU ao carregar o interpretador: %s\n", err.c_str());
        return 2;
    }
    printf("interpretador carregado (%s)\n", caminho[0] ? caminho : "padrão do sistema");

    if (!py.set_code(exemplo_python(), &err)) {
        printf("FALHOU ao compilar o exemplo: %s\n%s\n", err.c_str(), py.traceback().c_str());
        return 3;
    }
    printf("código de exemplo compilado\n");

    // sensores típicos: pista livre à frente, mais perto nas laterais
    float obs[24];
    for (int i = 0; i < 24; ++i) obs[i] = 0.0f;
    const float raios[9] = {0.25f, 0.35f, 0.5f, 0.8f, 1.0f, 0.8f, 0.5f, 0.35f, 0.25f};
    for (int i = 0; i < 9; ++i) obs[i] = raios[i];
    obs[9] = 0.4f;     // velocidade
    obs[14] = 0.1f;    // deslocamento lateral

    float out[2] = {0, 0};
    py.act(obs, 24, out);
    if (!py.valid()) {
        printf("FALHOU ao chamar dirigir(): %s\n", py.traceback().c_str());
        return 4;
    }
    printf("dirigir() -> esterço %.3f, acelerador %.3f\n", out[0], out[1]);
    if (out[0] < -1.0f || out[0] > 1.0f || out[1] < -1.0f || out[1] > 1.0f) {
        printf("FALHOU: ação fora de [-1, 1]\n");
        return 5;
    }

    // erro de propósito: o traceback precisa aparecer e a ação ficar neutra
    PyDriver py2;
    if (!py2.load_runtime(caminho, &err)) {
        printf("FALHOU (segundo driver): %s\n", err.c_str());
        return 6;
    }
    if (!py2.set_code("def dirigir(sensores):\n    return 1 / 0, 0.0\n", &err)) {
        printf("FALHOU ao compilar o código com erro: %s\n", err.c_str());
        return 7;
    }
    float out2[2] = {9, 9};
    py2.act(obs, 24, out2);
    if (py2.valid()) {
        printf("FALHOU: dirigir() com erro deveria invalidar o driver\n");
        return 8;
    }
    if (py2.traceback().empty()) {
        printf("FALHOU: traceback vazio\n");
        return 9;
    }
    printf("erro capturado com traceback (%d caracteres), ação neutra %.1f/%.1f\n",
           int(py2.traceback().size()), out2[0], out2[1]);

    // código sem a função dirigir() é recusado com mensagem
    if (py2.set_code("x = 1 + 1\n", &err)) {
        printf("FALHOU: código sem dirigir() foi aceito\n");
        return 10;
    }
    printf("código sem dirigir() recusado: %s\n", err.c_str());
    printf("\nTUDO OK — a IA em Python funciona\n");
    return 0;
}
