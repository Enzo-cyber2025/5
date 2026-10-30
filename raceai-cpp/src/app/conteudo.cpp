// conteudo.cpp — leitura do pacote embutido no próprio executável.
//
// Compila em qualquer plataforma, mas só faz algo no Windows: é lá que o .exe
// precisa ser autossuficiente (um arquivo só, sem zip para descompactar).
#include "conteudo.hpp"

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#ifdef _WIN32
#define RACEAI_WIN 1
#include <windows.h>
#else
#include <dirent.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

namespace raceai {
namespace {

const char kMagia[] = "RACEAIPAK";
const char kMagiaFim[] = "RACEAIPAKEND";
const int kTamTrailer = 24;

// ------------------------------------------------------------ utf8 <-> wide
#ifdef RACEAI_WIN
std::wstring wide_(const std::string& utf8) {
    if (utf8.empty()) return L"";
    int n = MultiByteToWideChar(CP_UTF8, 0, utf8.c_str(), int(utf8.size()), nullptr, 0);
    std::wstring w(size_t(n), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, utf8.c_str(), int(utf8.size()), &w[0], n);
    return w;
}
std::string narrow_(const std::wstring& w) {
    if (w.empty()) return "";
    int n = WideCharToMultiByte(CP_UTF8, 0, w.c_str(), int(w.size()), nullptr, 0,
                                nullptr, nullptr);
    std::string s(size_t(n), '\0');
    WideCharToMultiByte(CP_UTF8, 0, w.c_str(), int(w.size()), &s[0], n, nullptr,
                        nullptr);
    return s;
}
#endif

std::string juntar(const std::string& a, const std::string& b) {
    if (a.empty()) return b;
    if (b.empty()) return a;
    if (a.back() == '/' || a.back() == '\\') return a + b;
    return a + "/" + b;
}

bool existe_(const std::string& p) {
    if (p.empty()) return false;
#ifdef RACEAI_WIN
    return GetFileAttributesW(wide_(p).c_str()) != INVALID_FILE_ATTRIBUTES;
#else
    if (FILE* f = std::fopen(p.c_str(), "rb")) {
        std::fclose(f);
        return true;
    }
    return false;
#endif
}

bool criar_dirs_(const std::string& caminho) {
    std::string atual;
    for (char c : caminho) {
        if (c == '/' || c == '\\') {
            if (!atual.empty() && !existe_(atual)) {
#ifdef RACEAI_WIN
                CreateDirectoryW(wide_(atual).c_str(), nullptr);
#else
                mkdir(atual.c_str(), 0755);
#endif
            }
        }
        atual.push_back(c);
    }
    // o último componente também (a pasta final do caminho pedido)
    if (!atual.empty() && !existe_(atual)) {
#ifdef RACEAI_WIN
        CreateDirectoryW(wide_(atual).c_str(), nullptr);
#else
        mkdir(atual.c_str(), 0755);
#endif
    }
    return true;
}

std::string diretorio_do_exe() {
#ifdef RACEAI_WIN
    wchar_t modulo[MAX_PATH];
    if (!GetModuleFileNameW(nullptr, modulo, MAX_PATH)) return "";
    std::wstring w(modulo);
    const size_t barra = w.find_last_of(L"\\/");
    if (barra == std::wstring::npos) return ".";
    return narrow_(w.substr(0, barra));
#else
    return "";
#endif
}

#ifdef RACEAI_WIN
std::string env_(const wchar_t* nome) {
    wchar_t buf[2048];
    if (!GetEnvironmentVariableW(nome, buf, 2048)) return "";
    return narrow_(std::wstring(buf));
}
#endif

// ------------------------------------------------- varredura de pastas
struct ArqPac {
    std::string rel;      // caminho dentro do pacote (sempre com '/')
    std::string full;     // caminho no disco
};

void listar_pasta(const std::string& dir, const std::string& prefixo, char sep,
                  std::vector<ArqPac>& out) {
    if (dir.empty()) return;
#ifdef RACEAI_WIN
    (void)sep;
    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA((dir + "\\*").c_str(), &fd);
    if (h == INVALID_HANDLE_VALUE) return;
    do {
        const std::string nome = fd.cFileName;
        if (nome == "." || nome == "..") continue;
        const std::string full = dir + "\\" + nome;
        const std::string rel = prefixo.empty() ? nome : prefixo + "/" + nome;
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            listar_pasta(full, rel, sep, out);
        } else {
            out.push_back({rel, full});
        }
    } while (FindNextFileA(h, &fd));
    FindClose(h);
#else
    (void)sep;
    DIR* d = ::opendir(dir.c_str());
    if (!d) return;
    while (struct dirent* e = ::readdir(d)) {
        const std::string nome = e->d_name;
        if (nome == "." || nome == "..") continue;
        const std::string full = dir + "/" + nome;
        const std::string rel = prefixo.empty() ? nome : prefixo + "/" + nome;
        struct stat st;
        if (::stat(full.c_str(), &st) == 0 && S_ISDIR(st.st_mode)) {
            listar_pasta(full, rel, sep, out);
        } else {
            out.push_back({rel, full});
        }
    }
    ::closedir(d);
#endif
}

uint32_t u32_(const unsigned char* p) {
    return uint32_t(p[0]) | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16) |
           (uint32_t(p[3]) << 24);
}

