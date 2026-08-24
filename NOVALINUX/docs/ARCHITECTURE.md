# Arquitetura do NovaLinux

## Visão geral em camadas

```
+------------------------------------------------------------+
|  Aplicativos (Firefox ESR, LibreOffice, GIMP, VLC, ...)     |
|                  empacotados como .nvpkg                      |
+------------------------------------------------------------+
|  NovaUI (interface 100% original)                           |
|   NovaWM  |  NovaPanel  |  NovaTerm  |  NovaFiles  |        |
|   NovaConfig (central)  |  NovaLauncher (Alt+Espaço)        |
+------------------------------------------------------------+
|  X11 (Xlib) + Cairo + Pango + FreeType + libinput + GL/Vulkan|
+------------------------------------------------------------+
|  OpenRC (init; proibido systemd)  |  NovaPKG (pkg manager)  |
+------------------------------------------------------------+
|  Kernel Linux 6.6.x LTS (patches Goldmont Plus)            |
+------------------------------------------------------------+
|  Hardware: Intel Pentium N5030 (Goldmont Plus, x86_64)      |
+------------------------------------------------------------+
```

## Componentes

### Kernel
- `6.6.x` LTS, compilado com `KCFLAGS=-O3 -pipe -march=goldmont-plus -mtune=goldmont-plus`.
- Patches: `kernel/patches/0001-nova-goldmont-plus-tuning.patch` (documentação + schedutil default).
- Config de referência: `kernel/config.nova`.
- Boot: `quiet loglevel=3 mitigations=off intel_idle.max_cstate=4`.

### Toolchain
- Bootstrap em 2 estágios (`build_toolchain.sh`): binutils 2.41 → glibc 2.38 →
  gcc 13.2, instalados em `SYSROOT_DIR` (`/tools`), todos com
  `-O3 -pipe -flto=auto -march=goldmont-plus -mtune=goldmont-plus`.
- Recompilação stage-1 para garantir toolchain dominante.

### Init
- `OpenRC` (0.45.2), `sbin/init` → `openrc-init`. Services em `rootfs/etc/init.d/`.

### NovaUI (sem toolkit)
Cada binário é um processo X11 que desenha com Cairo/Pango:

| Binário        | Arquivo       | Função                                          |
|----------------|---------------|-------------------------------------------------|
| `novawm`       | `src/wm.c`    | Gerenciador de janelas (decoração, mover, foco, Alt+Tab, Alt+Espaço) |
| `nova-panel`   | `src/panel.c` | Painel inferior: tasks, relógio, indicadores    |
| `nova-terminal`| `src/terminal.c` | Emulador VT100 via forkpty + Cairo/Pango      |
| `nova-files`   | `src/files.c` | Gerenciador de arquivos (grid, navegação)       |
| `nova-config`  | `src/config.c`| Central: rede, áudio, vídeo, teclado, mouse, energia, aparência |
| `nova-launcher`| `src/launcher.c`| Lançador rápido (Alt+Espaço)                   |

O launcher é acionado pelo WM via um `ClientMessage` com átomo `novalaunch`.
Temas: `novaui/themes/*.novatheme` (claro/escuro), com cores, fontes e métricas.

### NovaPKG
- `novapkg/novapkg` — comando único com `install|remove|update|search|info|list|build`.
- Formato `.nvpkg`: `tar.xz` com `.novapkg/metadata.json` + payload (ver `novapkg/format.md`).
- Especificações de apps: `novapkg/specs/*.json.nvpspec`.

### Boot / ISO
- GRUB 2.12 com `grub.cfg` e tema `novatheme`.
- `initramfs` com dracut; kernel + initramfs empacotados num **ISO híbrido**
  (UEFI via GPT/El Torito + BIOS legado) gerado com `xorriso`.

## Otimizações para N5030

| Área | Configuração |
|------|--------------|
| CPU freq. | `CONFIG_CPU_FREQ_DEFAULT_GOV_SCHEDUTIL=y`, `CONFIG_HZ_1000=y` |
| Swap | zram + zstd (`CONFIG_ZRAM_DEF_COMP_ZSTD`), `vm.swappiness=10` |
| Página | `vm.vfs_cache_pressure=50` |
| OOM    | `earlyoom` em OpenRC |
| Preload| `preload` em OpenRC |
| ext4   | `noatime,commit=120,data=ordered` |
| Boot   | `quiet loglevel=3 mitigations=off intel_idle.max_cstate=4` |
