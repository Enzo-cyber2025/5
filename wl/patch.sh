export BOX64_DYNAREC_BIGBLOCK=3
export BOX64_DYNAREC_STRONGMEM=2
export BOX64_DYNAREC_SAFEFLAGS=1
export BOX64_NOBANNER=1
export BOX64_DYNAREC_PERSISTENT=1
export BOX64_DYNAREC_PERSISTENT_DIR="$HOME/.cache/box64"
export BOX64_DYNAREC_PERSISTENT_PAGES=1
mkdir -p "${BOX64_DYNAREC_PERSISTENT_DIR:-/tmp/bx}" 2>/dev/null || true
export WINEDLLOVERRIDES="dxgi,d3d9,d3d10core,d3d11=n,b;winemenubuilder.exe=d"
export DXVK_STATE_CACHE_PATH="$HOME/.cache/dxvk"; mkdir -p "$DXVK_STATE_CACHE_PATH" 2>/dev/null || true
export DXVK_LOG_LEVEL=none
export MESA_SHADER_CACHE_DIR="$HOME/.cache/mesa"; mkdir -p "$MESA_SHADER_CACHE_DIR" 2>/dev/null || true
export TU_OVERDRIVE=0; export WINEDEBUG=-all; export BOX64_LOG=0
