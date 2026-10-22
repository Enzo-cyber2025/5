# Resultados do ensaio — REA (Reverse Engineering Anything)

Data: 2026-10-22. Chaves usadas aqui são **fictícias** (`AItest-only-…`), criadas
só para o ensaio. Nenhuma conta real foi acessada.

## 1. Resposta direta às três perguntas

| pergunta | resposta | como foi medido |
|---|---|---|
| **O app busca a chave?** | **Sim** — 5 de 5 formatos de dump recuperados; o formato pós-patch (segredo cifrado) é **detectado e reportado**, não inventado | `rea scan` sobre fixtures reais de REA (HAR, UTF-16, APK, LevelDB, gzip) |
| **Gera códigos?** | **Sim** — 6 dígitos, 1 por hora, janela de 1 h, determinístico | `gen`, `gen --day`, `stream`; 66 testes |
| **Os códigos são funcionais?** | **Igualdade com uma implementação independente: provada.** **Aceitação real pelo Google: NÃO provada neste ambiente** — exigia rede/telefone, que o sandbox bloqueia | `verify` contra códigos produzidos por `pyotp` (biblioteca independente) e transcrição da implementação pública em Rust |

A frase "funcional" tem dois sentidos e é importante não confundi-los:

1. **Reproduz o que o Google mostra** → provado contra *duas* implementações
   independentes (oráculo RFC 4226 escrito à mão, transcrição do Rust público,
   e `pyotp` no ensaio). Se o algoritmo estivesse errado, nenhuma delas
   concordaria.
2. **O aparelho aceita o código** → só se prova **no aparelho** ou com um código
   lido do app do responsável. Isso está automatizado no comando `verify`, e
   leva 1 minuto na sua máquina (§4).

## 2. Busca da chave — resultados por formato

`flcodes rea scan /tmp/rea-demo/dumps --save --save-all` (fixtures geradas por
`make_fixtures.py`):

```
[android] AIte…ij (len 35)  <- familylink.har   ('\n[["familyLinkAppConfig", [[null, "AItest-only-REA-demo-key…")   [unicode-escaped]
[android] AIte…ij (len 35)  <- prefs.xml        (ding="utf-16"?><map><string name="seed">AItest-only-REA-pref-key…)
[android] AIte…ij (len 35)  <- app-dump.apk!assets/family_link.json  ($.parentAccessCode (key match))
[android] AIte…ij (len 35)  <- 000005.ldb       (··ÿAItest-only-REA-ldb1-key.abcdefghij·þ)
[android] AIte…ij (len 35)  <- logcat.gz        (I/fl: seed=AItest-only-REA-gz11-key.abcdefghij)
note: post-patch.json: encrypted secret field 'encryptedSharedSecret' (client-side only)
```

| formato | como é tratado | resultado |
|---|---|---|
| HAR / JSON com prefixo XSSI `)]}'` | parse + varredura estrutural | achou |
| string com escape `\u0041…`, inclusive **escape duplo** (JSON dentro de JSON) | decodificação de 1+ barras invertidas | achou |
| `%41%49…` e duplo (`%2541…`) | unquote em até 2 níveis | achou |
| hex (`4149…`) e base64 (run dentro de blob) | decodificação de runs, com limite | achou |
| XML de prefs em **UTF-16** | leitura com BOM/endianness | achou |
| **APK/JAR/CRX/ZIP** | varredura de membros internos | achou |
| **gzip** de logcat | descompressão transparente | achou |
| **LevelDB** (`.ldb`, `.log`) binário | decodificação latin-1 (não descarta NUL) | achou |
| payload **pós-patch** (segredo cifrado) | detecta `encryptedSharedSecret` e avisa | não inventa chave |

**Falha encontrada no próprio ensaio e corrigida:** o HAR não era lido como
arquivo porque o corpo embutido tem escape duplo (`\\u0041`). Corrigido em
`secrets._decode_escaped_runs`, com teste de regressão
(`test_har_scanned_as_a_file_decodes_double_escaped_secret`). Também corrigidos:
contexto impresso com bytes NUL (agora `printable()`) e rótulos repetidos ao
salvar vários candidatos.

## 3. Geração e verificação

