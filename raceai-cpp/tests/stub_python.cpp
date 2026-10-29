// stub_python.cpp — **falso** libpython para testar a ponte Python sem precisar
// do CPython de verdade no ambiente de desenvolvimento.
//
// Ele exporta exatamente os símbolos que src/core/py_driver.cpp usa e simula o
// comportamento relevante: instalação do código, chamada de dirigir(sensores) e
// devolução de (esterço, acelerador). Serve para garantir que a sequência de
// chamadas, a montagem da lista de sensores e o tratamento de erro estão
// corretos — o teste com o Python de verdade roda no Windows (CI).
#include <cstdio>
#include <cstdlib>
#include <cstdarg>
#include <cstring>
#include <string>
#include <vector>

// Compilado com -DSTUB_PYTHON_NONE, este falso interpretador imita o CPython
// de verdade: em vez de nullptr, as funções devolvem None nas falhas. É o que
// pega bugs do tipo "só testei o ponteiro contra nulo".
#ifdef STUB_PYTHON_NONE
extern "C" {
struct StubNone { int kind; };
StubNone _Py_NoneStruct = {0};
}
static void* stub_none() { return (void*)&_Py_NoneStruct; }
#define STUB_FALHA stub_none()
#else
#define STUB_FALHA nullptr
#endif

