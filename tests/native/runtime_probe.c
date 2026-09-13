// Android/Bionic regression: invoke the runtime's real recursive_mutex ctor.
// The assembly wrapper detects callee-saved RBX corruption without dereferencing
// the corrupted value. This is NOT a Vulkan or inference substitute.
#include <dlfcn.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

_Static_assert(sizeof(pthread_mutexattr_t) == 8, "Expected Android LP64 pthread ABI");
extern uint64_t check_callee_saved(void (*constructor)(void *), void *object);
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    void *library = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!library) { fprintf(stderr, "dlopen: %s\n", dlerror()); return 2; }
    void (*ctor)(void *) = (void (*)(void *))dlsym(library, "_ZNSt6__ndk115recursive_mutexC1Ev");
    void (*dtor)(void *) = (void (*)(void *))dlsym(library, "_ZNSt6__ndk115recursive_mutexD1Ev");
    if (!ctor || !dtor) return 2;
    void *object = calloc(1, sizeof(pthread_mutex_t));
    if (!object) return 2;
    uint64_t result = check_callee_saved(ctor, object);
    const int preserved = result == UINT64_C(0x1122334455667788);
    printf("{\"pthread_mutexattr_size\":%zu,\"callee_saved_preserved\":%s,\"rbx\":\"%016" PRIx64 "\"}\n",
           sizeof(pthread_mutexattr_t), preserved ? "true" : "false", result);
    dtor(object);
    free(object);
    dlclose(library);
    return preserved ? 0 : 1;
}
