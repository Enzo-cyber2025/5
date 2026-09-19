#!/usr/bin/env bash
# Disposable GitHub runner only. Charactersises the CPU Vulkan (llvmpipe) path with
# the pinned source and the pinned text fixture, host side, without an emulator.
# This is a measurement lab: it never approves a release and is not phone evidence.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true ]]

SRC=${LAB_LLAMA_SRC:-.cache/llama-host}
BUILD=${LAB_LLAMA_BUILD:-.cache/llama-host-build}
LAB=${LAB_DIR:-.cache/lab}
MODEL=${LAB_MODEL:-.cache/mobile-models/SmolLM2-135M-Instruct-Q4_K_M.gguf}
PIN=b29c606e28a01b1bc8c1351026a0fa6e616bf6c4
MODEL_SHA=2e8040ceae7815abe0dcb3540b9995eaa1fa0d2ca9e797d0a635ae4433c68c2d
mkdir -p "$LAB"

if [[ ! -d "$SRC/.git" ]]; then
  rm -rf "$SRC"
  git clone --depth 1 --branch v0.4.1 https://github.com/ggml-org/llama.cpp "$SRC"
fi
test "$(git -C "$SRC" rev-parse HEAD)" = "$PIN"

if [[ ! -f "$MODEL" ]]; then
  mkdir -p "$(dirname "$MODEL")"
  curl --fail --location --retry 3 --max-time 900 \
    'https://huggingface.co/bartowski/SmolLM2-135M-Instruct-GGUF/resolve/main/SmolLM2-135M-Instruct-Q4_K_M.gguf' \
    -o "$MODEL"
fi
echo "$MODEL_SHA  $MODEL" | sha256sum -c -

# Lavapipe is the only ICD in this job; leave no doubt about which device ran.
icd=$(python3 - <<'PY'
from pathlib import Path
paths = sorted(Path('/usr/share/vulkan/icd.d').glob('*lvp*.json'))
if len(paths) != 1:
    raise SystemExit(f'Expected one Lavapipe ICD, found {paths}')
print(paths[0])
PY
)
export VK_ICD_FILENAMES="$icd"
export VK_DRIVER_FILES="$icd"
export GALLIUM_DRIVER=llvmpipe
export LIBGL_ALWAYS_SOFTWARE=1
printf '%s\n' "$icd" > "$LAB/icd.txt"

{
  echo "host: $(nproc) cpus"
  grep -m1 'model name' /proc/cpuinfo || true
  free -m | head -2 || true
} | tee "$LAB/host.txt"
vulkaninfo --summary > "$LAB/vulkan-summary.txt" 2>&1 || true
cat "$LAB/vulkan-summary.txt"

lab_flags=''
lab_patches=''
if [[ -f "$SRC.lab-flags" ]]; then
  lab_flags=$(sed -n 1p "$SRC.lab-flags")
  lab_patches=$(sed -n 2p "$SRC.lab-flags")
fi
printf 'compile flags for this build: [%s] patches: [%s]\n' "$lab_flags" "$lab_patches" | tee "$LAB/build-flags.txt"
cmake -S "$SRC" -B "$BUILD" -DGGML_VULKAN=ON -DGGML_NATIVE=OFF -DGGML_OPENMP=OFF \
  -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_SERVER=OFF -DLLAMA_CURL=OFF \
  -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_TOOLS=ON -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CXX_FLAGS="$lab_flags" | tail -20
cmake --build "$BUILD" --target llama-bench -j "$(nproc)" | tail -5

BENCH="$BUILD/bin/llama-bench"
test -x "$BENCH"
COMMON=(-m "$MODEL" -p 16 -n 128 -t 2 -b 128 -ub 32 -o md)
QUICK=(-m "$MODEL" -p 16 -n 128 -t 2 -b 128 -ub 32 -o md -r 1)

run() { # run <label> [env assignments...] -- extra bench args
  local label=$1; shift
  echo "### $label"
  echo "### $label" >> "$LAB/table.md"
  set +e
  "$@" 2>&1 | tee "$LAB/$label.log" | tail -25
  local rc=${PIPESTATUS[0]}
  set -e
  echo "(exit $rc)" >> "$LAB/table.md"
  tail -6 "$LAB/$label.log" >> "$LAB/table.md"
  echo
}

echo "# llvmpipe host lab $(date -u +%FT%TZ) [flags: $lab_flags]" > "$LAB/table.md"

run gpu-default        "$BENCH" "${COMMON[@]}" -r 2 -ngl 99
run cpu-reference      "$BENCH" "${COMMON[@]}" -r 2 -ngl 0
for threads in 1 2 4 8; do
  LP_NUM_THREADS=$threads run "gpu-lp-threads-$threads" env LP_NUM_THREADS=$threads "$BENCH" "${QUICK[@]}" -ngl 99
done
run gpu-no-multi-add   env GGML_VK_DISABLE_MULTI_ADD=1 "$BENCH" "${QUICK[@]}" -ngl 99
run gpu-force-mmvq     env GGML_VK_FORCE_MMVQ=1 "$BENCH" "${QUICK[@]}" -ngl 99
run gpu-no-fusion      env GGML_VK_DISABLE_FUSION=1 "$BENCH" "${QUICK[@]}" -ngl 99
run gpu-no-graph-opt   env GGML_VK_DISABLE_GRAPH_OPTIMIZE=1 "$BENCH" "${QUICK[@]}" -ngl 99
run gpu-nodes-8        env GGML_VK_MAX_NODES_PER_SUBMIT=8 "$BENCH" "${QUICK[@]}" -ngl 99
run gpu-nodes-128      env GGML_VK_MAX_NODES_PER_SUBMIT=128 "$BENCH" "${QUICK[@]}" -ngl 99
if [[ "$lab_patches" == *row_tile_patches* ]]; then
  run gpu-rowtile-2      env GGUF_VK_ROW_TILE=2 "$BENCH" "${QUICK[@]}" -ngl 99
  run gpu-rowtile-4      env GGUF_VK_ROW_TILE=4 "$BENCH" "${QUICK[@]}" -ngl 99
  run gpu-rowtile-8      env GGUF_VK_ROW_TILE=8 "$BENCH" "${QUICK[@]}" -ngl 99
fi
if [[ "$lab_patches" == *dmmv_large_patches* ]]; then
  run gpu-dmmv-large     env GGUF_VK_DMMV_LARGE=1 "$BENCH" "${QUICK[@]}" -ngl 99
fi

# Per-operation table for the decode path only (prompt 16, generation 128).
echo "### profile"
GGML_VK_PERF_LOGGER=1 "$BENCH" -m "$MODEL" -p 16 -n 128 -t 2 -b 128 -ub 32 -r 1 -ngl 99 \
  > "$LAB/profile.stdout.log" 2> "$LAB/profile.stderr.log" || true
grep -i -E 'GFLOPS|Total time|Vulkan Timings' "$LAB/profile.stderr.log" | tail -60 | tee "$LAB/profile-ops.txt" || true
tail -6 "$LAB/profile.stdout.log"

echo
echo "===== table.md ====="
cat "$LAB/table.md"
