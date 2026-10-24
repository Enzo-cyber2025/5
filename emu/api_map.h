/* Classification of a PE module's imported API surface.
 *
 * Why this exists. "Does a Vulkan game need less translation than a DirectX game?"
 * is a question with a measurable answer, and the answer is not the one the
 * phrasing suggests. Two separate things get conflated:
 *
 *   - CPU translation. The module's own machine code. This is x86-64 in both
 *     cases and 100% of it needs translating either way. A Vulkan renderer's
 *     engine code is not somehow already ARM64.
 *   - API translation. The calls the module makes into graphics libraries. A D3D
 *     game needs D3D reimplemented on Vulkan, plus its shader bytecode translated
 *     from DXBC/DXIL to SPIR-V. A Vulkan game needs neither: its shaders are
 *     already SPIR-V and its API already exists on Android, so all it needs is a
 *     thin loader shim redirecting vulkan-1.dll to libvulkan.so and swapping the
 *     win32 surface for an android surface.
 *
 * So the saving from Vulkan is entirely in the second category, and it is large -
 * DXVK and VKD3D-Proton are hundreds of thousands of lines - but it does not
 * reduce the first category by one byte. This module measures both so the
 * difference can be stated in numbers rather than argued.
 *
 * One limitation is built into the report rather than hidden: the import table
 * only shows STATIC imports. A module that imports LoadLibrary and GetProcAddress
 * resolves more of its API surface at run time than any static analysis can see,
 * so for such a module these numbers are a lower bound and the report says so.
 * Emulators do this constantly, and so do most graphics backends that pick D3D or
 * Vulkan at run time.
 */
#ifndef API_MAP_H
#define API_MAP_H

#include <stdint.h>

#include "pe_load.h"

typedef enum {
    API_GFX_D3D = 0,    /* d3d9/10/11/12, dxgi, dxcore, dcomp, dxva2 */
    API_GFX_VULKAN,     /* vulkan-1 */
    API_GFX_GL,         /* opengl32, glu32, glew32, libgl*, libegl* */
    API_SHADER,         /* d3dcompiler_*, dxil - shader bytecode compilation */
    API_PRESENT,        /* user32, gdi32, dwmapi, uxtheme: window and presentation */
    API_AUDIO,          /* xaudio2*, dsound, winmm, x3daudio*, avrt, mmdevapi */
    API_INPUT,          /* dinput8, xinput*, hid */
    API_WIN_CORE,       /* kernel32, ntdll, msvcrt, advapi32, ws2_32, ... */
    API_APISET,         /* api-ms-win-*, ext-ms-win-*: contract DLLs, no file */
    API_THIRD_PARTY,    /* shipped beside the executable: SDL2, engine DLLs, ... */
    API_OTHER,
    API_CLASS_COUNT
} api_class;

typedef struct {
    uint32_t dlls;
    uint32_t funcs;
    uint32_t pct_funcs_x10;   /* permille of imported functions */
} api_bucket;

typedef struct {
    api_bucket by_class[API_CLASS_COUNT];
    uint32_t   total_dlls;
    uint32_t   total_funcs;

    /* The module's own code: every byte of it needs CPU translation regardless of
     * which graphics API it uses. This is the number that settles the question. */
    uint64_t   exec_code_bytes;

    /* Static imports are a lower bound when the module can load more at run time. */
    int        dynamic_resolution;
    uint32_t   dynamic_funcs;      /* LoadLibrary/GetProcAddress/GetModuleHandle */

    int        managed;            /* CLR present: no native code to translate */
    uint16_t   machine;
} api_surface;

api_class   api_classify(const char *dll_name);
const char *api_class_name(api_class c);

/* True for the function names through which a module can resolve more API surface
 * at run time than its import table shows. */
int api_is_dynamic_loader(const char *func_name);

void api_surface_of(const pe_image *im, api_surface *out);

/* Prints the breakdown with percentages. Never fails, never allocates. */
void api_surface_print(const api_surface *s, const char *label);

#endif /* API_MAP_H */
