#!/bin/sh
export HOME="/data/data/$BOX64_PACKAGE_NAME/files/wine"; mkdir -p "$HOME"
export BOX64_DYNAREC_BIGBLOCK=3
export BOX64_DYNAREC_STRONGMEM=2
export BOX64_DYNAREC_SAFEFLAGS=1
export BOX64_NOBANNER=1
export BOX64_DYNAREC_PERSISTENT=1
export BOX64_DYNAREC_PERSISTENT_DIR="$HOME/.cache/box64"
export BOX64_DYNAREC_PERSISTENT_PAGES=1
mkdir -p "$BOX64_DYNAREC_PERSISTENT_DIR"
export WINEDLLOVERRIDES="dxgi,d3d9,d3d10core,d3d11=n,b;winemenubuilder.exe=d"
export DXVK_STATE_CACHE_PATH="$HOME/.cache/dxvk"; mkdir -p "$DXVK_STATE_CACHE_PATH"
export DXVK_LOG_LEVEL=none
export MESA_SHADER_CACHE_DIR="$HOME/.cache/mesa"; mkdir -p "$MESA_SHADER_CACHE_DIR"
export TU_OVERDRIVE=0
export PATH="$BOX64_BOX64_PATH:$PATH"
export BOX64_LOG=0; export WINEPREFIX="$BOX64_WINEPREFIX_PATH"; export WINEDEBUG=-all
export LC_ALL=en_US.UTF-8; export DISPLAY=:0
ANDROID_DATA=$HOME/data ANDROID_ROOT=$HOME/system $BOX64_BOX64_PATH/box64 "$(dirname "$0")/wine" "$@" &
wait
