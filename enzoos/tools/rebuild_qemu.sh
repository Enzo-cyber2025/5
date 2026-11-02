#!/bin/bash
# =============================================================================
#  EnzoOS — tools/rebuild_qemu.sh
#  Reconstrói QEMU 3.1.0 (x86_64-softmmu) sem apt/pkg-config/autoconf.
#  Rede permitida: codeload.github.com (tarballs) + pypi (meson/ninja/cmake).
#  Instala em /tmp/ql/bin/qemu-system-x86_64 e copia para tools/toolchain/bin/.
#  Lições embutidas (2026-11-01):
#   - shim pkg-config PRECISA responder --version e Version: dos .pc
#   - glib: gvdb INTEIRO em subprojects/gvdb + -Dgvdb:tests=false
#   - keycodemapdb tem que ser o de 2018 (16e5b07) p/ qemu 3.1
#   - pixman sem configure: config.h manual (PACKAGE, TLS, TOOLCHAIN__THREAD)
#     + pixman-version.h com macro PIXMAN_VERSION + PIXMAN_API no header instalado
#   - libffi: header gerado do ffi.h.in + .so do sistema
#   - pcre2: cmake do pypi (tarball git não tem configure)
#   - link final: --extra-ldflags com -L (ordem -L/-l)
# =============================================================================
set -e
B=/tmp/qb
INST=$B/inst
TC=/home/user/5/enzoos/tools/toolchain
mkdir -p $B/src $INST $B/bin
cd $B/src

# ---------- 0) pip meson/ninja/cmake ----------
export PATH=$HOME/.local/bin:$PATH
command -v meson >/dev/null || pip3 install --quiet --break-system-packages --user meson ninja
command -v cmake >/dev/null || pip3 install --quiet --break-system-packages --user cmake
command -v ninja  >/dev/null || pip3 install --quiet --break-system-packages --user ninja

# ---------- 1) downloads ----------
dl() { [ -s "$2" ] || curl -sL "$1" -o "$2"; }
dl https://codeload.github.com/qemu/qemu/tar.gz/refs/tags/v3.1.0 qemu.tgz &
dl https://codeload.github.com/madler/zlib/tar.gz/refs/tags/v1.3.1 zlib.tgz &
dl https://codeload.github.com/PCRE2Project/pcre2/tar.gz/refs/tags/pcre2-10.42 pcre2.tgz &
dl https://codeload.github.com/libffi/libffi/tar.gz/refs/tags/v3.4.4 ffi.tgz &
dl https://codeload.github.com/GNOME/glib/tar.gz/refs/tags/2.74.7 glib.tgz &
dl https://codeload.github.com/GNOME/gvdb/tar.gz/refs/heads/main gvdb.tgz &
dl https://codeload.github.com/aseprite/pixman/tar.gz/refs/heads/master pixman.tgz &
dl https://codeload.github.com/qemu/keycodemapdb/tar.gz/16e5b0787687 kcm.tgz &
wait
for f in qemu zlib pcre2 ffi glib gvdb pixman kcm; do tar xzf $f.tgz; done
QEMU=$(ls -d qemu-3.1.0); PCRE2=$(ls -d pcre2-pcre2-* | head -1); FFI=$(ls -d libffi-3.4.4)
GLIB=$(ls -d glib-2.74.7); GVDB=$(ls -d gvdb-main); PIX=$(ls -d pixman-master); KCM=$(ls -d keycodemapdb-16e5b0787687)

# ---------- 2) shim pkg-config ----------
cat > $B/bin/pkg-config <<'PCEOF'
#!/usr/bin/env python3
import sys, os
PC = [d for d in os.environ.get('PKG_CONFIG_PATH','').split(':') if d]
PC.append('/tmp/qb/inst/lib/pkgconfig')
PC.append('/tmp/qb/inst/lib/x86_64-linux-gnu/pkgconfig')
PC.append('/tmp/qb/inst/share/pkgconfig')
def find(name):
    for d in PC:
        p = os.path.join(d, name + '.pc')
        if os.path.exists(p): return p
def parse(p):
    vars = {}; lines = []
    txt = open(p).read().replace('\\\n', ' ')
    for ln in txt.split('\n'):
        ln = ln.strip()
        if not ln or ln.startswith('#'): continue
        if '=' in ln and (':' not in ln or ln.index('=') < ln.index(':')):
            k, v = ln.split('=', 1); vars[k.strip()] = v.strip()
        elif ':' in ln:
            k, v = ln.split(':', 1); lines.append((k.strip(), v.strip()))
    def subst(s):
        out = ''; i = 0
        while i < len(s):
            if s[i] == '$':
                if s[i+1:i+2] == '{':
                    j = s.index('}', i); out += subst(vars.get(s[i+2:j], '')); i = j+1
                else:
                    j = i+1
                    while j < len(s) and (s[j].isalnum() or s[j] == '_'): j += 1
                    out += subst(vars.get(s[i+1:j], '')); i = j
            else: out += s[i]; i += 1
        return out
    d = {}
    for k, v in lines: d[k] = subst(v)
    return d
