"""Critérios de desempenho desta entrega, lidos da medição real do emulador.

Este script NÃO gera números: ele lê `evidence/performance.json`, que é escrito
pelo harness a partir dos contadores nativos (`GGUF_GENERATION_STATS`) e do
relógio da thread principal (`GGUF_UI_FIRST_TEXT`). A taxa é sempre
tokens nativos / tempo nativo de decodificação. Se a medição não existir, o
critério é declarado não avaliado — nunca aprovado por ausência de dado.

Metas pedidas: +50% de T/s (ganho medido >= 1,5x) e espera até o primeiro token
reduzida a um terço (>= 3x mais rápido). A leitura literal de "−300%" é
impossível (um tempo negativo), por isso o critério aplicado é 1/3 do tempo; os
dois números ficam registrados no mesmo arquivo de evidência.
"""
import json
import sys
from pathlib import Path

TARGETS = {'throughput_1_5x': 'ganho de 1,5x em tokens/s',
           'first_token_3x': 'primeiro token/texto 3x mais rápido'}


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else 'evidence/performance.json')
    if not path.is_file():
        raise SystemExit(f'Sem medição de desempenho: {path} não existe')
    report = json.loads(path.read_text())
    candidates = report.get('candidates') or {}
    if not candidates:
        raise SystemExit('Sem medição comparável: nenhuma etapa produziu contadores nativos')
    print(json.dumps({'baseline': report.get('baseline'), 'candidates': candidates,
                      'targets_met': report.get('targets_met')}, ensure_ascii=False, indent=2))
    met = report.get('targets_met') or []
    if met:
        print('Metas atingidas em: ' + ', '.join(met))
        return
    for name, candidate in sorted(candidates.items()):
        missing = [TARGETS[key] for key, ok in (candidate.get('targets') or {}).items() if not ok]
        print(f'{name}: falta ' + ', '.join(missing) if missing else name)
    raise SystemExit('Metas de desempenho não atingidas nas etapas medidas')


if __name__ == '__main__':
    main()
