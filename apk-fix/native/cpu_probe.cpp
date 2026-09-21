#include <jni.h>
#include <sys/auxv.h>
#include "cpu_dispatch.h"
extern "C" JNIEXPORT jint JNICALL Java_com_ggufchat_app_NativeDispatch_cpuVariant(JNIEnv *,jclass) {
#if defined(__aarch64__)
    return cpu_variant(getauxval(AT_HWCAP),getauxval(AT_HWCAP2));
#else
    return 0;
#endif
}
