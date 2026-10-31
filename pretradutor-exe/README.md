# Pré-Tradutor EXE (protótipo heurístico) — app novo e independente

**[Baixar APK](release/PreTradutorEXE.apk)** · SHA-256 em `release/PreTradutorEXE.apk.sha256` ·
Android 8+ (minSdk 26) · pacote `com.exepretranslator.app`.

Este app **não tem relação com o GGUF Chat** deste repositório — é um projeto novo,
separado, criado a pedido específico de um "app de pré-tradução de .exe".

## O que ele realmente faz

1. Você escolhe um arquivo `.exe` do armazenamento do celular.
2. O app lê o cabeçalho real do arquivo (formato PE do Windows: assinatura
   `MZ`, cabeçalho PE, tabela de seções) e localiza a seção de código
   executável (ex.: `.text`).
3. Ele percorre os bytes dessa seção **decodificando o comprimento de cada
   instrução x86/x86-64** com uma tabela de opcodes feita à mão (cobre as
   instruções mais comuns geradas por compiladores: `mov`, `push`/`pop`,
   `add`/`sub`/`cmp`/`test`/`and`/`or`/`xor`, `lea`, `call`/`jmp`/`jcc`,
   `ret`, `nop`, prefixos REX/operand-size, ModRM/SIB/deslocamento/imediato).
4. Para cada instrução reconhecida, grava uma linha de texto com: deslocamento
   no arquivo, bytes em hexadecimal, o mnemônico x86 e uma dica textual de
   equivalente ARM64 (quando existe uma correspondência simples mapeada).
   Isso é salvo incrementalmente em
   `Android/data/com.exepretranslator.app/files/pretranslated.txt` (texto
   simples, para revisão humana).
5. Isso roda numa **foreground service** com notificação, então continua
   processando **mesmo com a tela bloqueada**. O progresso (byte processado /
   total da seção de código) é salvo a cada bloco lido, e a porcentagem
   aparece na tela principal e na notificação. Se você fechar o app ou o
   sistema matar o processo, o próximo "Iniciar / continuar" retoma do byte
   onde parou (não refaz do zero).

## Novo: modo experimental que **de fato executa** um `.exe`

Além da pré-tradução/anotação acima (que funciona com qualquer `.exe` real,
mas só lê e anota, nunca executa), o app agora tem um segundo recurso, bem
mais limitado e explícito: um **interpretador x86 real** (`ExecuteService`)
que de fato decodifica, a partir da pré-tradução, e **executa** instruções
x86 de 32 bits (mov, add, sub, cmp, push/pop, jmp, jg, ret) sobre um arquivo
PE32 carregado na memória do app, usando registradores e pilha simulados de
verdade — e mostra o resultado calculado na tela.

Toque **"Executar exemplo embutido (experimental)"**: o app roda um
programa de teste minúsculo, embutido no APK (`assets/teste.exe`, 8 KB, um
PE32 feito à mão por mim para este fim), que soma 1+2+3+4+5 num laço com
comparação e desvio condicional reais. Se tudo correr bem, o resultado
mostrado é **15**. A lógica de decodificação/execução foi validada
separadamente (réplica fiel em Python do mesmo algoritmo, rodando contra os
mesmos bytes) antes de ser escrita em smali, porque não há como rodar o APK
de verdade nesta sandbox — mas, de novo, **isso não substitui testar no
celular**.

**Isto não é o mesmo que "rodar programas reais do Windows":**
- Só entende um subconjunto pequeno de instruções x86 de 32 bits (PE32, não
  PE32+/64-bit) — exatamente o necessário para funções simples com
  variáveis locais, aritmética, comparação e laços. Instruções fora desse
  subconjunto (a enorme maioria do que um programa real usa, incluindo
  **qualquer chamada a uma API do Windows** como abrir uma janela, desenhar
  algo na tela, ler um arquivo, etc.) fazem a execução **parar
  imediatamente** no ponto não suportado, informando o endereço — não
  trava, não finge, apenas avisa claramente que chegou ao limite.
- Não existe nenhuma implementação de `kernel32`/`user32`/`gdi32`/etc., nem
  carregamento de DLLs, nem suporte a interface gráfica.
- Por isso, um `.exe` real do Windows (que depende de centenas dessas
  chamadas desde a primeira instrução gerada pelo compilador/CRT) **vai
  parar quase imediatamente** se você tentar "executar" ele neste modo —
  ele serve para pequenas rotinas de cálculo próprias, não para rodar
  programas de terceiros.
- Seção de código limitada a 64 KB e imagem total a 16 MB nesse modo
  (limites de segurança para não estourar a memória do app).

## O que ele **não** é (para não criar expectativa errada)

