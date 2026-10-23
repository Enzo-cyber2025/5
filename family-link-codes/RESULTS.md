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

## 4c. Emulador Android (QEMU) no GitHub Actions — executado

O sandbox de desenvolvimento não tem QEMU, imagem nem KVM; o GitHub Actions tem
os três. O workflow `flcodes-emulator.yml` sobe **Android 11 (API 30, x86_64)**
com KVM (boot em ~26 s) e roda o pipeline inteiro. Resultado real do job
`emulator` (run 39846471546, verde):

```
$ adb install -r selftest.apk          # app de teste: allowBackup=true, grava o config
$ python3 -m flcodes device info       # props + pacotes, sem root
$ python3 -m flcodes device apk        # pull do APK instalado (leitura pública)
$ python3 -m flcodes apk scan base.apk
private-dir: /data/data/com.flcodes.selftest/...
prefs:       sp/familylink_preferences.xml
config-key:  sharedSecret, accessCodeTtl, clockDriftTolerance, parentAccessCode

$ adb backup -f com.flcodes.selftest.ab -noapk com.flcodes.selftest   # diálogo aceito via uiautomator
$ ls -l com.flcodes.selftest.ab
-rw-r----- 1 runner runner 1235 ... com.flcodes.selftest.ab

$ python3 -m flcodes abe info com.flcodes.selftest.ab
version 5 · compressed=True · encryption=none · payload at 24
apps: com.flcodes.selftest

$ python3 -m flcodes abe scan com.flcodes.selftest.ab --save --label emulator
extracted 2 file(s) from com.flcodes.selftest
[android] AIte…ey (len 24)  <- …/apps/com.flcodes.selftest/sp/familylink_preferences.xml
saved: id=2b4d8338828e kind=android ttl=600s

$ python3 -m flcodes gen --label emulator --json
{"code": "502849", "valid_from": 1792699200, "validity": 600, ...}
```

Prova de que **não houve root** em nenhum passo, do mesmo run:

```
$ adb shell ls /data/data/com.flcodes.selftest
ls: /data/data/com.flcodes.selftest: Permission denied
$ adb shell ls /data/data/com.flcodes.selftest/shared_prefs
ls: /data/data/com.flcodes.selftest/shared_prefs: Permission denied
```

O diretório privado existe, é inacessível ao adb — e ainda assim a chave saiu,
porque quem escreveu o container foi o **aparelho** após o diálogo de backup.

### Achado do aparelho real

O Android grava o JSON **escapado** dentro do XML de SharedPreferences
(`{&quot;parentAccessCode&quot;:…}`). Na primeira execução a chave saiu sem o
TTL; corrigido com `html.unescape` antes de percorrer o JSON embutido, e há
teste (`test_shared_preferences_xml_keeps_the_ttl`).

### Family Link real: o que o CI consegue e o que não consegue

O job `real-family-link` tenta, nesta ordem: `FLCODES_APK_URL` (sua cópia),
Google Play via `apkeep` (login anônimo), APKPure via `apkeep`, API JSON do
APKPure, Aptoide e APKMirror. No runner, **todas falham**:

| fonte | resultado |
|---|---|
| Google Play anônimo | `Could not log in to Google Play. Invalid payload` (Google bloqueia sessão anônima) |
| APKPure via apkeep 1.1.0 | imprime "Downloading…" e não grava arquivo |
| API pureapk.com | sem `download_url` |
| Aptoide | `404` (o app não está lá) |
| APKMirror | download exige POST com token da página |

Conclusão honesta: **o APK do Family Link não é obtível de fonte pública sem
credenciais**. Com a sua cópia, o job roda o mesmo pipeline nela:

```bash
gh secret set FLCODES_APK_URL --repo Enzo-cyber2025/5   # URL do seu APK
gh workflow run flcodes-emulator.yml
```

O job baixa, verifica o assinante (`apksigner --print-certs`), desempacota com
`flcodes apk scan`, instala no emulador, puxa de volta, faz `adb backup`, extrai
e reporta — sem root. Sem conta logada no aparelho o app não grava o config, e o
job diz isso em vez de fingir.

## 4d. Duas contas no mesmo aparelho (executado, verde)

O teste `tools/two_users_test.sh` roda no emulador (Android 11) e cria **dois
perfis** — o que dá para automatizar. Contas Google não: o cadastro abre
verificação por telefone e anti-automação, então as contas de pai e filho
precisam ser criadas por uma pessoa.

Resultado real (run 39875712785, `exit: 0`):

```
Users:
        UserInfo{0:Owner:c13} running
        UserInfo{10:parent:400}
        UserInfo{11:child:400}

package:com.flcodes.selftest        (instalado nos dois perfis)

u10_a130  4734 com.flcodes.selftest
flcodes-selftest: uid 1010130 wrote 117 bytes     <- perfil parent
u11_a130  4943 com.flcodes.selftest
flcodes-selftest: uid 1110130 wrote 117 bytes     <- perfil child

parent uid: 1010130   child uid: 1110130
PASS: dois perfis, app instalado nos dois, cada um escrevendo o próprio
      config privado com um uid Android diferente

adb shell ls /data/data/com.flcodes.selftest/shared_prefs
ls: ... Permission denied        <- e mesmo assim a chave saiu, sem root
```

