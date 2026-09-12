#!/bin/sh
# build_and_run.sh — compila (Zig -> aarch64-linux-musl) e roda a camada
# nativa arm64 REAL do APK sob qemu-aarch64 + musl + bionic_shim.
#
# Uso:  ./build_and_run.sh [gguf] [mmproj] [gpuLayers] [useMmap]
#   default: /tmp/models/tiny-llama-022.gguf "" 0 1   (CPU, mmap=1)

set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ZIG=/usr/local/lib/python3.11/dist-packages/ziglang/zig
SYS=/tmp/sysroot
QEMU=/home/user/tools/qemu-aarch64

GGUF="${1:-/tmp/models/tiny-llama-022.gguf}"
MMPROJ="${2:-}"
GPU="${3:-0}"
MMAP="${4:-1}"

# 1) shim bionic (contém a correção do sysconf)
"$ZIG" cc -target aarch64-linux-musl -dynamic -shared -fPIC -O2 \
  -o "$SYS/lib/libbionic_shim.so" "$HERE/bionic_shim.c"

# 2) runner (harness JNI)
"$ZIG" cc -target aarch64-linux-musl -dynamic -O2 \
  -o "$SYS/runner_jni" "$HERE/runner.c" "$HERE/log_stub.c"

# 3) executa
"$QEMU" -L "$SYS" \
  -E LD_LIBRARY_PATH="$SYS/lib" \
  -E LD_PRELOAD="$SYS/lib/libbionic_shim.so" \
  "$SYS/runner_jni" "$GGUF" "$MMPROJ" "$GPU" "$MMAP"
