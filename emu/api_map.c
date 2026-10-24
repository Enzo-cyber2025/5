#include "api_map.h"

#include <stddef.h>
#include <string.h>

/* ---- case-insensitive helpers ----------------------------------------- */

static int lc(int c)
{
    return (c >= 'A' && c <= 'Z') ? c + 32 : c;
}

static int ieq(const char *a, const char *b)
{
    while (*a && *b) {
        if (lc((unsigned char)*a) != lc((unsigned char)*b)) return 0;
        a++; b++;
    }
    return *a == 0 && *b == 0;
}

static int istarts(const char *s, const char *pre)
{
    while (*pre) {
        if (lc((unsigned char)*s) != lc((unsigned char)*pre)) return 0;
        s++; pre++;
    }
    return 1;
}

/* ---- classification ---------------------------------------------------- */

/* Names that are unambiguously one thing. Matching is on the base name without
 * the .dll suffix where the table says so. */
static const struct { const char *name; api_class cls; } exact[] = {
    { "dxgi.dll",           API_GFX_D3D   },
    { "dxcore.dll",         API_GFX_D3D   },
    { "dcomp.dll",          API_GFX_D3D   },
    { "dxva2.dll",          API_GFX_D3D   },
    { "vulkan-1.dll",       API_GFX_VULKAN},
    { "vulkan.dll",         API_GFX_VULKAN},
    { "opengl32.dll",       API_GFX_GL    },
    { "glu32.dll",          API_GFX_GL    },
    { "glew32.dll",         API_GFX_GL    },
    { "dxil.dll",           API_SHADER    },
    { "user32.dll",         API_PRESENT   },
    { "gdi32.dll",          API_PRESENT   },
    { "gdi32full.dll",      API_PRESENT   },
    { "dwmapi.dll",         API_PRESENT   },
    { "uxtheme.dll",        API_PRESENT   },
    { "dsound.dll",         API_AUDIO     },
    { "winmm.dll",          API_AUDIO     },
    { "avrt.dll",           API_AUDIO     },
    { "mmdevapi.dll",       API_AUDIO     },
    { "dinput8.dll",        API_INPUT     },
    { "hid.dll",            API_INPUT     },
    { "kernel32.dll",       API_WIN_CORE  },
    { "kernelbase.dll",     API_WIN_CORE  },
    { "ntdll.dll",          API_WIN_CORE  },
    { "msvcrt.dll",         API_WIN_CORE  },
    { "ucrtbase.dll",       API_WIN_CORE  },
    { "advapi32.dll",       API_WIN_CORE  },
    { "ws2_32.dll",         API_WIN_CORE  },
    { "iphlpapi.dll",       API_WIN_CORE  },
    { "ole32.dll",          API_WIN_CORE  },
    { "oleaut32.dll",       API_WIN_CORE  },
    { "shell32.dll",        API_WIN_CORE  },
    { "shlwapi.dll",        API_WIN_CORE  },
    { "version.dll",        API_WIN_CORE  },
    { "bcrypt.dll",         API_WIN_CORE  },
    { "bcryptprimitives.dll", API_WIN_CORE },
    { "crypt32.dll",        API_WIN_CORE  },
    { "secur32.dll",        API_WIN_CORE  },
    { "userenv.dll",        API_WIN_CORE  },
    { "psapi.dll",          API_WIN_CORE  },
    { "setupapi.dll",       API_WIN_CORE  },
    { "cfgmgr32.dll",       API_WIN_CORE  },
    { "imm32.dll",          API_WIN_CORE  },
    { "msimg32.dll",        API_WIN_CORE  },
    { "winhttp.dll",        API_WIN_CORE  },
    { "comdlg32.dll",       API_WIN_CORE  },
    { "comctl32.dll",       API_WIN_CORE  },
    { "rpcrt4.dll",         API_WIN_CORE  },
    { "normaliz.dll",       API_WIN_CORE  },
    { "wtsapi32.dll",       API_WIN_CORE  },
    { "powrprof.dll",       API_WIN_CORE  },
    { "dbghelp.dll",        API_WIN_CORE  },
    { "sdl2.dll",           API_THIRD_PARTY },
    { "sdl3.dll",           API_THIRD_PARTY },
    { "sdl2_ttf.dll",       API_THIRD_PARTY },
    { NULL, 0 }
};

