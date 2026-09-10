#!/usr/bin/env bash
# Reprodução HOST-side do problema e da correção (não requer Android).
# Roda em Linux com g++/make/python3. Passos:
#   1) build do llama.cpp (CPU) no commit EXATO do APK (50f068f)
#   2) geração de um GGUF mínimo válido
#   3) inferência CPU (prova que o engine carrega e gera)
#   4) repro do crash nativo (bug vs fix)
set -euo pipefail
LLAMACPP_DIR="${LLAMACPP_DIR:-/tmp/llamacpp}"
GGUF_PY_PATH="${GGUF_PY_PATH:-$LLAMACPP_DIR/gguf-py}"

if [ ! -x "$LLAMACPP_DIR/build/bin/llama" ]; then
  echo "==> clonando/building llama.cpp (commit 50f068f) =="
  [ -d "$LLAMACPP_DIR" ] || git clone https://github.com/ggerganov/llama.cpp "$LLAMACPP_DIR"
  ( cd "$LLAMACPP_DIR" && git fetch --depth 1 origin 50f068ffffc3e0e4c9c2e4139281c6075224f429 && git checkout -q 50f068ffffc3e0e4c9c2e4139281c6075224f429 )
  ( cd "$LLAMACPP_DIR" && cmake -S . -B build -DLLAMA_BUILD_SERVER=ON -DLLAMA_BUILD_UI=OFF -DLLAMA_CURL=OFF && cmake --build build -j"$(nproc)" --target llama-app )
fi

echo "==> gerando GGUF mínimo =="
python3 - "$GGUF_PY_PATH" <<PY
import sys; sys.path.insert(0, "$GGUF_PY_PATH")
exec(open("$(dirname "$0")/gen_tiny_gguf.py").read())
PY

echo "==> inferência CPU (engine) =="
timeout 60 "$LLAMACPP_DIR/build/bin/llama" cli -m /tmp/tiny-llama.gguf -p "world" -n 8 --no-warmup || true

echo "==> repro do crash nativo =="
g++ -O0 -g "$(dirname "$0")/repro_crash.cpp" -I"$LLAMACPP_DIR/ggml/include" \
    -L"$LLAMACPP_DIR/build/bin" -lggml-base -Wl,-rpath,"$LLAMACPP_DIR/build/bin" -o /tmp/repro_crash
echo "--- bug (espera SIGABRT, exit 134) ---"
/tmp/repro_crash bug; echo "bug exit=$?"
echo "--- fix (espera OK, exit 0) ---"
/tmp/repro_crash fix; echo "fix exit=$?"
