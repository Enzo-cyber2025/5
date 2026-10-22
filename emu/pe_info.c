/* pe_info - reads a PE file from disk and reports what it is and what it needs.
 *
 * This exists because a parser tested only against fixtures written by the same
 * author proves less than it appears to. The fixtures here are deliberately
 * awkward, but they are still shaped by the same understanding that wrote the
 * parser, so a misunderstanding shows up in both and cancels out. Running this
 * over a real shipped executable is what closes that gap, and CI does exactly
 * that against a pinned, checksum-verified release binary.
 *
 * It only reads and reports. Nothing here maps the image into memory as an
 * image, applies relocations, resolves an import, or executes a byte of it.
 *
 * Exit status: 0 parsed and usable, 2 a valid PE this translator refuses (32-bit,
 * non-x86-64, or managed) with the reason printed, 1 unreadable or malformed.
 */
#include "pe_load.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Refuse to slurp anything larger than this. A PE that big is either not a PE
 * or is being used to make this tool allocate without bound. */
#define MAX_IMAGE (256u * 1024u * 1024u)

static const char *status_name(pe_status st)
{
    switch (st) {
    case PE_OK:         return "PE_OK";
    case PE_BAD_MAGIC:  return "PE_BAD_MAGIC";
    case PE_TRUNCATED:  return "PE_TRUNCATED";
    case PE_UNSUPPORTED:return "PE_UNSUPPORTED";
    case PE_MALFORMED:  return "PE_MALFORMED";
    default:            return "?";
    }
}

static const char *subsystem_name(uint16_t sub)
{
    switch (sub) {
    case 1u:  return "native";
    case 2u:  return "GUI";
    case 3u:  return "console";
    default:  return "other";
    }
}

static void print_flags(uint32_t c)
{
    putchar((c & PE_SCN_MEM_READ)    ? 'R' : '-');
    putchar((c & PE_SCN_MEM_WRITE)   ? 'W' : '-');
    putchar((c & PE_SCN_MEM_EXECUTE) ? 'X' : '-');
    if (c & PE_SCN_CNT_CODE)             printf(" CODE");
    if (c & PE_SCN_CNT_INITIALIZED_DATA) printf(" IDATA");
    if (c & PE_SCN_MEM_DISCARDABLE)      printf(" DISCARDABLE");
}

static int read_file(const char *path, uint8_t **out, size_t *out_len)
{
    FILE  *fp = fopen(path, "rb");
    uint8_t *b;
    long   sz;

    if (!fp) { fprintf(stderr, "pe_info: cannot open %s\n", path); return 0; }
    if (fseek(fp, 0, SEEK_END) != 0) { fclose(fp); return 0; }
    sz = ftell(fp);
    if (sz < 0) { fclose(fp); return 0; }
    rewind(fp);
    if ((unsigned long)sz > MAX_IMAGE) {
        fprintf(stderr, "pe_info: %s is %ld bytes, above the %u byte limit\n",
                path, sz, MAX_IMAGE);
        fclose(fp);
        return 0;
    }
    b = malloc((size_t)sz ? (size_t)sz : 1u);
    if (!b) { fclose(fp); return 0; }
    if (sz > 0 && fread(b, 1, (size_t)sz, fp) != (size_t)sz) {
        fprintf(stderr, "pe_info: short read on %s\n", path);
        free(b); fclose(fp);
        return 0;
    }
    fclose(fp);
    *out = b;
    *out_len = (size_t)sz;
    return 1;
}

int main(int argc, char **argv)
{
    const char *path;
    uint8_t    *img = NULL;
    size_t      len = 0;
    pe_image    im;
    pe_status   st;
    uint32_t    i;

    if (argc != 2) {
        fprintf(stderr, "usage: pe_info <file.exe>\n");
        return 1;
    }
    path = argv[1];
    if (!read_file(path, &img, &len)) return 1;

    st = pe_load(img, len, &im);

    printf("file:      %s (%zu bytes)\n", path, len);
    printf("status:    %s\n", status_name(st));
    printf("detail:    %s\n", im.detail ? im.detail : "(null)");
    printf("machine:   %s [0x%04x]\n", pe_machine_name(im.machine), im.machine);
    printf("format:    %s\n",
           im.opt_magic == PE_MAGIC_PE32PLUS ? "PE32+ (64-bit)" :
           im.opt_magic == PE_MAGIC_PE32     ? "PE32 (32-bit)"  : "unknown");
    printf("kind:      %s   subsystem: %s (%u)\n",
           im.is_dll ? "DLL" : (im.is_exe ? "executable" : "?"),
           subsystem_name(im.subsystem), im.subsystem);
    printf("entry:     %08x (rva)   image base: 0x%llx\n", im.entry_rva,
           (unsigned long long)im.image_base);
    printf("size:      image 0x%x   section align 0x%x   file align 0x%x\n",
           im.size_of_image, im.section_align, im.file_align);
    printf("managed:   %s   (CLR directory %s)\n",
           im.has_clr ? "YES - no native code to translate" : "no",
           im.has_clr ? "present" : "absent");

    printf("sections:  %u%s\n", im.num_sections,
           im.sections_truncated ? " (CAPPED - RVA mapping incomplete)" : "");
    for (i = 0; i < im.num_sections; i++) {
        const pe_section *s = &im.sections[i];
        printf("  %-9s va=%08x vsize=%08x raw=%08x/%08x  ",
               s->name, s->virtual_addr, s->virtual_size, s->raw_ptr, s->raw_size);
        print_flags(s->characteristics);
        printf("  [0x%08x]\n", s->characteristics);
    }

    printf("directories: imports=%s relocs=%s tls=%s debug=%s bound=%s delay=%s\n",
           im.has_imports ? "yes" : "no", im.has_relocs ? "yes" : "no",
           im.has_tls ? "yes" : "no", im.has_debug ? "yes" : "no",
           im.has_bound_imports ? "yes" : "no",
           im.has_delay_imports ? "yes" : "no");
    if (im.has_tls)
        printf("  note: TLS callbacks run BEFORE the entry point\n");
    if (im.has_bound_imports)
        printf("  note: bound image - the IAT holds pre-resolved addresses\n");

    printf("imports:   %u DLL(s), %u function(s)%s\n",
           im.num_dlls, pe_total_imports(&im),
           im.imports_truncated ? "  (CAPPED - list incomplete)" : "");
    for (i = 0; i < im.num_dlls; i++) {
        const pe_import_dll *d = &im.dlls[i];
        uint32_t k, ordinals = 0;
        printf("  %s  -  %u function(s)  [ILT %08x, IAT %08x]\n",
               d->dll_name ? d->dll_name : "(null)", d->func_count,
               d->ilt_rva, d->iat_rva);
        for (k = 0; k < d->func_count; k++) {
            const pe_import_func *fn = &im.funcs[d->first_func + k];
            if (fn->by_ordinal) { ordinals++; continue; }
            printf("      %s%s\n", fn->name ? fn->name : "(null)",
                   fn->name_truncated ? "  [unusually long]" : "");
        }
        if (ordinals)
            printf("      (%u imported by ordinal only)\n", ordinals);
    }

    free(img);
    if (st == PE_OK) return 0;
    if (st == PE_UNSUPPORTED) return 2;
    return 1;
}
