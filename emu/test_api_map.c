/* Tests for the API surface classifier.
 *
 * The pe_image is filled in by hand rather than parsed from a fixture, because
 * what is under test here is the classification and the arithmetic, and a
 * hand-filled struct lets each expectation name the exact mix it means. Parsing is
 * covered separately, and the real binaries in CI cover the two together.
 */
#include "api_map.h"

#include <stdio.h>
#include <string.h>

static int checks, failures;

#define CHECK(cond, ...) do { \
    checks++; \
    if (!(cond)) { failures++; printf("  FAIL %s:%d: ", __FILE__, __LINE__); \
                   printf(__VA_ARGS__); printf("\n"); } \
} while (0)

/* ------------------------------------------------------------- classification */

static void test_classify(void)
{
    static const struct { const char *name; api_class want; } t[] = {
        /* Direct3D, including the versioned and companion libraries */
        { "d3d9.dll",          API_GFX_D3D },
        { "d3d11.dll",         API_GFX_D3D },
        { "d3d12.dll",         API_GFX_D3D },
        { "d3d12core.dll",     API_GFX_D3D },
        { "dxgi.dll",          API_GFX_D3D },
        { "dxcore.dll",        API_GFX_D3D },
        { "dcomp.dll",         API_GFX_D3D },
        /* Vulkan: exactly the loader, nothing else */
        { "vulkan-1.dll",      API_GFX_VULKAN },
        { "VULKAN-1.DLL",      API_GFX_VULKAN },
        /* Shader bytecode compilation is its own problem, not a renderer */
        { "d3dcompiler_47.dll",API_SHADER },
        { "dxil.dll",          API_SHADER },
        { "opengl32.dll",      API_GFX_GL },
        { "libglesv2.dll",     API_GFX_GL },
        { "user32.dll",        API_PRESENT },
        { "dwmapi.dll",        API_PRESENT },
        { "xaudio2_9.dll",     API_AUDIO },
        { "x3daudio1_7.dll",   API_AUDIO },
        { "dsound.dll",        API_AUDIO },
        { "xinput1_4.dll",     API_INPUT },
        { "dinput8.dll",       API_INPUT },
        { "kernel32.dll",      API_WIN_CORE },
        { "ntdll.dll",         API_WIN_CORE },
        { "ucrtbase.dll",      API_WIN_CORE },
        { "vcruntime140.dll",  API_WIN_CORE },
        { "msvcp140.dll",      API_WIN_CORE },
        { "bcryptprimitives.dll", API_WIN_CORE },
        /* Contract DLLs are not files; they must not be counted as system DLLs */
        { "api-ms-win-core-synch-l1-2-0.dll", API_APISET },
        { "ext-ms-win-shell32-shellfolders-l1-1-0.dll", API_APISET },
        { "SDL2.dll",          API_THIRD_PARTY },
        { "sdl2_ttf.dll",      API_THIRD_PARTY },
        { "somevendor.dll",    API_OTHER },
    };
    size_t i;
    printf("DLL names classify into the right family\n");
    for (i = 0; i < sizeof(t) / sizeof(t[0]); i++) {
        api_class got = api_classify(t[i].name);
        CHECK(got == t[i].want, "'%s' -> %s, expected %s", t[i].name,
              api_class_name(got), api_class_name(t[i].want));
    }
    /* Case insensitivity matters: the import table stores whatever the linker
     * wrote, and real binaries are inconsistent about it. */
    CHECK(api_classify("D3D11.DLL") == API_GFX_D3D, "upper case not matched");
    CHECK(api_classify("D3D11.dll") == API_GFX_D3D, "mixed case not matched");
    CHECK(api_classify("Kernel32.DLL") == API_WIN_CORE, "upper case core not matched");
    CHECK(api_classify(NULL) == API_OTHER, "NULL name not handled");
    CHECK(api_classify("") == API_OTHER, "empty name not handled");
    /* A name that merely contains d3d must not be swept into the family. */
    CHECK(api_classify("notd3d.dll") == API_OTHER,
          "substring match leaked into the Direct3D family");
    CHECK(strcmp(api_class_name(API_GFX_VULKAN), "Vulkan") == 0,
          "class name for Vulkan changed");
}

