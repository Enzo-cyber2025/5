/* liblog.so stub (bionic) para aarch64 — o libaijni.so do APK depende de liblog.so. */
#include <stdio.h>
#include <stdarg.h>

int __android_log_print(int prio, const char *tag, const char *fmt, ...){
    (void)prio; va_list ap; va_start(ap, fmt);
    fprintf(stderr, "[android:%s] ", tag ? tag : "?");
    vfprintf(stderr, fmt, ap); fprintf(stderr, "\n"); va_end(ap); return 0;
}
int __android_log_write(int prio, const char *tag, const char *msg){
    (void)prio; fprintf(stderr, "[android:%s] %s\n", tag ? tag : "?", msg); return 0;
}
int __android_log_vprint(int prio, const char *tag, const char *fmt, va_list ap){
    (void)prio; fprintf(stderr, "[android:%s] ", tag ? tag : "?");
    vfprintf(stderr, fmt, ap); fprintf(stderr, "\n"); return 0;
}
int __android_log_assert(const char *cond, const char *tag, const char *fmt, ...){
    fprintf(stderr, "[android-assert:%s] %s ", tag?tag:"?", cond?cond:"?");
    va_list ap; va_start(ap, fmt); vfprintf(stderr, fmt, ap); fprintf(stderr, "\n"); va_end(ap);
    return 0;
}