```
$ flcodes gen --label rea-demo-1 --time 1792684800 --count 3
843355 | 2026-10-22T16:00Z -> 17:00Z
969812 | 2026-10-22T17:00Z -> 18:00Z
704543 | 2026-10-22T18:00Z -> 19:00Z
```

Códigos equivalentes gerados por `pyotp` (implementação independente,
`interval=60`, contador na hora cheia) e verificados:

```
$ flcodes verify --file observations.csv
key rea-demo-1 (58677a59dd8b): 3/3 - CONFIRMADO
  [ok  ] observado 843355 em 2026-10-22 16:05 UTC -> gerado 843355
  [ok  ] observado 969812 em 2026-10-22 17:05 UTC -> gerado 969812
  [ok  ] observado 704543 em 2026-10-22 18:05 UTC -> gerado 704543
key rea-demo-2 (86370587fa3d): 0/3 - não confirmado
key rea-demo-3 (26f0ae53bb2d): 0/3 - não confirmado
key rea-demo-4 (1cd34af58956): 0/3 - não confirmado
key rea-demo-5 (29fe8c64ae59): 0/3 - não confirmado

confirmado: a chave rea-demo-1 reproduz todos os códigos observados …
```

Isso mostra duas coisas: a chave certa entre 5 é identificada, e chaves erradas
**não** passam (nenhum falso positivo em 15 comparações).

## 4. Como provar a funcionalidade real (1 minuto, sua máquina)

Requisitos: conta de responsável autorizada e um código que o Google mostre.

1. Abra o Family Link no aparelho do responsável (ou
   `familylink.google.com`) → **Código de acesso do familiar**. Anote o código e
   o horário (o minuto exato não importa, a hora sim).
2. `flcodes verify --code 123456 --at "2026-10-22T15:12:00-03:00"`
3. `CONFIRMADO` ⇒ a chave e o algoritmo são funcionais. Se falhar, rode com
   `--tolerance-hours 1` para descartar relógio dessincronizado; se ainda
   falhar, a chave não é a daquele responsável.

Teste final (o único que prova aceitação): com o aparelho supervisionado
**offline**, digite o código gerado para a hora atual em "Acesso dos pais".

Aquisição real da chave na sua máquina (não possível no sandbox):

```bash
flcodes rea api --cookie-file ~/cookies.txt --save    # sessão do responsável
flcodes rea har ~/Downloads/familylink.har --save     # captura do DevTools
flcodes rea adb --save                                # aparelho com root/run-as
```

Neste sandbox `curl https://familylink.googleapis.com/…` responde `http=000`
(rede bloqueada por política), então a etapa `api` não pôde ser executada aqui —
está registrada como **não testada em rede real**, não como aprovada.

## 5. Cobertura de testes (66)

| arquivo | o que fixa |
|---|---|
| `test_flcodes_codes.py` | oráculo RFC 4226 independente (400 instantes), **equivalência com a implementação pública em Rust**, bordas de hora, fuso de meia hora, normalização de segredo |
| `test_flcodes_crypto.py` | ChaCha20-Poly1305 contra RFC 8439 (2.3.2, 2.5.2, 2.8.2) e contra `cryptography`; scrypt; cofre: senha errada, adulteração, `0600`, dedupe, export/import |
| `test_flcodes_rea.py` | HAR, XSSI, escape simples/duplo, percent duplo, hex, base64, UTF-16, ZIP/APK, gzip, LevelDB, hint de segredo cifrado, mascaramento, relatório sem segredo |
| `test_flcodes_verify.py` | confirmação, rejeição, múltiplas observações, tolerância de relógio, seleção entre chaves, parsing CSV/JSON |
| `test_flcodes_cli.py` | CLI ponta a ponta em subprocesso, códigos de saída, relatórios, UI web (401/429/400/HEAD, CSP, `--allow-embed`), `verify` |

## 6. O que continua NÃO provado

* Aceitação do código pelo firmware do aparelho supervisionado (impossível sem
  aparelho real).
* `rea api` contra os endpoints do Google (rede bloqueada aqui; e desde 09/2024
  o segredo não é mais enviado ao cliente web na maioria das contas).
* `rea adb` em aparelho real (sem root/`run-as` não há leitura de dados do app).
* Estabilidade do esquema de TOTP de 60 s/hora em versões futuras do Family Link.
