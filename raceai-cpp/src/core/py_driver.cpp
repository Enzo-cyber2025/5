#include "py_driver.hpp"

#include <cstdio>
#include <cstring>

#include <cstdlib>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <dlfcn.h>
#endif

namespace raceai {

// ------------------------------------------------------------------ carregador
static void* lib_open(const char* path) {
#ifdef _WIN32
    return (void*)LoadLibraryA(path);
#else
    return dlopen(path, RTLD_NOW | RTLD_GLOBAL);
#endif
}

static void* lib_sym(void* h, const char* name) {
#ifdef _WIN32
    return (void*)GetProcAddress((HMODULE)h, name);
#else
    return dlsym(h, name);
#endif
}

static void lib_close(void* h) {
    if (!h) return;
#ifdef _WIN32
    FreeLibrary((HMODULE)h);
#else
    dlclose(h);
#endif
}

// Tipos da C-API do CPython que usamos (todos existem do 3.6 ao 3.13).
using FnInit        = void (*)(int);
using FnIsInit      = int (*)(void);
using FnRun         = int (*)(const char*);
using FnImport      = void* (*)(const char*);
using FnGetAttr     = void* (*)(void*, const char*);
using FnCall        = void* (*)(void*, void*);
using FnCallArgs    = void* (*)(void*, ...);
using FnListNew     = void* (*)(long long);
using FnListSet     = int (*)(void*, long long, void*);
using FnFloatFrom   = void* (*)(double);
using FnFloatAs     = double (*)(void*);
using FnUniFrom     = void* (*)(const char*, long long);
using FnUniUTF8     = void* (*)(void*);
using FnBytesAs     = char* (*)(void*);
using FnSeqSize     = long long (*)(void*);
using FnSeqGet      = void* (*)(void*, long long);
using FnDecRef      = void (*)(void*);
using FnIncRef      = void (*)(void*);
using FnErrPrint    = void (*)(void);
using FnErrClear    = void (*)(void);
using FnErrOcc      = void* (*)(void);
using FnFinalize    = int (*)(void);

struct PyApi {
    FnInit init = nullptr;
    FnIsInit is_init = nullptr;
    FnRun run = nullptr;
    FnImport import = nullptr;
    FnGetAttr getattr = nullptr;
    FnCall call = nullptr;
    FnCallArgs call_args = nullptr;
    FnListNew list_new = nullptr;
    FnListSet list_set = nullptr;
    FnFloatFrom float_from = nullptr;
    FnFloatAs float_as = nullptr;
    FnUniFrom uni_from = nullptr;
    FnUniUTF8 uni_utf8 = nullptr;
    FnBytesAs bytes_as = nullptr;
    FnSeqSize seq_size = nullptr;
    FnSeqGet seq_get = nullptr;
    FnDecRef decref = nullptr;
    FnIncRef incref = nullptr;
    FnErrPrint err_print = nullptr;
    FnErrClear err_clear = nullptr;
    FnErrOcc err_occ = nullptr;
    FnFinalize finalize = nullptr;
};

static PyApi& api() {
    static PyApi a;
    return a;
}

// script fixo: recebe o código do usuário como **argumento** (nada de escapar
// aspas) e expõe um chamador que captura o traceback para a interface
static const char* kBootstrap =
    "import sys, traceback\n"
    "_raceai_error = \"\"\n"
    "_raceai_dirigir = None\n"
    "def _raceai_install(src):\n"
    "    global _raceai_dirigir, _raceai_error\n"
    "    ns = {'__name__': '__raceai_ia__'}\n"
    "    try:\n"
    "        exec(compile(src, '<ia-do-usuario>', 'exec'), ns)\n"
    "    except Exception:\n"
    "        _raceai_error = traceback.format_exc()\n"
    "        _raceai_dirigir = None\n"
    "        return None\n"
    "    f = ns.get('dirigir')\n"
    "    if not callable(f):\n"
    "        _raceai_error = ('o codigo precisa definir dirigir(sensores) -> '\n"
    "                         '(esterco, acelerador)')\n"
    "        _raceai_dirigir = None\n"
    "        return None\n"
    "    _raceai_dirigir = f\n"
    "    _raceai_error = \"\"\n"
    "    return f\n"
    "def _raceai_call(vals):\n"
    "    global _raceai_error\n"
    "    if _raceai_dirigir is None:\n"
    "        return None\n"
    "    try:\n"
    "        return _raceai_dirigir(vals)\n"
    "    except Exception:\n"
    "        _raceai_error = traceback.format_exc()\n"
    "        return None\n";

// ------------------------------------------------------------------ runtime
bool PyDriver::load_runtime(const std::string& dll, std::string* err) {
    if (lib_) return true;
    const char* nomes[] = {
        dll.empty() ? nullptr : dll.c_str(),
#ifdef _WIN32
        "python\\python311.dll", "python311.dll", "python312.dll", "python313.dll",
        "python\\python312.dll", "python\\python313.dll", "python3.dll",
#else
        "libpython3.11.so", "libpython3.12.so", "libpython3.so",
#endif
    };
    for (const char* n : nomes) {
        if (!n) continue;
        lib_ = lib_open(n);
        if (lib_) break;
    }
    if (!lib_) {
        if (err) *err = "interpretador Python não encontrado (recurso opcional)";
        return false;
    }
    PyApi& a = api();
    a.init = (FnInit)lib_sym(lib_, "Py_InitializeEx");
    if (!a.init) a.init = (FnInit)lib_sym(lib_, "Py_Initialize");
    a.is_init = (FnIsInit)lib_sym(lib_, "Py_IsInitialized");
    a.run = (FnRun)lib_sym(lib_, "PyRun_SimpleString");
    a.import = (FnImport)lib_sym(lib_, "PyImport_ImportModule");
    a.getattr = (FnGetAttr)lib_sym(lib_, "PyObject_GetAttrString");
    a.call = (FnCall)lib_sym(lib_, "PyObject_CallObject");
    a.call_args = (FnCallArgs)lib_sym(lib_, "PyObject_CallFunctionObjArgs");
    a.list_new = (FnListNew)lib_sym(lib_, "PyList_New");
    a.list_set = (FnListSet)lib_sym(lib_, "PyList_SetItem");
    a.float_from = (FnFloatFrom)lib_sym(lib_, "PyFloat_FromDouble");
    a.float_as = (FnFloatAs)lib_sym(lib_, "PyFloat_AsDouble");
    a.uni_from = (FnUniFrom)lib_sym(lib_, "PyUnicode_FromStringAndSize");
    a.uni_utf8 = (FnUniUTF8)lib_sym(lib_, "PyUnicode_AsUTF8String");
    a.bytes_as = (FnBytesAs)lib_sym(lib_, "PyBytes_AsString");
    a.seq_size = (FnSeqSize)lib_sym(lib_, "PySequence_Size");
    a.seq_get = (FnSeqGet)lib_sym(lib_, "PySequence_GetItem");
    a.decref = (FnDecRef)lib_sym(lib_, "Py_DecRef");
    a.incref = (FnIncRef)lib_sym(lib_, "Py_IncRef");
    a.err_print = (FnErrPrint)lib_sym(lib_, "PyErr_Print");
    a.err_clear = (FnErrClear)lib_sym(lib_, "PyErr_Clear");
    a.err_occ = (FnErrOcc)lib_sym(lib_, "PyErr_Occurred");
    a.finalize = (FnFinalize)lib_sym(lib_, "Py_FinalizeEx");

    if (!a.init || !a.run || !a.import || !a.getattr || !a.call || !a.list_new ||
        !a.float_from || !a.uni_from) {
        if (err) *err = "a biblioteca Python foi encontrada mas não expõe a C-API esperada";
        lib_close(lib_);
        lib_ = nullptr;
        return false;
    }
    // O pacote "embutido" do CPython precisa saber onde está a biblioteca
    // padrão: apontamos PYTHONHOME para a pasta do próprio interpretador.
    if (!dll.empty()) {
        std::string dir = dll;
        size_t barra = dir.find_last_of("/\\");
        if (barra != std::string::npos) dir = dir.substr(0, barra);
        if (!dir.empty()) {
#ifdef _WIN32
            SetEnvironmentVariableA("PYTHONHOME", dir.c_str());
#else
            ::setenv("PYTHONHOME", dir.c_str(), 1);
#endif
        }
    }
    if (!a.is_init || !a.is_init()) a.init(0);
    initialized_ = true;

    if (a.run(kBootstrap) != 0) {
        if (a.err_print) a.err_print();
        if (err) *err = "falha ao preparar o ambiente Python";
        initialized_ = false;
        return false;
    }
    module_main_ = a.import("__main__");
    if (!module_main_) {
        if (err) *err = "não consegui abrir o módulo __main__";
        return false;
    }
    fn_install_ = a.getattr(module_main_, "_raceai_install");
    fn_call_ = a.getattr(module_main_, "_raceai_call");
    bootstrap_ok_ = fn_install_ && fn_call_;
    if (!bootstrap_ok_ && err) *err = "falha ao instalar as funções auxiliares";
    return bootstrap_ok_;
}

void PyDriver::unload() {
    PyApi& a = api();
    if (lib_ && initialized_) {
        if (module_main_ && a.decref) a.decref(module_main_);
        if (fn_call_ && a.decref) a.decref(fn_call_);
        if (fn_install_ && a.decref) a.decref(fn_install_);
        if (a.finalize) a.finalize();
    }
    lib_close(lib_);
    lib_ = nullptr;
    initialized_ = false;
    installed_ = false;
    bootstrap_ok_ = false;
    module_main_ = fn_call_ = fn_install_ = nullptr;
}

PyDriver::~PyDriver() { unload(); }

// ------------------------------------------------------------------ código
std::string PyDriver::read_error_var() {
    PyApi& a = api();
    if (!module_main_ || !a.getattr || !a.uni_utf8 || !a.bytes_as) return "";
    void* v = a.getattr(module_main_, "_raceai_error");
    if (!v) return "";
    void* b = a.uni_utf8(v);
    std::string out;
    if (b && a.bytes_as) {
        const char* s = a.bytes_as(b);
        if (s) out = s;
    }
    if (b && a.decref) a.decref(b);
    if (a.decref) a.decref(v);
    return out;
}

bool PyDriver::set_code(const std::string& code, std::string* err) {
    PyApi& a = api();
    installed_ = false;
    error_.clear();
    if (!runtime_loaded() || !bootstrap_ok_) {
        if (err) *err = "interpretador Python indisponível";
        return false;
    }
    void* src = a.uni_from(code.data(), (long long)code.size());
    if (!src) {
        if (err) *err = "não consegui converter o código";
        return false;
    }
    void* res = nullptr;
    if (a.call_args) res = a.call_args(fn_install_, src, (void*)nullptr);
    else { void* args = a.call ? nullptr : nullptr; (void)args; }
    if (a.decref) a.decref(src);
    if (a.err_occ && a.err_occ()) {
        if (a.err_print) a.err_print();
        else if (a.err_clear) a.err_clear();
    }
    bool ok = res != nullptr;
    if (res && a.decref) a.decref(res);
    error_ = read_error_var();
    if (!ok) {
        if (error_.empty()) error_ = "não foi possível compilar o código";
        if (err) *err = error_;
        return false;
    }
    error_.clear();
    installed_ = true;
    return true;
}

// ------------------------------------------------------------------ decisão
void PyDriver::act(const float* obs, int dim, float* out) {
    out[0] = 0.0f;
    out[1] = 0.0f;
    PyApi& a = api();
    if (!installed_ || !bootstrap_ok_ || !fn_call_) return;

    void* lista = a.list_new(dim);
    if (!lista) return;
    for (int i = 0; i < dim; ++i) {
        void* f = a.float_from(double(obs[i]));
        if (!f) continue;
        if (a.list_set(lista, i, f) != 0 && a.decref) a.decref(f);   // rouba a referência
    }

    double t0 = (double)clock() / CLOCKS_PER_SEC * 1000.0;
    void* res = nullptr;
    if (a.call_args) res = a.call_args(fn_call_, lista, (void*)nullptr);
    else if (a.call) res = a.call(fn_call_, lista);
    last_ms_ = (double)clock() / CLOCKS_PER_SEC * 1000.0 - t0;
    if (a.decref) a.decref(lista);
    calls_ += 1;

    if (!res) {
        errors_ += 1;
        error_ = read_error_var();
        if (error_.empty()) error_ = "erro desconhecido ao chamar dirigir()";
        if (a.err_occ && a.err_occ()) {
            if (a.err_print) a.err_print();
            else if (a.err_clear) a.err_clear();
        }
        installed_ = false;      // mostra o erro na interface; recompila ao editar
        return;
    }
    long long n = a.seq_size ? a.seq_size(res) : 0;
    if (n >= 2 && a.seq_get) {
        void* p0 = a.seq_get(res, 0);
        void* p1 = a.seq_get(res, 1);
        if (p0 && p1) {
            double s = a.float_as(p0);
            double d = a.float_as(p1);
            if (std::isfinite(s)) out[0] = float(std::max(-1.0, std::min(1.0, s)));
            if (std::isfinite(d)) out[1] = float(std::max(-1.0, std::min(1.0, d)));
        }
        if (p0 && a.decref) a.decref(p0);
        if (p1 && a.decref) a.decref(p1);
    } else {
        errors_ += 1;
        error_ = "dirigir() deve devolver (esterço, acelerador)";
        installed_ = false;
    }
    if (a.decref) a.decref(res);
}

}  // namespace raceai
