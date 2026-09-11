#define _GNU_SOURCE
#include <stdio.h>
#include <errno.h>
#include <dlfcn.h>
#include <string.h>
#include <stdint.h>

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
