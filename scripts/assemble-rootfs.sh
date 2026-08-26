#!/bin/sh
# Build the live root filesystem and initramfs.
set -e
ROOT=/home/user/5
RF="$ROOT/build/rootfs"
BB="$ROOT/build/busybox/busybox"
OUT="$ROOT/out"
ISO="$ROOT/build/iso"

rm -rf "$RF"
mkdir -p "$RF"

# directory tree
for d in bin sbin usr/bin usr/sbin usr/lib usr/share/novaui/themes \
         usr/share/novaui/apps usr/share/novaui/wallpapers \
         etc/init.d etc/runlevels/sysinit etc/runlevels/boot \
         etc/runlevels/default etc/runlevels/shutdown \
         etc/novaui home/nova/.config/novaui root tmp run proc sys dev \
         var/lib/novapkg/repo var/lib/novapkg var/cache/novapkg var/log var/run \
         lib lib64 mnt opt media; do
    mkdir -p "$RF/$d"
done
chmod 1777 "$RF/tmp"

# busybox + applets
if [ ! -x "$BB" ]; then
    echo "busybox missing" >&2
    exit 1
fi
cp "$BB" "$RF/bin/busybox"
chmod 755 "$RF/bin/busybox"
# install applets
"$RF/bin/busybox" --install -s "$RF/bin" 2>/dev/null || true
# also put links in sbin
for a in init halt poweroff reboot ifconfig route udhcpc mdev getty \
         insmod lsmod rmmod modprobe swapon swapoff mkswap sysctl \
         switch_root; do
    [ -e "$RF/bin/$a" ] || ln -sf /bin/busybox "$RF/sbin/$a"
    [ -e "$RF/sbin/$a" ] || ln -sf /bin/busybox "$RF/sbin/$a"
done
ln -sf busybox "$RF/bin/sh"
ln -sf busybox "$RF/bin/ash"
[ -e "$RF/sbin/init" ] || ln -sf /bin/busybox "$RF/sbin/init"

# our binaries
cp -f "$OUT/novashell" "$RF/usr/bin/novashell"
cp -f "$OUT/novapkg" "$RF/usr/bin/novapkg"
cp -f "$OUT/novafetch" "$RF/usr/bin/novafetch"
cp -f "$OUT/nova-oom" "$RF/usr/sbin/nova-oom"
cp -f "$OUT/nova-preload" "$RF/usr/sbin/nova-preload"
cp -f "$OUT/autologin" "$RF/usr/bin/autologin"
ln -sf /usr/bin/autologin "$RF/bin/autologin"
cp -f "$OUT/sudo" "$RF/usr/bin/sudo"
chmod 4755 "$RF/usr/bin/sudo"
chmod 755 "$RF/usr/bin/"* "$RF/usr/sbin/"*

# wrappers
for w in novasession novawm novapanel novafiles novaterm novasettings novalaunch; do
    cp -f "$ROOT/overlay/usr/bin/$w" "$RF/usr/bin/$w"
    chmod 755 "$RF/usr/bin/$w"
done

# overlay
cp -a "$ROOT/overlay/etc/." "$RF/etc/"
cp -f "$ROOT/overlay/init" "$RF/init"
chmod 755 "$RF/init" "$RF/etc/init.d/"* "$RF/sbin/"* 2>/dev/null || true
# OpenRC command names
cp -f "$ROOT/overlay/sbin/rc-service" "$RF/sbin/rc-service"
cp -f "$ROOT/overlay/sbin/rc-update" "$RF/sbin/rc-update"
cp -f "$ROOT/overlay/sbin/rc-status" "$RF/sbin/rc-status"
chmod 755 "$RF/sbin/rc-service" "$RF/sbin/rc-update" "$RF/sbin/rc-status" "$RF/etc/init.d/rc"

