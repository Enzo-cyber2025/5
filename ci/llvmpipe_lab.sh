#!/usr/bin/env bash
# Disposable GitHub runner only. Charactersises the CPU Vulkan (llvmpipe) path with
# the pinned source and the pinned text fixture, host side, without an emulator.
# This is a measurement lab: it never approves a release and is not phone evidence.
#
# When LAB_PATCHES is non-empty the lab builds BOTH a pristine checkout of the same
# pin (control) and the patched checkout (variant) and benches them in the same job,
# so a kernel change is compared against the untouched upstream on one machine.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true ]]

PIN=b29c606e28a01b1bc8c1351026a0fa6e616bf6c4
SRC=${LAB_LLAMA_SRC:-.cache/llama-host}
BUILD=${LAB_LLAMA_BUILD:-.cache/llama-host-build}
CTRL_SRC=${LAB_LLAMA_CTRL_SRC:-.cache/llama-host-ctrl}
CTRL_BUILD=${LAB_LLAMA_CTRL_BUILD:-.cache/llama-host-ctrl-build}
LAB=${LAB_DIR:-.cache/lab}
MODEL=${LAB_MODEL:-.cache/mobile-models/SmolLM2-135M-Instruct-Q4_K_M.gguf}
MODEL_SHA=2e8040ceae7815abe0dcb3540b9995eaa1fa0d2ca9e797d0a635ae4433c68c2d
mkdir -p "$LAB" evidence .cache

lab_flags=''
lab_patches=''
if [[ -f "$SRC.lab-flags" ]]; then
  lab_flags=$(sed -n 1p "$SRC.lab-flags")
  lab_patches=$(sed -n 2p "$SRC.lab-flags")
fi

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
} > "$LAB/host.txt"
vulkaninfo --summary > "$LAB/vulkan-summary.txt" 2>&1 || true

run_device_probe() { # subgroup shape and compute limits of the measured device
  if ! g++ -std=c++17 -O2 ci/vulkan_features.cpp -lvulkan -o "$LAB/vulkan-features" >> "$LAB/probe-build.log" 2>&1; then
    printf '### device probe failed to build\n' | tee -a "$LAB/table.md"
    tail -20 "$LAB/probe-build.log" || true
    return 0
  fi
  "$LAB/vulkan-features" > evidence/physical-llvmpipe-features.txt 2>&1 || true
  grep -E 'shaderFloat16|subgroupSize|subgroupArithmetic|subgroupShuffle|subgroupClustered|computeFullSubgroups|maxComputeWorkGroupInvocations|maxComputeWorkGroupSize' \
    evidence/physical-llvmpipe-features.txt >> "$LAB/table.md" || true
  return 0
}

run_ceiling() { # CPU Vulkan compute ceiling: is a 2-3x kernel win possible here?
  local dir=ci/lab_compute
  mkdir -p "$LAB/ceiling"
  local ok=1 pattern block
  for pattern in 0 1 2 3 4 5 6; do
    glslc -fshader-stage=comp -DPATTERN=$pattern -o "$LAB/ceiling/p$pattern.spv" "$dir/ceiling.comp" \
      >> "$LAB/ceiling-build.log" 2>&1 || ok=0
  done
  g++ -std=c++17 -O2 -Wall "$dir/ceiling.cpp" -lvulkan -o "$LAB/ceiling/ceiling" \
    >> "$LAB/ceiling-build.log" 2>&1 || ok=0
  if [[ $ok != 1 ]]; then
    printf '### ceiling probe failed to build (see ceiling-build.log)\n' | tee -a "$LAB/table.md"
    tail -20 "$LAB/ceiling-build.log" || true
    return 0
  fi
  : > "$LAB/ceiling.txt"
  # 0 vec4 fma | 1 scalar fma | 2 horizontal dot | 3 unpack+dot | 4 unpack+accumulate
  # 5 vec4 fma + barrier per iteration | 6 vec4 fma + shared round trip per iteration
  for pattern in 0 1 2 3 4 5 6; do
    local macs=4; [[ $pattern == 1 ]] && macs=1
    for block in 8 32 128; do
      local spec groups inner
      for spec in "512 128" "8192 128"; do
        read -r groups inner <<< "$spec"
        "$LAB/ceiling/ceiling" --spv "$LAB/ceiling/p$pattern.spv" --block "$block" --groups "$groups" \
          --inner "$inner" --reps 3 --macs "$macs" 2>&1 | sed "s/^/pattern=$pattern /" >> "$LAB/ceiling.txt" \
          || printf 'pattern=%s block=%s groups=%s FAILED\n' "$pattern" "$block" "$groups" >> "$LAB/ceiling.txt"
      done
    done
  done
  # Same shape, growing grid: how many cores does this driver actually use?
  local groups
  for groups in 1 8 512 8192 65536; do
    "$LAB/ceiling/ceiling" --spv "$LAB/ceiling/p0.spv" --block 32 --groups "$groups" --inner 256 \
      --reps 3 --macs 4 2>&1 | sed 's/^/scaling /' >> "$LAB/ceiling.txt" \
      || printf 'scaling groups=%s FAILED\n' "$groups" >> "$LAB/ceiling.txt"
  done
  cp "$LAB/ceiling.txt" evidence/physical-llvmpipe-ceiling.txt
  printf '### compute ceiling (llvmpipe)\n' >> "$LAB/table.md"
  grep -E 'pattern=(0|4|5|6) block=32 ' "$LAB/ceiling.txt" | head -8 >> "$LAB/table.md"
  grep '^scaling ' "$LAB/ceiling.txt" | head -5 >> "$LAB/table.md"
  return 0
}

