# Especificações de pacotes `.nvpkg` do NovaLinux

Cada arquivo `*.json.nvpspec` nesta pasta é um **manifesto** que descreve como
compilar um aplicativo para Intel Pentium N5030 (Goldmont Plus) e empacotá-lo
no formato `.nvpkg`. O orquestrador `build_apps.sh` lê esses manifestos,
compila (`-O3 -march=goldmont-plus -mtune=goldmont-plus -pipe -flto=auto`),
e gera o pacote com `nova-pkg build`.

Os aplicativos obrigatórios são:

| Pacote            | Descrição                                    |
|-------------------|----------------------------------------------|
| firefox-esr       | Browser Mozilla Firefox ESR                  |
| libreoffice       | Suite de escritório (Writer/Calc/Impress)    |
| gimp              | Editor de imagens                            |
| vlc               | Player multimídia                            |
| htop              | Monitor de processos                          |
| neofetch          | Info do sistema                               |
| git / curl / wget | Ferramentas de rede/segurança                 |
| nano / vim        | Editores de texto                             |
| openssh           | Servidor/cliente SSH                          |
| networkmanager    | Gerenciamento de rede                         |
| pulseaudio        | Servidor de áudio PulseAudio                  |
| pipewire          | Áudio/vídeo moderno                           |
| cups              | Impressão                                     |
| samba             | Compartilhamento de arquivos                  |
| earlyoom          | OOM killer antecipado                         |
| preload           | Pré-carregamento de binários                  |
| zstd              | Compressor                                    |

## Formato do manifesto (`*.nvpspec`)

```json
{
  "name": "htop",
  "version": "3.2.2",
  "arch": "x86_64",
  "source": "https://github.com/htop-dev/htop/archive/refs/tags/3.2.2.tar.gz",
  "build_deps": ["ncurses-dev", "autoconf", "automake"],
  "configure": "./autogen.sh && ./configure --prefix=/usr",
  "make": "make -j$(nproc)",
  "install_staging": "make install DESTDIR=$STAGE",
  "depends": ["glibc"],
  "description": "Monitor de processos interativo"
}
```

`build_apps.sh` executará `configure` e `make` dentro de um diretório temporário,
copiará os artefatos para um *staging* e chamará `nova-pkg build` para gerar o
arquivo `.nvpkg` final.
