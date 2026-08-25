# Formato de pacote `.nvpkg` — NovaPKG

Um pacote `.nvpkg` é um **arquivo tar comprimido com xz** (`tar.xz`), contendo os
arquivos do programa **mais** um arquivo de metadados JSON. Em outras palavras:

```
pacote.nvpkg  ==  tar.xz  |  contendo:
                    .novapkg/metadata.json     (obrigatório)
                    .novapkg/pre_install.sh    (opcional)
                    .novapkg/post_install.sh   (opcional)
                    .novapkg/pre_remove.sh     (opcional)
                    .novapkg/post_remove.sh    (opcional)
                    usr/bin/...                (payload: arquivos do programa)
                    usr/lib/...                (payload)
                    etc/...                    (payload)
```

## `metadata.json`

```json
{
  "name": "nova-utils",
  "version": "1.0.0",
  "release": 1,
  "arch": "x86_64",
  "description": "Utilitários básicos do NovaLinux",
  "license": "BSD-2-Clause",
  "maintainer": "Nova Project <nova@novastation>",
  "dependencies": ["glibc"],
  "provides": [],
  "conflicts": [],
  "scripts": {
    "pre_install":  ".novapkg/pre_install.sh",
    "post_install": ".novapkg/post_install.sh",
    "pre_remove":   ".novapkg/pre_remove.sh",
    "post_remove":  ".novapkg/post_remove.sh"
  },
  "installed_size": 1048576,
  "build": {
    "compiler": "gcc",
    "optimization": "-O3 -march=goldmont-plus -mtune=goldmont-plus -pipe -flto=auto"
  }
}
```

## Regras do formato

1. Os metadados **sempre** vivem dentro do caminho `.novapkg/` na raiz do archive.
2. Os arquivos do programa (payload) usam caminhos **absolutos relativos** à raiz do
   sistema (ex.: `usr/bin/foo`, `etc/foo.conf`). Nunca haverá `./` no início.
3. Não são permitidos caminhos com `..`, caminhos absolutos iniciando por `/` no
   payload, nem hard links/device nodes por segurança no presente formato (apenas
   arquivos regulares e symlinks).
4. Os scripts de ciclo de vida (quando presentes) são executados por `sh -e`,
   com a raiz do sistema definida por `$ROOT` (para instalação em sistema de destino).

## Como criar um `.nvpkg`

```sh
nova-pkg build --name pacote --version 1.0.0 --staging ./stage .
```

ou manualmente:

```sh
tar -cJf pacote.nvpkg .novapkg usr etc
```
