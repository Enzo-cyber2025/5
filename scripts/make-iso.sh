#!/bin/sh
# Assemble NovaLinux hybrid-style UEFI ISO.
set -e
ROOT=/home/user/5
KERN="$ROOT/build/linux/arch/x86/boot/bzImage"
ISO_ROOT="$ROOT/build/iso"
OUT="$ROOT/out"
ISO="$OUT/NovaLinux-1.0-n5030.iso"

if [ ! -f "$KERN" ]; then
    echo "kernel bzImage missing" >&2
    exit 1
fi
if [ ! -f "$OUT/initramfs.cpio.gz" ]; then
    echo "initramfs missing" >&2
    exit 1
fi

rm -rf "$ISO_ROOT"
mkdir -p "$ISO_ROOT/boot" "$ISO_ROOT/EFI/BOOT"

cp -f "$KERN" "$ISO_ROOT/boot/vmlinuz"
# BIOS El Torito loader (patched with kernel LBA by mkiso.py)
cp -f "$ROOT/src/biosboot/biosboot.bin" "$ISO_ROOT/boot/biosboot.bin"
# EFI stub: the kernel itself is the PE executable
cp -f "$KERN" "$ISO_ROOT/EFI/BOOT/BOOTX64.EFI"

cat > "$ISO_ROOT/README.TXT" << 'EOF'
NovaLinux 1.0 — Intel Pentium N5030 (Goldmont Plus)
Boot this image in UEFI mode.
User: nova   Password: nova123
Hostname: novastation
Init: OpenRC    Desktop: NovaUI    Packages: NovaPKG
EOF

# FAT ESP containing the EFI binary
python3 - << PY
from pathlib import Path
import sys
sys.path.insert(0, "/home/user/5/src/novaiso")
from mkiso import write_fat16, write_iso
kern = Path("$KERN").read_bytes()
initrd = Path("$OUT/initramfs.cpio.gz").read_bytes()
write_fat16({
    "EFI/BOOT/BOOTX64.EFI": kern,
    "EFI/BOOT/INITRD.IMG": initrd,
}, "$ISO_ROOT/boot/uefi.img", size=32*1024*1024)
write_iso("$ISO_ROOT", "$ISO")
PY

sha256sum "$ISO" | tee "$ISO.sha256"
ls -lh "$ISO" "$ISO.sha256"
echo "ISO ready: $ISO"
