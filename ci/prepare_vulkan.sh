#!/usr/bin/env bash
# Disposable GitHub runner only: Mesa CPU Vulkan, NOT a physical GPU benchmark.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true ]]
mkdir -p evidence .cache
sudo apt-get update -qq
sudo apt-get install -y mesa-vulkan-drivers vulkan-tools libvulkan-dev libgl1-mesa-dri xvfb x11-utils
icd=$(python3 - <<'PY'
from pathlib import Path
paths = list(Path('/usr/share/vulkan/icd.d').glob('*lvp*.json'))
if len(paths) != 1:
    raise SystemExit(f'Expected one Lavapipe ICD, found {paths}')
print(paths[0])
PY
)
export VK_ICD_FILENAMES="$icd"
export VK_DRIVER_FILES="$icd"
export LIBGL_ALWAYS_SOFTWARE=1
export GALLIUM_DRIVER=llvmpipe
export ANDROID_EMULATOR_USE_SYSTEM_LIBS=1
export DISPLAY=:93
# This server lives only inside the disposable CI job and is destroyed with it.
Xvfb "$DISPLAY" -screen 0 1280x1024x24 -nolisten tcp > .cache/xvfb.log 2>&1 &
for key in VK_ICD_FILENAMES VK_DRIVER_FILES LIBGL_ALWAYS_SOFTWARE GALLIUM_DRIVER ANDROID_EMULATOR_USE_SYSTEM_LIBS DISPLAY; do
  printf '%s=%s\n' "$key" "${!key}" >> "$GITHUB_ENV"
done
# Wait for this CI-owned X server before probing surfaces or starting Android.
ready=0
for attempt in {1..30}; do
  if xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then ready=1; break; fi
  sleep 0.2
done
[[ "$ready" == 1 ]] || { cat .cache/xvfb.log; exit 1; }
vulkaninfo --summary > evidence/host-vulkan.txt 2>&1
# Full vulkaninfo can fail while probing irrelevant host presentation surfaces.
# Use a direct Vulkan API feature query for the mandatory compute prerequisite;
# do not weaken it or fake the capability if the diagnostic utility fails.
g++ -std=c++17 ci/vulkan_features.cpp -lvulkan -o .cache/vulkan-features
.cache/vulkan-features | tee -a evidence/host-vulkan.txt
if ! vulkaninfo > .cache/host-vulkan-full.txt 2>&1; then
  printf '\nOptional full vulkaninfo failed (real feature query above passed):\n' >> evidence/host-vulkan.txt
  tail -15 .cache/host-vulkan-full.txt >> evidence/host-vulkan.txt
fi
cat evidence/host-vulkan.txt