Limite encontrado: `adb backup` cobre **apenas o perfil do dono** (o Android
recusa para usuários secundários). Por isso a leitura por perfil usa o próprio
app (uid no log) e o `adb backup` fica como caminho de extração do perfil
principal — ambos sem root.

## 4e. Play Store dentro do emulador (pronto, gated em credenciais)

`tools/play_store_reap.sh` sobe a imagem `google_apis_playstore`, entra na conta
por uiautomator, instala o Family Link e — sem root — extrai o APK com
`adb backup -apk`, porque a cópia em `/data/app` não é legível pelo adb:

```bash
FLCODES_GPLAY_EMAIL=... FLCODES_GPLAY_PASSWORD=... \
  tools/play_store_reap.sh --work /tmp/store --api 30
```

No CI isso é o job `play-store`, que só roda quando os secrets
`FLCODES_GPLAY_EMAIL` e `FLCODES_GPLAY_PASSWORD` existem. **Não rodei com conta
real**: não tenho uma, e criar contas Google por automação não é possível
(verificação por telefone, bloqueio anti-bot) — além de violar os termos do
Google. O job, quando há credenciais, faz tudo e publica o resultado no PR; sem
credenciais ele reporta isso explicitamente, sem fingir sucesso.

## 4f. APKs reais de terceiros, sem root (executado, verde)

Job `real-apps` (run [40030745582](https://github.com/Enzo-cyber2025/5/actions/runs/40030745582)),
imagem `google_apis` no QEMU, nenhuma credencial usada.

| alvo | origem | resultado |
|---|---|---|
| `com.google.android.gsf` (Google Services Framework) | `pm path` no `/system/priv-app`, `adb pull` sem root | APK de **93 MB**, 7972 entradas, assinado com a chave de plataforma AOSP (`CN=Android`) |
| `cm.aptoide.pt` 9.22.5.3 | loja instalada por `adb install`, depois `flcodes device apk` | `base.apk` com **4089 entradas**, assinatura V2 verificada (SHA-256 `73534d45…`) |

O que o `flcodes apk scan` tirou desses binários reais, sem desmontar nada:

```
com.google.android.gsf
  config-key: sharedSecret, shared_secret
  endpoint-hint: kidsmanagement, clients6.google.com
  prefs: /data/data/com.google.android.gsf/shared_prefs/CheckinService.xml

cm.aptoide.pt
  backup-flag: allowBackup
  root-hint: /su, Superuser
  native libs: 8 (arm64-v8a, armeabi-v7a, x86, x86_64)
```

Isto prova três coisas que faltavam no relatório:

1. **`adb pull` de APK de sistema sem root funciona** — a extração não depende de
   root nem de credencial; o que depende é a leitura de `/data/data`.
2. **O scanner roda em binários reais e obfuscados** (o Aptoide devolveu
   `no config field names in plain text`, como esperado num APK comercial).
3. **`adb backup` do Aptoide devolve um container vazio (47 bytes)** — app que
   desliga backup não entrega dado nenhum. É exatamente o muro que o Family Link
   coloca, e não é falha do extrator: `flcodes abe scan` diz "nothing to scan".

O que este job **não** faz: processar o APK do Family Link. O binário do Family
Link continua indisponível (ver 4e), então o que está provado aqui é o pipeline +
a assinatura de um app Google real, não a chave daquele app.

### O caminho do APK publicado: sondagem de fontes (outubro/2026)

`tools/probe_apk_sources.sh` foi rodado **dentro do runner** (não do sandbox) e
está no comentário do PR. Resultado bruto:

| fonte | HTTP | nota |
|---|---|---|
| `play.google.com` (página) | 200 | HTML, sem link de download |
| apkmirror (4 rotas), apkpure (4), apkfab, apkgk, aurora | 403 | Cloudflare / bloqueio de IP de datacenter |
| apkcombo, apkcombo.app, apk.support, apkfollow | — | não resolvem DNS |
| `pureapk` API | 200 | 36 bytes: sem `download_url` |

Conclusão honesta: **nenhuma fonte pública entrega o APK para um IP de CI**, e a
Play Store anônima está fechada. Restam os dois caminhos já implementados e
gated em segredo: `FLCODES_APK_URL` (link direto seu) ou `FLCODES_GPLAY_*`
(conta que já tem o app). Sem eles o job `real-family-link` é verde por *skip*,
e diz isso no comentário.

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

## 7. Cobertura de testes (112)

```bash
pytest -q tests/test_flcodes_*.py    # 112 passed
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
