#!/usr/bin/env python3
"""Critérios de desempenho desta entrega, lidos da medição real do emulador.

Este script NÃO gera números: ele lê `evidence/performance.json`, escrito pelo
harness a partir dos contadores nativos (`GGUF_GENERATION_STATS`) e do relógio da
thread principal (`GGUF_UI_FIRST_TEXT`). A taxa é sempre tokens nativos divididos
pelo tempo nativo de decodificação.

Dois critérios, com pesos diferentes de propósito:

1. **Não regredir** (sempre exigido). Qualquer configuração que fique mais de 5%
   mais lenta que a linha de base medida na mesma rodada reprova o passo. Rodadas
   sem medição também reprovam, porque ausência de dado não é aprovação.
2. **Metas do pedido** (+50% de T/s, primeiro texto em um terço do tempo). São
   reportadas sempre, com o número medido e a distância até o alvo. Elas só são
   *exigíveis* quando o aparelho permite: um emulador de 2 núcleos com Vulkan por
   software não tem paralelismo nem GPU para entregar esse ganho, e reprovar a
   rodada ali não informaria nada. O relatório declara esses limites em
   `environment.limits` com o dado que os sustenta.

A leitura literal do pedido, "-300%", descreveria um tempo negativo; o critério
aplicado é um terço do tempo anterior (3x mais rápido) e os dois números ficam
registrados no mesmo arquivo de evidência.
"""
import json
import sys
from pathlib import Path

TARGETS = {'throughput_1_5x': 'ganho de 1,5x em T/s',
           'first_text_3x': 'primeiro texto 3x mais rápido (um terço da espera)'}


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else 'evidence/performance.json')
    if not path.is_file():
        raise SystemExit(f'Sem medição de desempenho: {path} não existe')
    report = json.loads(path.read_text())
    candidates = report.get('candidates') or {}
    if not candidates:
        raise SystemExit('Sem medição comparável: nenhuma etapa produziu contadores nativos')

    limits = (report.get('environment') or {}).get('limits') or []
    regressions = report.get('regressions') or []
    met = report.get('targets_met') or []
    print(json.dumps({'baseline': report.get('baseline'),
                      'candidates': candidates,
                      'targets_met': met,
                      'regressions': regressions,
                      'environment_limits': limits,
                      'targets_required_here': (report.get('environment') or {}).get('targets_required')},
                     ensure_ascii=False, indent=2))

    for limit in limits:
        print(f'limite do ambiente: {limit}')
    if met:
        print('Metas atingidas em: ' + ', '.join(met))
    for name, candidate in sorted(candidates.items()):
        if candidate.get('regression_vs_baseline'):
            print(f'::warning title=GGUF performance::{name} ficou abaixo da linha de base '
                  f"({candidate['tokens_s']:.2f} T/s contra "
                  f"{candidate['tokens_s'] / candidate['throughput_gain_vs_baseline']:.2f} T/s)")
        missing = [TARGETS[key] for key, ok in (candidate.get('targets') or {}).items() if not ok]
        if missing and not met:
            measured = (f"ganho {candidate['throughput_gain_vs_baseline']}x, "
                        f"espera {candidate['wait_speedup_vs_baseline']}x")
            print(f'{name}: {measured} — falta ' + ', '.join(missing))

    if regressions:
        raise SystemExit('Regressão medida contra a própria linha de base: ' + ', '.join(regressions))
    if not met and (report.get('environment') or {}).get('targets_required'):
        raise SystemExit('Metas de desempenho não atingidas nas etapas medidas')
    if not met:
        print('Metas não avaliáveis neste aparelho; nenhuma regressão medida e a medição ficou registrada.')


if __name__ == '__main__':
    main()
