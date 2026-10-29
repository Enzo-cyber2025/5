// py_driver.hpp — driver de IA escrito em Python pelo usuário.
//
// O interpretador CPython é carregado **em tempo de execução** (LoadLibrary /
// dlopen), sem linker nem headers de desenvolvimento: o executável funciona
// mesmo que o Python não esteja presente (aí o recurso aparece desabilitado).
//
// O contrato é simples — o usuário cola um código como:
//
//     def dirigir(sensores):
//         esterco = (sensores[3] - sensores[5]) * 2.0     # raios à frente
//         acelerador = 1.0 if sensores[9] < 0.8 else 0.2  # velocidade
//         return esterco, acelerador
//
// `sensores` é uma lista de floats (índices documentados no arquivo de ajuda e
// na própria interface). O retorno pode ser uma tupla/lista [esterço,
// acelerador] com valores em [-1, 1].
#pragma once

#include <string>

#include "driver.hpp"

namespace raceai {

class PyDriver : public Driver {
public:
    ~PyDriver() override;

    // Carrega o CPython. `dll` vazio = procura nos locais padrão.
    bool load_runtime(const std::string& dll = "", std::string* err = nullptr);
    bool runtime_loaded() const { return lib_ != nullptr && initialized_; }
    void unload();

    //Compila o código do usuário (define `dirigir`). Devolve false + traceback.
    bool set_code(const std::string& code, std::string* err = nullptr);
    bool has_code() const { return installed_; }

    void act(const float* obs, int obs_dim, float* out) override;
    std::string name() const override { return "python"; }
    bool valid() const override { return installed_; }
    std::string error() const override { return error_; }

    std::string traceback() const { return error_; }
    double last_call_ms() const { return last_ms_; }
    int call_count() const { return calls_; }
    int error_count() const { return errors_; }

private:
    void* lib_ = nullptr;
    bool initialized_ = false;
    bool installed_ = false;
    bool bootstrap_ok_ = false;
    void* module_main_ = nullptr;    // PyObject* (__main__)
    void* fn_call_ = nullptr;        // PyObject* _raceai_call
    void* fn_install_ = nullptr;     // PyObject* _raceai_install
    std::string error_;
    double last_ms_ = 0.0;
    int calls_ = 0, errors_ = 0;

    std::string read_error_var();
    void* call_no_args(void* fn);
};

}  // namespace raceai