static void test_dynamic_loader(void)
{
    printf("dynamic resolution is detected, because it caps what statics can show\n");
    CHECK(api_is_dynamic_loader("GetProcAddress") == 1, "GetProcAddress missed");
    CHECK(api_is_dynamic_loader("LoadLibraryA") == 1, "LoadLibraryA missed");
    CHECK(api_is_dynamic_loader("LoadLibraryExW") == 1, "LoadLibraryExW missed");
    CHECK(api_is_dynamic_loader("GetModuleHandleW") == 1, "GetModuleHandleW missed");
    CHECK(api_is_dynamic_loader("LdrLoadDll") == 1, "LdrLoadDll missed");
    CHECK(api_is_dynamic_loader("loadlibrarya") == 1, "lower case missed");
    CHECK(api_is_dynamic_loader("CreateFileW") == 0, "an ordinary import was flagged");
    CHECK(api_is_dynamic_loader(NULL) == 0, "NULL was flagged");
}

/* ------------------------------------------------------------- surface totals */

/* Builds a pe_image from a table so each test states its mix explicitly. */
typedef struct { const char *dll; const char **funcs; uint32_t n; } dll_spec;

static pe_image build(const dll_spec *specs, uint32_t nspecs, uint32_t code_sect_bytes)
{
    pe_image im;
    uint32_t i, k, fi = 0;
    memset(&im, 0, sizeof(im));
    im.machine = PE_MACHINE_AMD64;
    im.num_sections = 1;
    strcpy(im.sections[0].name, ".text");
    im.sections[0].virtual_size = code_sect_bytes;
    im.sections[0].characteristics = PE_SCN_CNT_CODE | PE_SCN_MEM_EXECUTE |
                                     PE_SCN_MEM_READ;
    for (i = 0; i < nspecs && i < PE_DLL_MAX; i++) {
        im.dlls[i].dll_name = specs[i].dll;
        im.dlls[i].first_func = fi;
        im.dlls[i].func_count = specs[i].n;
        for (k = 0; k < specs[i].n && fi < PE_FUNC_MAX; k++)
            im.funcs[fi++].name = specs[i].funcs[k];
        im.num_dlls++;
    }
    im.num_funcs = fi;
    im.has_imports = im.num_dlls != 0;
    return im;
}

