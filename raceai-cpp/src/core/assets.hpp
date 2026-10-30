// assets.hpp — descoberta e carregamento de pistas/carros (inclui mods).
//
// Procura em <raiz>/assets/tracks, <raiz>/assets/cars e nas pastas de mods do
// usuário (<raiz>/mods/tracks, <raiz>/mods/cars). `raiz` é o diretório do
// executável ou o diretório atual (o que existir).
#pragma once

#include <string>
#include <vector>

#include "car.hpp"
#include "track.hpp"

namespace raceai {

struct AssetItem {
    std::string id;      // nome do arquivo sem extensão
    std::string name;    // nome exibido (vem do JSON)
    std::string path;
    std::string detail;  // resumo (dificuldade / potência)
    std::string error;   // vazio se carregou
};

// Diretório base (assets/) — tenta algumas localizações conhecidas.
std::string assets_root();

// Pasta de dados usada pelo executável quando ele extrai o conteúdo embutido
// (um .exe só). Vazia = usa a pasta atual, como antes.
void definir_raiz_dados(const std::string& dir);
std::string raiz_dados();

std::vector<AssetItem> list_tracks();
std::vector<AssetItem> list_cars();

bool load_track(const std::string& id_or_path, Track& out, std::string* err = nullptr);
bool load_car(const std::string& id_or_path, CarSpec& out, std::string* err = nullptr);

// Diretórios de mods (o usuário pode largar JSONs lá).
std::string mods_tracks_dir();
// modelos .json já treinados na pasta modelos/ (a corrida usa como adversários)
std::vector<std::string> list_models();
std::string mods_cars_dir();

}  // namespace raceai
