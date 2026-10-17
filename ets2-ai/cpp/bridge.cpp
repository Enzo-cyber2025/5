// ---------------------------------------------------------------------------
// ETS2-AI bridge — C++ PURO (Win32). Sem Python. Sem adb. Sem APK. Sem celular.
//
// Um unico .exe que faz TUDO:
//   1. DESCOBRE o jogo (processo aberto > cache > Steam > varredura do disco);
//   2. instala a DLL de telemetria IDEAL (banco embutido: nossa universal
//      para 1.36+ / RenCloud+nlhans para as antigas — mesma tabela do repo);
//   3. le a memoria compartilhada Local\SCSTelemetry (ABI real do SDK);
//   4. roda a IA (MLP 13->290x13->3, tanh ocultas, saida linear) NO PROPRIO
//      exe — pesos oficiais EMBUTIDOS como recurso (formato texto do APK);
//   5. injeta as teclas REAIS (SendInput/scan codes, PWM calibrado).
//
// Uso:
//   ETS2-AI-bridge.exe                     (GUI: BUSCAR/AUTOTESTE/COMEÇAR)
//   ETS2-AI-bridge.exe --autoteste [--game-dir D] [--saida F]
//   ETS2-AI-bridge.exe --ets2 drive --inject [--window "Euro Truck"]
//   ETS2-AI-bridge.exe --bench
//
// Recursos embutidos (gerados no build):
//   RCDATA "DLL:<repo>:<tag>:<arch>"       (banco de DLLs de telemetria)
//   RCDATA "WEIGHTS_OFFICIAL" / "WEIGHTS_NANO"  (pesos, formato ETS2AI,v1)
// ESC = kill switch. A IA so injeta com o jogo em 1o plano E tela cheia.
// ---------------------------------------------------------------------------
#define UNICODE
#define _UNICODE
#define NOMINMAX
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tlhelp32.h>
#include <shlobj.h>
#include <shellapi.h>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <string>
#include <vector>
#include <thread>
#include <atomic>
#include <mutex>
#include <chrono>
#include <fstream>
#include <sstream>
#include <algorithm>
#include <cstdarg>
#include <cctype>
#include <cwctype>
#include <cwchar>

#pragma comment(lib, "user32.lib")
#pragma comment(lib, "shell32.lib")
#pragma comment(lib, "advapi32.lib")

static const wchar_t* APP_VERSION = L"0.5.0-cpp";
static const wchar_t* MMF_NAME = L"Local\\SCSTelemetry";
static const DWORD  MMF_SIZE = 32 * 1024;

// ---------------- offsets publicos do scsTelemetryMap_t ----------------
static const int O_SDK = 0, O_PAUSED = 4, O_TIME = 8, O_REV = 40,
  O_VMAJ = 44, O_VMIN = 48, O_GAMEID = 52, O_TAMIN = 64,
  O_FUEL_CAP = 704, O_SPEED = 948, O_USTEER = 956, O_UTHROTTLE = 960,
  O_UBRAKE = 964, O_FUEL = 1000, O_ROUTE = 1060, O_SLIMIT = 1068,
  O_MAGIC = 1472, O_PARK = 1566, O_ENGINE = 1576, O_ONJOB = 4300;

// ---------------- teclado (scan codes; setas/Enter/. = estendidas) -----
static const unsigned SC_LEFT = 0x1E, SC_RIGHT = 0x20, SC_ACCEL = 0x11,
  SC_BRAKE = 0x1F, SC_ENGINE = 0x12, SC_DOCK = 0x14, SC_OK = 0x1C,
  SC_DOWN = 0x50, SC_PARK = 0x34;
static bool is_ext(unsigned sc) {
  return sc == 0x48 || sc == 0x4B || sc == 0x4D || sc == 0x50 ||
         sc == 0x52 || sc == 0x53 || sc == 0x1C || sc == 0x34;
}
static const int PWM_PHASES = 8;
static const double STEER_DEADBAND = 0.05;

// =======================================================================
// log: console + arquivo ao lado do exe
// =======================================================================
static std::wstring exe_dir() {
  wchar_t buf[MAX_PATH * 2];
  DWORD n = GetModuleFileNameW(nullptr, buf, ARRAYSIZE(buf));
  std::wstring p(buf, n);
  size_t s = p.find_last_of(L"\\/");
  return s == std::wstring::npos ? L"." : p.substr(0, s);
}
static std::mutex g_logmtx;
static void log_line(const std::string& msg) {
  std::lock_guard<std::mutex> lk(g_logmtx);
  SYSTEMTIME st; GetLocalTime(&st);
  char stamp[32];
  snprintf(stamp, sizeof stamp, "[%02d:%02d:%02d] ",
           st.wHour, st.wMinute, st.wSecond);
  FILE* f = nullptr;
  _wfopen_s(&f, (exe_dir() + L"\\ets2-ai-log.txt").c_str(), L"a");
  if (f) { fprintf(f, "%s%s\n", stamp, msg.c_str()); fclose(f); }
  printf("%s%s\n", stamp, msg.c_str());
  fflush(stdout);
}
static void logf(const char* fmt, ...) {
  char buf[1024];
  va_list ap; va_start(ap, fmt);
  vsnprintf(buf, sizeof buf, fmt, ap);
  va_end(ap);
  log_line(buf);
}
static std::string wide2utf8(const std::wstring& w) {
  int n = WideCharToMultiByte(CP_UTF8, 0, w.c_str(), (int)w.size(),
                              nullptr, 0, nullptr, nullptr);
  std::string s(n, 0);
  WideCharToMultiByte(CP_UTF8, 0, w.c_str(), (int)w.size(), &s[0], n,
                      nullptr, nullptr);
  return s;
}
static std::wstring utf82wide(const std::string& s) {
  int n = MultiByteToWideChar(CP_UTF8, 0, s.data(), (int)s.size(),
                              nullptr, 0);
  std::wstring w(n, 0);
  MultiByteToWideChar(CP_UTF8, 0, s.data(), (int)s.size(), &w[0], n);
  return w;
}
static std::string json_escape(const std::string& s) {
  std::string o;
  for (char c : s) {
    if (c == '"' || c == '\\') { o += '\\'; o += c; }
    else if ((unsigned char)c < 0x20) o += ' ';
    else o += c;
  }
  return o;
}

