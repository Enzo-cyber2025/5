#!/usr/bin/env python3
"""Configure Linux 6.6 without bison/flex using Kconfiglib."""
import os
import shutil
import sys
from pathlib import Path

ROOT = Path("/home/user/5")
LINUX = ROOT / "build/linux"
KLIB = ROOT / "build/Kconfiglib"
INITRAMFS = ROOT / "out/initramfs.cpio.gz"

os.environ.setdefault("srctree", str(LINUX))
os.environ.setdefault("CC", "gcc")
os.environ.setdefault("HOSTCC", "gcc")
os.environ.setdefault("LD", "ld")
os.environ.setdefault("ARCH", "x86")
os.environ.setdefault("SRCARCH", "x86")
os.environ.setdefault("KERNELVERSION", "6.6.153")
os.environ.setdefault("cc-option-yn", "n")
os.environ.setdefault("RUSTC", "false")

sys.path.insert(0, str(KLIB))
os.chdir(LINUX)

from kconfiglib import Kconfig  # noqa: E402

print("loading Kconfig...")
kconf = Kconfig("Kconfig", warn=False)

defcfg = LINUX / "arch/x86/configs/x86_64_defconfig"
print("loading", defcfg)
kconf.load_config(str(defcfg))

FRAGMENT = {
    "WERROR": "n",
    "MODULE_SIG": "n",
    "MODULE_SIG_ALL": "n",
    "SYSTEM_TRUSTED_KEYRING": "n",
    "SYSTEM_REVOCATION_LIST": "n",
    "DEBUG_INFO": "n",
    "DEBUG_INFO_NONE": "y",
    "DEBUG_INFO_DWARF_TOOLCHAIN_DEFAULT": "n",
    "DEBUG_INFO_BTF": "n",
    "DEBUG_KERNEL": "n",
    "DEBUG_WX": "n",
    "DEBUG_STACK_USAGE": "n",
    "DEBUG_DEVRES": "n",
    "DEBUG_BOOT_PARAMS": "n",
    "PM_DEBUG": "n",
    "UNWINDER_ORC": "n",
    "UNWINDER_FRAME_POINTER": "y",
    "STACK_VALIDATION": "n",
    "FRAMEBUFFER_CONSOLE": "y",
    "FRAMEBUFFER_CONSOLE_DETECT_PRIMARY": "y",
    "FB": "y",
    "FB_VESA": "y",
    "FB_EFI": "y",
    "DRM": "y",
    "DRM_FBDEV_EMULATION": "y",
    "DRM_SIMPLEDRM": "y",
    "DRM_BOCHS": "y",
    "DRM_VMWGFX": "y",
    "DRM_VBOXVIDEO": "y",
    "DRM_VIRTIO_GPU": "y",
    "DRM_I915": "y",
    "SYSFB": "y",
    "SYSFB_SIMPLEFB": "y",
    "VT": "y",
    "VT_CONSOLE": "y",
    "VGA_CONSOLE": "y",
    "DUMMY_CONSOLE": "y",
    "INPUT": "y",
    "INPUT_EVDEV": "y",
    "INPUT_KEYBOARD": "y",
    "KEYBOARD_ATKBD": "y",
    "INPUT_MOUSE": "y",
    "MOUSE_PS2": "y",
    "MOUSE_PS2_VMMOUSE": "y",
    "SERIO": "y",
    "SERIO_I8042": "y",
    "SERIO_LIBPS2": "y",
    "UNIX98_PTYS": "y",
    "DEVTMPFS": "y",
    "DEVTMPFS_MOUNT": "y",
    "BLK_DEV_INITRD": "y",
    "EFI": "y",
    "EFI_STUB": "y",
    "CMDLINE_BOOL": "y",
    "CMDLINE": "console=tty0 earlyprintk=vga loglevel=7 mitigations=off intel_idle.max_cstate=4",
    "CPU_FREQ_DEFAULT_GOV_SCHEDUTIL": "y",
    "HZ_1000": "y",
    "SECURITY_SELINUX": "n",
    "DEFAULT_SECURITY_SELINUX": "n",
    "DEFAULT_SECURITY_DAC": "y",
    "IKHEADERS": "n",
    "RUST": "n",
    "KPROBES": "n",
    "CRASH_DUMP": "n",
    "HIBERNATION": "n",
    "PROFILING": "n",
    "KALLSYMS_ALL": "n",
    "PRINTK_TIME": "y",
    "EARLY_PRINTK": "y",
    "EARLY_PRINTK_DBGP": "y",
    "EXPERT": "y",
    "EMBEDDED": "y",
}

if INITRAMFS.is_file():
    FRAGMENT["INITRAMFS_SOURCE"] = str(INITRAMFS)
    FRAGMENT["INITRAMFS_COMPRESSION_GZIP"] = "y"

for name, val in FRAGMENT.items():
    sym = kconf.syms.get(name)
    if not sym:
        print("skip unknown", name)
        continue
    try:
        if val in ("y", "n", "m"):
            sym.set_value({"n": 0, "m": 1, "y": 2}[val] if sym.orig_type in (2, 3) else val)
            # BOOL=2, TRISTATE=3 in older kconfiglib; just assign string
            sym.set_value(val)
        else:
            sym.set_value(val)
    except Exception as e:
        print("set", name, val, "failed", e)

print("olddefconfig...")
# assign defaults for unset symbols
for sym in kconf.unique_defined_syms:
    if not sym.user_value and sym.name:
        try:
            # leave defaults
            pass
        except Exception:
            pass

kconf.write_config(str(LINUX / ".config"))
print("wrote .config")

# headers
inc = LINUX / "include"
(inc / "config").mkdir(parents=True, exist_ok=True)
(inc / "generated").mkdir(parents=True, exist_ok=True)
kconf.write_autoconf(str(inc / "generated/autoconf.h"))
# auto.conf is CONFIG_FOO=y lines
auto = []
for sym in kconf.unique_defined_syms:
    if not sym.name:
        continue
    v = sym.str_value
    if v == "n" or v == "":
        continue
    auto.append(f"CONFIG_{sym.name}={v}\n")
(inc / "config/auto.conf").write_text("".join(auto))
(inc / "config/auto.conf.cmd").write_text("deps_config :=\n$(deps_config): ;\n")
(inc / "generated/autoconf.h").touch()
print("wrote autoconf, symbols", len(auto))

# sanity
cfg = (LINUX / ".config").read_text()
for need in [
    "CONFIG_X86_64=y",
    "CONFIG_64BIT=y",
    "CONFIG_FB=y",
    "CONFIG_EFI_STUB=y",
    "CONFIG_BLK_DEV_INITRD=y",
    "CONFIG_DEVTMPFS=y",
]:
    print(need, need in cfg or need.replace("=y", "") in cfg)

for key in ["INITRAMFS_SOURCE", "DRM_VMWGFX", "FB_VESA", "FRAMEBUFFER_CONSOLE", "UNWINDER_FRAME_POINTER"]:
    for line in cfg.splitlines():
        if key in line and not line.startswith("# "):
            print(" ", line)
            break
    else:
        print(" MISSING", key)
