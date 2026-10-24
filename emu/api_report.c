/* api_report - what a PE module actually needs from the host, in percentages.
 *
 *   api_report <file> [<file>...]
 *
 * Prints, per module: how many bytes of its own code need CPU translation (all of
 * them), and how its imported functions split across Direct3D, Vulkan, OpenGL,
 * shader compilers, windowing, audio, input, core Windows, API-set contract DLLs
 * and third-party libraries. Then the same totals across every module given.
 *
 * Exit status: 0 if every file parsed, 1 otherwise. A file the parser refuses
 * (32-bit, ARM64, managed) is reported with its reason and counted as refused,
 * because "this one needs no CPU translation at all" is itself a result.
 */
#include "api_map.h"

#include "pe_load.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#define MAX_IMAGE (512u * 1024u * 1024u)
#define MAX_FILES 512

static int read_file(const char *path, uint8_t **out, size_t *len)
{
    FILE *fp = fopen(path, "rb");
    uint8_t *b;
    long sz;
    if (!fp) { fprintf(stderr, "api_report: cannot open %s\n", path); return 0; }
    if (fseek(fp, 0, SEEK_END) != 0) { fclose(fp); return 0; }
    sz = ftell(fp);
    rewind(fp);
    if (sz < 0 || (unsigned long)sz > MAX_IMAGE) {
        fprintf(stderr, "api_report: %s is %ld bytes, out of range\n", path, sz);
        fclose(fp);
        return 0;
    }
    b = malloc((size_t)sz ? (size_t)sz : 1u);
    if (!b) { fclose(fp); return 0; }
    if (sz > 0 && fread(b, 1, (size_t)sz, fp) != (size_t)sz) {
        fprintf(stderr, "api_report: short read on %s\n", path);
        free(b); fclose(fp);
        return 0;
    }
    fclose(fp);
    *out = b; *len = (size_t)sz;
    return 1;
}

static void print_buckets(const api_surface *s)
{
    int i;
    printf("  own machine code needing CPU translation: %llu bytes  (100%% - this is "
           "x86-64 whatever graphics API it calls)\n",
           (unsigned long long)s->exec_code_bytes);
    printf("  imported functions: %u across %u DLL(s)\n", s->total_funcs, s->total_dlls);
    for (i = 0; i < API_CLASS_COUNT; i++) {
        const api_bucket *b = &s->by_class[i];
        if (!b->dlls && !b->funcs) continue;
        printf("    %-18s %5u func(s) %6.1f%%   %u dll(s)\n",
               api_class_name((api_class)i), b->funcs,
               (double)b->pct_funcs_x10 / 10.0, b->dlls);
    }
    if (s->dynamic_resolution)
        printf("  WARNING: imports %u dynamic-resolution function(s) "
               "(LoadLibrary/GetProcAddress/...), so it resolves more API at run "
               "time than this table shows - these percentages are a LOWER BOUND\n",
               s->dynamic_funcs);
}

int main(int argc, char **argv)
{
    api_surface total, one;
    uint8_t *img;
    size_t len;
    int i, parsed = 0, refused = 0, unreadable = 0;

    if (argc < 2) {
        fprintf(stderr, "usage: api_report <file> [<file>...]\n");
        return 1;
    }
    memset(&total, 0, sizeof(total));

    for (i = 1; i < argc && i < MAX_FILES; i++) {
        pe_image im;
        pe_status st;
        img = NULL; len = 0;
        if (!read_file(argv[i], &img, &len)) { unreadable++; continue; }
        st = pe_load(img, len, &im);
        if (st == PE_UNSUPPORTED) {
            /* Refused, and the refusal is informative: an ARM64 or 32-bit or
             * managed module needs none of this project's CPU translation. */
            printf("%s\n  REFUSED: %s\n", argv[i], im.detail ? im.detail : "?");
            printf("  machine=%s managed=%s -> CPU translation needed: %s\n",
                   pe_machine_name(im.machine), im.has_clr ? "yes" : "no",
                   (im.machine == PE_MACHINE_AMD64 && !im.has_clr) ? "yes" : "NO");
            refused++;
            free(img);
            continue;
        }
        if (st != PE_OK) {
            printf("%s\n  UNREADABLE: %s (%s)\n", argv[i],
                   st == PE_BAD_MAGIC ? "not a PE image" : "malformed",
                   im.detail ? im.detail : "?");
            unreadable++;
            free(img);
            continue;
        }
        api_surface_of(&im, &one);
        printf("%s  (%zu bytes)\n", argv[i], len);
        printf("  %s %s, entry %08x\n",
               im.is_dll ? "DLL" : "exe", pe_machine_name(im.machine), im.entry_rva);
        print_buckets(&one);
        printf("\n");

        {
            int k;
            for (k = 0; k < API_CLASS_COUNT; k++) {
                total.by_class[k].dlls  += one.by_class[k].dlls;
                total.by_class[k].funcs += one.by_class[k].funcs;
            }
            total.total_dlls += one.total_dlls;
            total.total_funcs += one.total_funcs;
            total.exec_code_bytes += one.exec_code_bytes;
            if (one.dynamic_resolution) {
                total.dynamic_resolution = 1;
                total.dynamic_funcs += one.dynamic_funcs;
            }
        }
        parsed++;
        free(img);
    }

    for (i = 0; i < API_CLASS_COUNT; i++)
        total.by_class[i].pct_funcs_x10 =
            total.total_funcs
                ? (uint32_t)((uint64_t)total.by_class[i].funcs * 1000u /
                             total.total_funcs)
                : 0u;

    printf("=== TOTAL across %d parsed module(s), %d refused, %d unreadable ===\n",
           parsed, refused, unreadable);
    print_buckets(&total);

    /* One line a CI annotation can carry whole. */
    printf("SUMMARY parsed=%d refused=%d dlls=%u funcs=%u code_bytes=%llu "
           "d3d=%.1f%% vulkan=%.1f%% gl=%.1f%% shader=%.1f%% present=%.1f%% "
           "audio=%.1f%% input=%.1f%% wincore=%.1f%% apiset=%.1f%% third=%.1f%% "
           "other=%.1f%% dynamic=%s\n",
           parsed, refused, total.total_dlls, total.total_funcs,
           (unsigned long long)total.exec_code_bytes,
           (double)total.by_class[API_GFX_D3D].pct_funcs_x10 / 10.0,
           (double)total.by_class[API_GFX_VULKAN].pct_funcs_x10 / 10.0,
           (double)total.by_class[API_GFX_GL].pct_funcs_x10 / 10.0,
           (double)total.by_class[API_SHADER].pct_funcs_x10 / 10.0,
           (double)total.by_class[API_PRESENT].pct_funcs_x10 / 10.0,
           (double)total.by_class[API_AUDIO].pct_funcs_x10 / 10.0,
           (double)total.by_class[API_INPUT].pct_funcs_x10 / 10.0,
           (double)total.by_class[API_WIN_CORE].pct_funcs_x10 / 10.0,
           (double)total.by_class[API_APISET].pct_funcs_x10 / 10.0,
           (double)total.by_class[API_THIRD_PARTY].pct_funcs_x10 / 10.0,
           (double)total.by_class[API_OTHER].pct_funcs_x10 / 10.0,
           total.dynamic_resolution ? "yes" : "no");

    return (unreadable || !parsed) ? 1 : 0;
}