// =======================================================================
// recursos embutidos (banco de DLLs + pesos)
// =======================================================================
struct ResData { const void* ptr; DWORD size; };
static bool load_res(const wchar_t* name, ResData* out) {
  HRSRC r = FindResourceW(nullptr, name, RT_RCDATA);
  if (!r) return false;
  HGLOBAL g = LoadResource(nullptr, r);
  if (!g) return false;
  out->ptr = LockResource(g);
  out->size = SizeofResource(nullptr, r);
  return out->ptr && out->size;
}
// rc.exe GUARDA nomes-string com ASPAS e MAIUSCULADOS — FindResource por
// nome nunca acha. Por isso o banco usa IDs NUMERICOS: 101 = manifesto
// ("repo tag arch id" por linha, ids 110+), 102 = pesos oficiais, 103 nano.
static bool load_res_id(int id, ResData* out) {
  return load_res(MAKEINTRESOURCEW(id), out);
}
struct BankDll { std::string repo, tag, arch; ResData data; };
static std::vector<BankDll> g_bank;
static int g_res_total = 0;
static BOOL WINAPI info_cb(HMODULE, LPCWSTR type, LPWSTR name, LONG_PTR) {
  ++g_res_total;
  if (g_res_total <= 8) {
    std::wstring n = IS_INTRESOURCE(name) ? L"(numerico)" : name;
    logf("[info] RCDATA: %ls", n.c_str());
  }
  return TRUE;
}
static BOOL WINAPI enum_cb(HMODULE mod, LPCWSTR type, LPWSTR name,
                           LONG_PTR lparam) {
  std::wstring n = IS_INTRESOURCE(name) ? L"" : name;
  if (n.rfind(L"DLL~", 0) == 0) {
    // nome do recurso: "DLL~<repo>~<tag>~<arch>" ('~' e seguro no rc.exe)
    std::string full = wide2utf8(n.substr(4));
    size_t a = full.find('~'), b = full.find('~', a + 1);
    if (a != std::string::npos && b != std::string::npos) {
      BankDll d;
      d.repo = full.substr(0, a);
      d.tag = full.substr(a + 1, b - a - 1);
      d.arch = full.substr(b + 1);
      ResData rd;
      if (load_res(name, &rd)) { d.data = rd; g_bank.push_back(d); }
    }
  }
  return TRUE;
}
static void load_bank() {
  if (!g_bank.empty()) return;
  ResData man;
  if (!load_res_id(101, &man)) return;
  std::istringstream ss(std::string((const char*)man.ptr, man.size));
  std::string repo, tag, arch;
  int id;
  while (ss >> repo >> tag >> arch >> id) {
    ResData rd;
    if (load_res_id(id, &rd)) {
      BankDll d;
      d.repo = repo; d.tag = tag; d.arch = arch; d.data = rd;
      g_bank.push_back(d);
    }
  }
}

// =======================================================================
// banco: mesma tabela DLL_BANK do repo (telemetry.py)
// =======================================================================
struct BankEntry { const char* repo, * tag; int min_major, min_minor; };
static const BankEntry DLL_BANK[] = {
  {"ets2ai",  "universal",              1, 36},
  {"rencloud", "V.1.12.1",              1, 46},
  {"rencloud", "V.1.12",                1, 46},
  {"rencloud", "V.1.11.1",              1, 45},
  {"rencloud", "V.1.11",                1, 41},
  {"rencloud", "V.1.10.6",              1, 36},
  {"rencloud", "V.1.10.5",              1, 36},
  {"rencloud", "V.1.10.4",              1, 36},
  {"rencloud", "v.1.9.0",               1, 32},
  {"nlhans",  "revision_5_rel_1_4_0",   1, 17},
  {"nlhans",  "revision_4_rel_1_3_0",   1, 17},
  {"nlhans",  "revision_3_rel_1_2_1",   1, 10},
  {"nlhans",  "revision_3",             1, 10},
  {"nlhans",  "revision_2",             1, 10},
  {"nlhans",  "revision_1",             1, 10},
};
static const BankDll* bank_find(const std::string& repo, const std::string& tag,
                                const std::string& arch) {
  for (auto& d : g_bank)
    if (d.repo == repo && d.tag == tag && d.arch == arch) return &d;
  return nullptr;
}
// DLL ideal: release mais nova que suporta a versao do jogo; desconhecida =
// a mais nova (universal); jogo pre-historico = a mais antiga do banco.
static const BankDll* pick_dll(int maj, int min, const std::string& arch,
                               bool known) {
  for (auto& e : DLL_BANK) {
    const BankDll* d = bank_find(e.repo, e.tag, arch);
    if (!d) continue;
    if (!known || (e.min_major < maj || (e.min_major == maj &&
                                         e.min_minor <= min)))
      return d;
  }
  for (int i = (int)(sizeof(DLL_BANK) / sizeof(DLL_BANK[0])) - 1; i >= 0;
       --i) {
    const BankDll* d = bank_find(DLL_BANK[i].repo, DLL_BANK[i].tag, arch);
    if (d) return d;
  }
  return nullptr;
}

