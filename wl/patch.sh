# Box64 dynarec PRE-AOT (persistent cache = "traduz" x86_64 -> ARM64 em cache, reaproveita entre runs)
export BOX64_DYNAREC_BIGBLOCK=3
export BOX64_DYNAREC_STRONGMEM=2
export BOX64_DYNAREC_SAFEFLAGS=1
export BOX64_NOBANNER=1
export BOX64_DYNAREC_PERSISTENT=1
export BOX64_DYNAREC_PERSISTENT_DIR="$HOME/.cache/box64"
export BOX64_DYNAREC_PERSISTENT_PAGES=1
export BOX64_DYNAREC_PERSISTENT_LOG=0
export BOX64_LOG=0
# Box86 para binarios 32-bit
export BOX86_DYNAREC_BIGBLOCK=3
export BOX86_DYNAREC_PERSISTENT=1
export BOX86_DYNAREC_PERSISTENT_DIR="$HOME/.cache/box86"
export BOX86_NOBANNER=1
export BOX86_LOG=0
# DXVK forçado (dxgi/d3d9/d3d10core/d3d11 = builtin,native)
export WINEDLLOVERRIDES="dxgi,d3d9,d3d10core,d3d11=n,b;winemenubuilder.exe=d"
export DXVK_ASYNC=1
export DXVK_LOG_LEVEL=none
export WINEDEBUG=-all
export MESA_SHADER_CACHE_DIR="$HOME/.cache/mesa_shader"
export TU_OVERDRIVE=0
mkdir -p "$HOME/.cache/box64" "$HOME/.cache/box86" "$HOME/.cache/mesa_shader"
