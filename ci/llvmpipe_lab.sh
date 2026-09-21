#!/usr/bin/env bash
# Disposable GitHub runner only. Charactersises the CPU Vulkan (llvmpipe) path with
# the pinned source and the pinned text fixture, host side, without an emulator.
# This is a measurement lab: it never approves a release and is not phone evidence.
#
# When LAB_PATCHES is non-empty the lab builds BOTH a pristine checkout of the same
# pin (control) and the patched checkout (variant) and benches them in the same job,
# so a kernel change is compared against the untouched upstream on one machine.
set -Eeuo pipefail
# Name the exact line that aborted: two lab runs died silently inside a bare
# `test`, which left the failure invisible in the published annotation.
trap 'rc=$?; echo "lab aborted: line $LINENO rc=$rc"
' ERR
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
if [[ "$(git -C "$SRC" rev-parse HEAD)" != "$PIN" ]]; then
  echo "pinned checkout is not at the pin: $(git -C "$SRC" rev-parse HEAD) != $PIN"
  exit 1
fi
echo "# llvmpipe host lab $(date -u +%FT%TZ) [flags: $lab_flags patches: $lab_patches]" > "$LAB/table.md"

if [[ ! -f "$MODEL" ]]; then
  mkdir -p "$(dirname "$MODEL")"
  curl --fail --location --retry 3 --max-time 900 \
    'https://huggingface.co/bartowski/SmolLM2-135M-Instruct-GGUF/resolve/main/SmolLM2-135M-Instruct-Q4_K_M.gguf' \
    -o "$MODEL"
fi
echo "$MODEL_SHA  $MODEL" | sha256sum -c -

# What the fixture model is actually made of: a relayout that targets a type the
# model does not contain measures nothing. Header only, so it costs no bandwidth.
echo "### gguf tensor types (fixture) into the table"
{
  echo "### gguf tensor types (fixture)"
  python3 ci/gguf_tensor_types.py "$MODEL"
} >> "$LAB/table.md" 2>&1 || echo "gguf tensor type dump failed" >> "$LAB/table.md"

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

