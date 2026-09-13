// Test only the byte forwarding, not Vulkan or model inference.
#define GGUF_DIAGNOSTICS_TEST
#include "../../apk-fix/native/diagnostics.c"
#include <assert.h>
#include <stdarg.h>
#include <string.h>

int __android_log_write(int priority, const char *tag, const char *text) {
    (void)priority;
    (void)tag;
    return puts(text);
}
int __android_log_print(int priority, const char *tag, const char *format, ...) {
    (void)priority;
    (void)tag;
    va_list args;
    va_start(args, format);
    int n = vprintf(format, args);
    va_end(args);
    puts("");
    return n;
}
int main(void) {
    int fd[2];
    assert(pipe(fd) == 0);
    const char *first = "fragment ", *second = "continued\n\n100% literal\n";
    assert(write(fd[1], first, strlen(first)) == (ssize_t)strlen(first));
    assert(write(fd[1], second, strlen(second)) == (ssize_t)strlen(second));
    char long_line[7001];
    memset(long_line, 'x', sizeof(long_line));
    long_line[7000] = '\n';
    assert(write(fd[1], long_line, sizeof(long_line)) == sizeof(long_line));
    assert(write(fd[1], "EOF tail", 8) == 8);
    close(fd[1]);
    forward_stderr((void *)(intptr_t)fd[0]);
    assert(fcntl(fd[0], F_GETFD) == -1 && errno == EBADF);
    return 0;
}
