# Referências usadas para modelar o ARB RB20

Todas as imagens e modelos abaixo foram usados **apenas como referência visual /
dimensional**. Nenhuma malha, textura, logo ou arquivo de terceiros foi copiado
para dentro do mod: a geometria é 100% paramétrica e original
(`tools/mesh_core.py`), e as texturas são geradas por código (`tools/textures.py`).

## 1. Imagens de referência (visualizadas, não redistribuídas)

| O que | URL | Uso |
|---|---|---|
| Fotos de lançamento / 3-4 e vista superior do RB20 | https://www.topgear.com/car-news/formula-one/2024-f1-cars-revealed | formato do nariz, sidepod com entrada alta, asa dianteira, t-cam |
| Galeria Red Bull RB20 2024 (vista superior / traseira) | https://www.topgear.com.ph/news/racing-news/2024-f1-cars-red-bull-rb20-a2620-20240218 | largura do assoalho, coke-bottle, asa traseira, airbox |
| Perfil lateral em pista | https://www.planetf1.com/news/red-bull-rb20-f1-2024-car-clues | proporção nariz/cockpit/engine cover, altura do halo |
| Silhueta lateral "RB20 2024" (modelo 3D para impressão) | https://www.crealitycloud.com/model-detail/664cbf79896c7d2726ae3986 | silhueta lateral e posição das rodas |
| Ilustração técnica / blueprint | https://www.etsy.com/es/listing/1677672024/rb20-red-bull-technical-drawing | linhas gerais de fluxo, elementos de asa |

As miniaturas baixadas para inspeção ficam em `image-search/` (fora do ZIP do
mod). Não há redistribuição de fotografia protegida dentro do mod.

## 2. Modelos 3D de referência

| Modelo | URL | Uso |
|---|---|---|
| **Red Bull RB6 (2010) — cena Maya + 5 vistas ortográficas** | https://github.com/pronaypeddiraju/F1_Car | referência de workflow de modelagem por image planes e proporções gerais de F1 (geração anterior). Nenhum `.mb`/`.ma` foi copiado. |
| **RB20 2024 side silhouette (STL/3D print)** | https://www.crealitycloud.com/model-detail/664cbf79896c7d2726ae3986 | comprimento relativo, posicionamento dos eixos, perfil do difusor |
| **Formula K (Kunos AC SDK)** | https://github.com/javirs200/acCar/tree/master/EXAMPLE/formula_k | referência de *formato* de arquivos vanilla (`car.ini`, `tyres.ini`, `aero.ini`, LUTs, `collider.kn5`). Valores **não** copiados: todos foram recalibrados por telemetria. Licença GPL-3.0 no repositório de origem. |
| **fbx-to-kn5-tool** | https://github.com/gitgc/fbx-to-kn5-tool | documentação pública do formato binário KN5 v5/v6 e do `data.acd` (usada para escrever um *writer* próprio em `tools/kn5format.py`). |

## 3. Dados dimensionais e técnicos publicados

| Grandeza | Valor adotado | Fonte |
|---|---|---|
| Massa mínima 2024 (com piloto, sem combustível) | 798 kg | https://en.wikipedia.org/wiki/Red_Bull_Racing_RB20 |
| Potência divulgada | 1.021 hp / ~750 kW (ICE + MGU-K, pico) | idem |
| Limite de rotação | 15.000 rpm | idem |
| Pneus | 305/720-18 dianteiro, 405/720-18 traseiro | https://f1mavericks.com/redbull-racing-team-rb20-2024/ |
| Largura máxima / entre-eixos (regulamento 2024) | 2,00 m / ~3,60 m | regulamento FIA 2024 + silhuetas acima |
| Altura do CG adotada | 0,30 m | estimativa a partir do perfil lateral |
| 8 marchas, tração traseira, sem ABS/TC | — | regulamento 2024 |
| `INERTIA = largura, altura, comprimento` | 2,00 / 0,95 / 5,60 | convenção Kunos confirmada nos `car.ini` do AC SDK |

> Nota: a potência **efetiva** ajustada pela telemetria (~483 kW sustentados na
> volta) é menor que o pico divulgado de ~750 kW. Limite de fluxo de combustível,
> estado de carga do ERS e o próprio filtro dos dados de timing explicam a
> diferença. Optou-se por reproduzir a telemetria real, não o número de
> marketing — e a velocidade final simulada (322,6 km/h) coincide com os
> 322 km/h registrados no Bahrein.

## 4. O que NÃO foi usado

- Nenhum `.kn5`, `.fbx`, `.blend`, livery, banco FMOD ou `data.acd` de mods de
  terceiros (incluindo os mods de RB20 listados em assettoworld/modland).
- Nenhuma extensão CSP, shader patch, Sol, Lua, `ext_config.ini`.
- Nenhum logotipo de equipe ou patrocinador.