build_bench() { # build_bench <src> <build> <flags>
  local src=$1 build=$2 flags=$3
  cmake -S "$src" -B "$build" -DGGML_VULKAN=ON -DGGML_NATIVE=OFF -DGGML_OPENMP=OFF \
    -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_SERVER=OFF -DLLAMA_CURL=OFF \
    -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_TOOLS=ON -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_CXX_FLAGS="$flags" > "$LAB/$(basename "$build")-cmake.log" 2>&1
  cmake --build "$build" --target llama-bench llama-cli -j "$(nproc)" > "$LAB/$(basename "$build")-build.log" 2>&1
  test -x "$build/bin/llama-bench"
}

generate_fixture() { # generate_fixture <bin> <label>
  local bin=$1 label=$2
  set +e
  "$bin" -m "$MODEL" -p 'Explain ten practical ways to learn a language. Give a detailed example for each.'     -n 24 --temp 0 -t 2 -b 128 -ub 32 -ngl 99 -no-cnv -s 1 > "$LAB/greedy-$label.txt" 2> "$LAB/greedy-$label.err"
  local rc=$?
  set -e
  # Keep only generated text: timing/stat lines are not comparable between runs.
  grep -v -E 't/s|ms per token|llama_perf|llama_|load time|sampling time|prompt eval|total time|^$|^\[' \
    "$LAB/greedy-$label.txt" | tail -c 1200 > "$LAB/greedy-$label.tail"
  printf '### greedy-%s exit=%s bytes=%s\n' "$label" "$rc" "$(wc -c < "$LAB/greedy-$label.tail")" | tee -a "$LAB/table.md"
}

run_device_probe
run_ceiling
build_bench "$SRC" "$BUILD" "$lab_flags"
BENCH="$BUILD/bin/llama-bench"
CTRL_BENCH=''
if [[ -n "$lab_patches" ]]; then
  if [[ ! -d "$CTRL_SRC/.git" ]]; then
    rm -rf "$CTRL_SRC"
    git clone --depth 1 --branch v0.4.1 https://github.com/ggml-org/llama.cpp "$CTRL_SRC"
  fi
  test "$(git -C "$CTRL_SRC" rev-parse HEAD)" = "$PIN"
  build_bench "$CTRL_SRC" "$CTRL_BUILD" ''
  CTRL_BENCH="$CTRL_BUILD/bin/llama-bench"
fi

COMMON=(-m "$MODEL" -p 16 -n 128 -t 2 -b 128 -ub 32 -o md)
QUICK=(-m "$MODEL" -p 16 -n 128 -t 2 -b 128 -ub 32 -o md -r 1)

