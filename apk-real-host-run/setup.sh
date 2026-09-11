#!/usr/bin/env bash
# Reconstrói /tmp/android-run a partir do APK REAL + shims, e compila o
# runner_jni que executa a camada nativa REAL do APK (libaijni.so + libllama.so
# + libggml*.so) no host. Depois de rodar, execute:
#   cd /tmp/android-run && LD_LIBRARY_PATH=/tmp/android-run ./runner_jni \
#       /tmp/tiny-llama-022.gguf /tmp/tiny-mmproj-022.gguf 0
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
APK="${1:-/home/user/5/GGUF-Chat.apk}"
D=/tmp/android-run
mkdir -p "$D" /tmp/apk_extract
unzip -o -q "$APK" 'lib/x86_64/*' -d /tmp/apk_extract

# 1) libs reais do APK (deversioned p/ glibc)
for L in libggml-base libggml-vulkan libggml-cpu libggml libllama; do
  python3 "$HERE/deversion.py" "/tmp/apk_extract/lib/x86_64/$L.so" "$D/$L.so"
done
cp /tmp/apk_extract/lib/x86_64/libc++_shared.so "$D/"
cp /tmp/apk_extract/lib/x86_64/libunwind.so     "$D/"
cp /tmp/apk_extract/lib/x86_64/libaijni.so      "$D/"   # sem DT_VERSYM

# 2) shims de host (bionic -> glibc)
gcc -O2 -shared -fPIC "$HERE/shim.c"       -o "$D/libc.so"
gcc -O2 -shared -fPIC "$HERE/log_stub.c"   -o "$D/liblog.so"
gcc -O2 -shared -fPIC "$HERE/vulkan_stub.c" -o "$D/libvulkan.so"
ln -sf libvulkan.so "$D/libvulkan.so.1"
ln -sf /lib/x86_64-linux-gnu/libm.so.6 "$D/libm.so"
ln -sf /lib/x86_64-linux-gnu/libdl.so.2 "$D/libdl.so"

# 3) neutraliza o backend Vulkan (host não tem Vulkan; simula "sem GPU")
gcc -O2 -shared -fPIC "$HERE/vkstub.c" -o "$D/libggml-vulkan.so"

# 4) contorna a corrupção do caminho mmap no host (load_mode AUTO->NONE/pread)
python3 "$HERE/patch_llama.py" "$D/libllama.so"

# 5) compila o runner JNI (mini-JVM que chama JNI_OnLoad/create/... do APK)
gcc -O0 -g "$HERE/runner_jni.c" -o "$D/runner_jni" -ldl -rdynamic

# 6) modelos de teste (GGUF + mmproj minúsculos, só p/ exercitar o pipeline)
cp -f "$HERE/models/tiny-llama-022.gguf"  /tmp/tiny-llama-022.gguf
cp -f "$HERE/models/tiny-mmproj-022.gguf" /tmp/tiny-mmproj-022.gguf

echo "OK: /tmp/android-run pronto. Para rodar:"
echo "  cd /tmp/android-run && LD_LIBRARY_PATH=/tmp/android-run ./runner_jni /tmp/tiny-llama-022.gguf /tmp/tiny-mmproj-022.gguf 0"