// =======================================================================
// descoberta do jogo
// =======================================================================
static bool dir_exists(const std::wstring& p) {
  DWORD a = GetFileAttributesW(p.c_str());
  return a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_DIRECTORY);
}
static bool file_exists(const std::wstring& p) {
  DWORD a = GetFileAttributesW(p.c_str());
  return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY);
}
static std::wstring localappdata() {
  wchar_t buf[MAX_PATH];
  if (SUCCEEDED(SHGetFolderPathW(nullptr, CSIDL_LOCAL_APPDATA, nullptr, 0,
                                 buf)))
    return buf;
  return L".";
}
static std::wstring game_cache_path() {
  return localappdata() + L"\\ets2-ai";
}
static bool looks_like_game(const std::wstring& dir) {
  if (!dir_exists(dir + L"\\bin")) return false;
  return dir_exists(dir + L"\\bin\\win_x64") ||
         dir_exists(dir + L"\\bin\\win_x86");
}
// processo eurotrucks2.exe aberto -> pasta do jogo
static std::wstring find_by_process() {
  HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
  if (snap == INVALID_HANDLE_VALUE) return L"";
  PROCESSENTRY32W pe; pe.dwSize = sizeof pe;
  std::wstring out;
  if (Process32FirstW(snap, &pe)) {
    do {
      if (_wcsicmp(pe.szExeFile, L"eurotrucks2.exe") == 0) {
        HANDLE h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE,
                               pe.th32ProcessID);
        if (h) {
          wchar_t buf[MAX_PATH * 2]; DWORD n = ARRAYSIZE(buf);
          if (QueryFullProcessImageNameW(h, 0, buf, &n)) {
            std::wstring p(buf, n);  // ...\bin\win_x64\eurotrucks2.exe
            for (int i = 0; i < 3 && !p.empty(); ++i) {
              size_t s = p.find_last_of(L"\\/");
              if (s == std::wstring::npos) break;
              p = p.substr(0, s);
            }
            if (looks_like_game(p)) out = p;
          }
          CloseHandle(h);
          if (!out.empty()) break;
        }
      }
    } while (Process32NextW(snap, &pe));
  }
  CloseHandle(snap);
  return out;
}
// bibliotecas Steam (libraryfolders.vdf)
static std::vector<std::wstring> steam_libraries() {
  std::vector<std::wstring> out;
  const wchar_t* roots[] = {
    L"C:\\Program Files (x86)\\Steam", L"C:\\Program Files\\Steam",
  };
  for (auto* r : roots) {
    if (!dir_exists(r)) continue;
    out.push_back(r);
    std::wifstream vdf((std::wstring(r) + L"\\steamapps\\libraryfolders.vdf")
                         .c_str());
    std::wstring ln;
    while (std::getline(vdf, ln)) {
      if (ln.find(L"\"path\"") == std::wstring::npos) continue;
      size_t a = ln.find(L'"', 6), b = ln.find(L'"', a + 1);
      if (a == std::wstring::npos || b == std::wstring::npos) continue;
      std::wstring p = ln.substr(a + 1, b - a - 1);
      for (auto& c : p) if (c == L'/') c = L'\\';
      if (!p.empty() && dir_exists(p + L"\\steamapps"))
        out.push_back(p);
    }
  }
  return out;
}
static std::vector<std::wstring> common_game_guesses() {
  std::vector<std::wstring> guesses;
  for (auto& lib : steam_libraries()) {
    guesses.push_back(lib + L"\\steamapps\\common\\Euro Truck Simulator 2");
    guesses.push_back(lib + L"\\steamapps\\common\\Euro Truck Simulator 2 Demo");
  }
  return guesses;
}
// varredura recursiva do disco (win_x64/win_x86 com steam.inf)
static bool scan_root(const std::wstring& root, std::wstring* found,
                      std::atomic<bool>* cancel) {
  static const wchar_t* skip[] = { L"$recycle.bin", L"windows",
                                   L"system volume information",
                                   L"node_modules", L"ets2-ai" };
  std::vector<std::wstring> stack{ root };
  int visited = 0;
  while (!stack.empty()) {
    if (cancel && cancel->load()) return false;
    if (++visited > 220000) return false;
    std::wstring dir = stack.back(); stack.pop_back();
    std::wstring pat = dir + L"\\*";
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(pat.c_str(), &fd);
    if (h == INVALID_HANDLE_VALUE) continue;
    do {
      if (wcscmp(fd.cFileName, L".") == 0 || wcscmp(fd.cFileName, L"..") == 0)
        continue;
      std::wstring full = dir + L"\\" + fd.cFileName;
      if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
        bool bad = false;
        for (auto* s : skip)
          if (_wcsicmp(fd.cFileName, s) == 0) { bad = true; break; }
        if (!bad && !(fd.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT))
          stack.push_back(full);
        // ACHOU: bin\win_xX com steam.inf (ou eurotrucks2.exe) no pai
        if ((_wcsicmp(fd.cFileName, L"win_x64") == 0 ||
             _wcsicmp(fd.cFileName, L"win_x86") == 0)) {
          std::wstring bin = dir;             // ...\<game>\bin
          size_t s = bin.find_last_of(L"\\/");
          std::wstring game = s == std::wstring::npos ? L"" : bin.substr(0, s);
          if (!game.empty() && looks_like_game(game) &&
              (file_exists(game + L"\\steam.inf") ||
               file_exists(full + L"\\eurotrucks2.exe") ||
               file_exists(game + L"\\eurotrucks2.exe"))) {
            *found = game;
            FindClose(h);
            return true;
          }
        }
      }
    } while (FindNextFileW(h, &fd));
    FindClose(h);
  }
  return false;
}
struct Discovery { std::wstring dir; std::string how; };
static Discovery discover_game(const std::wstring& hint,
                               std::atomic<bool>* cancel = nullptr) {
  Discovery d{ L"", "" };
  if (!hint.empty() && looks_like_game(hint)) {
    d.dir = hint; d.how = "--game-dir"; return d;
  }
  std::wstring p = find_by_process();
  if (!p.empty()) { d.dir = p; d.how = "processo do jogo aberto"; return d; }
  std::wstring cache = game_cache_path() + L"\\game-dir.txt";
  if (file_exists(cache)) {
    std::ifstream f(cache);
    std::string ln; std::getline(f, ln);
    std::wstring w = utf82wide(ln);
    if (!w.empty() && looks_like_game(w)) {
      d.dir = w; d.how = "cache"; return d;
    }
  }
  for (auto& g : common_game_guesses())
    if (looks_like_game(g)) {
      d.dir = g; d.how = "Steam"; return d;
    }
  DWORD drives = GetLogicalDrives();
  for (wchar_t letter = L'A'; letter <= L'Z' && d.dir.empty(); ++letter) {
    if (!(drives & (1 << (letter - L'A')))) continue;
    std::wstring root{ letter, L':' };
    UINT type = GetDriveTypeW((root + L"\\").c_str());
    if (type == DRIVE_CDROM || type == DRIVE_NO_ROOT_DIR) continue;
    std::wstring found;
    if (scan_root(root, &found, cancel)) {
      d.dir = found; d.how = "varredura do disco"; break;
    }
  }
  if (!d.dir.empty()) {
    CreateDirectoryW(game_cache_path().c_str(), nullptr);
    std::ofstream(game_cache_path() + L"\\game-dir.txt")
      << wide2utf8(d.dir) << "\n";
  }
  return d;
}

// =======================================================================
// versao + instalacao da DLL
// =======================================================================
static bool parse_version(const std::wstring& steam_inf, int* maj, int* min) {
  std::ifstream f(steam_inf);
  std::string ln, txt;
  while (std::getline(f, ln)) txt += ln + "\n";
  *maj = *min = -1;
  auto scan = [&](const char* key) -> bool {
    size_t p = txt.find(key);
    if (p == std::string::npos) return false;
    int a = -1, b = -1;
    // parse manual: primeiro "digito.digito" apos a chave
    size_t i = p + strlen(key);
    while (i < txt.size() && !isdigit((unsigned char)txt[i])) {
      if (txt[i] == '\n') return false;
      ++i;
    }
    a = atoi(txt.c_str() + i);
    while (i < txt.size() && isdigit((unsigned char)txt[i])) ++i;
    if (i >= txt.size() || txt[i] != '.') return false;
    ++i;
    if (!isdigit((unsigned char)txt[i])) return false;
    b = atoi(txt.c_str() + i);
    if (a < 0 || b < 0) return false;
    *maj = a; *min = b;
    return true;
  };
  if (scan("exe_version_info=")) return true;
  if (scan("PatchVersion")) return true;
  if (scan("version")) return true;
  // qualquer d.d.d
  size_t i = 0;
  while (i < txt.size() && !isdigit((unsigned char)txt[i])) ++i;
  if (i + 2 < txt.size() && txt.find('.', i) != std::string::npos) {
    size_t dot = txt.find('.', i);
    if (dot != std::string::npos && dot > i &&
        isdigit((unsigned char)txt[dot + 1])) {
      *maj = atoi(txt.c_str() + i);
      *min = atoi(txt.c_str() + dot + 1);
      return *maj >= 0 && *min >= 0;
    }
  }
  return false;
}
struct InstallInfo {
  bool ok = false; std::string repo, tag, arch, version, dll_path;
};
static bool mkdirs(const std::wstring& p) {
  std::wstring cur;
  for (size_t i = 0; i < p.size(); ++i) {
    if (p[i] == L'\\' || p[i] == L'/') {
      if (!cur.empty()) CreateDirectoryW(cur.c_str(), nullptr);
    }
    cur += p[i];
  }
  CreateDirectoryW(cur.c_str(), nullptr);
  return dir_exists(p);
}
static InstallInfo install_dll(const std::wstring& game_dir) {
  InstallInfo r;
  std::wstring arch_dir = dir_exists(game_dir + L"\\bin\\win_x64")
                            ? L"win_x64" : L"win_x86";
  std::string arch = arch_dir == L"win_x64" ? "x64" : "x86";
  int maj = -1, min = -1;
  bool known = parse_version(game_dir + L"\\steam.inf", &maj, &min);
  const BankDll* d = pick_dll(maj, min, arch, known);
  if (!d) return r;
  std::wstring plugins = game_dir + L"\\bin\\" + arch_dir + L"\\plugins";
  if (!mkdirs(plugins)) return r;
  std::wstring dst = plugins + L"\\scs-telemetry.dll";
  // verifica por tamanho (hash barato) e REPARA se divergir
  bool need = true;
  HANDLE hf = CreateFileW(dst.c_str(), GENERIC_READ, FILE_SHARE_READ,
                          nullptr, OPEN_EXISTING, 0, nullptr);
  if (hf != INVALID_HANDLE_VALUE) {
    if (GetFileSize(hf, nullptr) == d->data.size) need = false;
    CloseHandle(hf);
  }
  if (need) {
    HANDLE out = CreateFileW(dst.c_str(), GENERIC_WRITE, 0, nullptr,
                             CREATE_ALWAYS, 0, nullptr);
    if (out == INVALID_HANDLE_VALUE) return r;
    DWORD wr = 0;
    if (!WriteFile(out, d->data.ptr, d->data.size, &wr, nullptr) ||
        wr != d->data.size) { CloseHandle(out); return r; }
    CloseHandle(out);
  }
  char vs[32];
  if (known) snprintf(vs, sizeof vs, "%d.%d", maj, min);
  else snprintf(vs, sizeof vs, "?");
  r.ok = true; r.repo = d->repo; r.tag = d->tag; r.arch = arch;
  r.version = vs; r.dll_path = wide2utf8(dst);
  return r;
}

