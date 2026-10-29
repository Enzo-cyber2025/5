#include "assets.hpp"

#include <algorithm>

// leitura de diretório: POSIX (Linux/macOS) e Win32
#ifdef _WIN32
#include <windows.h>
#else
#include <dirent.h>
#include <sys/stat.h>
#endif

namespace raceai {

static bool path_exists(const std::string& p) {
#ifdef _WIN32
    DWORD a = GetFileAttributesA(p.c_str());
    return a != INVALID_FILE_ATTRIBUTES;
#else
    struct stat st;
    return ::stat(p.c_str(), &st) == 0;
#endif
}

static std::vector<std::string> list_json(const std::string& dir) {
    std::vector<std::string> out;
    if (dir.empty()) return out;
#ifdef _WIN32
    std::string pattern = dir + "\\*.json";
    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA(pattern.c_str(), &fd);
    if (h == INVALID_HANDLE_VALUE) return out;
    do {
        if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) {
            out.push_back(dir + "\\" + std::string(fd.cFileName));
        }
    } while (FindNextFileA(h, &fd));
    FindClose(h);
#else
    DIR* d = ::opendir(dir.c_str());
    if (!d) return out;
    while (struct dirent* e = ::readdir(d)) {
        std::string name = e->d_name;
        if (name.size() > 5 && name.compare(name.size() - 5, 5, ".json") == 0) {
            out.push_back(dir + "/" + name);
        }
    }
    ::closedir(d);
#endif
    std::sort(out.begin(), out.end());
    return out;
}

static std::string join(const std::string& a, const std::string& b) {
    if (a.empty()) return b;
    if (a.back() == '/' || a.back() == '\\') return a + b;
    return a + "/" + b;
}

std::string assets_root() {
    const char* candidates[] = {"assets", "../assets", "raceai-cpp/assets", "../raceai-cpp/assets"};
    for (const char* c : candidates) {
        if (path_exists(join(c, "tracks")) || path_exists(join(c, "cars"))) return std::string(c);
    }
    return "assets";
}

std::string mods_tracks_dir() { return join(assets_root(), join("mods", "tracks")); }
std::string mods_cars_dir() { return join(assets_root(), join("mods", "cars")); }

static void collect(std::vector<AssetItem>& out, const std::string& dir, bool is_track) {
    for (const std::string& p : list_json(dir)) {
        AssetItem it;
        it.path = p;
        it.id = base_name(p);
        if (is_track) {
            Track t;
            std::string err;
            if (Track::load(p, t, &err)) {
                it.name = t.name;
                char buf[128];
                std::snprintf(buf, sizeof(buf), "%.0f m · %d pontos", t.length, t.n());
                it.detail = buf;
            } else {
                it.name = it.id;
                it.error = err;
            }
        } else {
            CarSpec c;
            std::string err;
            if (CarSpec::load(p, c, &err)) {
                it.name = c.name;
                it.detail = c.summary();
            } else {
                it.name = it.id;
                it.error = err;
            }
        }
        out.push_back(it);
    }
}

std::vector<AssetItem> list_tracks() {
    std::vector<AssetItem> out;
    const std::string root = assets_root();
    collect(out, join(root, "tracks"), true);
    collect(out, mods_tracks_dir(), true);
    return out;
}

std::vector<AssetItem> list_cars() {
    std::vector<AssetItem> out;
    const std::string root = assets_root();
    collect(out, join(root, "cars"), false);
    collect(out, mods_cars_dir(), false);
    return out;
}

static bool by_id_or_path(const std::string& id_or_path, const std::vector<AssetItem>& items,
                          std::string& path) {
    for (const AssetItem& it : items) {
        if (it.id == id_or_path || it.name == id_or_path) { path = it.path; return true; }
    }
    if (path_exists(id_or_path)) { path = id_or_path; return true; }
    return false;
}

bool load_track(const std::string& id_or_path, Track& out, std::string* err) {
    std::string path;
    if (!by_id_or_path(id_or_path, list_tracks(), path)) {
        // tenta como caminho direto (pode estar fora das pastas padrão)
        path = id_or_path;
    }
    return Track::load(path, out, err);
}

bool load_car(const std::string& id_or_path, CarSpec& out, std::string* err) {
    std::string path;
    if (!by_id_or_path(id_or_path, list_cars(), path)) path = id_or_path;
    return CarSpec::load(path, out, err);
}

}  // namespace raceai
