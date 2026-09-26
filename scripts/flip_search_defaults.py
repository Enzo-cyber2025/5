#!/usr/bin/env python3
"""Vira PADRÃO as melhorias que a rodada MEDIU — e só com ganho declarado.

Uso:
    scripts/flip_search_defaults.py --race-gain 1,8 --round 36270000000 [--dry-run]
    scripts/flip_search_defaults.py --race-gain 1,8 --ubatch-gain 1,25 --round ... \
        [--dry-run]

Regra da casa: o padrão do aplicativo não muda por opinião. A corrida de provedores
só vira padrão com ganho medido na MESMA rodada e no MESMO aparelho, e o número da
rodada fica registrado no próprio código (abaixo do comentário) para quem ler depois
saber de onde ele veio. O cache de consulta repetida é ligado pelo mesmo motivo: a
segunda busca igual não deve custar rede.

A propriedade continua existindo: `debug.gguf.search_race 0` e
`debug.gguf.search_cache_ms 0` desligam, para comparar de novo no aparelho.
"""
import argparse
import pathlib
import sys

TOOL = pathlib.Path('apk-fix/java/com/ggufchat/app/SearchTool.java')
NATIVE = pathlib.Path('apk-fix/native/mobile.cpp')
GANHO_MINIMO = 1.1  # abaixo disto não é ganho: é ruído de rede


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--race-gain', required=True,
                        help='ganho medido da corrida (sequencial ÷ corrida), com vírgula ou ponto')
    parser.add_argument('--ubatch-gain', default=None,
                        help='ganho medido do sub-lote 256 sobre 128 (opcional)')
    parser.add_argument('--round', required=True, help='rodada verde que mediu o ganho')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    ganho = float(args.race_gain.replace(',', '.'))
    if ganho < GANHO_MINIMO:
        print(f'ganho medido {ganho:.2f}x é menor que {GANHO_MINIMO}x: NADA foi mudado')
        return 1
    if args.ubatch_gain is not None:
        sub = float(args.ubatch_gain.replace(',', '.'))
        if sub < GANHO_MINIMO:
            print(f'ganho medido do sub-lote {sub:.2f}x é menor que {GANHO_MINIMO}x: '
                  'o padrão do pré-preenchimento NÃO foi mudado')
        else:
            nativo = NATIVE.read_text()
            antigo = 'uint32_t prefill_ubatch=context>=1024?128:64;'
            novo = ('uint32_t prefill_ubatch=context>=1024?256:64;'
                    f'  // 256 medido {sub:.2f}x melhor que 128 (rodada {args.round})')
            if antigo in nativo:
                if args.dry_run:
                    print(f'(ensaio) o sub-lote viraria 256 ({sub:.2f}x medido)')
                else:
                    NATIVE.write_text(nativo.replace(antigo, novo))
                    print(f'mobile.cpp: sub-lote do pré-preenchimento 256 por padrão '
                          f'(rodada {args.round}, ganho medido {sub:.2f}x)')
            else:
                print('o sub-lote já não está em 128; nada a fazer')

    texto = TOOL.read_text()
    if 'intProperty(RACE_PROPERTY,1)' in texto:
        print('os padrões de busca já estavam ligados; nada a fazer')
        return 0
    antigo_race = 'private static boolean raceEnabled(){return intProperty(RACE_PROPERTY,0)==1;}'
    novo_race = (
        '// Corrida LIGADA por padrão: medido na mesma rodada e no mesmo aparelho\n'
        f'    // (rodada {args.round}), ela devolve fonte com a latência do provedor mais rápido\n'
        f'    // em vez da soma das tentativas — {ganho:.2f}x menos espera, dentro do MESMO\n'
        '    // orçamento. `debug.gguf.search_race 0` desliga para comparar de novo.\n'
        '    private static boolean raceEnabled(){return intProperty(RACE_PROPERTY,1)!=0;}')
    antigo_cache = 'private static int cacheMs(){return Math.max(0,intProperty(CACHE_PROPERTY,0));}'
    novo_cache = (
        '// Consulta repetida sai da memória por padrão (60 s): repetir a mesma pergunta\n'
        '    // na mesma execução do aplicativo não volta à rede. A idade do resultado vai\n'
        '    // para o log e o que passou do teto é descartado em vez de servido velho;\n'
        '    // `debug.gguf.search_cache_ms 0` desliga.\n'
        '    private static int cacheMs(){return Math.max(0,intProperty(CACHE_PROPERTY,60000));}')
    for antigo in (antigo_race, antigo_cache):
        if antigo not in texto:
            print(f'não encontrei no SearchTool.java: {antigo[:60]}…')
            return 2
    texto = texto.replace(antigo_race, novo_race).replace(antigo_cache, novo_cache)
    if args.dry_run:
        print('(ensaio) o arquivo seria alterado; nada foi escrito')
        return 0
    TOOL.write_text(texto)
    print(f'SearchTool.java: corrida e cache ligados por padrão (rodada {args.round}, '
          f'ganho medido {ganho:.2f}x)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