def load(name, seen=()):
    if name in seen: return {}
    p = find(name)
    if not p: return None
    d = parse(p)
    req = d.get('Requires','') + ' ' + d.get('Requires.private','')
    cf = d.get('Cflags',''); lb = d.get('Libs',''); lp = d.get('Libs.private','')
    for r in req.split():
        if r in ('>','<','>=','<=','='): continue
        rd = load(r, seen + (name,))
        if rd:
            cf += ' ' + rd.get('cflags',''); lb += ' ' + rd.get('libs','')
    return {'cflags': cf, 'libs': lb, 'libs_priv': lp, 'version': d.get('Version','')}
args = sys.argv[1:]
want_c = want_l = want_e = want_v = False
for a in args:
    if a == '--version': print('0.29.2'); sys.exit(0)
    if a == '--about':   print('shim');   sys.exit(0)
    if a == '--cflags':      want_c = True
    elif a == '--libs':      want_l = True
    elif a == '--exists':    want_e = True
    elif a == '--modversion': want_v = True
names = [a for a in args if not a.startswith('-')]
ok = True; cf = []; lb = []; mv = []
for n in names:
    d = load(n)
    if d is None: ok = False; continue
    if want_c and d.get('cflags'): cf.append(d['cflags'])
    if want_l: lb.append((d.get('libs','') + ' ' + d.get('libs_priv','')).strip())
    if want_v: mv.append(d.get('version','0.0'))
if want_e: sys.exit(0 if ok else 1)
if want_v: print(' '.join(mv) if mv else '0.0'); sys.exit(0 if ok else 1)
if cf: print(' '.join(cf).replace('  ',' ').strip())
if lb: print(' '.join(lb).replace('  ',' ').strip())
sys.exit(0 if ok else 1)
PCEOF
chmod +x $B/bin/pkg-config
export PATH=$B/bin:$HOME/.local/bin:$PATH
export PKG_CONFIG_PATH=$INST/lib/pkgconfig:$INST/lib/x86_64-linux-gnu/pkgconfig:$INST/share/pkgconfig

# ---------- 3) zlib ----------
[ -f $INST/lib/libz.a ] || { cd $B/src/$PIX >/dev/null 2>&1; cd $B/src/zlib-1.3.1 && ./configure --prefix=$INST --static >/dev/null && make -j2 >/dev/null 2>&1 && make install >/dev/null; }
echo "zlib ok"

# ---------- 4) pcre2 (cmake) ----------
[ -f $INST/lib/libpcre2-8.a ] || { cd $B/src/$PCRE2 && cmake -S . -B bld -DCMAKE_INSTALL_PREFIX=$INST -DBUILD_SHARED_LIBS=OFF -DPCRE2_BUILD_PCRE2_8=ON -DPCRE2_BUILD_PCRE2_16=OFF -DPCRE2_BUILD_PCRE2_32=OFF -DPCRE2_SUPPORT_UNICODE=ON -DPCRE2_BUILD_PCRE2GREP=OFF -DPCRE2_BUILD_PCRE2TEST=OFF -DCMAKE_POLICY_VERSION_MINIMUM=3.5 >/dev/null && cmake --build bld -j2 >/dev/null && cmake --install bld >/dev/null; }
echo "pcre2 ok"

# ---------- 5) libffi (header manual + .so do sistema) ----------
if [ ! -f $INST/lib/pkgconfig/libffi.pc ]; then
  mkdir -p $INST/include $INST/lib/pkgconfig
  cd $B/src/$FFI
  sed -e 's/@TARGET@/X86_64/' -e 's/@HAVE_LONG_DOUBLE@/1/' -e 's/@FFI_EXEC_TRAMPOLINE_TABLE@/0/' -e 's/@VERSION@/3.4.4/' include/ffi.h.in > $INST/include/ffi.h
  cp include/ffi_cfi.h include/tramp.h include/ffi_common.h src/x86/ffitarget.h $INST/include/
  ln -sf /lib/x86_64-linux-gnu/libffi.so.8 $INST/lib/libffi.so
  printf 'prefix=%s\nName: libffi\nDescription: libffi (system)\nVersion: 3.4.4\nLibs: -L${prefix}/lib -lffi\nCflags: -I${prefix}/include\n' $INST > $INST/lib/pkgconfig/libffi.pc
fi
echo "ffi ok"

# ---------- 6) pixman (gcc manual) ----------
if [ ! -f $INST/lib/libpixman-1.a ]; then
  cd $B/src/$PIX/pixman && mkdir -p bld && cd bld
  cat > config.h <<'CFG'
#define PIXMAN_API /**/
#define SIZEOF_LONG 8
#define HAVE_64BIT 1
#define PACKAGE pixman
#define PACKAGE_VERSION 0.40.1
#define TOOLCHAIN_SUPPORTS__THREAD 1
#define TLS __thread
CFG
  cat > pixman-version.h <<'VH'