static void test_surface(void)
{
    static const char *k32[] = { "GetProcAddress", "LoadLibraryA", "ExitProcess",
                                 "GetTickCount64", "VirtualAlloc" };
    static const char *vulk[] = { "vkCreateInstance", "vkEnumeratePhysicalDevices",
                                  "vkCreateDevice", "vkCmdDraw" };
    static const char *d3d[]  = { "D3D11CreateDevice", "CreateDXGIFactory2" };
    static const char *dxgi[] = { "DXGIGetDebugInterface1" };
    static const char *usr[]  = { "MessageBoxA", "PostQuitMessage",
                                  "RegisterClassExA" };
    static const char *apis[] = { "WaitOnAddress", "WakeByAddressSingle" };
    static const char *sdl[]  = { "SDL_Init", "SDL_CreateWindow" };
    api_surface s;
    pe_image im;

    printf("a Vulkan-shaped module\n");
    {
        dll_spec specs[] = {
            { "kernel32.dll", k32, 5 }, { "vulkan-1.dll", vulk, 4 },
            { "user32.dll", usr, 3 },
            { "api-ms-win-core-synch-l1-2-0.dll", apis, 2 },
            { "SDL2.dll", sdl, 2 },
        };
        im = build(specs, 5, 0x100000u);
        api_surface_of(&im, &s);
        CHECK(s.total_dlls == 5, "total dlls %u", s.total_dlls);
        CHECK(s.total_funcs == 16, "total funcs %u, expected 16", s.total_funcs);
        CHECK(s.exec_code_bytes == 0x100000u, "code bytes %llu",
              (unsigned long long)s.exec_code_bytes);
        CHECK(s.by_class[API_GFX_VULKAN].funcs == 4, "vulkan funcs %u",
              s.by_class[API_GFX_VULKAN].funcs);
        CHECK(s.by_class[API_GFX_D3D].funcs == 0, "a Vulkan module reported D3D funcs");
        CHECK(s.by_class[API_WIN_CORE].funcs == 5, "core funcs %u",
              s.by_class[API_WIN_CORE].funcs);
        CHECK(s.by_class[API_APISET].funcs == 2, "api-set funcs %u",
              s.by_class[API_APISET].funcs);
        CHECK(s.by_class[API_THIRD_PARTY].funcs == 2, "third-party funcs %u",
              s.by_class[API_THIRD_PARTY].funcs);
        CHECK(s.by_class[API_PRESENT].funcs == 3, "present funcs %u",
              s.by_class[API_PRESENT].funcs);
        /* 4/16 = 25.0% */
        CHECK(s.by_class[API_GFX_VULKAN].pct_funcs_x10 == 250u,
              "vulkan share %u permille, expected 250",
              s.by_class[API_GFX_VULKAN].pct_funcs_x10);
        CHECK(s.dynamic_resolution == 1, "GetProcAddress/LoadLibrary not detected");
        CHECK(s.dynamic_funcs == 2, "dynamic funcs %u, expected 2", s.dynamic_funcs);
        CHECK(s.managed == 0, "a native module reported as managed");
    }

    printf("a Direct3D-shaped module\n");
    {
        dll_spec specs[] = {
            { "kernel32.dll", k32, 5 }, { "d3d11.dll", d3d, 2 },
            { "dxgi.dll", dxgi, 1 }, { "user32.dll", usr, 3 },
        };
        im = build(specs, 4, 0x100000u);
        api_surface_of(&im, &s);
        CHECK(s.total_funcs == 11, "total funcs %u, expected 11", s.total_funcs);
        CHECK(s.by_class[API_GFX_D3D].funcs == 3, "d3d funcs %u, expected 3",
              s.by_class[API_GFX_D3D].funcs);
        CHECK(s.by_class[API_GFX_VULKAN].funcs == 0, "a D3D module reported Vulkan");
        /* The code that needs CPU translation is identical in both cases. */
        CHECK(s.exec_code_bytes == 0x100000u,
              "code bytes differ between the Vulkan and D3D modules");
    }

    printf("percentages are permille and add up\n");
    {
        uint32_t sum = 0;
        int i;
        dll_spec specs[] = {
            { "kernel32.dll", k32, 5 }, { "vulkan-1.dll", vulk, 4 },
            { "user32.dll", usr, 3 },
            { "api-ms-win-core-synch-l1-2-0.dll", apis, 2 },
            { "SDL2.dll", sdl, 2 },
        };
        im = build(specs, 5, 0x1000u);
        api_surface_of(&im, &s);
        for (i = 0; i < API_CLASS_COUNT; i++) sum += s.by_class[i].pct_funcs_x10;
        /* 16 funcs: 5,4,3,2,2 -> 312+250+187+125+125 = 999, one permille lost to
         * truncation. Allowing for that is honest; allowing more would hide a bug. */
        CHECK(sum >= 990u && sum <= 1000u,
              "percentages sum to %u permille, expected 990..1000", sum);
    }

    printf("a module with no imports must not divide by zero\n");
    {
        im = build(NULL, 0, 0x2000u);
        api_surface_of(&im, &s);
        CHECK(s.total_dlls == 0 && s.total_funcs == 0, "empty module counted imports");
        CHECK(s.by_class[API_WIN_CORE].pct_funcs_x10 == 0, "non-zero percent with no funcs");
        CHECK(s.exec_code_bytes == 0x2000u, "code bytes not measured on an empty module");
        CHECK(s.dynamic_resolution == 0, "dynamic resolution reported with no imports");
    }

    printf("non-code sections are not counted as translatable code\n");
    {
        im = build(NULL, 0, 0x1000u);
        im.num_sections = 2;
        strcpy(im.sections[1].name, ".data");
        im.sections[1].virtual_size = 0x9000u;
        im.sections[1].characteristics = PE_SCN_CNT_INITIALIZED_DATA | PE_SCN_MEM_READ;
        api_surface_of(&im, &s);
        CHECK(s.exec_code_bytes == 0x1000u,
              "counted %llu bytes, expected only the 0x1000 of code",
              (unsigned long long)s.exec_code_bytes);
    }

    printf("defensive: a NULL image\n");
    api_surface_of(NULL, &s);
    CHECK(s.total_funcs == 0 && s.exec_code_bytes == 0, "NULL image produced counts");
    api_surface_of(&im, NULL);
    checks++;   /* reaching here is the assertion: NULL out must be survived */
}

int main(void)
{
    printf("=== API surface classification ===\n");
    test_classify();
    test_dynamic_loader();
    test_surface();
    printf("\n%d checks, %d failure(s)\n", checks, failures);
    return failures ? 1 : 0;
}