// =======================================================================
// telemetria: leitura da MMF + jogo falso (autoteste)
// =======================================================================
struct Snap {
  bool sdk = false, paused = false, on_job = false, park = false, engine = true;
  unsigned long long time = 0;
  int vmaj = 0, vmin = 0, game_id = 0, tamin = 0;
  float speed = 0, usteer = 0, uthrottle = 0, ubrake = 0, fuel = 0,
    fuel_cap = 0, route = 0, slimit = 0;
  unsigned magic = 0;
};
static float rdf(const unsigned char* v, int off) {
  float f; memcpy(&f, v + off, 4); return f;
}
static unsigned rdu32(const unsigned char* v, int off) {
  unsigned u; memcpy(&u, v + off, 4); return u;
}
static unsigned long long rdu64(const unsigned char* v, int off) {
  unsigned long long u; memcpy(&u, v + off, 8); return u;
}
static void wfloat(unsigned char* v, int off, float f) {
  memcpy(v + off, &f, 4);
}
static void wu32(unsigned char* v, int off, unsigned u) {
  memcpy(v + off, &u, 4);
}
static Snap parse(const unsigned char* v) {
  Snap s;
  s.sdk = rdu32(v, O_SDK) & 0xFF;
  s.paused = rdu32(v, O_PAUSED) & 0xFF;
  s.time = rdu64(v, O_TIME);
  s.vmaj = (int)rdu32(v, O_VMAJ); s.vmin = (int)rdu32(v, O_VMIN);
  s.game_id = (int)rdu32(v, O_GAMEID);
  s.tamin = (int)rdu32(v, O_TAMIN);
  s.speed = rdf(v, O_SPEED); s.usteer = rdf(v, O_USTEER);
  s.uthrottle = rdf(v, O_UTHROTTLE); s.ubrake = rdf(v, O_UBRAKE);
  s.fuel = rdf(v, O_FUEL); s.fuel_cap = rdf(v, O_FUEL_CAP);
  s.route = rdf(v, O_ROUTE); s.slimit = rdf(v, O_SLIMIT);
  s.magic = rdu32(v, O_MAGIC);
  s.park = rdu32(v, O_PARK) & 0xFF;
  s.engine = (rdu32(v, O_ENGINE) & 0xFF) || true;  // ausente = assume ligado
  s.on_job = rdu32(v, O_ONJOB) & 0xFF;
  return s;
}
struct Mmf {
  HANDLE h = nullptr; void* view = nullptr;
  bool open(bool write) {
    h = OpenFileMappingW(write ? FILE_MAP_ALL_ACCESS : FILE_MAP_READ,
                         FALSE, MMF_NAME);
    if (!h) return false;
    view = MapViewOfFile(h, write ? FILE_MAP_ALL_ACCESS : FILE_MAP_READ,
                         0, 0, MMF_SIZE);
    if (!view) { CloseHandle(h); h = nullptr; return false; }
    return true;
  }
  ~Mmf() {
    if (view) UnmapViewOfFile(view);
    if (h) CloseHandle(h);
  }
};
// jogo falso do autoteste: cria a MMF com um quadro VALIDO (como o plugin
// faria dentro do processo do jogo). NUNCA cria se o jogo real estiver
// aberto (a memoria dele e sagrada).
static bool start_fake_game(Mmf* m) {
  HANDLE probe = OpenFileMappingW(FILE_MAP_READ, FALSE, MMF_NAME);
  if (probe) { CloseHandle(probe); return false; }  // jogo REAL aberto
  HANDLE h = CreateFileMappingW(INVALID_HANDLE_VALUE, nullptr,
                                PAGE_READWRITE, 0, MMF_SIZE, MMF_NAME);
  if (!h) return false;
  void* v = MapViewOfFile(h, FILE_MAP_ALL_ACCESS, 0, 0, MMF_SIZE);
  if (!v) { CloseHandle(h); return false; }
  ZeroMemory(v, MMF_SIZE);
  unsigned char* p = (unsigned char*)v;
  wu32(p, O_SDK, 1); wu32(p, O_PAUSED, 0);
  wu32(p, O_TIME, 123456); wu32(p, O_TIME + 4, 0);
  wu32(p, O_REV, 15); wu32(p, O_VMAJ, 1); wu32(p, O_VMIN, 53);
  wu32(p, O_GAMEID, 1);
  wfloat(p, O_SPEED, 17.5f); wfloat(p, O_USTEER, 0.25f);
  wfloat(p, O_UTHROTTLE, 0.5f); wfloat(p, O_UBRAKE, 0.0f);
  wfloat(p, O_FUEL, 380.5f); wfloat(p, O_FUEL_CAP, 600.0f);
  wfloat(p, O_ROUTE, 12500.0f); wfloat(p, O_SLIMIT, 22.2f);
  wu32(p, O_ONJOB, 1);
  m->h = h; m->view = v;
  return true;
}