#ifndef PIXMAN_VERSION_H__
#define PIXMAN_VERSION_H__
#define PIXMAN_VERSION_MAJOR 0
#define PIXMAN_VERSION_MINOR 40
#define PIXMAN_VERSION_MICRO 1
#define PIXMAN_VERSION ((0 << 16) | (40 << 8) | 1)
#define PIXMAN_VERSION_STRING "0.40.1"
#endif
VH
  SRCS="pixman.c pixman-access.c pixman-access-accessors.c pixman-bits-image.c pixman-combine32.c pixman-combine-float.c pixman-conical-gradient.c pixman-filter.c pixman-x86.c pixman-mips.c pixman-arm.c pixman-ppc.c pixman-edge.c pixman-edge-accessors.c pixman-fast-path.c pixman-glyph.c pixman-general.c pixman-gradient-walker.c pixman-image.c pixman-implementation.c pixman-linear-gradient.c pixman-matrix.c pixman-noop.c pixman-radial-gradient.c pixman-region16.c pixman-region32.c pixman-solid-fill.c pixman-timer.c pixman-trap.c pixman-utils.c"
  for s in $SRCS; do gcc -O2 -DHAVE_CONFIG_H -c ../$s -I.. -I. -Ibld -o ${s%.c}.o; done
  ar rcs libpixman-1.a *.o
  cp libpixman-1.a $INST/lib/
  mkdir -p $INST/include/pixman-1 $INST/lib/pkgconfig
  cp ../pixman.h $INST/include/pixman-1/
  cp pixman-version.h $INST/include/pixman-1/
  python3 - <<'PY'
p = '/tmp/qb/inst/include/pixman-1/pixman.h'
s = open(p).read()
if 'added for hand build' not in s:
    i = s.find('#define PIXMAN_H__'); j = s.find('\n', i) + 1
    ins = '\n/* added for hand build */\n#ifndef PIXMAN_API\n# define PIXMAN_API\n#endif\n#ifndef PIXMAN_EXPORT\n# define PIXMAN_EXPORT\n#endif\n'
    open(p, 'w').write(s[:j] + ins + s[j:])
PY
  printf 'prefix=%s\nName: pixman-1\nDescription: pixman (hand build)\nVersion: 0.38.0\nLibs: -L${prefix}/lib -lpixman-1\nCflags: -I${prefix}/include/pixman-1\n' $INST > $INST/lib/pkgconfig/pixman-1.pc
fi
echo "pixman ok"

# ---------- 7) glib 2.74.7 (meson, estático, com gvdb) ----------
if [ ! -f $INST/lib/x86_64-linux-gnu/libglib-2.0.a ]; then
  cd $B/src/$GLIB
  mkdir -p subprojects
  rm -rf subprojects/gvdb && cp -r $B/src/$GVDB subprojects/gvdb
  rm -rf bld
  meson setup bld --prefix=$INST --default-library=static \
    -Dnls=disabled -Dtests=false -Dlibmount=disabled -Dselinux=disabled \
    -Dgtk_doc=false -Dman=false -Dsysprof=disabled -Doss_fuzz=disabled \
    -Dglib_assert=false -Dlibelf=disabled -Dgvdb:tests=false > /tmp/glib-setup.log 2>&1 || { tail -20 /tmp/glib-setup.log; exit 1; }
  ninja -C bld -j2 > /tmp/glib-build.log 2>&1 || { tail -20 /tmp/glib-build.log; exit 1; }
  meson install -C bld > /tmp/glib-install.log 2>&1 || { tail -5 /tmp/glib-install.log; exit 1; }
fi
echo "glib ok"

# ---------- 8) qemu 3.1.0 ----------
cd $B/src/$QEMU
rm -rf ui/keycodemapdb && cp -r $B/src/$KCM ui/keycodemapdb
# Makefile do qemu chama keymap-gen com opções ANTES do subcomando (formato 2018) — ok
./configure --prefix=/tmp/ql \
  --target-list=x86_64-softmmu \
  --python=python3 \
  --disable-strip \
  --audio-drv-list= \
  --extra-ldflags="-L$INST/lib -L$INST/lib/x86_64-linux-gnu" \
  > /tmp/qemu-conf.log 2>&1 || { tail -30 /tmp/qemu-conf.log; exit 1; }
make -j2 > /tmp/qemu-build.log 2>&1 || { grep -B6 "error" /tmp/qemu-build.log | tail -25; exit 1; }
make install > /tmp/qemu-install.log 2>&1 || { tail -10 /tmp/qemu-install.log; exit 1; }
strip /tmp/ql/bin/qemu-system-x86_64
mkdir -p $TC/bin
cp /tmp/ql/bin/qemu-system-x86_64 $TC/bin/
/tmp/ql/bin/qemu-system-x86_64 --version
echo QEMU-OK
