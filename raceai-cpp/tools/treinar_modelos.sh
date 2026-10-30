#!/usr/bin/env bash
# Treina os modelos pré-definidos que vão dentro do ZIP (pasta modelos/).
#
# Uso:
#   ./tools/treinar_modelos.sh            # só o modelo de demonstração (padrão)
#   ./tools/treinar_modelos.sh 12         # treina os 12 primeiros (leva ~10 min)
#
# Cada linha abaixo é: pista|carro|neurônios da 1a camada|gerações|segundos|semente
# As redes têm tamanhos diferentes de propósito: assim fica provado que o jogo
# aceita qualquer topologia, e não só um tamanho fixo.
set -e
cd "$(dirname "$0")/.."

LIMITE=${1:-1}   # por padrão só o 1o: é o modelo de demonstração
mkdir -p modelos

TREINOS=(
  "short_oval|kart|32|40|30|3"
  "oval_iniciante|sedan|64|60|45|7"
  "oval_iniciante|kart|48|60|45|9"
  "terra_dirt|buggy|40|60|40|23"
  "speedway|formula|64|100|45|5"
  "neve_gelo|rally|48|90|45|17"
  "dirt_oval|muscle|48|80|40|37"
  "praia_circuito|prototipo|72|80|45|41"
  "grande_premio|super_gt|64|90|45|11"
  "cidade|eletrico|56|110|45|29"
  "kartodromo|kart|48|160|60|21"
  "misto_tecnico|gt|64|120|45|31"
)

# no Windows o executável ganha .exe
BIN=./build/raceai_train
[ -x "$BIN.exe" ] && BIN="$BIN.exe"

n=0
for linha in "${TREINOS[@]}"; do
  n=$((n+1))
  [ "$n" -gt "$LIMITE" ] && break
  IFS='|' read -r pista carro hidden gens secs seed <<< "$linha"
  saida="modelos/demo_${pista}_${carro}.json"
  printf '\n=== [%d/%d] %s com %s (%d neurônios) ===\n' \
         "$n" "${#TREINOS[@]}" "$pista" "$carro" "$hidden"
  "$BIN" --track "$pista" --car "$carro" --hidden "$hidden" \
      -g "$gens" -p 60 --seconds "$secs" --seed "$seed" --out "$saida" --quiet
done

echo
echo "modelos prontos:"
ls -la modelos/
