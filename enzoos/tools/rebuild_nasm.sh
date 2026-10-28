#!/bin/bash
# Reconstroi o NASM 3.02 do zero sem autotools (sandbox limpo).
# Uso: bash tools/rebuild_nasm.sh   (instala em ~/bin/nasm)
set -e
mkdir -p "$HOME/bin" /tmp/nb && cd /tmp/nb
rm -rf nasm.tar.gz nasm-nasm-3.02
curl -sL https://codeload.github.com/netwide-assembler/nasm/tar.gz/refs/tags/nasm-3.02 -o nasm.tar.gz
tar xzf nasm.tar.gz && cd nasm-nasm-3.02

# 1) Makefile a partir do Makefile.in (substituicao manual das @VARS@)
python3 - <<'PY'
s = open('Makefile.in').read()
V = dict(
 SET_MAKE='', PACKAGE_NAME='nasm', PACKAGE_TARNAME='nasm',
 top_srcdir='.', srcdir='.', builddir='.',
 prefix='$HOME', exec_prefix='${prefix}', bindir='${exec_prefix}/bin',
 mandir='${datarootdir}/man', datarootdir='${prefix}/share', datadir='${datarootdir}',
 docdir='${datarootdir}/doc/nasm', htmldir='${docdir}', pdfdir='${docdir}', psdir='${docdir}',
 CC='gcc', CFLAGS='-O2 -g -fno-strict-aliasing -DHAVE_CONFIG_H', CPPFLAGS='', DEFS='', LDFLAGS='', LIBS='',
 AR='ar', RANLIB='ranlib', STRIP='strip', INSTALL='install', INSTALL_DATA='install -m 644',
 INSTALL_PROGRAM='install', LN_S='ln -s', MKDIR_P='mkdir -p',
 EXEEXT='', OBJEXT='o', LIBEXT='a', MANIFEST='', PYTHON3='python3',
 ASCIIDOC=':', XMLTO=':', XZ=':', MAKENSIS=':', NSIS=':', WINDRES=':',
)
for k,v in V.items(): s = s.replace('@%s@'%k, v)
s = s.replace('@MANPAGES@', '')
s = s.replace('ZLIBINC         = \n', 'ZLIBINC         = -I$(srcdir)/zlib\n', 1)
s = s.replace('ZLIB\t\t= \nZLIBINC\t\t= \n', 'ZLIB\t\t= $(ZLIBOBJ)\nZLIBINC\t\t= -I$(srcdir)/zlib\n', 1)
open('Makefile','w').write(s)
PY

# 2) dependencias (mkdep.pl) + stubs p/ config.status/configure/aclocal.m4
perl tools/mkdep.pl -s . -M Makefile.in -- . stdlib nasmlib include config output asm disasm x86 common zlib macros misc
: > autoconf/aclocal.m4 && : > config.status && : > configure && chmod +x config.status configure
: > config/config.h && : > doc/Makefile

# 3) config/config.h manual (Linux x86_64 gcc) + zlib interno
cat > config/config.h <<'CFG'
#define HAVE_STDINT_H 1
#define HAVE_INTTYPES_H 1
#define HAVE__BOOL 1
#define HAVE_UNISTD_H 1
#define HAVE_STRING_H 1
#define HAVE_STRINGS_H 1
#define HAVE_LIBGEN_H 1
#define HAVE_ERRNO_H 1
#define HAVE_LIMITS_H 1
#define HAVE_STDDEF_H 1
#define WORDS_LITTLEENDIAN 1
#define X86_MEMORY 1
#define HAVE_HTOLE16 1
#define HAVE_HTOLE32 1
#define HAVE_HTOLE64 1
#define HAVE_LE16TOH 1
#define HAVE_LE32TOH 1
#define HAVE_LE64TOH 1
#define HAVE_BE64TOH 1
#define HAVE_STRCASECMP 1
#define HAVE_STRNCASECMP 1
#define HAVE_STRNLEN 1
#define HAVE_STRSEP 1
#define HAVE_SNPRINTF 1
#define HAVE_VSNPRINTF 1
#define HAVE_STRDUP 1
#define HAVE_STRNDUP 1
#define HAVE_STRTOL 1
#define HAVE_STRTOUL 1
#define HAVE_STRTOLL 1
#define HAVE_STRTOULL 1
#define HAVE___BUILTIN_BSWAP16 1
#define HAVE___BUILTIN_BSWAP32 1
#define HAVE___BUILTIN_BSWAP64 1
#define HAVE___BUILTIN_CLZ 1
#define HAVE___BUILTIN_CLZLL 1
#define HAVE___BUILTIN_CTZ 1
#define HAVE___BUILTIN_CTZLL 1
#define HAVE___BUILTIN_EXPECT 1
#define HAVE___BUILTIN_UNREACHABLE 1
#define HAVE_FFS 1
#define HAVE_FFSLL 1
#define HAVE_FILENO 1
#define HAVE_GETC_UNLOCKED 1
#define HAVE_MKSTEMP 1
#define HAVE_PUTC_UNLOCKED 1
#define HAVE_REALPATH 1
#define HAVE_STAT 1
#define SIZEOF_UNSIGNED_SHORT 2
#define SIZEOF_UNSIGNED_INT 4
#define SIZEOF_UNSIGNED_LONG 8
#define SIZEOF_UNSIGNED_LONG_LONG 8
#define SIZEOF_VOID_P 8
#include "unconfig.h"
CFG

# 4) build
make nasm -j"$(nproc)"
install -m 755 nasm "$HOME/bin/nasm"
"$HOME/bin/nasm" -v