// =======================================================================
// IA: pesos em formato texto (ETS2AI,v1) + MLP tanh
// =======================================================================
struct Net {
  int nin = 0, nout = 0;
  std::vector<int> hidden;
  std::vector<std::vector<float>> W;   // [layer] fan_in x fan_out
  std::vector<std::vector<float>> B;   // [layer] fan_out
  bool loaded = false;
  bool load(const std::string& text) {
    std::istringstream ss(text);
    std::string head;
    if (!std::getline(ss, head)) return false;
    if (head.rfind("ETS2AI,v1", 0) != 0) return false;
    std::vector<std::string> parts;
    std::string cur;
    for (char c : head) {
      if (c == ',') { parts.push_back(cur); cur.clear(); }
      else cur += c;
    }
    parts.push_back(cur);
    if (parts.size() < 5) return false;
    nin = atoi(parts[2].c_str()); nout = atoi(parts[3].c_str());
    for (size_t i = 4; i < parts.size(); ++i)
      hidden.push_back(atoi(parts[i].c_str()));
    int fan_in = nin;
    for (size_t L = 0; L < hidden.size() + 1; ++L) {
      int fan_out = (L < hidden.size()) ? hidden[L] : nout;
      std::vector<float> w((size_t)fan_in * fan_out);
      for (int i = 0; i < fan_in; ++i) {
        std::string ln;
        if (!std::getline(ss, ln)) return false;
        int j = 0; size_t pos = 0;
        while (j < fan_out && pos < ln.size()) {
          size_t c = ln.find(',', pos);
          std::string tok = ln.substr(pos, c == std::string::npos
                                        ? std::string::npos : c - pos);
          if (!tok.empty()) w[(size_t)i * fan_out + j++] =
            (float)atof(tok.c_str());
          if (c == std::string::npos) break;
          pos = c + 1;
        }
        if (j != fan_out) return false;
      }
      std::vector<float> b((size_t)fan_out);
      std::string ln;
      if (!std::getline(ss, ln)) return false;
      int j = 0; size_t pos = 0;
      while (j < fan_out && pos < ln.size()) {
        size_t c = ln.find(',', pos);
        std::string tok = ln.substr(pos, c == std::string::npos
                                      ? std::string::npos : c - pos);
        if (!tok.empty()) b[j++] = (float)atof(tok.c_str());
        if (c == std::string::npos) break;
        pos = c + 1;
      }
      if (j != fan_out) return false;
      W.push_back(std::move(w)); B.push_back(std::move(b));
      fan_in = fan_out;
    }
    loaded = true;
    return true;
  }
  // tanh ocultas, saida linear -> [steer, throttle, brake]
  void forward(const float x[13], float out[3]) const {
    std::vector<float> a(x, x + nin), t;
    for (size_t L = 0; L < W.size(); ++L) {
      int fo = (int)B[L].size();
      t.assign((size_t)fo, 0.0f);
      for (size_t i = 0; i < a.size(); ++i)
        for (int j = 0; j < fo; ++j)
          t[(size_t)j] += a[i] * W[L][(size_t)i * fo + j];
      for (int j = 0; j < fo; ++j) {
        t[(size_t)j] += B[L][(size_t)j];
        if (L + 1 < W.size())
          t[(size_t)j] = tanhf(t[(size_t)j]);
      }
      a = t;
    }
    out[0] = a[0]; out[1] = a[1]; out[2] = a[2];
  }
};
static Net g_official, g_nano;
static void load_nets() {
  ResData rd;
  if (load_res_id(102, &rd))
    g_official.load(std::string((const char*)rd.ptr, rd.size));
  else {
    std::ifstream f(exe_dir() + L"\\model-weights.txt");
    if (f) { std::stringstream ss; ss << f.rdbuf();
             g_official.load(ss.str()); }
  }
  if (load_res_id(103, &rd))
    g_nano.load(std::string((const char*)rd.ptr, rd.size));
}
static double bench(const Net& n, double seconds) {
  if (!n.loaded) return 0;
  float x[13] = { 0 }, y[3];
  auto t0 = std::chrono::steady_clock::now();
  long long it = 0;
  for (;;) {
    for (int i = 0; i < 500; ++i) { x[0] = (float)(i % 25) / 25; n.forward(x, y); }
    it += 500;
    double el = std::chrono::duration<double>(
      std::chrono::steady_clock::now() - t0).count();
    if (el >= seconds) return it / el;
  }
}

// =======================================================================
// injetor de teclas (SendInput REAL — winuser.h, sem structs manuais)
// =======================================================================
static bool send_key(unsigned scan, bool up) {
  INPUT inp; ZeroMemory(&inp, sizeof inp);
  inp.type = INPUT_KEYBOARD;
  inp.ki.wScan = (WORD)scan;
  inp.ki.dwFlags = KEYEVENTF_SCANCODE | (up ? KEYEVENTF_KEYUP : 0) |
                   (is_ext(scan) ? KEYEVENTF_EXTENDEDKEY : 0);
  return SendInput(1, &inp, sizeof inp) == 1;
}
struct Injector {
  bool enabled = false;
  std::wstring window_sub = L"Euro Truck";
  int phase = 0;
  bool kill = false, gate = false;
  bool down[4] = { false, false, false, false };  // L R A B
  double tap_hold = 0.08, tap_gap = 0.05, menu_gap = 0.30;

  bool gate_ok(bool announce) {
    if (!enabled) return false;
    HWND fg = GetForegroundWindow();
    if (!fg) return false;
    wchar_t buf[512];
    GetWindowTextW(fg, buf, 512);
    std::wstring t = buf;
    std::wstring sub = window_sub;
    auto lower = [](std::wstring s) {
      for (auto& c : s) c = towlower(c); return s; };
    if (lower(t).find(lower(sub)) == std::wstring::npos) return false;
    RECT wr; MONITORINFO mi{ sizeof mi };
    if (!GetWindowRect(fg, &wr)) return false;
    HMONITOR mon = MonitorFromWindow(fg, MONITOR_DEFAULTTONEAREST);
    if (!mon || !GetMonitorInfoW(mon, &mi)) return false;
    bool ok = wr.left <= mi.rcMonitor.left && wr.top <= mi.rcMonitor.top &&
              wr.right >= mi.rcMonitor.right &&
              wr.bottom >= mi.rcMonitor.bottom;
    if (announce && ok != gate) {
      gate = ok;
      logf("[inject] %s", ok
        ? "jogo em TELA CHEIA — IA assumindo o volante"
        : "fora da TELA CHEIA — teclas soltas; a IA so age com o jogo "
          "em tela cheia (e em 1o plano)");
    }
    return ok;
  }
  void tap(unsigned scan, const char* name) {
    if (!enabled) return;
    if (!gate_ok(false)) {
      logf("[inject] macro '%s' ignorada — jogo nao esta em TELA CHEIA",
           name ? name : "?");
      return;
    }
    send_key(scan, false);
    Sleep((int)(tap_hold * 1000));
    send_key(scan, true);
    Sleep((int)(tap_gap * 1000));
    if (name && *name) logf("[macro] %s", name);
  }
  void release_all() {
    for (int i = 0; i < 4; ++i)
      if (down[i]) {
        send_key(i == 0 ? SC_LEFT : i == 1 ? SC_RIGHT
                : i == 2 ? SC_ACCEL : SC_BRAKE, true);
        down[i] = false;
      }
  }
  // PWM bang-bang: pedais por limiar, volante proporcional
  void update(double steer, double throttle, double brake) {
    if (!enabled) return;
    if (GetAsyncKeyState(VK_ESCAPE) & 0x8000) {
      if (!kill) logf("[inject] ESC — kill switch: parando de injetar");
      kill = true;
    }
    if (kill) { release_all(); return; }
    bool want[4] = { false, false, false, false };
    if (throttle > 0.30) want[2] = true;
    if (brake > 0.30) want[3] = true;
    int side = -1; double duty = 0;
    if (steer < -STEER_DEADBAND) { side = 0; duty = std::min(1.0, -steer); }
    else if (steer > STEER_DEADBAND) { side = 1; duty = std::min(1.0, steer); }
    if (side >= 0 && (phase % PWM_PHASES) < (int)(duty * PWM_PHASES + 0.5))
      want[side] = true;
    phase = (phase + 1) % PWM_PHASES;
    if (!gate_ok(true)) { want[0] = want[1] = want[2] = want[3] = false; }
    static const unsigned sc[4] = { SC_LEFT, SC_RIGHT, SC_ACCEL, SC_BRAKE };
    for (int i = 0; i < 4; ++i) {
      if (down[i] && !want[i]) { send_key(sc[i], true); down[i] = false; }
      else if (!down[i] && want[i]) { send_key(sc[i], false); down[i] = true; }
    }
  }
};

