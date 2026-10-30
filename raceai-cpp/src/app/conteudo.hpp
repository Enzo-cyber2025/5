// conteudo.hpp — o jogo em UM arquivo só.
//
// O executável Windows carrega dentro dele (no próprio arquivo, depois do
// código) todas as pistas, carros, modelos e o interpretador Python opcional.
// Na primeira vez ele descompacta tudo para uma pasta de dados e passa a usar
// essa pasta — assim o usuário baixa UM .exe, clica duas vezes e joga, sem
// descompactar zip e sem instalar nada.
//
// Formato do pacote (no fim do próprio .exe):
//   [conteúdo ...][trailer de 24 bytes]
//   conteúdo: "RACEAIPAK" + u32 versão + u32 quantidade +
//             para cada arquivo: u32 tam_nome + nome + u64 tamanho + dados
//   trailer:  "RACEAIPAKEND" + u64 tamanho do conteúdo + u32 flags
//
// Tudo em little-endian. Se não houver pacote, o jogo usa a pasta do .exe
// (modo portátil, como era antes).
#pragma once

#include <string>
#include <vector>

namespace raceai {

// Pasta onde ficam assets/, modelos/ e python/.
// - modo portátil: a própria pasta do .exe (quando já tem assets/ nela);
// - modo instalado: %LOCALAPPDATA%\RaceAI2D (no Windows).
// Fora do Windows devolve vazio (usa a pasta atual).
std::string dir_dados();

// Onde os dados embutidos devem morar (mesma regra acima, mas já cria a pasta).
std::string dir_instalado(bool criar = false);

// Verdadeiro se o .exe tem um pacote embutido.
bool tem_conteudo_embutido();

// Grava as pastas (assets, modelos, python...) dentro de um executável.
// Se ele já tiver um pacote, o antigo é substituído.
bool criar_pacote(const std::string& exe, const std::vector<std::string>& pastas,
                  std::string* erro = nullptr);

// Extrai o pacote de um arquivo para uma pasta (só o que ainda não existe).
// Usado pelo jogo na primeira vez e pelos testes.
bool extrair_pacote(const std::string& arquivo, const std::string& destino,
                    std::string* erro = nullptr);

// Extrai o pacote para a pasta de dados (só o que ainda não existe, para não
// apagar mod do usuário). Devolve a pasta pronta — ou "" se não há pacote.
// O erro (se houver) sai em *erro.
std::string garantir_conteudo(std::string* erro = nullptr);

}  // namespace raceai