- **Não é um emulador do Windows.** Não executa o `.exe`, não roda o
  programa, não produz um `.exe` traduzido nem qualquer binário executável.
  "Tradução" aqui significa leitura/anotação das instruções, não emulação
  nem recompilação (isso é um projeto de anos, do tamanho de Wine/Box86 —
  fora do escopo do que pode ser entregue aqui).
- A cobertura de opcodes é **aproximada**: cobre a grande maioria das
  instruções comuns em código compilado normal, mas instruções raras,
  SSE/AVX completas, FPU detalhado ou opcodes exóticos caem num modo
  aproximado (ou em "opcode não mapeado"), podendo, em casos raros,
  desalinhar a leitura de uma instrução seguinte.
- Deslocamentos/tamanhos são tratados como inteiros de 32 bits — arquivos
  absurdamente grandes (>2 GB) não são suportados.
- **Não foi testado em um dispositivo ou emulador Android real.** Este
  ambiente de trabalho não tem um emulador Android disponível. O único
  nível de verificação possível aqui foi: (a) o bytecode monta sem erros no
  assembler smali, (b) o APK final foi decodificado de volta com sucesso
  (dex estruturalmente válido), (c) a assinatura verifica com `apksigner`,
  e (d) `aapt2 dump badging` confirma manifesto, permissões e atividade
  principal corretos. Isso **não substitui** rodar de verdade num celular.
  Pode haver bugs de execução (crash, permissão, etc.) que só apareceriam
  ao instalar e usar.

## Como testar

1. Instale `release/PreTradutorEXE.apk` num Android 8+ (ative "fontes
   desconhecidas"/"instalar apps desconhecidos" para o navegador/gerenciador
   de arquivos usado).
2. Abra o app, toque **Selecionar .exe** e escolha um arquivo.
3. Toque **Iniciar / continuar pré-tradução**. Aceite a permissão de
   notificação se for pedida (Android 13+).
4. Bloqueie a tela — o processamento continua em segundo plano (há uma
   notificação fixa com a porcentagem).
5. O rascunho da tradução fica em texto simples dentro da pasta privada do
   app (acessível via um gerenciador de arquivos com acesso a
   `Android/data`, em aparelhos que ainda permitem isso, ou via `adb pull`).
6. Para testar o modo de execução experimental, toque **"Executar exemplo
   embutido (experimental)"** e veja o campo "Execucao:" mudar para
   `concluido (resultado=15)`. Se aparecer `erro`, a mensagem explica onde
   a execução parou.

## Por que o pacote de ferramentas é diferente do resto do repositório

O restante do repositório só faz *patch* binário em um APK já compilado
(nunca recria manifesto/recursos do zero). Para este app novo, com
atividade e manifesto próprios, foi necessário compilar um AndroidManifest
binário e um `classes.dex` do zero. Esta sandbox não tem acesso ao Android
SDK oficial (`dl.google.com` não está liberado), então o build usa:

- `jdk4py` (PyPI) — fornece `java`/`keytool`.
- `@postar/apktool-node` (npm) — fornece `apktool.jar` (monta `.smali` →
  `classes.dex`) e `apksigner.jar` (assinatura oficial do Android, sem
  implementação própria de assinatura).
- `aaptjs3` (npm) — fornece o binário oficial `aapt2` do Google (Linux x64),
  usado só para compilar o manifesto/recursos.

Tudo isso vem de `registry.npmjs.org` e `pypi.org`, hosts já liberados neste
ambiente. Veja `scripts/build.sh` para reproduzir o build inteiro do zero.

## Código-fonte

- `src/AndroidManifest.xml` — manifesto (permissões, atividade, serviço).
- `src/smali/.../MainActivity.smali` — tela única (sem XML de layout; a UI é
  montada por código), seletor de arquivo (SAF), barra de progresso, status.
- `src/smali/.../TranslateService.smali` — parsing do cabeçalho PE,
  mecanismo de leitura de comprimento de instrução x86, geração das linhas
  de saída, notificação em primeiro plano, retomada de progresso.
- `src/smali/.../ExecuteService.smali` — parser PE32 completo (seções,
  ponto de entrada, base de imagem), decodificador/cache de instruções
  x86 de 32 bits e o interpretador que de fato executa essas instruções
  (registradores, pilha e memória virtual simulados).
- `src/assets/teste.exe` — PE32 de 8 KB, montado byte a byte à mão para
  este projeto, usado pelo botão "Executar exemplo embutido".

Este app foi escrito diretamente em smali (bytecode Dalvik textual) porque
não há, nesta sandbox, um compilador Java→dex oficial (`d8`/`dx`) — apenas o
assembler smali embutido no apktool. Isso é incomum e mais arriscado que o
caminho normal (Kotlin/Java + Gradle); trate este app como um protótipo.