// =======================================================================
// loop de direcao (modo drive)
// =======================================================================
static int run_drive(bool inject, const std::wstring& window_sub,
                     const std::wstring& game_dir_hint) {
  Injector inj;
  inj.enabled = inject;
  inj.window_sub = window_sub.empty() ? L"Euro Truck" : window_sub;
  load_bank(); load_nets();
  if (!g_official.loaded) {
    logf("[ia] pesos oficiais ausentes — nao posso dirigir");
    return 2;
  }
  logf("[pratica] IA 100%% no exe (C++, %.0f inf/s) — sem celular, "
       "sem APK, sem rede", bench(g_official, 0.2));
  logf("[inject] alvo: janela com '%ls' no titulo | ESC = kill switch",
       inj.window_sub.c_str());
  // espera o jogo abrir (ate 15 min) — COMEÇAR pode vir ANTES do jogo
  Mmf mmf;
  auto deadline = std::chrono::steady_clock::now() +
                  std::chrono::minutes(15);
  bool announced = false;
  while (!mmf.open(false)) {
    if (std::chrono::steady_clock::now() > deadline) {
      logf("[pratica] desisti de esperar o jogo (15 min)");
      return 3;
    }
    if (!announced) {
      announced = true;
      logf("[pratica] esperando o jogo abrir (Local\\SCSTelemetry) — "
           "a IA comeca sozinha");
    }
    Sleep(1000);
  }
  logf("[pratica] telemetria CONECTADA — IA no volante");
  // descobre o jogo em background so para instalar a DLL (best-effort)
  if (game_dir_hint.empty()) {
    std::thread([&] {
      Discovery d = discover_game(L"");
      if (!d.dir.empty()) {
        logf("[dll] jogo em %ls (%s) — garantindo plugin",
             d.dir.c_str(), d.how.c_str());
        install_dll(d.dir);
      }
    }).detach();
  } else {
    install_dll(game_dir_hint);
  }
  double last_macro = -1e9, cold_t0 = -1e9;
  bool parked_at_dest = false;
  auto t_start = std::chrono::steady_clock::now();
  long long ticks = 0;
  for (;;) {
    Snap s = parse((const unsigned char*)mmf.view);
    double now = std::chrono::duration<double>(
      std::chrono::steady_clock::now() - t_start).count();
    if (!s.sdk) { Sleep(500); continue; }
    ++ticks;
    // jogo fechou? (processo sumiu)
    if (ticks % 30 == 0 && find_by_process().empty() && ticks > 30) {
      logf("[pratica] processo do jogo encerrou — fim da sessao");
      inj.release_all();
      break;
    }
    if (s.paused) { inj.release_all(); Sleep(200); continue; }
    // features do contrato (sem mapa de pista: lane/heading/curvs = 0,
    // como o practice.py quando nao consegue se localizar)
    float feat[13];
    double speed = s.speed < 0 ? 0 : s.speed;
    double limit = s.slimit;
    if (limit < 0.5) limit = 25.0;
    limit = std::min(limit, 25.0);
    double fuel = s.fuel_cap > 1.0
      ? std::min(1.0, std::max(0.0, (double)s.fuel / s.fuel_cap))
      : 1.0;
    double route_km = s.route > 0 ? s.route / 1000.0 : 0.0;
    feat[0] = (float)(std::min(speed, 50.0) / 25.0);
    feat[1] = 0; feat[2] = 0;
    feat[3] = feat[4] = feat[5] = feat[6] = feat[7] = 0;
    feat[8] = (float)(limit / 25.0);
    feat[9] = (float)fuel;
    feat[10] = (float)std::min(1.0, s.tamin / 660.0);
    feat[11] = (float)(std::min(route_km, 20.0) / 20.0);
    feat[12] = 1.0f;
    float cmd[3];
    g_official.forward(feat, cmd);
    double steer = cmd[0], throttle = cmd[1], brake = cmd[2];
    // mapa vazio: moderado ate se situar (11 m/s ~ 40 km/h)
    limit = std::min(limit, 11.0);
    // governador: teto da via + aproximacao do destino
    if (speed > limit + 2.0) { throttle = 0; brake = 0.85; }
    if (s.route > 0 && s.route < 8.0) { throttle = 0; brake = 1.0; }
    // destino alcancado: freio de mao
    if (s.route > 0 && s.route <= 1.5 && speed < 0.5 && !parked_at_dest) {
      parked_at_dest = true;
      inj.tap(SC_PARK, ". (freio de estacionamento)");
    }
    // tomada imediata: caminhao parado -> liga o motor, solta o freio de mao
    if (speed < 0.5) {
      if (cold_t0 < -1e8) {
        cold_t0 = now;
        logf("[pratica] caminhao parado: IA ligando o motor e soltando o "
             "freio de mao sozinha (tomada imediata)");
      }
      if (now - cold_t0 >= 0.8 && now - last_macro >= 2.5) {
        last_macro = now;
        if (!s.engine || now - cold_t0 > 6.0)
          inj.tap(SC_ENGINE, "E (ligar motor)");
        if (s.park) inj.tap(SC_PARK, ". (freio de mao)");
      }
    } else {
      cold_t0 = -1e9;
    }
    if (s.park && speed < 0.5) inj.release_all();
    else inj.update(steer, throttle, brake);
    if (ticks % 600 == 0)
      logf("[pratica] %lld ticks | %.1f m/s | cmd %.2f/%.2f/%.2f | %s",
           ticks, speed, steer, throttle, brake,
           inj.gate ? "TELA CHEIA (dirigindo)" : "esperando tela cheia");
    if (inj.kill) break;
    Sleep(33);   // ~30 Hz
  }
  inj.release_all();
  logf("[pratica] sessao encerrada (%lld ticks)", ticks);
  return 0;
}

