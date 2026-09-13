#!/usr/bin/env bash
# Disposable GitHub runner only: Mesa CPU Vulkan, NOT a physical GPU benchmark.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true ]]
mkdir -p evidence .cache
sudo apt-get update -qq
sudo apt-get install -y mesa-vulkan-drivers vulkan-tools libgl1-mesa-dri xvfb
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
vulkaninfo --summary > evidence/host-vulkan.txt 2>&1
vulkaninfo > .cache/host-vulkan-full.txt 2>&1
# Capability prerequisite, not a claim that the Android guest inherits it.
grep -E 'storageBuffer16BitAccess[[:space:]]*=[[:space:]]*true' .cache/host-vulkan-full.txt >> evidence/host-vulkan.txt
cat evidence/host-vulkan.txt
