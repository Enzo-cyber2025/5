# Resultados do ensaio — REA (Reverse Engineering Anything)

Data: 2026-10-22. Chaves aqui são **fictícias** (`AItest-only-…`) ou o vetor
público de teste do Chromium. Nenhuma conta real foi acessada.

## 0. Resposta direta

| pergunta | estado |
|---|---|
| **Acha os caminhos?** | **Sim** — 7 candidatos com proveniência (`paths list`), descoberta a partir de captura real (`paths discover`) sem inventar host+caminho, e teste HTTP com status/tamanho/segredo (`paths check`). Verificação de rede real contra o Google: **não executada aqui** (bloqueio de rede do sandbox). |
| **Gera códigos?** | **Sim**, 6 dígitos, por balde de TTL. |
| **Funcionam no Family Link?** | **Igualdade com o app oficial: PROVADA** — os 5 vetores do Chromium, que foram *gerados no app Family Link do Android*, são reproduzidos 5/5. **Aceitação no firmware do aparelho: não provada aqui** (sem aparelho). |

## 1. A prova mais forte: vetores do app oficial

O Chromium embute, em
`chrome/browser/ash/child_accounts/parent_access_code/parent_access_test_utils.cc`,
códigos "generated in Family Link Android app" com o config
`shared_secret = AIfVJHITSar8keeq3779V70dWiS1xbPv8g`, `access_code_ttl = 600 s`,
`clock_drift_tolerance = 300 s`:

| esperado (app Google) | instante | flcodes (TTL 600 s) | flcodes (TTL 3600 s) |
|---|---|---|---|
| 734261 | 2019-01-08 16:58:07 PST | **734261** | 182975 |
| 472150 | 2019-01-14 15:35:05 PST | **472150** | 673233 |
| 204984 | 2019-01-14 15:42:49 PST | **204984** | 673233 |
| 157758 | 2019-01-14 15:53:01 PST | **157758** | 673233 |
| 524186 | 2019-01-14 16:00:00 PST | **524186** | **524186** |

**5/5 com 600 s; 1/5 com 1 h.** Isso corrigiu uma premissa errada da primeira
versão desta ferramenta: o código **não** vale sempre uma hora. A validade vem
do config (`access_code_ttl`, entre 60 s e 3600 s) e precisa ser usada; a
única coincidência é quando o instante cai exatamente na virada.

Implementado: TTL por chave (lido de `access_code_ttl`/`accessCodeTtl`), TTL
descobrível a partir de uma observação (`discover_validity`), e aviso explícito
quando dois TTLs explicam a mesma amostra (600 s e 300 s são indistinguíveis com
uma amostra só).

## 2. Caminhos (endpoints)

`flcodes paths list` — candidatos com a origem da informação:

| endpoint | tipo | por quê |
|---|---|---|
| `familylink.googleapis.com/v1/familyLinkAppConfig` | app-config | documentado no write-up público (filtro DevTools `familyLinkAppConfig`) |
| `kidsmanagement-pa.clients6.google.com/kidsmanagement/v1/familyLinkAppConfig` | app-config | mesma família de hosts do painel web |
| `kidsmanagement-pa.googleapis.com/kidsmanagement/v1/familyLinkAppConfig` | app-config | host alternativo |
| `familylink.google.com/` | web-app | HTML + bundles JS contêm o caminho |
| `…/kidsmanagement/v1/families/mine/members` | session-check | valida a sessão antes da caça |
| `file:///var/lib/whitelist/preferences` | chromeos-policy | política `ParentAccessCodeConfig` no Local State |
| `file:///home/chronos/Local State` | chromeos-policy | idem, usuário logado |

`flcodes paths discover --file captura.har` ranqueia o que a captura mostra
(`app-config` acima de `session-check`, lixo de analytics descartado) e **não**
monta combinações inexistentes — bug corrigido no ensaio (antes ele produzia
`familylink.googleapis.com/kidsmanagement/...`). `paths check` faz GET só
quando pedido e reporta `status`, `bytes`, presença de segredo ou do campo
cifrado.

Rede real: `curl https://familylink.googleapis.com/…` responde `http=000` neste
sandbox (política de rede), então **`paths check`/`rea api` não foram exercitados
contra o Google**. Os testes usam stub local (200/401, corpo com segredo,
caminho aninhado).