ensure_spirv_headers() { # ggml's Vulkan CMake asks for SPIRV-Headers explicitly
  local pin=29981f65241605e08b0ede4cfeb999fe3b723c6a
  local src=.cache/spirv-headers install=.cache/spirv-install
  if [[ ! -d "$src/.git" ]]; then
    rm -rf "$src"
    git clone --depth 1 --branch vulkan-sdk-1.4.357.0 https://github.com/KhronosGroup/SPIRV-Headers "$src"
  fi
  local head
  head=$(git -C "$src" rev-parse HEAD)
  if [[ "$head" != "$pin" ]]; then
    echo "SPIRV-Headers pin mismatch: $head != $pin"
    return 1
  fi
  local config
  config=$(find "$PWD/$install" -name SPIRV-HeadersConfig.cmake -print -quit 2>/dev/null || true)
  if [[ -z "$config" ]]; then
    cmake -S "$src" -B .cache/spirv-build -DCMAKE_INSTALL_PREFIX="$PWD/$install" > "$LAB/spirv-cmake.log" 2>&1
    cmake --install .cache/spirv-build >> "$LAB/spirv-cmake.log" 2>&1
    config=$(find "$PWD/$install" -name SPIRV-HeadersConfig.cmake -print -quit 2>/dev/null || true)
  fi
  if [[ -z "$config" ]]; then
    echo "SPIRV-HeadersConfig.cmake not found under $install; last cmake log lines:"
    tail -20 "$LAB/spirv-cmake.log" || true
    return 1
  fi
  # find_package(SPIRV-Headers CONFIG) only accepts an absolute <pkg>_DIR.
  SPIRV_HEADERS_DIR="$(cd "$(dirname "$config")" 2>/dev/null && pwd || true)"
  if [[ -z "$SPIRV_HEADERS_DIR" ]]; then
    echo "could not resolve an absolute package dir from $config"
    return 1
  fi
  # ggml calls find_package but never links the target, so the include directory
  # has to be handed to the compiler explicitly or ggml-vulkan.cpp cannot see
  # <spirv/unified1/spirv.hpp> and the whole build stops before any benchmark.
  SPIRV_HEADERS_INCLUDE="$(cd "$(dirname "$config")/../../.." 2>/dev/null && pwd || true)/include"
  if [[ ! -f "$SPIRV_HEADERS_INCLUDE/spirv/unified1/spirv.hpp" ]]; then
    echo "spirv.hpp missing under $SPIRV_HEADERS_INCLUDE; tree:"
    { find "$SPIRV_HEADERS_INCLUDE" -maxdepth 3 -name 'spirv*.hpp' || true; } | sed -n '1,10p'
    return 1
  fi
  echo "spirv-headers: $SPIRV_HEADERS_DIR (include $SPIRV_HEADERS_INCLUDE)"
  return 0
}

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
  for pattern in 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17; do
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
  # 5 fma + barrier per iteration | 6 fma + shared round trip per iteration
  # 7 four independent accumulators | 8 loads only | 9 pure ALU | 10 chained fma
  local pattern macs
  for pattern in 0 1 2 3 4 5 6 7 8 9 10 11 12; do
    macs=4
    case $pattern in
      1) macs=1;;
      7|9|10) macs=4;;
      11|12) macs=8;;
    esac
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
  # Streamed shapes: the pinned kernel walks a hundred megabyte weight set on
  # every token, so nothing it reads can stay in cache. Patterns 13/14/15 repeat
  # the 11/12 comparison over a buffer far larger than L3: five loads against two
  # against one contiguous vector load, for the same eight MACs.
  local pattern
  for pattern in 13 14 15 16 17; do
    for block in 32 128; do
      "$LAB/ceiling/ceiling" --spv "$LAB/ceiling/p$pattern.spv" --block "$block" --groups 8192 \
        --inner 512 --reps 3 --mb 256 --macs 8 2>&1 | sed "s/^/stream pattern=$pattern /" >> "$LAB/ceiling.txt" \
        || printf 'stream pattern=%s block=%s FAILED\n' "$pattern" "$block" >> "$LAB/ceiling.txt"
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
  # No pipe into head here: head exits early, grep dies of SIGPIPE and pipefail
  # turns that into a silent lab failure. The published evidence keeps every line.
  { grep -E 'pattern=(0|9|11|12) block=32 ' "$LAB/ceiling.txt" >> "$LAB/table.md" || true; }
  { grep -E '^stream pattern=(13|14|15|16|17) block=32 ' "$LAB/ceiling.txt" >> "$LAB/table.md" || true; }
  { grep '^scaling ' "$LAB/ceiling.txt" >> "$LAB/table.md" || true; }
  return 0
}