api_class api_classify(const char *n)
{
    size_t i;
    if (!n || !*n) return API_OTHER;

    /* API set contract DLLs first: they are not files at all, the loader maps
     * them through the API set schema, so they are a distinct problem and must
     * not be counted as ordinary system DLLs. */
    if (istarts(n, "api-ms-win-") || istarts(n, "ext-ms-win-")) return API_APISET;

    for (i = 0; exact[i].name; i++)
        if (ieq(n, exact[i].name)) return exact[i].cls;

    /* Prefix families whose members are versioned: d3d11.dll, d3d12core.dll,
     * d3dcompiler_47.dll, xaudio2_9.dll, xinput1_4.dll, x3daudio1_7.dll. */
    if (istarts(n, "d3dcompiler")) return API_SHADER;
    if (istarts(n, "d3d"))         return API_GFX_D3D;
    if (istarts(n, "xaudio"))      return API_AUDIO;
    if (istarts(n, "x3daudio"))    return API_AUDIO;
    if (istarts(n, "xinput"))      return API_INPUT;
    if (istarts(n, "libgl") || istarts(n, "libegl") || istarts(n, "libgles"))
        return API_GFX_GL;
    if (istarts(n, "msvcp") || istarts(n, "vcruntime") ||
        istarts(n, "api-ms-win-crt"))
        return API_WIN_CORE;

    return API_OTHER;
}

const char *api_class_name(api_class c)
{
    switch (c) {
    case API_GFX_D3D:     return "Direct3D";
    case API_GFX_VULKAN:  return "Vulkan";
    case API_GFX_GL:      return "OpenGL";
    case API_SHADER:      return "shader-compiler";
    case API_PRESENT:     return "window/present";
    case API_AUDIO:       return "audio";
    case API_INPUT:       return "input";
    case API_WIN_CORE:    return "windows-core";
    case API_APISET:      return "api-set-contract";
    case API_THIRD_PARTY: return "third-party";
    case API_OTHER:       return "other";
    default:              return "?";
    }
}

int api_is_dynamic_loader(const char *f)
{
    if (!f) return 0;
    return ieq(f, "LoadLibraryA") || ieq(f, "LoadLibraryW") ||
           ieq(f, "LoadLibraryExA") || ieq(f, "LoadLibraryExW") ||
           ieq(f, "GetProcAddress") || ieq(f, "GetModuleHandleA") ||
           ieq(f, "GetModuleHandleW") || ieq(f, "GetModuleHandleExA") ||
           ieq(f, "GetModuleHandleExW") || ieq(f, "LdrLoadDll") ||
           ieq(f, "LdrGetProcedureAddress");
}

void api_surface_of(const pe_image *im, api_surface *out)
{
    uint32_t i, k;
    if (!out) return;
    memset(out, 0, sizeof(*out));
    if (!im) return;

    out->managed = im->has_clr;
    out->machine = im->machine;

    for (i = 0; i < im->num_sections; i++)
        if (im->sections[i].characteristics & PE_SCN_CNT_CODE)
            out->exec_code_bytes += im->sections[i].virtual_size;

    for (i = 0; i < im->num_dlls; i++) {
        const pe_import_dll *d = &im->dlls[i];
        api_class c = api_classify(d->dll_name);
        out->by_class[c].dlls++;
        out->by_class[c].funcs += d->func_count;
        out->total_dlls++;
        out->total_funcs += d->func_count;
        for (k = 0; k < d->func_count; k++) {
            const pe_import_func *fn = &im->funcs[d->first_func + k];
            if (api_is_dynamic_loader(fn->name)) {
                out->dynamic_resolution = 1;
                out->dynamic_funcs++;
            }
        }
    }
    for (i = 0; i < API_CLASS_COUNT; i++)
        out->by_class[i].pct_funcs_x10 =
            out->total_funcs
                ? (uint32_t)((uint64_t)out->by_class[i].funcs * 1000u /
                             out->total_funcs)
                : 0u;
}