extern "C" {

struct StubObj {
    int kind;                 // 0=módulo 1=função instalar 2=função chamar 3=lista
                              // 4=float 5=string 6=bytes 7=tupla
    double valor = 0.0;
    std::string texto;
    std::vector<double> itens;
};

// estado observável pelo teste
static StubObj g_main{0};
static StubObj g_install{1};
static StubObj g_call{2};
static int g_inicializado = 0;
static std::string g_script;
static std::string g_codigo_instalado;
static std::string g_erro_instalacao;
static std::vector<double> g_ultimos_sensores;
static double g_resposta[2] = {0.0, 0.0};
static int g_deve_falhar = 0;
static int g_chamadas = 0;
static int g_refs_vivas = 0;

// API usada pelos testes para inspecionar o que o driver fez
void stubpython_reset() {
    g_codigo_instalado.clear();
    g_erro_instalacao.clear();
    g_ultimos_sensores.clear();
    g_deve_falhar = 0;
    g_chamadas = 0;
    g_resposta[0] = g_resposta[1] = 0.0;
}
void stubpython_set_response(double steer, double drive) { g_resposta[0] = steer; g_resposta[1] = drive; }
void stubpython_set_failure(int f) { g_deve_falhar = f; }
const char* stubpython_installed_code() { return g_codigo_instalado.c_str(); }
int stubpython_last_sensor_count() { return int(g_ultimos_sensores.size()); }
double stubpython_last_sensor(int i) {
    return (i >= 0 && i < int(g_ultimos_sensores.size())) ? g_ultimos_sensores[i] : 0.0;
}
const char* stubpython_script() { return g_script.c_str(); }
int stubpython_calls() { return g_chamadas; }
int stubpython_live_refs() { return g_refs_vivas; }

// contagem do "GIL" falso: PyGILState_Ensure/Release precisam andar em pares
static int g_gil = 0;
int stubpython_gil_balance() { return g_gil; }
#ifdef STUB_PYTHON_NONE
int PyObject_IsTrue(void* o) { return o == stub_none() ? 0 : 1; }
#endif
int PyGILState_Ensure(void) { g_gil += 1; return g_gil; }
void PyGILState_Release(int) { g_gil -= 1; }
void* PyEval_SaveThread(void) { return nullptr; }
void PyEval_RestoreThread(void*) {}

// ------------------------------------------------------------ C-API "Python"
void Py_InitializeEx(int) { g_inicializado = 1; }
void Py_Initialize(void) { g_inicializado = 1; }
int Py_IsInitialized(void) { return g_inicializado; }
int Py_FinalizeEx(void) { g_inicializado = 0; return 0; }

int PyRun_SimpleString(const char* code) {
    g_script += code ? code : "";
    return 0;
}

void* PyImport_ImportModule(const char* name) {
    if (name && std::strcmp(name, "__main__") == 0) return &g_main;
    return nullptr;
}

void* PyObject_GetAttrString(void* obj, const char* name) {
    if (obj == &g_main && name) {
        if (std::strcmp(name, "_raceai_install") == 0) return &g_install;
        if (std::strcmp(name, "_raceai_call") == 0) return &g_call;
    }
    if (obj == &g_main && name && std::strcmp(name, "_raceai_error") == 0) {
        StubObj* s = new StubObj{5};
        s->texto = !g_erro_instalacao.empty() ? g_erro_instalacao
                 : (g_deve_falhar ? "Traceback (falso): erro de teste" : "");
        g_refs_vivas += 1;
        return s;
    }
    return nullptr;
}

void* PyUnicode_FromStringAndSize(const char* s, long long n) {
    StubObj* o = new StubObj{5};
    o->texto.assign(s ? s : "", size_t(n < 0 ? 0 : n));
    g_refs_vivas += 1;
    return o;
}

void* PyFloat_FromDouble(double v) {
    StubObj* o = new StubObj{4};
    o->valor = v;
    g_refs_vivas += 1;
    return o;
}

double PyFloat_AsDouble(void* o) {
    StubObj* s = (StubObj*)o;
    return s ? s->valor : 0.0;
}

void* PyList_New(long long n) {
    StubObj* o = new StubObj{3};
    o->itens.assign(size_t(n < 0 ? 0 : n), 0.0);
    g_refs_vivas += 1;
    return o;
}

int PyList_SetItem(void* list, long long idx, void* item) {
    StubObj* l = (StubObj*)list;
    StubObj* it = (StubObj*)item;
    if (!l || !it || idx < 0) return -1;
    if (size_t(idx) >= l->itens.size()) return -1;
    l->itens[size_t(idx)] = it->valor;
    return 0;
}

long long PySequence_Size(void* o) {
    StubObj* s = (StubObj*)o;
    if (!s) return -1;
    if (s->kind == 3) return (long long)s->itens.size();
    if (s->kind == 7) return (long long)s->itens.size();
    return -1;
}

void* PySequence_GetItem(void* o, long long i) {
    StubObj* s = (StubObj*)o;
    if (!s || i < 0 || size_t(i) >= s->itens.size()) return nullptr;
    StubObj* f = new StubObj{4};
    f->valor = s->itens[size_t(i)];
    g_refs_vivas += 1;
    return f;
}

void* PyUnicode_AsUTF8String(void* o) {
    StubObj* s = (StubObj*)o;
    StubObj* b = new StubObj{6};
    b->texto = s ? s->texto : "";
    g_refs_vivas += 1;
    return b;
}

char* PyBytes_AsString(void* o) {
    StubObj* s = (StubObj*)o;
    static std::string buf;
    buf = s ? s->texto : "";
    return (char*)buf.c_str();
}

void Py_DecRef(void* o) {
    StubObj* s = (StubObj*)o;
    if (!s || s == &g_main || s == &g_install || s == &g_call) return;
#ifdef STUB_PYTHON_NONE
    if (o == stub_none()) return;      // None é estático: nunca é liberado
#endif
    delete s;
    g_refs_vivas -= 1;
}
void Py_IncRef(void*) {}
void PyErr_Print(void) {}
void PyErr_Clear(void) {}
void* PyErr_Occurred(void) { return nullptr; }

// PyObject_CallFunctionObjArgs(fn, arg..., NULL)
void* PyObject_CallFunctionObjArgs(void* fn, ...) {
    va_list ap;
    va_start(ap, fn);
    void* primeiro = va_arg(ap, void*);
    va_end(ap);
    if (fn == &g_install) {
        StubObj* src = (StubObj*)primeiro;
        if (g_deve_falhar) return STUB_FALHA;
        if (!src) return STUB_FALHA;
        // validação grosseira, mas suficiente para os testes: precisa existir
        // uma linha "def dirigir(...):" — sem os dois pontos é erro de sintaxe
        const std::string& t = src->texto;
        size_t p = t.find("def dirigir");
        if (p == std::string::npos) {                          // falta a função
            g_erro_instalacao =
                "Traceback (falso)\n  NameError: defina dirigir(sensores) -> (esterco, acelerador)";
            return STUB_FALHA;
        }
        size_t eol = t.find('\n', p);
        std::string linha = t.substr(p, eol == std::string::npos ? std::string::npos : eol - p);
        if (linha.find(':') == std::string::npos) {            // sintaxe inválida
            g_erro_instalacao =
                "Traceback (falso)\n  SyntaxError: expected ':' no fim do def";
            return STUB_FALHA;
        }
        g_erro_instalacao.clear();
        g_codigo_instalado = src->texto;
        return &g_install;
    }
    if (fn == &g_call) {
        StubObj* lista = (StubObj*)primeiro;
        g_chamadas += 1;
        if (g_deve_falhar == 2) return STUB_FALHA;
        if (!lista) return nullptr;
        g_ultimos_sensores = lista->itens;
        StubObj* t = new StubObj{7};
        t->itens.push_back(g_resposta[0]);
        t->itens.push_back(g_resposta[1]);
        g_refs_vivas += 1;
        return t;
    }
    return nullptr;
}

void* PyObject_CallObject(void* fn, void* args) {
    return PyObject_CallFunctionObjArgs(fn, args, (void*)nullptr);
}

}  // extern "C"