uint64_t u64_(const unsigned char* p) {
    uint64_t v = 0;
    for (int i = 7; i >= 0; --i) v = (v << 8) | uint64_t(p[i]);
    return v;
}

// lê o trailer do .exe; devolve o tamanho do pacote (0 = não tem pacote)
uint64_t le_trailer(const std::string& alvo, std::string* erro) {
    if (erro) erro->clear();
#ifdef RACEAI_WIN
    FILE* f = _wfopen(wide_(alvo).c_str(), L"rb");
#else
    FILE* f = std::fopen(alvo.c_str(), "rb");
#endif
    if (!f) {
        if (erro) *erro = "não consegui abrir o executável";
        return 0;
    }
    std::fseek(f, 0, SEEK_END);
    const long tam_total = std::ftell(f);
    if (tam_total <= kTamTrailer + 16) {
        std::fclose(f);
        if (erro) *erro = "arquivo sem pacote embutido";
        return 0;                       // não tem pacote: modo portátil
    }
    unsigned char t[24];
    std::fseek(f, tam_total - kTamTrailer, SEEK_SET);
    if (std::fread(t, 1, kTamTrailer, f) != size_t(kTamTrailer) ||
        std::memcmp(t, kMagiaFim, 12) != 0) {
        std::fclose(f);
        if (erro) *erro = "arquivo sem pacote embutido";
        return 0;                       // não tem pacote: modo portátil
    }
    const uint64_t tam_pacote = u64_(t + 12);
    std::fclose(f);
    if (tam_pacote == 0 ||
        tam_pacote + uint64_t(kTamTrailer) > uint64_t(tam_total)) {
        if (erro) *erro = "pacote embutido com tamanho inválido";
        return 0;
    }
    return tam_pacote;
}

}  // namespace

std::string dir_instalado(bool criar) {
#ifdef RACEAI_WIN
    std::string base = env_(L"LOCALAPPDATA");
    if (base.empty()) {
        base = env_(L"USERPROFILE");
        if (!base.empty()) base = juntar(base, "AppData/Local");
    }
    if (base.empty()) return "";
    std::string dir = juntar(base, "RaceAI2D");
    if (criar && !existe_(dir)) criar_dirs_(dir);
    return dir;
#else
    (void)criar;
    return "";
#endif
}

std::string dir_dados() {
    const std::string exe = diretorio_do_exe();
    // modo portátil: já existe assets/ do lado do .exe
    if (!exe.empty() && (existe_(juntar(exe, "assets/tracks")) ||
                         existe_(juntar(exe, "assets/cars")))) {
        return exe;
    }
    const std::string inst = dir_instalado(false);
    if (!inst.empty()) return inst;
    return exe;
}