build_bench() { # build_bench <src> <build> <flags>
  local src=$1 build=$2 flags=$3
  local cmake_log="$LAB/$(basename "$build")-cmake.log"
  local build_log="$LAB/$(basename "$build")-build.log"
  if ! cmake -S "$src" -B "$build" -DGGML_VULKAN=ON -DGGML_NATIVE=OFF -DGGML_OPENMP=OFF \
    -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_SERVER=OFF -DLLAMA_CURL=OFF \
    -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_TOOLS=ON -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_CXX_FLAGS="$flags -I$SPIRV_HEADERS_INCLUDE" \
    -DSPIRV-Headers_DIR="$SPIRV_HEADERS_DIR" \
    -DCMAKE_PREFIX_PATH="$SPIRV_HEADERS_DIR/../../.." \
    -DVulkan_GLSLC_EXECUTABLE="$(command -v glslc)" \
    > "$cmake_log" 2>&1; then
    echo "build failed: cmake configure for $build (tail of $cmake_log)"
    tail -30 "$cmake_log" || true
    return 1
  fi
  # A target that does not exist aborts the whole build. In this tree llama-cli is
  # only defined when LLAMA_BUILD_SERVER is on, because it links the server
  # library, so the greedy fixture runs llama-completion: the same CLI without
  # that dependency.
  local targets=(llama-bench)
  if [[ -d "$src/tools/completion" ]]; then
    targets+=(llama-completion)
  fi
  if ! cmake --build "$build" --target "${targets[@]}" -j "$(nproc)" > "$build_log" 2>&1; then
    # A parallel build can also die from a transient kill; retry once single
    # threaded before declaring the compile itself broken, and keep both logs.
    echo "compile for $build failed, retrying with one job"
    cp "$build_log" "$build_log.first" || true
    if ! cmake --build "$build" --target "${targets[@]}" -j 2 > "$build_log" 2>&1; then
      echo "build failed: compile for $build (details in evidence/physical-llvmpipe-build.txt)"
      # The job log is only readable through a 20000 character window, which drops
      # exactly the first errors, so they are published as evidence instead.
      mkdir -p evidence
      {
        echo "build: $build"
        echo "--- first attempt, error lines ---"
        { grep -m 12 -E 'error|Error [0-9]|undefined reference|Killed|ld:' "$build_log.first" || true; } | sed -n '1,12p'
        echo "--- first attempt, tail ---"
        tail -20 "$build_log.first" || true
        echo "--- retry, error lines ---"
        { grep -m 12 -E 'error|Error [0-9]|undefined reference|Killed|ld:' "$build_log" || true; } | sed -n '1,12p'
        echo "--- retry, tail ---"
        tail -30 "$build_log" || true
      } > evidence/physical-llvmpipe-build.txt 2>&1
      { grep -m 6 -E 'error|Error [0-9]|Killed|ld:' "$build_log" || true; } | sed -n '1,6p'
      return 1
    fi
  fi
  if [[ ${#targets[@]} -gt 1 && ! -x "$build/bin/llama-completion" ]]; then
    echo "build failed: $build/bin/llama-completion missing"
    return 1
  fi
  if [[ ! -x "$build/bin/llama-bench" ]]; then
    echo "build failed: $build/bin/llama-bench missing (tail of $build_log)"
    tail -20 "$build_log" || true
    return 1
  fi
}

generate_fixture() { # generate_fixture <bench-bin> <label>
  local bin=$1 label=$2
  if [[ -x "$(dirname "$bin")/llama-completion" ]]; then
    bin="$(dirname "$bin")/llama-completion"
  fi
  set +e
  "$bin" -m "$MODEL" -p 'Explain ten practical ways to learn a language. Give a detailed example for each.'     -n 24 --temp 0 -t 2 -b 128 -ub 32 -ngl 99 -no-cnv -s 1 > "$LAB/greedy-$label.txt" 2> "$LAB/greedy-$label.err"
  local rc=$?
  set -e
  # Keep only generated text: timing/stat lines are not comparable between runs.
  grep -v -E 't/s|ms per token|llama_perf|llama_|load time|sampling time|prompt eval|total time|^$|^\[' \
    "$LAB/greedy-$label.txt" | tail -c 1200 > "$LAB/greedy-$label.tail"
  printf '### greedy-%s exit=%s bytes=%s\n' "$label" "$rc" "$(wc -c < "$LAB/greedy-$label.tail")" | tee -a "$LAB/table.md"
  # The comparison needs real text, but a short generation is still a valid text:
  # any non-empty tail is compared, and the size is recorded either way.
}

publish_lab_evidence() {
  mkdir -p evidence
  cp "$LAB/table.md" evidence/physical-llvmpipe-lab.txt
  # Build diagnostics travel in their own evidence file: the job log is truncated
  # to its last 20000 characters, which is exactly where the first errors are not.
  [[ -f "$LAB/build-errors.txt" ]] && cp "$LAB/build-errors.txt" evidence/physical-llvmpipe-build.txt
  [[ -f "$LAB/ceiling.txt" ]] && cp "$LAB/ceiling.txt" evidence/physical-llvmpipe-ceiling.txt
  [[ -f evidence/physical-llvmpipe-features.txt ]] || true
  return 0
}

echo "phase: device probe"
run_device_probe
echo "phase: compute ceiling"
run_ceiling
if [[ "${LAB_SKIP_BUILD:-0}" == 1 ]]; then
  echo "probe-only run: no llama.cpp build, no bench"
  printf '### probe-only run: device probe and ceiling only, no llama.cpp bench\n' >> "$LAB/table.md"
  publish_lab_evidence
  exit 0
fi
echo "phase: spirv-headers"
ensure_spirv_headers
echo "phase: build patched source"
build_bench "$SRC" "$BUILD" "$lab_flags"
BENCH="$BUILD/bin/llama-bench"
CTRL_BENCH=''
if [[ -n "$lab_patches" ]]; then
  if [[ ! -d "$CTRL_SRC/.git" ]]; then
    rm -rf "$CTRL_SRC"
    git clone --depth 1 --branch v0.4.1 https://github.com/ggml-org/llama.cpp "$CTRL_SRC"
  fi
  test "$(git -C "$CTRL_SRC" rev-parse HEAD)" = "$PIN"
  echo "phase: build pristine control"
  build_bench "$CTRL_SRC" "$CTRL_BUILD" ''
  CTRL_BENCH="$CTRL_BUILD/bin/llama-bench"
fi

COMMON=(-m "$MODEL" -p 16 -n 128 -t 2 -b 128 -ub 32 -o md)
QUICK=(-m "$MODEL" -p 16 -n 128 -t 2 -b 128 -ub 32 -o md -r 1)

run() { # run <label> [env assignments...] -- extra bench args
  local label=$1; shift
  echo "### $label" | tee -a "$LAB/table.md"
  set +e
  "$@" > "$LAB/$label.log" 2>&1
  local rc=$?
  set -e
  printf '(exit %s)\n' "$rc" >> "$LAB/table.md"
  { grep -E '^\|' "$LAB/$label.log" | tail -4 >> "$LAB/table.md" || true; }
}

# Anchors: patched build against the pristine build of the same pin, same job.
if [[ -n "$CTRL_BENCH" ]]; then
  run gpu-control  "$CTRL_BENCH" "${COMMON[@]}" -r 2 -ngl 99
  run gpu-variant  "$BENCH"      "${COMMON[@]}" -r 2 -ngl 99
else
  run gpu-default  "$BENCH"      "${COMMON[@]}" -r 2 -ngl 99
fi
run cpu-reference  "$BENCH" "${COMMON[@]}" -r 2 -ngl 0
# How many host cores the software driver actually uses.
for threads in 1 2 4 8; do
  run "gpu-lp-threads-$threads" env LP_NUM_THREADS=$threads "$BENCH" "${QUICK[@]}" -ngl 99
done
# Are the graph level fusions on this driver a help or a cost?
run gpu-no-multi-add   env GGML_VK_DISABLE_MULTI_ADD=1 "$BENCH" "${QUICK[@]}" -ngl 99
run gpu-force-mmvq     env GGML_VK_FORCE_MMVQ=1 "$BENCH" "${QUICK[@]}" -ngl 99
run gpu-no-fusion      env GGML_VK_DISABLE_FUSION=1 "$BENCH" "${QUICK[@]}" -ngl 99
run gpu-no-graph-opt   env GGML_VK_DISABLE_GRAPH_OPTIMIZE=1 "$BENCH" "${QUICK[@]}" -ngl 99
run gpu-nodes-8        env GGML_VK_MAX_NODES_PER_SUBMIT=8 "$BENCH" "${QUICK[@]}" -ngl 99
run gpu-nodes-128      env GGML_VK_MAX_NODES_PER_SUBMIT=128 "$BENCH" "${QUICK[@]}" -ngl 99
if [[ "$lab_patches" == *row_tile_patches* ]]; then
  # Rows per workgroup: fewer workgroups for the same arithmetic.
  for factor in 2 4 8; do
    run "gpu-rowtile-$factor" env GGUF_VK_ROW_TILE=$factor "$BENCH" "${QUICK[@]}" -ngl 99
  done
fi
if [[ "$lab_patches" == *dmmv_large_patches* ]]; then
  # Upstream's large workgroup path, which this driver never selects by itself.
  run gpu-dmmv-large  env GGUF_VK_DMMV_LARGE=1 "$BENCH" "${QUICK[@]}" -ngl 99
  if [[ "$lab_patches" == *row_tile_patches* ]]; then
    run gpu-rowtile-4-large env GGUF_VK_ROW_TILE=4 GGUF_VK_DMMV_LARGE=1 "$BENCH" "${QUICK[@]}" -ngl 99
  fi
fi

# Greedy fixture: a faster kernel that changes the text is not a result.
if [[ -n "$CTRL_BENCH" ]]; then
  generate_fixture "$CTRL_BENCH" control
  generate_fixture "$BENCH" variant
  if [[ "$(wc -c < "$LAB/greedy-control.tail")" -lt 32 || "$(wc -c < "$LAB/greedy-variant.tail")" -lt 32 ]]; then
    printf 'greedy compare skipped: a run produced no usable text\n' | tee -a "$LAB/table.md"
  elif diff -q "$LAB/greedy-control.tail" "$LAB/greedy-variant.tail" > /dev/null; then
    printf 'greedy text identical: YES\n' | tee -a "$LAB/table.md"
  else
    printf 'greedy text identical: NO\n' | tee -a "$LAB/table.md"
    { diff "$LAB/greedy-control.tail" "$LAB/greedy-variant.tail" || true; } | sed -n '1,20p' | tee -a "$LAB/table.md" || true
  fi
fi

# Per-operation table for the decode path only (prompt 16, generation 128).
echo "### profile"
GGML_VK_PERF_LOGGER=1 "$BENCH" -m "$MODEL" -p 16 -n 64 -t 2 -b 128 -ub 32 -r 1 -ngl 99 \
  > "$LAB/profile.stdout.log" 2> "$LAB/profile.stderr.log" || true
if [[ -n "$CTRL_BENCH" ]]; then
  GGML_VK_PERF_LOGGER=1 "$CTRL_BENCH" -m "$MODEL" -p 16 -n 64 -t 2 -b 128 -ub 32 -r 1 -ngl 99 \
    > "$LAB/profile-control.stdout.log" 2> "$LAB/profile-control.stderr.log" || true
fi

# Bounded machine-readable results. physical-* names are inside the evidence
# publisher's allow-list, so these numbers reach the session branch even though
# Actions log and artifact downloads are not reachable from every client.
mkdir -p evidence
{
  echo "# backend decisions actually taken by the measured device"
  echo "spirv-headers dir: ${SPIRV_HEADERS_DIR:-unset}"
  for log in "$LAB"/gpu-*.log; do
    [[ -f "$log" ]] || continue
    { grep -h -E 'GGUF_ALIGNED_Q5|GGUF_VK_ROW_TILE|GGUF_VK_DMMV|use_subgroups|GGML_VK_' "$log" || true; } | sed -n "1,3p" | sed "s|^|$(basename "$log"): |"
    # A relayout that never ran looks exactly like a relayout that did not help, so
    # every stage of it is counted here: upload calls seen, tensors repacked, uses.
    for kind in GGUF_ALIGNED_Q5_DISPATCH GGUF_ALIGNED_Q5_ASYNC GGUF_ALIGNED_Q5_SET GGUF_ALIGNED_Q5_LAZY GGUF_ALIGNED_Q5_USE "GGUF_ALIGNED_Q5 tensor="; do
      n=$(grep -c "$kind" "$log" 2>/dev/null || true)
      echo "$(basename "$log"): ${kind} count=${n:-0}"
    done
  done
} > evidence/physical-llvmpipe-knobs.txt 2>/dev/null || true
{
  echo "host: $(nproc) cpus | $(grep -m1 'model name' /proc/cpuinfo | sed 's/.*: //')"
  echo "compile flags: [$lab_flags] patches: [$lab_patches]"
  echo
  echo "--- variant ---"
  { grep -E 'GFLOPS|Total time' "$LAB/profile.stderr.log" 2>/dev/null || true; } | sed -n '1,60p'
  if [[ -n "$CTRL_BENCH" ]]; then
    echo "--- control ---"
    { grep -E 'GFLOPS|Total time' "$LAB/profile-control.stderr.log" 2>/dev/null || true; } | sed -n '1,60p'
  fi
} > evidence/physical-llvmpipe-lab-profile.txt
# Copy the benchmark table here as well: the probe-only path never runs this far,
# and a missing table made a later line fail and hide every number.
cp "$LAB/table.md" evidence/physical-llvmpipe-lab.txt
# The relayout writes its own trace next to the working directory: line counts in a
# truncated log already misled this measurement once.
cp gguf_aligned_q5_trace.txt evidence/physical-llvmpipe-aligned-trace.txt 2>/dev/null || true
{ wc -c evidence/physical-llvmpipe-lab.txt evidence/physical-llvmpipe-lab-profile.txt || true; }

# The Checks API annotation channel keeps only the tail of this log, so the table
# is printed last, after everything else has been written to files.
echo
echo "===== table.md ====="
cat "$LAB/table.md"
echo "===== profile (tail) ====="
tail -20 evidence/physical-llvmpipe-lab-profile.txt

# Lab A/B run marker: the push trigger requires [lab] in the head commit message,
# and the job only runs when ci/llvmpipe_lab.sh (or the workflow) changed in the push.
