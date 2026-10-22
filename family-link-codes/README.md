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

REA é o nome da camada de **aquisição da chave** neste projeto:

**R**ecuperar → **E**xtrair → **A**rmazenar

1. **Recuperar** o payload `familyLinkAppConfig` (sessão do responsável,
   captura HAR, dump de prefs, logcat ou `adb`).
2. **Extrair** o *shared secret* — a string `AI…` que o app do responsável usa
   para calcular o código. A variante do Chromebook começa com `AL` e não serve
   para o Android.
3. **Armazenar** a chave num arquivo cifrado com a sua senha, para o
   experimento conseguir reproduzir códigos depois.

Depois disso, o resto é offline: o código é um TOTP calculado localmente.

## 2. Como o código funciona

| item | valor |
|---|---|
| chave | **bytes da string** do shared secret (não é base32) |
| hash | HMAC-SHA1 |
| passo | 60 s, porém **ancorado na hora cheia** |
| truncamento | RFC 4226 (offset dinâmico) |
| dígitos | 6, módulo 1 000 000 |

Consequência prática: **um código vale a hora inteira** e vira na hora cheia —
é por isso que o código do Family Link funciona sem internet e continua válido
enquanto o relógio não muda de hora.

O cálculo foi conferido contra um oráculo independente (TOTP com `interval=60`
iniciado na hora cheia) e contra o vetor conhecido do RFC 8439 para a cifra.
Ver `tests/test_flcodes_codes.py`.

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

```bash
flcodes gen                                   # código da hora atual
flcodes gen --time 2026-10-22T15:00:00-03:00  # hora específica
flcodes gen --time 1792000000 --count 6       # 6 horas seguidas
flcodes gen --day 2026-10-22                  # as 24 horas do dia
flcodes gen --day 2026-10-22 --out codigos.csv
flcodes gen --json --count 24 --out codigos.jsonl
flcodes gen --secret 'AI...' --encoding raw    # sem usar o cofre
flcodes stream --out ao-vivo.csv               # acompanha a virada da hora
```

Fuso: o código vira na hora cheia **UTC**. Para fusos de hora inteira isso
coincide com a hora local; para fusos de meia hora (UTC+05:30, +09:30) use
`--tz-offset-minutes 330`.

### 4.4 Interface web local

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
* O código vale para o **fuso do servidor** ancorado na hora cheia; relógio
  errado no aparelho invalida o código (o Family Link compara janelas).
* Não há garantia de que uma versão futura do Family Link mantenha o esquema
  de TOTP de 60 s/hora. Este app é de experimento, não de produção.
* O `secure_delete` sobrescreve e apaga o arquivo, mas em filesystem
  copy-on-write (btrfs, APFS, ZFS) blocos antigos podem sobreviver.

## 6. Segurança do próprio app

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

## 7. Estrutura

```
family-link-codes/
  flcodes/
    codes.py     TOTP (HMAC-SHA1, passo 60 s ancorado na hora)
    secrets.py   detecção/classificação/mascaramento da chave
    rea.py       camada REA: api, har, paste, scan, adb
    store.py     cofre cifrado
    report.py    exportação de códigos e relatório sem segredo
    cli.py       linha de comando
    server.py    UI web local + API com token
    web/index.html
  tests/ (na raiz do repositório): test_flcodes_{codes,crypto,rea,cli}.py
```

## 8. Descarte

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