bool tem_conteudo_embutido() {
#ifdef RACEAI_WIN
    wchar_t modulo[MAX_PATH];
    if (!GetModuleFileNameW(nullptr, modulo, MAX_PATH)) return false;
    const uint64_t tam = le_trailer(narrow_(std::wstring(modulo)), nullptr);
    return tam > 0;
#else
    return false;
#endif
}

// ---------------------------------------------------------- empacotar
static void empurra32(std::vector<unsigned char>& v, uint32_t x) {
    for (int i = 0; i < 4; ++i) v.push_back(static_cast<unsigned char>((x >> (8 * i)) & 0xff));
}
static void empurra64(std::vector<unsigned char>& v, uint64_t x) {
    for (int i = 0; i < 8; ++i) v.push_back(static_cast<unsigned char>((x >> (8 * i)) & 0xff));
}

// tira um pacote antigo do fim do arquivo (se houver)
static void trunca_pacote(const std::string& arquivo) {
    FILE* f = std::fopen(arquivo.c_str(), "r+b");
    if (!f) return;
    std::fseek(f, 0, SEEK_END);
    const long tam = std::ftell(f);
    if (tam > kTamTrailer + 16) {
        unsigned char t[24];
        std::fseek(f, tam - kTamTrailer, SEEK_SET);
        if (std::fread(t, 1, kTamTrailer, f) == size_t(kTamTrailer) &&
            std::memcmp(t, kMagiaFim, 12) == 0) {
            const uint64_t tam_pacote = u64_(t + 12);
            if (tam_pacote > 0 && tam_pacote < uint64_t(tam)) {
                const long corta = tam - kTamTrailer - long(tam_pacote);
                std::fclose(f);
#ifdef RACEAI_WIN
                HANDLE h = CreateFileW(wide_(arquivo).c_str(), GENERIC_WRITE, 0,
                                       nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL,
                                       nullptr);
                if (h != INVALID_HANDLE_VALUE) {
                    SetFilePointer(h, corta, nullptr, FILE_BEGIN);
                    SetEndOfFile(h);
                    CloseHandle(h);
                }
#else
                ::truncate(arquivo.c_str(), corta);
#endif
                return;
            }
        }
    }
    std::fclose(f);
}

bool criar_pacote(const std::string& exe, const std::vector<std::string>& pastas,
                  std::string* erro) {
    if (erro) erro->clear();
    std::vector<ArqPac> arquivos;
    for (const std::string& p : pastas) {
        std::string dir = p;
        while (!dir.empty() && (dir.back() == '/' || dir.back() == '\\')) dir.pop_back();
        if (dir.empty() || !existe_(dir)) continue;
        const size_t barra = dir.find_last_of("/\\");
        const std::string prefixo =
            (barra == std::string::npos) ? dir : dir.substr(barra + 1);
        listar_pasta(dir, prefixo, '/', arquivos);
    }
    if (arquivos.empty()) {
        if (erro) *erro = "nada para empacotar";
        return false;
    }
    std::vector<unsigned char> pacote;
    for (const char* p = kMagia; *p; ++p) pacote.push_back(static_cast<unsigned char>(*p));
    empurra32(pacote, 1);
    empurra32(pacote, uint32_t(arquivos.size()));
    for (const ArqPac& a : arquivos) {
        FILE* f = std::fopen(a.full.c_str(), "rb");
        if (!f) continue;
        std::fseek(f, 0, SEEK_END);
        const long tam = std::ftell(f);
        std::fseek(f, 0, SEEK_SET);
        empurra32(pacote, uint32_t(a.rel.size()));
        for (char c : a.rel) pacote.push_back(static_cast<unsigned char>(c));
        empurra64(pacote, uint64_t(tam));
        const size_t ini = pacote.size();
        pacote.resize(ini + size_t(tam));
        if (tam > 0 && std::fread(pacote.data() + ini, 1, size_t(tam), f) != size_t(tam)) {
            pacote.resize(ini);
        }
        std::fclose(f);
    }
    trunca_pacote(exe);
    FILE* out = std::fopen(exe.c_str(), "ab");
    if (!out) {
        if (erro) *erro = "não consegui escrever em " + exe;
        return false;
    }
    std::fwrite(pacote.data(), 1, pacote.size(), out);
    unsigned char trailer[24];
    std::memset(trailer, 0, sizeof(trailer));
    std::memcpy(trailer, kMagiaFim, 12);
    for (int i = 0; i < 8; ++i)
        trailer[12 + i] = static_cast<unsigned char>((uint64_t(pacote.size()) >> (8 * i)) & 0xff);
    std::fwrite(trailer, 1, sizeof(trailer), out);
    std::fclose(out);
    return true;
}

