#define _GNU_SOURCE
#include <stdio.h>
#include <errno.h>
#include <dlfcn.h>
#include <string.h>
#include <stdint.h>
#include <stdarg.h>

/* --- bionic-only symbols --- */
int * __errno(void) { return &errno; }
FILE * __sF[3];
__attribute__((constructor)) static void _init_sF(void){
    __sF[0] = stdin; __sF[1] = stdout; __sF[2] = stderr;
}

/* --- fortify do bionic que a glibc não exporta --- */
size_t __strlen_chk(const char *s, size_t n){ (void)n; return strlen(s); }
char * __strchr_chk(const char *s, int c, size_t n){ (void)n; return strchr(s, c); }

/* --- _Unwind_* -> libgcc_s --- */
static void *gcc_handle(void){
    static void *h = NULL;
    if (!h) h = dlopen("/lib/x86_64-linux-gnu/libgcc_s.so.1", RTLD_LAZY | RTLD_GLOBAL);
    return h;
}
void _Unwind_DeleteException(void *e){ void(*f)(void*)=(void(*)(void*))dlsym(gcc_handle(),"_Unwind_DeleteException"); f(e); }
unsigned long _Unwind_GetIP(void *c){ unsigned long(*f)(void*)=(unsigned long(*)(void*))dlsym(gcc_handle(),"_Unwind_GetIP"); return f(c); }
void * _Unwind_GetLanguageSpecificData(void *c){ void*(*f)(void*)=(void*(*)(void*))dlsym(gcc_handle(),"_Unwind_GetLanguageSpecificData"); return f(c); }
unsigned long _Unwind_GetRegionStart(void *c){ unsigned long(*f)(void*)=(unsigned long(*)(void*))dlsym(gcc_handle(),"_Unwind_GetRegionStart"); return f(c); }
int _Unwind_RaiseException(void *e){ int(*f)(void*)=(int(*)(void*))dlsym(gcc_handle(),"_Unwind_RaiseException"); return f(e); }
void _Unwind_Resume(void *e){ void(*f)(void*)=(void(*)(void*))dlsym(gcc_handle(),"_Unwind_Resume"); f(e); __builtin_unreachable(); }
void _Unwind_SetGR(void *c, int i, unsigned long v){ void(*f)(void*,int,unsigned long)=(void(*)(void*,int,unsigned long))dlsym(gcc_handle(),"_Unwind_SetGR"); f(c,i,v); }
void _Unwind_SetIP(void *c, unsigned long v){ void(*f)(void*,unsigned long)=(void(*)(void*,unsigned long))dlsym(gcc_handle(),"_Unwind_SetIP"); f(c,v); }

#include <stdarg.h>

/* --- sysconf: remapeia constantes _SC_ do bionic para glibc ---
 *
 * O APK é compilado para Android/bionic (bionic: _SC_PAGESIZE=39,
 * _SC_PAGE_SIZE=40; glibc/musl: 30). Sem isso, sysconf(39) retorna lixo e o
 * llama.cpp falha GGML_ASSERT(last % page_size == 0) em
 * llama_mmap::unmap_fragment -> abort(). Correção da causa-raiz do crash. */
long sysconf(int name){
    static long (*real_sysconf)(int) = NULL;
    if (!real_sysconf) real_sysconf = (long (*)(int))dlsym(RTLD_NEXT, "sysconf");
    switch (name) {
        case 39: case 40:                 /* bionic _SC_PAGESIZE / _SC_PAGE_SIZE */
            return real_sysconf ? real_sysconf(30) : 4096;
        case 37: return real_sysconf ? real_sysconf(87) : -1; /* _SC_ATEXIT_MAX */
        case 38: return real_sysconf ? real_sysconf(60) : -1; /* _SC_IOV_MAX    */
        case 96: return real_sysconf ? real_sysconf(83) : -1; /* _SC_NPROC_CONF */
        case 97: return real_sysconf ? real_sysconf(84) : -1; /* _SC_NPROC_ONLN */
        case 98: return real_sysconf ? real_sysconf(85) : -1; /* _SC_PHYS_PAGES */
        case 99: return real_sysconf ? real_sysconf(86) : -1; /* _SC_AVPHYS_PAG */
        default: return real_sysconf ? real_sysconf(name) : -1;
    }
}

/* --- bionic __android_log_print (usado pelo libaijni.so real) --- */
int __android_log_print(int prio, const char *tag, const char *fmt, ...){
    (void)prio;
    va_list ap; va_start(ap, fmt);
    fprintf(stderr, "[android:%s] ", tag ? tag : "?");
    vfprintf(stderr, fmt, ap);
    fprintf(stderr, "\n");
    va_end(ap);
    return 0;
}