# runlevels
ln -sf /etc/init.d/hostname   "$RF/etc/runlevels/sysinit/hostname"
ln -sf /etc/init.d/udev       "$RF/etc/runlevels/sysinit/udev"
ln -sf /etc/init.d/sysctl     "$RF/etc/runlevels/boot/sysctl"
ln -sf /etc/init.d/zram       "$RF/etc/runlevels/boot/zram"
ln -sf /etc/init.d/networking "$RF/etc/runlevels/default/networking"
ln -sf /etc/init.d/earlyoom   "$RF/etc/runlevels/default/earlyoom"
ln -sf /etc/init.d/preload    "$RF/etc/runlevels/default/preload"

# themes + wallpaper
cp -f "$ROOT/themes/"*.novatheme "$RF/usr/share/novaui/themes/"
if [ -f "$ROOT/artwork/wallpaper-novastation.png" ]; then
    cp -f "$ROOT/artwork/wallpaper-novastation.png" "$RF/usr/share/novaui/wallpapers/"
fi
if [ -f "$ROOT/artwork/boot-splash.png" ]; then
    cp -f "$ROOT/artwork/boot-splash.png" "$RF/usr/share/novaui/wallpapers/"
fi

# locales
mkdir -p "$RF/usr/share/locale"
printf 'en_US.UTF-8 UTF-8\npt_BR.UTF-8 UTF-8\nes_ES.UTF-8 UTF-8\nfr_FR.UTF-8 UTF-8\n' \
    > "$RF/etc/locale.gen"
echo 'LANG=en_US.UTF-8' > "$RF/etc/locale.conf"
mkdir -p "$RF/etc/profile.d"
cat > "$RF/etc/profile" << 'EOF'
export PATH=/usr/local/bin:/usr/bin:/bin:/sbin:/usr/sbin
export LANG=${LANG:-en_US.UTF-8}
export PS1='\u@\h:\w\$ '
umask 022
EOF

# home
mkdir -p "$RF/home/nova/Desktop" "$RF/home/nova/Documents" "$RF/home/nova/Downloads"
echo "Welcome to NovaLinux." > "$RF/home/nova/Desktop/README.txt"
cat > "$RF/home/nova/.profile" << 'EOF'
export PATH=/usr/local/bin:/usr/bin:/bin:/sbin:/usr/sbin
export LANG=en_US.UTF-8
export EDITOR=vi
EOF
chown -R 1000:1000 "$RF/home/nova" 2>/dev/null || true

# password nova123
if HASH=$(python3 - << 'PY'
import crypt
print(crypt.crypt("nova123", crypt.mksalt(crypt.METHOD_SHA512)))
PY
); then
    sed -i "s|nova:.*|nova:${HASH}:1:0:99999:7:::|" "$RF/etc/shadow"
fi
chmod 640 "$RF/etc/shadow"
chmod 644 "$RF/etc/passwd"

# sample .nvpkg
PKGDIR="$ROOT/build/nvpkg-hello"
rm -rf "$PKGDIR"
mkdir -p "$PKGDIR/root/usr/bin" "$PKGDIR"
cat > "$PKGDIR/metadata.json" << 'EOF'
{
  "name": "hello-nova",
  "version": "1.0.0",
  "arch": "x86_64",
  "description": "Sample NovaPKG hello package",
  "depends": [],
  "files": ["usr/bin/hello-nova"]
}
EOF
printf '#!/bin/sh\necho Hello from NovaPKG on NovaLinux\n' > "$PKGDIR/root/usr/bin/hello-nova"
chmod 755 "$PKGDIR/root/usr/bin/hello-nova"
( cd "$PKGDIR" && tar -cJf "$RF/var/lib/novapkg/repo/hello-nova.nvpkg" metadata.json root )

# motd
cat > "$RF/etc/motd" << 'EOF'

  NovaLinux 1.0  —  Intel Pentium N5030 (Goldmont Plus)
  Desktop: NovaUI     Packages: NovaPKG     Init: OpenRC

EOF

# cpio initramfs
echo "Creating initramfs..."
python3 "$ROOT/scripts/mkcpio.py" "$RF" /tmp/initramfs.cpio
gzip -9 -c /tmp/initramfs.cpio > "$OUT/initramfs.cpio.gz"
ls -lh "$OUT/initramfs.cpio.gz"
echo "rootfs ready at $RF"
