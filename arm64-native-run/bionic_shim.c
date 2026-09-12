/* bionic_shim.c — símbolos da libc bionic (Android) que o musl não exporta
 * com o mesmo nome. Pré-carregado via LD_PRELOAD para que as .so arm64 do
 * APK (libunwind/libllama/libggml/libc++_shared) resolvam suas dependências.
 *
 * Cobertura (determinada por diff entre os símbolos UND de todas as .so do APK
 * e os exportados por musl + pelas próprias .so do APK):
 *   __errno, __register_atfork,
 *   __cxa_thread_atexit_impl,
 *   __memcpy_chk, __strcpy_chk, __strlen_chk, __strchr_chk,
 *   __vsnprintf_chk, __read_chk, __readlink_chk, __open_2,
 *   __sF (FILE[3] do bionic = stdin/stdout/stderr),
 *   __system_property_get
 */
#define _GNU_SOURCE
#include <pthread.h>
#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <stdint.h>
#include <dlfcn.h>
#include <errno.h>

/* Completa o tipo opaco FILE (struct _IO_FILE) do musl — layout idêntico ao
 * musl 1.2.6 (verificado contra src/internal/stdio_impl.h). Necessário para
 * poder declarar FILE __sF[3] (símbolo bionic) e copiar stdin/stdout/stderr. */
struct _IO_FILE {
	unsigned flags;
	unsigned char *rpos, *rend;
	int (*close)(FILE *);
	unsigned char *wend, *wpos;
	unsigned char *mustbezero_1;
	unsigned char *wbase;
	size_t (*read)(FILE *, unsigned char *, size_t);
	size_t (*write)(FILE *, const unsigned char *, size_t);
	off_t (*seek)(FILE *, off_t, int);
	unsigned char *buf;
	size_t buf_size;
	FILE *prev, *next;
	int fd;
	int pipe_pid;
	long lockcount;
	int mode;
	volatile int lock;
	int lbf;
	void *cookie;
	off_t off;
	char *getln_buf;
	void *mustbezero_2;
	unsigned char *shend;
	off_t shlim, shcnt;
	FILE *prev_locked, *next_locked;
	struct __locale_struct *locale;
};

static void __chk_fail(void){ abort(); }

/* ---- 1. __errno : bionic/glibc int *__errno(void) == musl __errno_location ---- */
extern int *__errno_location(void);
int *__errno(void){ return __errno_location(); }

/* ---- 2. __register_atfork : delega para pthread_atfork ---- */
int __register_atfork(void (*prepare)(void), void (*parent)(void),
                      void (*child)(void), void *__dso_handle){
    (void)__dso_handle;
    return pthread_atfork(prepare, parent, child);
}

/* ---- 3. __cxa_thread_atexit_impl : registra no atexit do processo ---- */
extern int __cxa_atexit(void (*)(void *), void *, void *);
int __cxa_thread_atexit_impl(void (*func)(void *), void *arg, void *dso){
    return __cxa_atexit(func, arg, dso);
}

/* ---- 4. fortify (_FORTIFY_SOURCE) ---- */
void *__memcpy_chk(void *dst, const void *src, size_t n, size_t dstlen){
    if (dstlen != (size_t)-1 && n > dstlen) __chk_fail();
    return memcpy(dst, src, n);
}

char *__strcpy_chk(char *dst, const char *src, size_t dstlen){
    size_t n = strlen(src) + 1;
    if (dstlen != (size_t)-1 && n > dstlen) __chk_fail();
    return strcpy(dst, src);
}

size_t __strlen_chk(const char *s, size_t buflen){
    size_t n = strlen(s);
    if (buflen != (size_t)-1 && n >= buflen) __chk_fail();
    return n;
}

char *__strchr_chk(const char *p, int c, size_t buflen){
    for (;; ++p) {
        if (buflen == 0) __chk_fail();
        if ((char)*p == (char)c) return (char *)p;
        if (*p == '\0') return NULL;
        if (buflen != (size_t)-1) buflen--;
    }
}

int __vsnprintf_chk(char *s, size_t maxlen, int flags, size_t slen,
                    const char *fmt, va_list ap){
    (void)flags;
    if (slen != (size_t)-1 && slen >= maxlen) __chk_fail();
    return vsnprintf(s, maxlen, fmt, ap);
}

ssize_t __read_chk(int fd, void *buf, size_t n, size_t buflen){
    if (buflen != (size_t)-1 && n > buflen) __chk_fail();
    return read(fd, buf, n);
}

ssize_t __readlink_chk(const char *path, char *buf, size_t n, size_t buflen){
    if (buflen != (size_t)-1 && n > buflen) __chk_fail();
    return readlink(path, buf, n);
}

int __open_2(const char *path, int flags){
    if (flags & O_CREAT) __chk_fail(); /* open() com O_CREAT exige mode */
    return open(path, flags);
}

/* ---- 5. __sF : bionic exporta FILE __sF[3] = stdin/stdout/stderr ---- */
FILE __sF[3];
__attribute__((constructor))
static void __init_sF(void){
    __sF[0] = *stdin;
    __sF[1] = *stdout;
    __sF[2] = *stderr;
}

/* ---- 6. __system_property_get : sem props -> retorna 0 (não encontrada) ---- */
int __system_property_get(const char *name, char *value){
    (void)name;
    if (value) value[0] = '\0';
    return 0;
}

/* ---- 7. sysconf : remapeia constantes _SC_ do bionic para o musl ----
 *
 * O APK é compilado para Android/bionic, onde as constantes _SC_ são
 * DIFERENTES das do musl/glibc (bionic: _SC_PAGESIZE=39, _SC_PAGE_SIZE=40,
 * _SC_ATEXIT_MAX=37, _SC_IOV_MAX=38, _SC_NPROCESSORS_*=96..99). Sem isso,
 * sysconf(_SC_PAGESIZE) retorna lixo e o llama.cpp falha o
 * GGML_ASSERT(last % page_size == 0) no unmap_fragment.
 */
static long bionic_via_real(int n){
    static long (*real_sysconf)(int) = NULL;
    if (!real_sysconf) {
        real_sysconf = (long (*)(int))dlsym(RTLD_NEXT, "sysconf");
        if (real_sysconf == (long (*)(int))&sysconf) real_sysconf = NULL; /* evita recursão */
    }
    return real_sysconf ? real_sysconf(n) : -1;
}

long sysconf(int name){
    switch (name) {
        case 39: /* bionic _SC_PAGESIZE  */ return 4096;
        case 40: /* bionic _SC_PAGE_SIZE */ return 4096;
        case 37: /* bionic _SC_ATEXIT_MAX -> musl 87 */ return bionic_via_real(87);
        case 38: /* bionic _SC_IOV_MAX    -> musl 60 */ return bionic_via_real(60);
        case 96: /* bionic _SC_NPROCESSORS_CONF -> musl 83 */ return bionic_via_real(83);
        case 97: /* bionic _SC_NPROCESSORS_ONLN -> musl 84 */ return bionic_via_real(84);
        case 98: /* bionic _SC_PHYS_PAGES      -> musl 85 */ return bionic_via_real(85);
        case 99: /* bionic _SC_AVPHYS_PAGES    -> musl 86 */ return bionic_via_real(86);
        default:
            return bionic_via_real(name);
    }
}
