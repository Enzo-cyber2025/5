# flcodes — códigos do Family Link para testes autorizados

Ferramenta de bancada para uma única finalidade: **achar a chave dos códigos
offline do Family Link (REA), salvá-la cifrada e gerar os códigos de acesso
parental** para qualquer horário — passado, presente ou futuro — durante um
experimento de segurança com conta e aparelho que você controla.

> **Escopo.** Use somente em ambiente autorizado (seu, da sua família ou de um
> cliente com contrato). Acessar a conta de outra pessoa, ou destravar um
> aparelho que não é seu, é crime no Brasil (Lei 12.737/2012 e art. 154-A do
> Código Penal) e viola os termos do Google. O app foi escrito para ser
> descartado ao fim do experimento: nada aqui foi projetado para uso contínuo.

---

## 1. O que é "REA"

REA = **Reverse Engineering Anything** — a camada de engenharia reversa que
recupera a chave, aplicada aqui como **R**ecuperar → **E**xtrair → **A**rmazenar:

1. **Recuperar** o payload `familyLinkAppConfig` (sessão do responsável,
   captura HAR, dump de prefs, logcat, LevelDB ou `adb`).
2. **Extrair** o *shared secret* — a string `AI…` que o app do responsável usa
   para calcular o código. A variante do Chromebook começa com `AL` e não serve
   para o Android.
3. **Armazenar** a chave num arquivo cifrado com a sua senha, para o
   experimento conseguir reproduzir códigos depois.

Formatos que o extrator entende, porque dump real quase nunca tem o segredo em
UTF-8 limpo:

| formato | exemplo de origem |
|---|---|
| JSON com prefixo XSSI `)]}'` e arrays estilo protobuf | resposta do `familyLinkAppConfig` |
| `\u0041…` (inclusive escape duplo) e `%41…` (inclusive duplo) | HAR, JSON dentro de JSON, URL |
| hex e base64 (runs dentro de um blob maior) | dumps diversos, `base64:` |
| **UTF-16** | XML de shared prefs, capturas Windows |
| **ZIP / APK / JAR / CRX** | membros internos do app |
| **gzip** | logcat, logs rotacionados |
| **LevelDB** (`.ldb`, `.log`) binário | Chrome/ChromeOS Local Extension Settings |

Se o payload trouxer um segredo **cifrado** (estado pós-setembro/2024), o
extrator **reporta o campo** em vez de inventar uma chave.

Depois disso, o resto é offline: o código é um TOTP calculado localmente.

> Resultados medidos do ensaio (o que passou, o que não foi provado e como
> provar em 1 minuto): [`RESULTS.md`](RESULTS.md).

## 2. Como o código funciona (fonte: implementação oficial)

A referência não é um blog: é o código que o **Chromebook usa para validar** o
código de acesso parental —
`chrome/browser/ash/child_accounts/parent_access_code/authenticator.cc`
(Chromium, licença BSD). Ele define:

| item | valor |
|---|---|
| chave | **bytes da string** do `shared_secret` (não é base32) |
| hash | HMAC-SHA1 sobre o contador de 64 bits big endian |
| balde | `timestamp // code_validity`, com `code_validity` = `access_code_ttl` do config (**60 s a 3600 s**) |
| contador | início do balde dividido pela granularidade de **1 minuto** |
| truncamento | RFC 4226 (offset dinâmico), módulo 1 000 000 |
| dígitos | 6 |
| validação | aceita o código se bater em qualquer minuto dentro de `± clock_drift_tolerance` (0 a 1800 s) |

**O TTL não é fixo.** Ele vem no mesmo payload que carrega o segredo
(`shared_secret`, `access_code_ttl`, `clock_drift_tolerance`). O app Android
tem exibido códigos que viram de hora em hora, mas os dados de teste do próprio
Chromium (gerados com o app Family Link do Android) usam **600 s**:

| código gerado pelo app Android | instante (PST) | nosso resultado |
|---|---|---|
| 734261 | 2019-01-08 16:58:07 | 734261 |
| 472150 | 2019-01-14 15:35:05 | 472150 |
| 204984 | 2019-01-14 15:42:49 | 204984 |
| 157758 | 2019-01-14 15:53:01 | 157758 |
| 524186 | 2019-01-14 16:00:00 | 524186 |

Os cinco vetores são reproduzidos **5/5 com TTL 600 s** e falham com TTL de
1 hora — é por isso que o TTL é sempre lido do config (ou descoberto pelo
`verify`) e nunca presumido. Ver `tests/test_flcodes_codes.py`.

`flcodes verify` ainda aceita qualquer TTL e, se nenhum for informado, descobre
o valor a partir de um código visto no app (com aviso quando dois TTLs
explicam a mesma amostra — 600 s e 300 s são indistinguíveis numa amostra só).

## 3. Instalação

Requisitos: Python 3.9+ e **nada além da biblioteca padrão** (o app foi feito
para rodar em máquina isolada, sem rede).

```bash
cd family-link-codes
python3 -m flcodes --help
python3 -m flcodes audit      # autotestes: algoritmo, crypto e cofre
```

Opcional, para rodar como comando:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e .              # cria o comando `flcodes`
```

Testes:

```bash
pip install pytest cryptography   # cryptography é só oráculo de teste
python -m pytest -q tests/test_flcodes_codes.py tests/test_flcodes_crypto.py \
                   tests/test_flcodes_rea.py tests/test_flcodes_cli.py
```

## 4. Uso — passo a passo

### 4.0 Descobrir os caminhos (endpoints)

```bash
flcodes paths list                         # candidatos + de onde a informação veio
flcodes paths discover --file ~/Downloads/familylink.har   # acha os paths reais
flcodes paths check --cookie-file ~/cookies.txt            # testa cada um
```

`paths discover` lê um HAR/HTML/logcat/JS e ranqueia os endpoints que podem
entregar o config (nome `familyLinkAppConfig` pontua mais), sem inventar
combinações de host+caminho que não existem. `paths check` mostra código HTTP,
tamanho, e se o corpo trouxe segredo ou o campo cifrado.

### 4.1 Obter a chave (REA)

Uma das cinco fontes. Todas são locais, exceto `api` e `adb`, que só falam com
o que você apontar.

```bash
# a) sessão do responsável (cookie SAPISID), sem navegador
flcodes rea api --sapisid 'VALOR_DO_COOKIE' --save --label pai

# a partir de um arquivo cookies.txt exportado do navegador
flcodes rea api --cookie-file ~/cookies.txt --save --label pai

# b) captura HAR feita no DevTools (Network → Save all as HAR)
flcodes rea har ~/Downloads/familylink.har --save --label pai

# c) colar o trecho (resposta do DevTools, prefs, logcat)
pbpaste | flcodes rea paste --save --label pai
flcodes rea paste ./dump.xml --save

# d) varrer arquivos/diretórios
flcodes rea scan ~/dumps/familylink/ --save

