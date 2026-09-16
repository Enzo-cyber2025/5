#!/usr/bin/env bash
# Real patched ggml integration, CPU-only host. NOT Android/GPU speed evidence.
set -euo pipefail
SOURCE=.cache/llama-mobile
HOST=.cache/strict-host
cmake -S "$SOURCE" -B "$HOST" -DGGML_VULKAN=OFF -DGGML_NATIVE=OFF -DGGML_OPENMP=OFF \
  -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_TOOLS=OFF \
  -DLLAMA_BUILD_SERVER=OFF -DLLAMA_BUILD_COMMON=OFF -DBUILD_SHARED_LIBS=OFF
cmake --build "$HOST" --target ggml -j 2
g++ -std=c++17 -Wall -Wextra -Werror -I"$SOURCE/ggml/include" -Iapk-fix/native \
  tests/native_strict_vulkan.cpp -Wl,--start-group \
  "$HOST/ggml/src/libggml.a" "$HOST/ggml/src/libggml-cpu.a" "$HOST/ggml/src/libggml-base.a" \
  -Wl,--end-group -pthread -ldl -lm -o .cache/strict-actual-ggml
.cache/strict-actual-ggml