run() { # run <label> [env assignments...] -- extra bench args
  local label=$1; shift
  echo "### $label"
  echo "### $label" >> "$LAB/table.md"
  set +e
  "$@" 2>&1 | tee "$LAB/$label.log" | grep -E '^[|]|^llama_bench|t/s' | tail -8
  local rc=${PIPESTATUS[0]}
  set -e
  echo "(exit $rc)" >> "$LAB/table.md"
  grep -E '^[|]' "$LAB/$label.log" | tail -4 >> "$LAB/table.md"
  echo
}

echo "# llvmpipe host lab $(date -u +%FT%TZ) [flags: $lab_flags patches: $lab_patches]" > "$LAB/table.md"

if [[ -n "$CTRL_BENCH" ]]; then
  run gpu-control  "$CTRL_BENCH" "${COMMON[@]}" -r 2 -ngl 99
  run gpu-variant  "$BENCH"      "${COMMON[@]}" -r 2 -ngl 99
else
  run gpu-default  "$BENCH"      "${COMMON[@]}" -r 2 -ngl 99
fi
run cpu-reference  "$BENCH" "${COMMON[@]}" -r 2 -ngl 0
for threads in 1 2 4 8; do
  LP_NUM_THREADS=$threads run "gpu-lp-threads-$threads" env LP_NUM_THREADS=$threads "$BENCH" "${QUICK[@]}" -ngl 99
done
if [[ -n "$CTRL_BENCH" ]]; then
  # A faster kernel that changes the text is not a result: compare greedy output.
  generate_fixture "$CTRL_BENCH" control
  generate_fixture "$BENCH" variant
  if [[ "$(wc -c < "$LAB/greedy-control.tail")" -lt 200 || "$(wc -c < "$LAB/greedy-variant.tail")" -lt 200 ]]; then
    printf 'greedy compare skipped: a run produced no usable text\n' | tee -a "$LAB/table.md"
  elif diff -q "$LAB/greedy-control.tail" "$LAB/greedy-variant.tail" > /dev/null; then
    printf 'greedy text identical: YES\n' | tee -a "$LAB/table.md"
  else
    printf 'greedy text identical: NO\n' | tee -a "$LAB/table.md"
    diff "$LAB/greedy-control.tail" "$LAB/greedy-variant.tail" | head -20 | tee -a "$LAB/table.md" || true
  fi
fi
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
if [[ -n "$CTRL_BENCH" ]]; then
  GGML_VK_PERF_LOGGER=1 "$CTRL_BENCH" -m "$MODEL" -p 16 -n 128 -t 2 -b 128 -ub 32 -r 1 -ngl 99 \
    > "$LAB/profile-control.stdout.log" 2> "$LAB/profile-control.stderr.log" || true
fi

# Bounded machine-readable results. physical-* names are inside the evidence
# publisher's allow-list, so these numbers reach the session branch even though
# Actions log and artifact downloads are not reachable from every client.
mkdir -p evidence
cp "$LAB/table.md" evidence/physical-llvmpipe-lab.txt
{
  echo "host: $(nproc) cpus | $(grep -m1 'model name' /proc/cpuinfo | sed 's/.*: //')"
  echo "compile flags: [$lab_flags] patches: [$lab_patches]"
  echo
  echo "--- variant ---"
  grep -E 'GFLOPS|Total time' "$LAB/profile.stderr.log" 2>/dev/null | tail -40
  if [[ -n "$CTRL_BENCH" ]]; then
    echo "--- control ---"
    grep -E 'GFLOPS|Total time' "$LAB/profile-control.stderr.log" 2>/dev/null | tail -40
  fi
} > evidence/physical-llvmpipe-lab-profile.txt
wc -c evidence/physical-llvmpipe-lab.txt evidence/physical-llvmpipe-lab-profile.txt

# The Checks API annotation channel keeps only the tail of this log, so the table
# is printed last, after everything else has been written to files.
echo
echo "===== table.md ====="
cat "$LAB/table.md"
echo "===== profile (tail) ====="
tail -20 evidence/physical-llvmpipe-lab-profile.txt

# Lab A/B run marker: the push trigger requires [lab] in the head commit message,
# and the job only runs when ci/llvmpipe_lab.sh (or the workflow) changed in the push.