// =======================================================================
// autoteste (mesmo contrato JSON do exe python)
// =======================================================================
struct Step { std::string name, status, detail; };
static std::string g_autoteste_json;
static int run_autoteste(const std::wstring& hint, std::wstring saida) {
  load_bank(); load_nets();
  std::vector<Step> steps;
  auto step = [&](const char* name, int ok, const std::string& detail) {
    Step st{ name, ok < 0 ? "SKIP" : ok ? "PASS" : "FAIL", detail };
    steps.push_back(st);
    logf("[autoteste] %s: %s%s%s", st.status.c_str(), name,
         detail.empty() ? "" : " — ", detail.substr(0, 200).c_str());
  };
  // 1) banco
  char bd[64];
  snprintf(bd, sizeof bd, "%d DLLs embutidas", (int)g_bank.size());
  step("banco de DLLs embutidas", !g_bank.empty(), bd);
  std::string tags;
  for (auto& d : g_bank) {
    std::string t = d.repo + " " + d.tag;
    if (tags.find(t) == std::string::npos)
      tags += (tags.empty() ? "" : ", ") + t;
  }
  // 2) descoberta
  Discovery d = discover_game(hint);
  step("descoberta do jogo", !d.dir.empty(),
       d.dir.empty() ? "jogo nao achado (varredura completa ja rodou?)"
                     : wide2utf8(d.dir) + " (" + d.how + ")");
  InstallInfo inst;
  if (!d.dir.empty()) {
    inst = install_dll(d.dir);
    step("analise + instalacao da DLL ideal", inst.ok,
         inst.ok ? inst.repo + " " + inst.tag + " (" + inst.arch + ") p/ ETS2 "
                   + inst.version
                 : "instalacao falhou (permissao de administrador?)");
    step("verificacao da DLL (tamanho + reparo)", inst.ok,
         inst.ok ? "ok (reparada se necessario)" : "falhou");
  } else {
    step("analise + instalacao da DLL ideal", -1, "sem jogo");
  }
  // 3) telemetria REAL (jogo falso na memoria compartilhada)
  std::string tel = "SKIP";
  Mmf mmf;
  if (mmf.open(false)) {
    Snap s = parse((const unsigned char*)mmf.view);
    bool ok = s.sdk && s.game_id == 1;
    tel = ok ? "PASS" : "FAIL";
    char det[160];
    snprintf(det, sizeof det, "speed=%.1f fuel=%.1f steer=%.2f jogo=%s",
             s.speed, s.fuel, s.usteer, s.game_id == 1 ? "ets2" : "?");
    step("telemetria REAL (do JOGO ABERTO)", ok, det);
  } else if (start_fake_game(&mmf)) {
    Snap s = parse((const unsigned char*)mmf.view);
    bool ok = s.sdk && fabs(s.speed - 17.5) < 1e-3 &&
              fabs(s.fuel - 380.5) < 1e-3 && fabs(s.usteer - 0.25) < 1e-3 &&
              s.on_job && s.game_id == 1;
    tel = ok ? "PASS" : "FAIL";
    char det[160];
    snprintf(det, sizeof det, "speed=%.1f fuel=%.1f steer=%.2f jogo=%s",
             s.speed, s.fuel, s.usteer, s.game_id == 1 ? "ets2" : "?");
    step("telemetria REAL (memoria do jogo falso)", ok, det);
  } else {
    tel = "FAIL";
    step("telemetria REAL (memoria do jogo falso)", false,
         "nao consegui criar a memoria compartilhada");
  }
  // 4) politica + bench
  double oinf = bench(g_official, 0.3);
  char bf[64];
  snprintf(bf, sizeof bf, "%.0f inf/s", oinf);
  step("politica oficial (bench)", g_official.loaded && oinf >= 50,
       g_official.loaded ? bf : "pesos ausentes no exe");
  double ninf = bench(g_nano, 0.2);
  if (g_nano.loaded) {
    snprintf(bf, sizeof bf, "%.0f inf/s", ninf);
    step("politica destilada nano (bench)", ninf >= 2000, bf);
  }
  bool pass = true;
  std::string js = "{\n  \"so\": \"win32\", \"linguagem\": \"C++\", \"versao\": \"";
  js += wide2utf8(APP_VERSION);
  js += "\", \"exe_empacotado\": true,\n  \"banco_dlls\": ";
  js += std::to_string((int)g_bank.size());
  js += ", \"banco_tags\": \"";
  js += json_escape(tags);
  js += "\",\n  \"game_dir\": ";
  js += d.dir.empty() ? "null" : "\"" + json_escape(wide2utf8(d.dir)) + "\"";
  if (inst.ok) {
    js += ", \"dll_repo\": \"" + json_escape(inst.repo) + "\"";
    js += ", \"dll_tag\": \"" + json_escape(inst.tag) + "\"";
    js += ", \"dll_arch\": \"" + json_escape(inst.arch) + "\"";
    js += ", \"dll\": \"" + json_escape(inst.dll_path) + "\"";
    js += ", \"jogo_versao\": \"" + json_escape(inst.version) + "\"";
    js += ", \"dll_instalada\": true";
  } else {
    js += ", \"dll_instalada\": false";
  }
  js += ", \"telemetria\": \"" + tel + "\"";
  js += ", \"oficial_inf_s\": " + std::to_string((int)(oinf * 10) / 10.0);
  if (g_nano.loaded) js += ", \"nano_inf_s\": " +
                            std::to_string((int)(ninf * 10) / 10.0);
  js += ",\n  \"steps\": [";
  for (size_t i = 0; i < steps.size(); ++i) {
    js += "\n    {\"step\": \"" + json_escape(steps[i].name) +
          "\", \"status\": \"" + steps[i].status +
          "\", \"detail\": \"" + json_escape(steps[i].detail) + "\"}";
    if (i + 1 < steps.size()) js += ",";
    if (steps[i].status == "FAIL") pass = false;
  }
  js += "\n  ],\n  \"pass\": ";
  js += pass ? "true" : "false";
  js += "\n}\n";
  if (saida.empty())
    saida = exe_dir() + L"\\autoteste-resultado.json";
  FILE* f = nullptr;
  if (_wfopen_s(&f, saida.c_str(), L"wb") == 0 && f) {
    fwrite(js.data(), 1, js.size(), f);
    fclose(f);
    logf("[autoteste] relatorio: %ls", saida.c_str());
  }
  g_autoteste_json = js;
  logf("[autoteste] RESULTADO: %s (%lld ok / %lld falha)",
       pass ? "PASS" : "FAIL",
       (long long)std::count_if(steps.begin(), steps.end(),
                                 [](const Step& s) { return s.status == "PASS"; }),
       (long long)std::count_if(steps.begin(), steps.end(),
                                 [](const Step& s) { return s.status == "FAIL"; }));
  return pass ? 0 : 1;
}