## 3. Busca da chave — formatos

```
[android] AIte…ij (len 35)  <- familylink.har   (…"sharedSecret": "AItest-only-REA-demo-key…")
[android] AIte…ij (len 35)  <- prefs.xml        (UTF-16: <string name="seed">…)
[android] AIte…ij (len 35)  <- app-dump.apk!assets/family_link.json
[android] AIte…ij (len 35)  <- 000005.ldb       (LevelDB binário)
[android] AIte…ij (len 35)  <- logcat.gz        (gzip)
note: post-patch.json: encrypted secret field 'encryptedSharedSecret' (client-side only)
```

E o config vem junto: `ttl=600s` gravado na chave (`extra={'validity': 600,
'drift': 300}`).

Falhas encontradas no ensaio e corrigidas: HAR com escape duplo não detectado;
`access_code_ttl` perdido porque o corpo era JSON dentro de string (agora há
recursão de JSON embutido, com profundidade contada só para JSON aninhado);
contexto com bytes NUL; rótulos repetidos; servidor web com cache eterno do
cofre.

## 4. Ensaio completo reproduzível

```bash
bash family-link-codes/demo/run_demo.sh
```

Saída (resumo):

```
== 2. REA: find the shared secret ==       5 fontes + aviso do campo cifrado
== 3. stored keys (masked) ==              demo-1 … 600s  AIte…ij  demo-1
== 4. generate three codes ==              843355 / 203648 / 096046 (janelas de 10 min)
== 5. observations (oráculo Chromium) ==
== 6. verify ==                            key demo-1: 3/3 CONFIRMADO, ttl 600s
                                           demo-2..5: 0/3 não confirmado
== 7. negative control ==                  correctly rejected (exit 1)
```

## 4b. Sem root: onde a chave mora (REA estático + dinâmico)

**Onde mora:** `/data/data/com.google.android.apps.familylink/shared_prefs/*.xml`
no aparelho do **responsável** (e `databases/` se houver cache). No aparelho da
criança não há chave: a validação é do servidor.

**Como chegar sem root:** `adb backup` — o arquivo é escrito pelo aparelho após
o diálogo de confirmação, sem root e sem `run-as`.

Resultado do pipeline com um container `.ab` real (fixture escrita byte a byte
no mesmo formato de `com.android.server.backup`):

```
$ flcodes abe info /tmp/flcodes-demo/device/familylink.ab
version 5 · compressed=True · encryption=none · payload at 24
apps: com.google.android.apps.familylink

$ flcodes abe scan /tmp/flcodes-demo/device/familylink.ab --save --label parent
extracted 3 file(s) from com.google.android.apps.familylink
[android] AIte…ey (len 30)  <- …/f/shared_prefs/familylink_preferences.xml  ($.parentAccessCode.sharedSecret (key match))
saved: id=… kind=android ttl=600s
```

Container cifrado (`adb backup -k`): PBKDF2-SHA1 (10 000 rounds) → blob do
master key → AES-256-CBC → zlib → tar. Senha errada dá
`master key checksum mismatch`; senha ausente dá erro explícito. AES e PBKDF2
conferidos contra FIPS-197 e contra `cryptography` (`tests/test_flcodes_abe.py`).

O que o `flcodes apk scan` extrai de um APK real (rodado no `appteste.apk` de
4 089 entradas deste repositório, 20 MB, ~1,2 s):

```
apk: ../appteste.apk (4089 entries)
package (guess): app.aptoide.com
root-hint: /su, /su/, Superuser        backup-flag: allowBackup
native libs: 8 (arm64-v8a, armeabi-v7a, x86, x86_64)
note: no config field names in plain text: the strings are probably obfuscated…
```

Para o Family Link, os campos procurados são `sharedSecret`, `accessCodeTtl`,
`clockDriftTolerance`, `parentAccessCode`, além de `/data/data/<pkg>` e dos
endpoints de config.

### QEMU: por que não rodou aqui

Este sandbox **não executa** o teste em emulador:

* não existe pacote de QEMU no sistema (`apt-get download qemu-system-x86` →
  "Unable to locate package", e `deb.debian.org` responde `000`, sem `apt`);
