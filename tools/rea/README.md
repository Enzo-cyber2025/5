# R.E.A. — pipeline de auditoria estática de APK

Conjunto mínimo de ferramentas usadas para produzir
[`docs/familylink-rea/RELATORIO.md`](../../docs/familylink-rea/RELATORIO.md).
Tudo roda offline, em modo leitura sobre o APK, sem emulador.

## Instalação

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-test.txt   # androguard==4.1.4
```

`openssl` é opcional (só para descrever o certificado da âncora embutida).

## Uso

```bash
python3 tools/rea/executar_tudo.py <alvo.apk> <dir_saida>
```

O comando roda as três fases e valida o resultado contra as asserções do
relatório. Se o alvo mudar (outra versão, outro app), as checagens falham de
propósito — elas existem para impedir que o relatório e o binário se separem.
Para o `appteste.apk` documentado, a saída termina com
`OK: todas as checagens do relatorio passaram.` e os JSON são idênticos aos
versionados em `docs/familylink-rea/evidencias/appteste/`.

## Scripts

| Script | Fase | Saída |
|---|---|---|
| `recon.py` | 1 — Recon | `recon.json` (hashes, identidade, flags, permissões), `componentes.json` (58 componentes com exportação efetiva e filtros), `AndroidManifest.xml` legível |
| `integridade_apk.py` | 1/2 — empacotamento | `integridade_apk.json` (blocos v2/v3/SourceStamp, consistência, certificado, cobertura do `CERT.SF`, entradas atípicas) |
| `static_scan.py` | 2 — estática | `capacidades.json` (31 capacidades com classe/método/instrução de amostra), `strings_interessantes.json` (URLs, ações, caminhos) |
| `dump_metodos.py` | 2 — evidência | bytecode estilo smali de classes selecionadas, para citar linha a linha no relatório |
| `cvss.py` | 4 — relatório | CVSS v3.1 base a partir do vetor (mesma matemática da especificação, incluindo *roundup*) |
| `executar_tudo.py` | orquestração | roda tudo e aplica as asserções |

## Limites conhecidos

- `dump_metodos.py` não decodifica tabelas de `try/catch` no androguard 4.1.4
  (a API expõe `TryItem` opaco); imprime um marcador em vez do handler.
- `static_scan.py` conta ocorrências também em bibliotecas (Ads, Flurry, Sentry).
  O relatório sempre separa "capacidade presente no APK" de "capacidade em
  código próprio"; ao interpretar `capacidades.json`, filtre por prefixo
  `Lcm/aptoide`, `Lcom/aptoide`, `Lpt/aptoide`.
- `integridade_apk.py` valida estrutura e cobertura de assinatura, **não**
  verifica as assinaturas criptográficas (para isso: `apksigner verify`).
- Nenhum script executa o app. Fase 3 (dinâmica) exige emulador + `frida`, fora
  do escopo deste diretório.