// =======================================================================
// GUI minima Win32: BUSCAR / AUTOTESTE / VERIFICAR DLL / COMEÇAR / PARAR
// =======================================================================
static std::atomic<bool> g_busy{ false }, g_cancel{ false };
static HWND g_edit = nullptr, g_status = nullptr;
static void gui_log(const std::string& s) {
  if (!g_edit) { log_line(s); return; }
  std::wstring w = utf82wide(s + "\r\n");
  SendMessageW(g_edit, EM_SETSEL, (WPARAM)-1, (LPARAM)-1);
  SendMessageW(g_edit, EM_REPLACESEL, FALSE, (LPARAM)w.c_str());
  log_line(s);
}
static void gui_status(const wchar_t* s) {
  if (g_status) SetWindowTextW(g_status, s);
}
static void do_search() {
  if (g_busy.exchange(true)) return;   // ja ocupado: ignora
  gui_status(L"PROCURANDO o jogo no disco...");
  std::thread([] {
    Discovery d = discover_game(L"", &g_cancel);
    if (!d.dir.empty()) {
      gui_log("[busca] jogo: " + wide2utf8(d.dir) + " (" + d.how + ")");
      InstallInfo i = install_dll(d.dir);
      if (i.ok)
        gui_log("[dll] " + i.repo + " " + i.tag + " (" + i.arch +
                ") instalada p/ ETS2 " + i.version);
      gui_status(L"Jogo encontrado");
    } else {
      gui_log("[busca] jogo nao achado — abra o jogo e toque BUSCAR de novo");
      gui_status(L"Jogo nao encontrado");
    }
    g_busy = false;
  }).detach();
}
static void do_autoteste_gui() {
  if (g_busy.exchange(true)) return;   // ja ocupado: ignora
  gui_status(L"Rodando AUTOTESTE...");
  std::thread([] {
    run_autoteste(L"", L"");
    gui_status(L"Autoteste concluido (veja o log)");
    g_busy = false;
  }).detach();
}
static void do_drive() {
  if (g_busy.exchange(true)) return;   // ja ocupado: ignora
  gui_status(L"Dirigindo — ESC no jogo para parar");
  std::thread([] {
    run_drive(true, L"Euro Truck", L"");
    gui_status(L"Sessao encerrada");
    g_busy = false;
  }).detach();
}
static LRESULT CALLBACK wndproc(HWND h, UINT m, WPARAM w, LPARAM l) {
  switch (m) {
    case WM_CREATE: {
      CreateWindowW(L"BUTTON", L"BUSCAR jogo", WS_CHILD | WS_VISIBLE |
        BS_PUSHBUTTON, 16, 12, 170, 34, h, (HMENU)1, nullptr, nullptr);
      CreateWindowW(L"BUTTON", L"AUTOTESTE", WS_CHILD | WS_VISIBLE |
        BS_PUSHBUTTON, 194, 12, 170, 34, h, (HMENU)2, nullptr, nullptr);
      CreateWindowW(L"BUTTON", L"VERIFICAR DLL", WS_CHILD | WS_VISIBLE |
        BS_PUSHBUTTON, 372, 12, 170, 34, h, (HMENU)3, nullptr, nullptr);
      CreateWindowW(L"BUTTON",
        L"COMEÇAR (IA no PC — nao precisa de celular)",
        WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON, 16, 54, 526, 44, h,
        (HMENU)4, nullptr, nullptr);
      CreateWindowW(L"BUTTON", L"PARAR busca", WS_CHILD | WS_VISIBLE |
        BS_PUSHBUTTON, 550, 12, 120, 34, h, (HMENU)5, nullptr, nullptr);
      g_edit = CreateWindowW(L"EDIT", L"", WS_CHILD | WS_VISIBLE |
        WS_VSCROLL | ES_MULTILINE | ES_READONLY | ES_AUTOVSCROLL,
        16, 106, 654, 380, h, (HMENU)10, nullptr, nullptr);
      SendMessageW(g_edit, WM_SETFONT,
        (WPARAM)GetStockObject(SYSTEM_FIXED_FONT), TRUE);
      g_status = CreateWindowW(L"STATIC",
        L"ETS2-AI C++ — IA 100% neste exe (sem celular/APK)",
        WS_CHILD | WS_VISIBLE, 16, 494, 654, 22, h, (HMENU)11, nullptr,
        nullptr);
      gui_log("ETS2-AI v" + wide2utf8(APP_VERSION) +
              " (C++ puro) — log salvo em ets2-ai-log.txt ao lado do exe");
      gui_log("Fluxo: BUSCAR (acha o jogo e instala a telemetria) -> "
              "abra o ETS2 em TELA CHEIA -> COMEÇAR. ESC = kill switch.");
      return 0;
    }
    case WM_COMMAND: {
      int id = LOWORD(w);
      if (id == 1) do_search();
      else if (id == 2) do_autoteste_gui();
      else if (id == 3) do_search();  // verificar = re-descobrir + reparar
      else if (id == 4) do_drive();
      else if (id == 5) g_cancel = true;
      return 0;
    }
    case WM_DESTROY: PostQuitMessage(0); return 0;
  }
  return DefWindowProcW(h, m, w, l);
}
static int run_gui() {
  WNDCLASSW wc{};
  wc.lpfnWndProc = wndproc;
  wc.hInstance = GetModuleHandleW(nullptr);
  wc.hCursor = LoadCursor(nullptr, IDC_ARROW);
  wc.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
  wc.lpszClassName = L"ETS2AI";
  RegisterClassW(&wc);
  HWND h = CreateWindowW(wc.lpszClassName,
    L"ETS2-AI — a IA roda 100% neste exe (C++)",
    WS_OVERLAPPEDWINDOW & ~WS_MAXIMIZEBOX & ~WS_THICKFRAME,
    CW_USEDEFAULT, CW_USEDEFAULT, 700, 570, nullptr, nullptr,
    wc.hInstance, nullptr);
  ShowWindow(h, SW_SHOW);
  MSG msg;
  while (GetMessageW(&msg, nullptr, 0, 0) > 0) {
    TranslateMessage(&msg);
    DispatchMessageW(&msg);
  }
  return 0;
}

// =======================================================================
// main
// =======================================================================
int main() {
  static char argv0[MAX_PATH * 2];
  GetModuleFileNameA(nullptr, argv0, sizeof argv0);
  int argc = 0;
  LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);
  std::wstring game_dir, saida, window = L"Euro Truck";
  bool autoteste = false, drive = false, inject = false, benchm = false,
    infom = false;
  for (int i = 1; i < argc; ++i) {
    std::wstring a = argv[i];
    auto next = [&]() -> std::wstring {
      return (i + 1 < argc) ? argv[++i] : L"";
    };
    if (a == L"--autoteste") autoteste = true;
    else if (a == L"--bench") benchm = true;
    else if (a == L"--info") infom = true;
    else if (a == L"--ets2") { std::wstring m = next(); drive = m == L"drive"; }
    else if (a == L"--inject") inject = true;
    else if (a == L"--game-dir") game_dir = next();
    else if (a == L"--saida") saida = next();
    else if (a == L"--window") window = next();
  }
  LocalFree(argv);
  if (autoteste) return run_autoteste(game_dir, saida);
  if (drive) return run_drive(inject, window, game_dir);
  if (infom) {
    load_bank(); load_nets();
    EnumResourceNamesW(nullptr, RT_RCDATA, info_cb, 0);
    logf("[info] RCDATA total: %d | banco parseado: %d DLLs | pesos: %s",
         g_res_total, (int)g_bank.size(),
         g_official.loaded ? "OK" : "AUSENTES");
    for (size_t i = 0; i < g_bank.size() && i < 4; ++i)
      logf("[info] banco[%d] = %s %s (%s)", (int)i,
           g_bank[i].repo.c_str(), g_bank[i].tag.c_str(),
           g_bank[i].arch.c_str());
    if (g_official.loaded)
      logf("[info] rede: %d-%d ocultas, %d saidas",
           g_official.nin, (int)g_official.hidden.size(),
           g_official.nout);
    return 0;
  }
  if (benchm) {
    load_bank(); load_nets();
    if (!g_official.loaded || g_bank.empty()) {
      logf("[bench] FALHOU: pesos=%d banco=%d (recurso nao embutido?)",
           (int)g_official.loaded, (int)g_bank.size());
      return 2;
    }
    logf("oficial: %.0f inf/s | nano: %.0f inf/s | banco: %d DLLs",
         bench(g_official, 0.3), bench(g_nano, 0.2), (int)g_bank.size());
    return 0;
  }
  return run_gui();
}