* `dl.google.com` (imagens do SDK) está bloqueado pela política de rede;
* não há `/dev/kvm`, e a máquina tem 2 vCPUs / 3 GB de RAM (TCG puro);
* binário de QEMU até existe no GitHub (`ziglang/qemu-static`, 10.1.2.2, 62 MB),
  mas sem **imagem de sistema Android** ele não sobe nada — e é a imagem que
  não está acessível.

Então o teste de dispositivo foi feito nesta equivalência estrita:

| camada | como foi exercitada aqui |
|---|---|
| `adb` (devices/getprop/pm/pull/backup) | binário `adb` falso que responde como um aparelho real e **escreve um `.ab` de verdade** (`tests/test_flcodes_device.py`) |
| container `.ab` | fixtures reais, claro e cifrado, + extração e varredura ponta a ponta |
| emulador Android | **não executado**; `tools/qemu_android_test.sh` faz isso na sua máquina |

O script (`tools/qemu_android_test.sh`) sobe a imagem com `-display none`,
encaminha `tcp:127.0.0.1:5555`, espera `sys.boot_completed`, roda `device info`,
`device apk` e `device backup --scan --save`, e falha se o segredo não sair. Usa
KVM quando existe e cai para TCG quando não existe.

## 5. O que ainda NÃO está provado

* **Aceitação pelo firmware do aparelho supervisionado** — precisa de aparelho
  real. É o único passo que falta e ele é do usuário: ver §6.
* `paths check` / `rea api` contra os endpoints do Google (rede bloqueada aqui;
  e desde 09/2024 a maioria das contas não recebe mais o segredo no cliente web).
* `rea adb` com root em aparelho real.
* **QEMU/emulador Android**: sem QEMU, imagem ou KVM neste sandbox; o runner está
  pronto e o fluxo `adb` equivalente foi provado com um `adb` simulado que gera o
  mesmo container.
* `adb backup` em aparelho real: o diálogo precisa ser aceito e, se o pacote
  declarar `allowBackup=false`, o container vem vazio — limite do Android, não
  do extrator.
* Estabilidade futura do esquema (TTL e política podem mudar).

## 6. Como fechar a prova em 1 minuto (na sua máquina)

1. Family Link no aparelho do responsável → **Código de acesso do familiar**;
   anote o código e o horário.
2. `flcodes verify --code 123456 --at "2026-10-22T16:12:00-03:00"`
   → `CONFIRMADO` e o TTL usado. Se der `ambíguo`, repita com outro horário.
3. No aparelho supervisionado **offline**, digite o código atual em
   "Acesso dos pais" — esse é o teste de aceitação final.

## 7. Cobertura de testes (111)

```bash
pytest -q tests/test_flcodes_*.py    # 111 passed
```

(`pytest -q` na raiz do repositório também coleta os testes de outro projeto
daquele repo, que exigem `jdk4py`; não têm relação com esta ferramenta.)

| arquivo | o que fixa |
|---|---|
| `test_flcodes_codes.py` | **5 vetores oficiais do app Android**; guarda contra voltar ao TTL de 1 h; oráculo RFC 4226 independente; equivalência com a implementação Rust pública; descoberta de TTL e ambiguidade |
| `test_flcodes_crypto.py` | ChaCha20-Poly1305 vs RFC 8439 e `cryptography`; cofre (senha, adulteração, `0600`, recarga por mtime) |
| `test_flcodes_rea.py` | HAR/XSSI, escape simples e duplo, percent duplo, hex, base64, UTF-16, ZIP/APK, gzip, LevelDB, TTL+drift no config, campo cifrado |
| `test_flcodes_endpoints.py` | lista com proveniência, descoberta sem inventar hosts, JS bundle vs ruído, `check` 200/401/arquivo local |
| `test_flcodes_verify.py` | confirmação/rejeição, TTL descoberto, ambiguidade, drift, seleção entre chaves |
| `test_flcodes_cli.py` | CLI ponta a ponta, `paths`, TTL no `rea`/`gen`/`verify`, UI web (401/429/400/HEAD, CSP, TTL) |
| `test_flcodes_abe.py` | FIPS-197 + `cryptography`, cabeçalho, `--password`, zlib, cifrado e claro, path traversal, container vazio, `apk scan` |
| `test_flcodes_device.py` | `adb` simulado: info, pull dos splits, `adb backup` real, varredura + `keys`/`gen` com TTL, e prova de que nenhum comando usa root |