# e) aparelho conectado por adb (root, run-as ou build de depuração)
flcodes rea adb --serial R58M123ABC --save
```

O comando mostra apenas a chave **mascarada** (`AIte…ij (len 33)`) e grava um
relatório em `flcodes-out/output/rea-*.json` que **nunca** contém o segredo.

### 4.2 Chaves salvas

```bash
flcodes keys list                 # mascaradas, com id e rótulo
flcodes keys show --reveal        # imprime o segredo no terminal (cuidado)
flcodes keys use 1a2b3c4d5e6f     # define a chave ativa
flcodes keys export store.json    # exporta mascarado
flcodes keys export full.json --reveal
flcodes keys import full.json
flcodes keys rm 1a2b3c4d5e6f
flcodes keys add --label manual   # lê o segredo da entrada padrão
```

O cofre fica em `~/.config/flcodes/store.json` (ou `$FLCODES_HOME`), com
permissão `0600`, cifrado em ChaCha20-Poly1305 e chave derivada por scrypt. A
senha vem de `FLCODES_PASSPHRASE` ou é pedida no terminal; **nunca** é gravada.

### 4.3 Gerar e salvar códigos

O TTL efetivo vem da chave salva (`access_code_ttl` do config). Para forçar:

```bash
flcodes gen --validity 600 --time 2026-10-22T16:05:00-03:00
```

```bash
flcodes gen                                   # código atual (TTL da chave)
flcodes gen --validity 600                    # força 10 minutos
flcodes gen --time 2026-10-22T15:00:00-03:00  # hora específica
flcodes gen --time 1792000000 --count 6       # 6 horas seguidas
flcodes gen --day 2026-10-22                  # as 24 horas do dia
flcodes gen --day 2026-10-22 --out codigos.csv
flcodes gen --json --count 24 --out codigos.jsonl
flcodes gen --secret 'AI...' --encoding raw    # sem usar o cofre
flcodes stream --out ao-vivo.csv               # acompanha a virada da hora
```

Fuso: os baldes são alinhados ao **epoch UTC** no múltiplo do TTL (com TTL de
3600 s a virada é na hora cheia; com 600 s, a cada 10 minutos). Para fusos de
meia hora (UTC+05:30, +09:30) use `--tz-offset-minutes 330`.

### 4.4 Verificar se o código é funcional (`verify`)

Gerar seis dígitos não prova nada. A prova objetiva é comparar com um código que
**o Google produziu** para aquela chave: abra o Family Link no aparelho do
responsável → **Código de acesso do familiar**, anote o código e o horário.

```bash
flcodes verify --code 123456 --at "2026-10-22T15:12:00-03:00"
flcodes verify --code 123456 --minutes 3            # observado 3 min atrás
flcodes verify --file observacoes.csv               # várias observações
flcodes verify --code 123456 --tolerance-hours 1    # tolera relógio fora de hora
```

Saída: por chave, quantas observações ela reproduz e em qual janela. Uma chave
`CONFIRMADO` prova, ao mesmo tempo, que o segredo é o daquela família e que os
bytes da chave, o contador do balde, o TTL e o truncamento estão certos. O
relatório (`flcodes-out/output/verify-*.json`) não contém segredo.

### 4.5 Interface web local

```bash
flcodes serve                       # http://127.0.0.1:8765/?token=...
flcodes serve --host 0.0.0.0 --port 8765
```

O navegador **nunca recebe o segredo**: só ids, rótulos mascarados e códigos. O
token de acesso é sorteado no início (ou `--token`), todas as chamadas `/api`
exigem `X-Token`, há limite de 10 falhas por minuto, CSP sem recursos externos
e `Cache-Control: no-store`. A página permite copiar o código, ver a contagem
para a virada da hora, gerar 1/6/24 horas e baixar CSV.

## 5. Limitações conhecidas (o que quebra e por quê)

* **O Google fechou o caminho do site em setembro de 2024**: a resposta de
  `familyLinkAppConfig` deixou de trazer o *shared secret* em texto para o
  cliente. Se a conta já expõe a chave, ela continua valendo; se não expõe,
  `rea api` não acha nada e o relatório registra isso. Não há força bruta
  viável: a chave tem ~20 bytes aleatórios.
* `rea api` depende do cookie `SAPISID` de uma sessão válida do responsável.
* `rea adb` só funciona com root, `run-as` ou build de depuração; sem isso o
  Android bloqueia a leitura dos dados do app.
* Relógio errado no aparelho invalida o código: a validação aceita apenas
  `± clock_drift_tolerance` (0 a 1800 s) ao redor do instante. Use
  `flcodes verify --drift 300` para simular essa tolerância.
* O TTL pode ser 600 s, 3600 s ou outro valor do intervalo 60–3600 s; usar o
  valor errado gera código que o aparelho não aceita. Sempre que possível leia
  `access_code_ttl` do payload.
* Não há garantia de que uma versão futura do Family Link mantenha o esquema
  de TOTP de 60 s/hora. Este app é de experimento, não de produção.
* O `secure_delete` sobrescreve e apaga o arquivo, mas em filesystem
  copy-on-write (btrfs, APFS, ZFS) blocos antigos podem sobreviver.

## 6. O que foi provado (e o que não foi)

Ver [`RESULTS.md`](RESULTS.md) para as medições. Resumo:

| item | estado |
|---|---|
| recupera a chave em HAR, UTF-16, ZIP/APK, gzip, LevelDB, hex/base64/escape | **provado** (5/5 fixtures) |
| não inventa chave quando o payload traz segredo cifrado | **provado** (reporta o campo) |
| gera códigos 6 dígitos, 1 por hora, determinístico | **provado** (66 testes) |
| código igual ao de implementações independentes (oráculo RFC + Rust público + pyotp) | **provado** |
| **código igual ao gerado pelo app Family Link do Android** (5 vetores oficiais do Chromium) | **provado** (TTL 600 s) |
| TTL lido do config e descoberto por observação | **provado** |
| caminhos descobertos de um HAR e testados por HTTP | **provado** (stub local; rede Google bloqueada aqui) |
| identificação da chave certa entre 5 chaves | **provado** (3/3 vs 0/3) |
| aceitação real pelo aparelho / `rea api` em rede real / `rea adb` com root | **não provado aqui** (sem rede Google, sem aparelho) |

## 7. Segurança do próprio app

| proteção | como |
|---|---|
| segredo em repouso | ChaCha20-Poly1305 + scrypt (N=16384, r=8, p=1), salt por gravação |
| segredo em trânsito | não sai do processo; a web só recebe ids e códigos |
| segredo em log/relatório | mascarado (`AIte…ij`), com teste que falha se vazar |
| senha | `FLCODES_PASSPHRASE`/prompt, nunca gravada, nunca em argumento por padrão |
| arquivos gerados | permissão `0600` |
| dependências | zero em produção (só stdlib) |
| cifra | implementação própria conferida contra RFC 8439 e `cryptography` |

Riscos residuais, honestamente: `--passphrase` na linha de comando aparece no
histórico do shell e em `ps` (prefira a variável de ambiente); o token da web
vai na URL por conveniência; o processo em memória contém o segredo em claro —
quem controla a máquina consegue lê-lo. Nada disso é um cofre de grau
hardware.

## 8. Estrutura

```
family-link-codes/
  flcodes/
    codes.py     TOTP (HMAC-SHA1, balde de TTL, granularidade de 60 s)
    secrets.py   detecção/classificação/mascaramento da chave
    rea.py       camada REA: api, har, paste, scan, adb (UTF-16, zip, gzip, LevelDB)
    verify.py    confirmação contra códigos produzidos pelo Google
    endpoints.py caminhos candidatos + descoberta em capturas
    store.py     cofre cifrado
    report.py    exportação de códigos e relatório sem segredo
    cli.py       linha de comando
    server.py    UI web local + API com token
    web/index.html
  demo/
    make_fixtures.py     dumps sintéticos: HAR, UTF-16, APK, LevelDB, gzip
    make_observations.py códigos por um oráculo RFC 4226 independente
    run_demo.sh          ensaio completo: scan -> save -> gen -> verify
  tests/ (na raiz do repositório): test_flcodes_{codes,crypto,rea,verify,cli}.py
```

## 9. Descarte

Ao fim do experimento:

```bash
flcodes keys rm <id>            # remove a chave do cofre (regrava o arquivo)
rm -rf ~/.config/flcodes        # remove o cofre inteiro
rm -rf flcodes-out              # relatórios e códigos gerados
unset FLCODES_PASSPHRASE
```

Se a chave foi obtida de um ambiente real, revogue a sessão usada, troque a
senha da conta do responsável e considere pedir ao Google a rotação do segredo
(suporte Family Link). Falhas encontradas devem ser reportadas ao Google pelo
programa de vulnerabilidades; este repositório documenta o experimento, não
distribui a chave de ninguém.