bool extrair_pacote(const std::string& arquivo, const std::string& destino,
                    std::string* erro) {
    if (erro) erro->clear();
    const uint64_t tam_pacote = le_trailer(arquivo, erro);
    if (tam_pacote == 0) return false;

    FILE* f = std::fopen(arquivo.c_str(), "rb");
    if (!f) {
        if (erro) *erro = "não consegui abrir " + arquivo;
        return false;
    }
    std::fseek(f, 0, SEEK_END);
    const long tam_total = std::ftell(f);
    std::fseek(f, tam_total - kTamTrailer - long(tam_pacote), SEEK_SET);
    const size_t n_pacote = size_t(tam_pacote);
    std::vector<unsigned char> pacote(n_pacote);
    if (std::fread(pacote.data(), 1, n_pacote, f) != n_pacote) {
        std::fclose(f);
        if (erro) *erro = "pacote embutido truncado";
        return false;
    }
    std::fclose(f);

    if (pacote.size() < 17 || std::memcmp(pacote.data(), kMagia, 9) != 0) {
        if (erro) *erro = "pacote embutido corrompido";
        return false;
    }
    size_t p = 9;
    if (u32_(pacote.data() + p) != 1) {
        if (erro) *erro = "versão de pacote desconhecida";
        return false;
    }
    p += 4;
    const uint32_t quantos = u32_(pacote.data() + p);
    p += 4;

    criar_dirs_(destino);
    for (uint32_t i = 0; i < quantos; ++i) {
        if (p + 4 > pacote.size()) break;
        const uint32_t tam_nome = u32_(pacote.data() + p);
        p += 4;
        if (p + tam_nome > pacote.size()) break;
        std::string nome(pacote.begin() + p, pacote.begin() + p + tam_nome);
        p += tam_nome;
        if (p + 8 > pacote.size()) break;
        const uint64_t tam = u64_(pacote.data() + p);
        p += 8;
        if (p + size_t(tam) > pacote.size()) break;
        for (char& c : nome)
            if (c == '\\') c = '/';
        const std::string caminho = juntar(destino, nome);
        // não sobrescreve: se o arquivo existe, pode ser mod do usuário
        if (!existe_(caminho)) {
            const size_t barra = caminho.find_last_of("/\\");
            if (barra != std::string::npos) criar_dirs_(caminho.substr(0, barra));
            FILE* out = std::fopen(caminho.c_str(), "wb");
            if (out) {
                if (tam > 0) std::fwrite(pacote.data() + p, 1, size_t(tam), out);
                std::fclose(out);
            }
        }
        p += size_t(tam);
    }
    return true;
}

std::string garantir_conteudo(std::string* erro) {
    if (erro) erro->clear();
#ifdef RACEAI_WIN
    wchar_t modulo[MAX_PATH];
    if (!GetModuleFileNameW(nullptr, modulo, MAX_PATH)) {
        if (erro) *erro = "não achei o caminho do executável";
        return "";
    }
    const std::string alvo = narrow_(std::wstring(modulo));
    if (!tem_conteudo_embutido()) return "";   // modo portátil: nada a extrair
    std::string destino = dir_instalado(true);
    if (destino.empty()) {
        destino = diretorio_do_exe();
        if (destino.empty()) destino = ".";
    }
    criar_dirs_(destino);
    if (!extrair_pacote(alvo, destino, erro)) return "";
    return destino;
#else
    (void)erro;
    return "";
#endif
}

}  // namespace raceai
