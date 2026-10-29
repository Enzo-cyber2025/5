/* Tests for the PE image parser.
 *
 * The fixtures here are built in memory rather than committed as files, for
 * three reasons: no binary belongs in this repository, a hand-written .exe
 * cannot be varied byte by byte to test a corruption path, and a fixture whose
 * layout the test controls can be made to defeat a parser that cuts corners.
 *
 * That last point is the reason the layout is deliberately awkward. In every
 * fixture .rdata has VirtualAddress 0x2000 but PointerToRawData somewhere else
 * entirely, which is what real files look like once alignment is applied. A
 * parser that treats a data directory RVA as a file offset reads unrelated
 * bytes and can still appear to work on a hand-made sample where the two
 * happen to coincide - so one test below asserts that reading the import
 * directory at its RVA as an offset does NOT find the descriptors.
 *
 * The same trick is used for the ILT/IAT distinction: the IAT is filled with
 * zero thunks while the ILT holds the real names. A parser that read
 * FirstThunk instead of OriginalFirstThunk would report zero imported
 * functions, and the expected counts below would fail.
 */
#include "pe_load.h"

#include <sys/mman.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int checks, failures;

#define CHECK(cond, ...) do { \
    checks++; \
    if (!(cond)) { failures++; printf("  FAIL %s:%d: ", __FILE__, __LINE__); \
                   printf(__VA_ARGS__); printf("\n"); } \
} while (0)

/* strcmp on a NULL is a crash, and a crash names a line but not an
 * expectation. Every string comparison in this file goes through here. */
static int seq(const char *a, const char *b)
{
    if (!a || !b) return 0;
    return strcmp(a, b) == 0;
}

/* Reports a parse that was supposed to succeed, and lets the caller stop there
 * rather than dereferencing fields the parser never filled in. */
static int parsed(pe_status st, const pe_image *im, const char *what)
{
    CHECK(st == PE_OK, "%s: pe_load returned %d (%s)", what, st,
          im->detail ? im->detail : "(null)");
    return st == PE_OK;
}

/* ------------------------------------------------------------- image writer */

typedef struct {
    uint8_t *b;
    size_t   len, cap;
} buf;

static void bgrow(buf *f, size_t need)
{
    if (f->len + need <= f->cap) return;
    while (f->len + need > f->cap) f->cap = f->cap ? f->cap * 2 : 4096;
    f->b = realloc(f->b, f->cap);
    if (!f->b) { fprintf(stderr, "out of memory\n"); exit(1); }
}

static void bput(buf *f, const void *p, size_t n)
{
    bgrow(f, n); memcpy(f->b + f->len, p, n); f->len += n;
}
static void bzero(buf *f, size_t n) { bgrow(f, n); memset(f->b + f->len, 0, n); f->len += n; }
static void bu8(buf *f, uint8_t v)  { bput(f, &v, 1); }
static void bu16(buf *f, uint16_t v){ uint8_t t[2] = { (uint8_t)v, (uint8_t)(v >> 8) }; bput(f, t, 2); }
static void bu32(buf *f, uint32_t v){ uint8_t t[4] = { (uint8_t)v, (uint8_t)(v >> 8),
                                                        (uint8_t)(v >> 16), (uint8_t)(v >> 24) }; bput(f, t, 4); }
static void bu64(buf *f, uint64_t v){ bu32(f, (uint32_t)v); bu32(f, (uint32_t)(v >> 32)); }
static void bstr(buf *f, const char *s) { bput(f, s, strlen(s) + 1); }
static size_t btell(const buf *f) { return f->len; }

static void bpatch32(buf *f, size_t off, uint32_t v)
{
    f->b[off] = (uint8_t)v; f->b[off + 1] = (uint8_t)(v >> 8);
    f->b[off + 2] = (uint8_t)(v >> 16); f->b[off + 3] = (uint8_t)(v >> 24);
}

/* ------------------------------------------------------------ fixture build */

#define RDATA_VA   0x2000u
#define TEXT_VA    0x1000u
#define DATA_VA    0x3000u
#define FILE_ALIGN 0x200u

typedef struct {
    uint16_t machine;
    uint16_t opt_magic;
    int      is_dll;
    uint16_t subsystem;
    int      num_sections;   /* 3 for the normal shape; more for section tests */
    int      with_imports;
    int      clr_dir;
    int      tls_dir;
    int      reloc_dir;
    int      bound_dir;
    int      ordinal_dll;    /* add a third DLL importing purely by ordinal */
    int      long_name;      /* one imported name longer than PE_NAME_MAX */
    int      unterminated_name;  /* DLL name is the last bytes, with no NUL */
    uint32_t entry_rva;
    uint64_t image_base;

    /* filled in by the builder, so tests can mutate the right bytes */
    size_t   dos_magic_off;
    size_t   pe_sig_off;
    size_t   e_lfanew_off;
    size_t   coff_off;
    size_t   opt_off;
    size_t   sec_off;
    size_t   desc_off;       /* file offset of the import descriptor array */
    size_t   term_desc_off;  /* file offset of the terminating descriptor */
    size_t   dllname_off;    /* file offset of "kernel32.dll" */
    size_t   raw_len;
} fix;

static void fix_default(fix *s)
{
    memset(s, 0, sizeof(*s));
    s->machine = PE_MACHINE_AMD64;
    s->opt_magic = PE_MAGIC_PE32PLUS;
    s->subsystem = PE_SUBSYS_GUI;
    s->num_sections = 3;
    s->with_imports = 1;
    s->reloc_dir = 1;
    s->entry_rva = TEXT_VA;
    s->image_base = 0x140000000ULL;
}

/* Builds a PE image and returns it. The caller owns the buffer.
 *
 * The spec is taken by pointer and written back, because the builder is what
 * learns where the descriptor array, its terminator and the DLL name string
 * ended up. A caller that could not see those offsets could not corrupt them
 * deliberately - and a corruption test that patches the wrong offset passes
 * while testing nothing. */
static buf build(fix *io)
{
    fix      s = *io;
    buf      out;
    buf      rd;                     /* .rdata contents, in virtual order */
    size_t   e_lfanew = 0x80;
    size_t   opt_size = (s.opt_magic == PE_MAGIC_PE32PLUS) ? 240u : 224u;
    size_t   hdr_size, text_raw, rdata_raw, data_raw, total;
    int      i, plus = (s.opt_magic == PE_MAGIC_PE32PLUS);
    uint32_t size_of_image;

    /* Offsets of the pieces inside .rdata, recorded as they are appended. */
    size_t   ibn_exit, ibn_getproc, ibn_loadlib, ibn_msgbox, ibn_long;
    size_t   ilt_k32, ilt_u32, ilt_ord;
    size_t   iat_k32, iat_u32, iat_ord;
    size_t   nm_k32, nm_u32, nm_ord;
    size_t   desc_base;
    uint32_t ord_dll_rva = 0;

    memset(&out, 0, sizeof(out));
    memset(&rd, 0, sizeof(rd));

    /* --- .rdata: import-by-name entries first, so thunks can reference them */
    ibn_exit    = btell(&rd); bu16(&rd, 0x0123); bstr(&rd, "ExitProcess");
    ibn_getproc = btell(&rd); bu16(&rd, 0x0456); bstr(&rd, "GetProcAddress");
    ibn_loadlib = btell(&rd); bu16(&rd, 0x0789); bstr(&rd, "LoadLibraryA");
    ibn_msgbox  = btell(&rd); bu16(&rd, 0x0ABC); bstr(&rd, "MessageBoxA");
    ibn_long    = btell(&rd); bu16(&rd, 0x0DEF);
    {   /* a name longer than PE_NAME_MAX, to exercise the truncated flag */
        int k;
        for (k = 0; k < PE_NAME_MAX + 12; k++) bu8(&rd, (uint8_t)('A' + (k % 26)));
        bu8(&rd, 0);
    }

    /* --- ILT arrays: the names as stored in the file */
    ilt_k32 = btell(&rd);
    if (plus) {
        bu64(&rd, RDATA_VA + (uint32_t)ibn_exit);
        bu64(&rd, RDATA_VA + (uint32_t)ibn_getproc);
        bu64(&rd, RDATA_VA + (uint32_t)ibn_loadlib);
        if (s.long_name) bu64(&rd, RDATA_VA + (uint32_t)ibn_long);
        bu64(&rd, 0);              /* terminator, present in both shapes */
    } else {
        bu32(&rd, RDATA_VA + (uint32_t)ibn_exit);
        bu32(&rd, RDATA_VA + (uint32_t)ibn_getproc);
        bu32(&rd, RDATA_VA + (uint32_t)ibn_loadlib);
        bu32(&rd, 0);
    }

    ilt_u32 = btell(&rd);
    if (plus) {
        bu64(&rd, RDATA_VA + (uint32_t)ibn_msgbox);
        bu64(&rd, 0x8000000000000000ULL | 0x1234u);   /* ordinal-only import */
        bu64(&rd, 0);
    } else {
        bu32(&rd, RDATA_VA + (uint32_t)ibn_msgbox);
        bu32(&rd, 0x80000000u | 0x1234u);
        bu32(&rd, 0);
    }

    ilt_ord = btell(&rd);
    if (plus) {
        bu64(&rd, 0x8000000000000000ULL | 7u);
        bu64(&rd, 0x8000000000000000ULL | 8u);
        bu64(&rd, 0);
    } else {
        bu32(&rd, 0x80000000u | 7u);
        bu32(&rd, 0x80000000u | 8u);
        bu32(&rd, 0);
    }

    /* --- IAT arrays: deliberately ZERO, not a copy of the ILT.
     * In a real unbound file these mirror the ILT and the loader overwrites
     * them with resolved addresses. Zeroing them here means a parser that
     * reads FirstThunk instead of OriginalFirstThunk finds an immediately
     * terminated list and reports no imports at all. */
    iat_k32 = btell(&rd); bu64(&rd, 0); bu64(&rd, 0);
    iat_u32 = btell(&rd); bu64(&rd, 0); bu64(&rd, 0);
    iat_ord = btell(&rd); bu64(&rd, 0); bu64(&rd, 0);

    /* --- DLL name strings */
    nm_k32 = btell(&rd); bstr(&rd, "kernel32.dll");
    nm_u32 = btell(&rd); bstr(&rd, "user32.dll");
    nm_ord = btell(&rd); bstr(&rd, "ordinalonly.dll");

    /* --- import descriptor array, last so every RVA above is already known */
    desc_base = btell(&rd);
    if (s.with_imports) {
        /* kernel32.dll */
        bu32(&rd, RDATA_VA + (uint32_t)ilt_k32);   /* OriginalFirstThunk (ILT) */
        bu32(&rd, 0);                              /* TimeDateStamp */
        bu32(&rd, 0xFFFFFFFFu);                    /* ForwarderChain */
        /* With unterminated_name the kernel32 name points into the tail of
         * .data, which the builder extends so those bytes are the end of the
         * file and nothing after them is zero. */
        bu32(&rd, s.unterminated_name ? (DATA_VA + 0x200u)
                                      : (RDATA_VA + (uint32_t)nm_k32));
        bu32(&rd, RDATA_VA + (uint32_t)iat_k32);   /* FirstThunk (IAT) */
        /* user32.dll */
        bu32(&rd, RDATA_VA + (uint32_t)ilt_u32);
        bu32(&rd, 0);
        bu32(&rd, 0xFFFFFFFFu);
        bu32(&rd, RDATA_VA + (uint32_t)nm_u32);
        bu32(&rd, RDATA_VA + (uint32_t)iat_u32);
        if (s.ordinal_dll) {
            bu32(&rd, RDATA_VA + (uint32_t)ilt_ord);
            bu32(&rd, 0);
            bu32(&rd, 0xFFFFFFFFu);
            bu32(&rd, RDATA_VA + (uint32_t)nm_ord);
            bu32(&rd, RDATA_VA + (uint32_t)iat_ord);
            ord_dll_rva = RDATA_VA + (uint32_t)nm_ord;
        }
        bzero(&rd, 20);                            /* terminating descriptor */
    }

    /* --- lay out the file: headers, then the three raw sections */
    hdr_size  = e_lfanew + 4u + 20u + opt_size + (size_t)s.num_sections * 40u;
    hdr_size  = (hdr_size + FILE_ALIGN - 1u) & ~(size_t)(FILE_ALIGN - 1u);
    text_raw  = hdr_size;
    rdata_raw = hdr_size + 0x200u;
    data_raw  = hdr_size + 0x400u;
    total     = hdr_size + 0x600u + (s.unterminated_name ? 12u : 0u);
    if (rd.len > 0x200u) {
        fprintf(stderr, "fixture .rdata overflowed its 0x200 slot: %zu\n", rd.len);
        exit(1);
    }

    size_of_image = 0x4000u + (uint32_t)(s.num_sections > 3 ?
                            (uint32_t)(s.num_sections - 3) * 0x1000u : 0u);

    /* DOS header */
    s.dos_magic_off = btell(&out);
    bu16(&out, 0x5A4Du);
    /* e_lfanew lives at 0x3C, inside the 64-byte DOS header - not at the end of
     * the DOS stub. Written anywhere else, every reader sees zero there and the
     * image looks like it has no PE headers at all. */
    bzero(&out, 0x3Cu - 2u);
    s.e_lfanew_off = btell(&out);
    bu32(&out, (uint32_t)e_lfanew);
    bzero(&out, e_lfanew - btell(&out));

    /* NT signature + COFF header */
    s.pe_sig_off = btell(&out);
    bu32(&out, 0x00004550u);                       /* "PE\0\0" */
    s.coff_off = btell(&out);
    bu16(&out, s.machine);
    bu16(&out, (uint16_t)s.num_sections);
    bu32(&out, 0x60000000u);                       /* TimeDateStamp */
    bu32(&out, 0); bu32(&out, 0);                  /* symbol table */
    bu16(&out, (uint16_t)opt_size);
    bu16(&out, (uint16_t)(0x0022u | (s.is_dll ? 0x2000u : 0u)));

    /* Optional header */
    s.opt_off = btell(&out);
    bu16(&out, s.opt_magic);
    bu8(&out, 14); bu8(&out, 0);                   /* linker version */
    bu32(&out, 0x200); bu32(&out, (uint32_t)rd.len); bu32(&out, 0);
    bu32(&out, s.entry_rva);
    bu32(&out, TEXT_VA);                           /* BaseOfCode */
    if (!plus) bu32(&out, DATA_VA);                /* BaseOfData: PE32 only */
    if (plus) bu64(&out, s.image_base); else bu32(&out, (uint32_t)s.image_base);
    bu32(&out, 0x1000u);                           /* SectionAlignment */
    bu32(&out, FILE_ALIGN);
    bu16(&out, 6); bu16(&out, 0);                  /* OS version */
    bu16(&out, 0); bu16(&out, 0);                  /* image version */
    bu16(&out, 6); bu16(&out, 0);                  /* subsystem version */
    bu32(&out, 0);                                 /* Win32VersionValue */
    bu32(&out, size_of_image);
    bu32(&out, (uint32_t)hdr_size);                /* SizeOfHeaders */
    bu32(&out, 0);                                 /* CheckSum */
    bu16(&out, s.subsystem);
    bu16(&out, 0x0160u);                           /* DllCharacteristics */
    if (plus) { bu64(&out, 0x100000); bu64(&out, 0x1000);
                bu64(&out, 0x100000); bu64(&out, 0x1000); }
    else      { bu32(&out, 0x100000); bu32(&out, 0x1000);
                bu32(&out, 0x100000); bu32(&out, 0x1000); }
    bu32(&out, 0);                                 /* LoaderFlags */
    bu32(&out, PE_DIR_COUNT);                      /* NumberOfRvaAndSizes */

    /* Data directories */
    for (i = 0; i < PE_DIR_COUNT; i++) {
        uint32_t rva = 0, sz = 0;
        if (i == PE_DIR_IMPORT && s.with_imports) {
            rva = RDATA_VA + (uint32_t)desc_base; sz = 60;
        } else if (i == PE_DIR_BASERELOC && s.reloc_dir) {
            rva = DATA_VA; sz = 12;
        } else if (i == PE_DIR_TLS && s.tls_dir) {
            rva = RDATA_VA; sz = 40;
        } else if (i == PE_DIR_CLR && s.clr_dir) {
            rva = RDATA_VA; sz = 72;
        } else if (i == PE_DIR_BOUNDIMP && s.bound_dir) {
            rva = RDATA_VA; sz = 32;
        } else if (i == PE_DIR_IAT && s.with_imports) {
            rva = RDATA_VA + (uint32_t)iat_k32; sz = 16;
        }
        bu32(&out, rva); bu32(&out, sz);
    }

    /* Section table */
    s.sec_off = btell(&out);
    for (i = 0; i < s.num_sections; i++) {
        if (i == 0) {
            bput(&out, ".text\0\0\0", 8);
            bu32(&out, 0x50); bu32(&out, TEXT_VA);
            bu32(&out, 0x200); bu32(&out, (uint32_t)text_raw);
            bu32(&out, 0); bu32(&out, 0); bu16(&out, 0); bu16(&out, 0);
            bu32(&out, PE_SCN_CNT_CODE | PE_SCN_MEM_EXECUTE | PE_SCN_MEM_READ);
        } else if (i == 1) {
            bput(&out, ".rdata\0\0", 8);
            bu32(&out, (uint32_t)rd.len); bu32(&out, RDATA_VA);
            bu32(&out, 0x200); bu32(&out, (uint32_t)rdata_raw);
            bu32(&out, 0); bu32(&out, 0); bu16(&out, 0); bu16(&out, 0);
            bu32(&out, PE_SCN_CNT_INITIALIZED_DATA | PE_SCN_MEM_READ);
        } else if (i == 2) {
            bput(&out, ".data\0\0\0", 8);
            bu32(&out, 0x20); bu32(&out, DATA_VA);
            bu32(&out, 0x200); bu32(&out, (uint32_t)data_raw);
            bu32(&out, 0); bu32(&out, 0); bu16(&out, 0); bu16(&out, 0);
            bu32(&out, PE_SCN_CNT_INITIALIZED_DATA | PE_SCN_MEM_READ |
                       PE_SCN_MEM_WRITE);
        } else {
            char nm[9];
            /* Masked because i is only bounded by num_sections, which the
             * caller controls; snprintf alone would still be truncating for a
             * large i, and a truncated section name is a silent wrong answer. */
            snprintf(nm, sizeof(nm), ".x%02d", i & 0xFF);
            bput(&out, nm, 8);
            bu32(&out, 0x10); bu32(&out, 0x4000u + (uint32_t)(i - 3) * 0x1000u);
            bu32(&out, 0); bu32(&out, 0);
            bu32(&out, 0); bu32(&out, 0); bu16(&out, 0); bu16(&out, 0);
            bu32(&out, PE_SCN_MEM_READ);
        }
    }

    /* Pad to the first raw section, then write the three sections. */
    bzero(&out, text_raw - btell(&out));

    /* .text: a real x86-64 prologue and epilogue, so the fixture is the kind of
     * bytes the decoder will eventually be pointed at. */
    {
        static const uint8_t code[] = {
            0x48, 0x89, 0x5C, 0x24, 0x08,   /* mov [rsp+8], rbx */
            0x55, 0x56, 0x57,               /* push rbp/rsi/rdi */
            0x48, 0x83, 0xEC, 0x20,         /* sub rsp, 0x20 */
            0x48, 0x8B, 0xE9,               /* mov rbp, rcx */
            0x33, 0xC0,                     /* xor eax, eax */
            0x48, 0x83, 0xC4, 0x20,         /* add rsp, 0x20 */
            0x5F, 0x5E, 0x5D,               /* pop rdi/rsi/rbp */
            0xC3                            /* ret */
        };
        bput(&out, code, sizeof(code));
        bzero(&out, 0x200u - sizeof(code));
    }

    /* .rdata, at a file offset that is NOT its RVA */
    s.desc_off      = rdata_raw + desc_base;
    s.term_desc_off = rdata_raw + rd.len - 20u;
    s.dllname_off   = rdata_raw + nm_k32;
    bput(&out, rd.b, rd.len);
    bzero(&out, 0x200u - rd.len);

    /* .data */
    bzero(&out, 0x200u);
    if (s.unterminated_name) {
        /* Twelve bytes with no terminator as the final bytes of the file, and
         * .data widened to cover them so the RVA maps. Any zero padding after
         * this would silently terminate the scan and the test would pass for
         * the wrong reason. */
        int k;
        for (k = 0; k < 12; k++) bu8(&out, 'Q');
        bpatch32(&out, s.sec_off + 2u * 40u + 8u,  0x20Cu);  /* VirtualSize */
        bpatch32(&out, s.sec_off + 2u * 40u + 16u, 0x20Cu);  /* SizeOfRawData */
    }

    s.raw_len = btell(&out);
    CHECK(s.raw_len == total, "fixture length %zu != expected %zu", s.raw_len, total);
    (void)ord_dll_rva;

    free(rd.b);
    *io = s;              /* hand the recorded offsets back to the caller */
    return out;
}

/* --------------------------------------------------------------- good image */

static void test_good_image(void)
{
    fix s; buf f; pe_image im; pe_status st;
    fix_default(&s);
    f = build(&s);
    st = pe_load(f.b, f.len, &im);

    printf("a normal x86-64 GUI executable\n");
    if (!parsed(st, &im, "normal executable")) { free(f.b); return; }
    CHECK(im.machine == PE_MACHINE_AMD64, "machine %04x", im.machine);
    CHECK(seq(pe_machine_name(im.machine), "x64 (AMD64)"),
          "machine name '%s'", pe_machine_name(im.machine));
    CHECK(im.is_exe == 1 && im.is_dll == 0, "is_exe/is_dll = %d/%d",
          im.is_exe, im.is_dll);
    CHECK(im.subsystem == PE_SUBSYS_GUI, "subsystem %u", im.subsystem);
    CHECK(im.opt_magic == PE_MAGIC_PE32PLUS, "opt magic %04x", im.opt_magic);
    CHECK(im.entry_rva == TEXT_VA, "entry rva %08x", im.entry_rva);
    CHECK(im.image_base == 0x140000000ULL, "image base 0x%llx",
          (unsigned long long)im.image_base);
    CHECK(im.section_align == 0x1000u && im.file_align == FILE_ALIGN,
          "alignments %u/%u", im.section_align, im.file_align);
    CHECK(im.num_dirs == PE_DIR_COUNT, "num_dirs %u", im.num_dirs);
    CHECK(im.has_relocs == 1, "relocations not reported");
    CHECK(im.has_clr == 0, "CLR reported on a native image");
    CHECK(im.has_tls == 0, "TLS reported when the directory is empty");

    printf("section table\n");
    CHECK(im.num_sections == 3, "num_sections %u", im.num_sections);
    CHECK(im.sections_truncated == 0, "sections_truncated set");
    CHECK(seq(im.sections[0].name, ".text"), "section 0 '%s'",
          im.sections[0].name);
    CHECK(seq(im.sections[1].name, ".rdata"), "section 1 '%s'",
          im.sections[1].name);
    CHECK(seq(im.sections[2].name, ".data"), "section 2 '%s'",
          im.sections[2].name);
    CHECK((im.sections[0].characteristics & PE_SCN_MEM_EXECUTE) != 0,
          ".text is not marked executable");
    CHECK((im.sections[0].characteristics & PE_SCN_MEM_WRITE) == 0,
          ".text is marked writable");
    CHECK((im.sections[2].characteristics & PE_SCN_MEM_WRITE) != 0,
          ".data is not marked writable");

    /* The layout point the whole fixture exists for. */
    CHECK(im.sections[1].virtual_addr != im.sections[1].raw_ptr,
          "fixture is not exercising RVA != file offset");

    free(f.b);
}

static void test_rva_is_not_an_offset(void)
{
    fix s; buf f; pe_image im; int ok = 0; uint32_t off;
    fix_default(&s);
    f = build(&s);
    if (!parsed(pe_load(f.b, f.len, &im), &im, "good image failed to parse")) { free(f.b); return; }

    printf("an RVA is not a file offset\n");
    off = pe_rva_to_off(&im, im.dir_rva[PE_DIR_IMPORT], f.len, &ok);
    CHECK(ok == 1, "import directory RVA did not map");
    CHECK(off == s.desc_off, "mapped offset %08x != actual descriptor offset %08zx",
          off, s.desc_off);
    CHECK(off != im.dir_rva[PE_DIR_IMPORT],
          "mapping returned the RVA itself, so the fixture is not proving anything");

    /* Reading the descriptor array at its RVA as if that were a file offset
     * must NOT find a valid descriptor.
     *
     * This assertion has to guard its own pointer arithmetic. In this fixture
     * the RVA is larger than the whole image, so the naive read is not merely
     * wrong, it is out of bounds - which is the same mistake in a more extreme
     * form. A test that overflows to prove a parser should not overflow would
     * be a poor joke, so the two cases are handled separately. */
    {
        uint32_t rva = im.dir_rva[PE_DIR_IMPORT];
        if (rva + 20u <= f.len) {
            const uint8_t *naive = f.b + rva;
            CHECK(memcmp(naive, f.b + s.desc_off, 20) != 0,
                  "a naive RVA-as-offset read found the real descriptors, so the "
                  "fixture is too friendly to prove anything");
        } else {
            CHECK(rva > f.len,
                  "import RVA %08x lies inside the %zu-byte image, so this "
                  "fixture does not demonstrate that an RVA is not an offset",
                  rva, f.len);
        }
    }

    /* Unmappable RVAs must be reported, not clamped. */
    pe_rva_to_off(&im, 0x900000u, f.len, &ok);
    CHECK(ok == 0, "an RVA in no section was accepted");
    /* Inside .rdata's virtual range but past its raw data. */
    pe_rva_to_off(&im, RDATA_VA + 0x1F0u, f.len, &ok);
    CHECK(ok == 0, "an RVA in the zero-fill tail was mapped to a real offset");

    free(f.b);
}

/* ------------------------------------------------------------------ imports */

static void test_imports(void)
{
    fix s; buf f; pe_image im;
    fix_default(&s);
    f = build(&s);
    if (!parsed(pe_load(f.b, f.len, &im), &im, "good image failed to parse")) { free(f.b); return; }

    printf("import table: the DLLs a real binary needs\n");
    CHECK(im.has_imports == 1, "imports not reported");
    CHECK(im.num_dlls == 2, "num_dlls %u, expected 2", im.num_dlls);
    CHECK(seq(im.dlls[0].dll_name, "kernel32.dll"), "dll 0 '%s'",
          im.dlls[0].dll_name);
    CHECK(seq(im.dlls[1].dll_name, "user32.dll"), "dll 1 '%s'",
          im.dlls[1].dll_name);
    CHECK(im.dlls[0].func_count == 3, "kernel32 func_count %u, expected 3",
          im.dlls[0].func_count);
    CHECK(im.dlls[1].func_count == 2, "user32 func_count %u, expected 2",
          im.dlls[1].func_count);
    CHECK(pe_total_imports(&im) == 5, "total imports %u, expected 5",
          pe_total_imports(&im));

    /* Names must have come from the ILT. The IAT in this fixture is all zeros,
     * so a parser reading FirstThunk would have found nothing. */
    CHECK(im.dlls[0].ilt_rva != 0 && im.dlls[0].iat_rva != 0,
          "ILT or IAT rva is zero");
    CHECK(im.dlls[0].ilt_rva != im.dlls[0].iat_rva,
          "ILT and IAT are the same rva, so the distinction is not tested");

    CHECK(seq(im.funcs[0].name, "ExitProcess"),
          "func 0 '%s'", im.funcs[0].name ? im.funcs[0].name : "(null)");
    CHECK(im.funcs[0].by_ordinal == 0, "func 0 flagged by-ordinal");
    CHECK(seq(im.funcs[1].name, "GetProcAddress"),
          "func 1 '%s'", im.funcs[1].name ? im.funcs[1].name : "(null)");
    CHECK(seq(im.funcs[2].name, "LoadLibraryA"),
          "func 2 '%s'", im.funcs[2].name ? im.funcs[2].name : "(null)");
    CHECK(seq(im.funcs[3].name, "MessageBoxA"),
          "func 3 '%s'", im.funcs[3].name ? im.funcs[3].name : "(null)");

    CHECK(im.funcs[4].by_ordinal == 1, "ordinal import not flagged");
    CHECK(im.funcs[4].name == NULL, "ordinal import has a non-NULL name");
    CHECK(im.funcs[4].ordinal == 0x1234u, "ordinal %04x, expected 1234",
          im.funcs[4].ordinal);
    CHECK(im.imports_truncated == 0, "imports_truncated set on a small image");

    /* first_func/func_count must slice the flat array correctly */
    CHECK(im.dlls[1].first_func == 3, "user32 first_func %u, expected 3",
          im.dlls[1].first_func);

    free(f.b);
}

static void test_ordinal_only_dll(void)
{
    fix s; buf f; pe_image im;
    printf("a DLL imported purely by ordinal\n");

    fix_default(&s); s.ordinal_dll = 1;
    f = build(&s);
    if (!parsed(pe_load(f.b, f.len, &im), &im, "ordinal-dll image failed")) { free(f.b); return; }
    CHECK(im.num_dlls == 3, "num_dlls %u, expected 3", im.num_dlls);
    CHECK(seq(im.dlls[2].dll_name, "ordinalonly.dll"), "dll 2 '%s'",
          im.dlls[2].dll_name);
    CHECK(im.dlls[2].func_count == 2, "ordinal dll func_count %u",
          im.dlls[2].func_count);
    CHECK(im.funcs[5].by_ordinal == 1 && im.funcs[5].ordinal == 7u,
          "ordinal 7 not read: by_ord=%d ord=%u",
          im.funcs[5].by_ordinal, im.funcs[5].ordinal);
    CHECK(im.funcs[6].by_ordinal == 1 && im.funcs[6].ordinal == 8u,
          "ordinal 8 not read");
    CHECK(pe_total_imports(&im) == 7, "total %u, expected 7",
          pe_total_imports(&im));
    free(f.b);
}

static void test_over_long_name(void)
{
    fix s; buf f; pe_image im;
    printf("an imported name longer than PE_NAME_MAX\n");

    fix_default(&s); s.long_name = 1;
    f = build(&s);
    if (!parsed(pe_load(f.b, f.len, &im), &im, "long-name image failed")) { free(f.b); return; }
    CHECK(im.dlls[0].func_count == 4, "long-name dll func_count %u",
          im.dlls[0].func_count);
    CHECK(im.funcs[3].name_truncated == 1, "over-long name not flagged");
    CHECK(im.funcs[3].name && strlen(im.funcs[3].name) == PE_NAME_MAX + 12u,
          "over-long name length wrong");
    CHECK(im.funcs[0].name_truncated == 0, "short name flagged as truncated");
    free(f.b);
}

static void test_dll_shape(void)
{
    fix s; buf f; pe_image im;
    fix_default(&s);
    s.is_dll = 1;
    s.entry_rva = 0;          /* many DLLs export functions and have no entry */
    s.subsystem = PE_SUBSYS_CUI;
    f = build(&s);

    printf("a DLL with no entry point\n");
    if (!parsed(pe_load(f.b, f.len, &im), &im, "dll image failed")) { free(f.b); return; }
    CHECK(im.is_dll == 1 && im.is_exe == 0, "is_dll/is_exe = %d/%d",
          im.is_dll, im.is_exe);
    CHECK(im.entry_rva == 0, "entry_rva %u on a DLL with none", im.entry_rva);
    CHECK(im.subsystem == PE_SUBSYS_CUI, "subsystem %u", im.subsystem);
    free(f.b);
}

static void test_many_sections(void)
{
    fix s; buf f; pe_image im;
    printf("section counts, including the internal cap\n");

    /* Ten sections is what the real-world binaries in this project's census
     * had; the loop must handle it without disturbing the first three. */
    fix_default(&s); s.num_sections = 10; s.with_imports = 0;
    f = build(&s);
    if (!parsed(pe_load(f.b, f.len, &im), &im, "10-section image failed")) { free(f.b); return; }
    CHECK(im.num_sections == 10, "num_sections %u, expected 10", im.num_sections);
    CHECK(im.sections_truncated == 0, "truncation flagged at 10 sections");
    CHECK(seq(im.sections[9].name, ".x09"), "section 9 '%s'",
          im.sections[9].name);
    CHECK(im.has_imports == 0, "imports reported when the directory is empty");
    CHECK(im.num_dlls == 0, "num_dlls %u with no import directory", im.num_dlls);
    free(f.b);

    /* Over the cap: the section table is what makes RVA mapping correct, so a
     * capped table must be a refusal rather than a silent partial parse. */
    fix_default(&s); s.num_sections = PE_SCN_MAX + 4; s.with_imports = 0;
    f = build(&s);
    {
        pe_status st = pe_load(f.b, f.len, &im);
        CHECK(st == PE_UNSUPPORTED, "over-cap image returned %d, expected UNSUPPORTED", st);
        CHECK(im.sections_truncated == 1, "sections_truncated not set");
        CHECK(im.num_sections == PE_SCN_MAX, "num_sections %u, expected the cap",
              im.num_sections);
        CHECK(im.detail && strstr(im.detail, "sections") != NULL,
              "detail does not explain the refusal: '%s'", im.detail);
    }
    free(f.b);
}

/* ---------------------------------------------------------------- refusals */

static void test_unsupported_shapes(void)
{
    fix s; buf f; pe_image im; pe_status st;

    printf("images this translator must refuse rather than approximate\n");

    /* 32-bit x86: a real shape, and the single most common wrong answer is to
     * parse it as if it were 64-bit. */
    fix_default(&s);
    s.machine = PE_MACHINE_I386; s.opt_magic = PE_MAGIC_PE32;
    s.image_base = 0x00400000ULL; s.with_imports = 0;
    f = build(&s);
    st = pe_load(f.b, f.len, &im);
    CHECK(st == PE_UNSUPPORTED, "PE32 returned %d, expected UNSUPPORTED", st);
    CHECK(im.machine == PE_MACHINE_I386, "machine not reported on refusal");
    CHECK(seq(pe_machine_name(im.machine), "x86 (i386)"),
          "machine name '%s'", pe_machine_name(im.machine));
    CHECK(im.image_base == 0x00400000ULL, "PE32 image base read as 0x%llx",
          (unsigned long long)im.image_base);
    CHECK(im.opt_magic == PE_MAGIC_PE32, "opt magic %04x", im.opt_magic);
    CHECK(im.detail && strstr(im.detail, "32-bit") != NULL,
          "detail '%s' does not say why", im.detail);
    free(f.b);

    /* ARM64: already the host architecture, so "translating" it is meaningless
     * and must be reported as such, not silently accepted. */
    fix_default(&s);
    s.machine = PE_MACHINE_ARM64; s.with_imports = 0;
    f = build(&s);
    st = pe_load(f.b, f.len, &im);
    CHECK(st == PE_UNSUPPORTED, "ARM64 PE returned %d", st);
    CHECK(seq(pe_machine_name(im.machine), "ARM64 (AArch64)"),
          "machine name '%s'", pe_machine_name(im.machine));
    free(f.b);

    /* Managed (.NET): the CLR directory means the image contains IL, not
     * machine code. A CPU translator has nothing to translate, and pretending
     * otherwise produces a loader that "succeeds" and then runs garbage. */
    fix_default(&s); s.clr_dir = 1; s.with_imports = 0;
    f = build(&s);
    st = pe_load(f.b, f.len, &im);
    CHECK(st == PE_UNSUPPORTED, "CLR image returned %d", st);
    CHECK(im.has_clr == 1, "CLR directory not detected");
    CHECK(im.detail && strstr(im.detail, "managed") != NULL,
          "detail '%s' does not say managed", im.detail);
    free(f.b);

    /* Unknown machine number: report the number, do not invent a name. */
    fix_default(&s); s.machine = 0x0EBCu; s.with_imports = 0;
    f = build(&s);
    st = pe_load(f.b, f.len, &im);
    CHECK(st == PE_UNSUPPORTED, "unknown machine returned %d", st);
    CHECK(im.machine == 0x0EBCu, "unknown machine number not preserved");
    CHECK(seq(pe_machine_name(0x0EBCu), "?"),
          "unknown machine got a name");
    free(f.b);
}

static void test_bound_imports(void)
{
    fix s; buf f; pe_image im;
    fix_default(&s); s.bound_dir = 1;
    f = build(&s);

    printf("bound imports\n");
    if (!parsed(pe_load(f.b, f.len, &im), &im, "bound image failed")) { free(f.b); return; }
    CHECK(im.has_bound_imports == 1, "bound import directory not detected");
    /* Names are still readable from the ILT, so this is a warning not a
     * refusal - but the detail must say the IAT is not trustworthy. */
    CHECK(im.num_dlls == 2 && pe_total_imports(&im) == 5,
          "bound image lost imports: dlls=%u funcs=%u",
          im.num_dlls, pe_total_imports(&im));
    CHECK(im.detail && strstr(im.detail, "bound") != NULL,
          "detail '%s' does not warn about bound imports", im.detail);
    free(f.b);
}

static void test_tls_reported(void)
{
    fix s; buf f; pe_image im;
    fix_default(&s); s.tls_dir = 1;
    f = build(&s);

    printf("TLS callbacks run before the entry point\n");
    if (!parsed(pe_load(f.b, f.len, &im), &im, "tls image failed")) { free(f.b); return; }
    CHECK(im.has_tls == 1, "TLS directory not detected");
    free(f.b);
}

/* -------------------------------------------------------------- corruption */

static void test_corruption(void)
{
    fix s; buf f; pe_image im; pe_status st;

    printf("corruption and truncation must be refused, never half-parsed\n");

    fix_default(&s); f = build(&s);

    st = pe_load(NULL, f.len, &im);
    CHECK(st == PE_TRUNCATED, "NULL image returned %d", st);
    CHECK(im.detail != NULL, "detail is NULL after a failure");

    st = pe_load(f.b, 63, &im);
    CHECK(st == PE_TRUNCATED, "63-byte image returned %d", st);

    st = pe_load(f.b, f.len / 2, &im);
    CHECK(st != PE_OK, "half an image parsed successfully");

    /* Bad MZ */
    f.b[s.dos_magic_off] = 'X';
    st = pe_load(f.b, f.len, &im);
    CHECK(st == PE_BAD_MAGIC, "bad MZ returned %d", st);
    CHECK(im.detail && strstr(im.detail, "MZ") != NULL, "detail '%s'", im.detail);
    f.b[s.dos_magic_off] = 'M';

    /* Bad PE signature */
    f.b[s.pe_sig_off] = 'X';
    st = pe_load(f.b, f.len, &im);
    CHECK(st == PE_BAD_MAGIC, "bad PE sig returned %d", st);
    f.b[s.pe_sig_off] = 'P';

    /* e_lfanew pointing outside the image */
    bpatch32(&f, s.e_lfanew_off, (uint32_t)f.len + 0x1000u);
    st = pe_load(f.b, f.len, &im);
    CHECK(st == PE_BAD_MAGIC, "out-of-range e_lfanew returned %d", st);
    CHECK(im.detail && strstr(im.detail, "e_lfanew") != NULL,
          "detail '%s' does not name e_lfanew", im.detail);
    bpatch32(&f, s.e_lfanew_off, 0x80u);

    /* e_lfanew too small: would read the PE signature out of the DOS header */
    bpatch32(&f, s.e_lfanew_off, 2u);
    st = pe_load(f.b, f.len, &im);
    CHECK(st == PE_BAD_MAGIC, "e_lfanew=2 returned %d", st);
    bpatch32(&f, s.e_lfanew_off, 0x80u);

    /* Section count larger than the file can hold */
    {
        uint16_t old = (uint16_t)(f.b[s.coff_off + 2] | (f.b[s.coff_off + 3] << 8));
        f.b[s.coff_off + 2] = 0xFF; f.b[s.coff_off + 3] = 0xFF;
        st = pe_load(f.b, f.len, &im);
        CHECK(st == PE_TRUNCATED || st == PE_UNSUPPORTED,
              "65535 sections returned %d", st);
        f.b[s.coff_off + 2] = (uint8_t)old; f.b[s.coff_off + 3] = (uint8_t)(old >> 8);
    }

    /* A section claiming raw data past the end of the file */
    bpatch32(&f, s.sec_off + 40u + 20u, (uint32_t)f.len + 0x100u);
    st = pe_load(f.b, f.len, &im);
    CHECK(st == PE_TRUNCATED, "section past EOF returned %d", st);
    CHECK(im.detail && strstr(im.detail, "section") != NULL, "detail '%s'",
          im.detail);
    bpatch32(&f, s.sec_off + 40u + 20u, (uint32_t)(s.raw_len - 0x400u));

    /* Import descriptor array with its terminator removed: the walk must run
     * into the end of the image and refuse, not return a longer list. */
    memset(f.b + s.term_desc_off, 0xAB, 20);
    st = pe_load(f.b, f.len, &im);
    CHECK(st == PE_MALFORMED, "unterminated descriptors returned %d", st);
    CHECK(im.detail && strstr(im.detail, "import") != NULL, "detail '%s'",
          im.detail);
    memset(f.b + s.term_desc_off, 0, 20);

    /* After all that mutation the original image must still be intact */
    st = pe_load(f.b, f.len, &im);
    CHECK(st == PE_OK, "fixture not restored: %d (%s)", st, im.detail);
    CHECK(pe_total_imports(&im) == 5, "restored fixture lost imports");

    free(f.b);

    /* Import directory pointing at no section at all */
    fix_default(&s); f = build(&s);
    bpatch32(&f, s.opt_off + (size_t)(112u + PE_DIR_IMPORT * 8u), 0x900000u);
    st = pe_load(f.b, f.len, &im);
    CHECK(st == PE_MALFORMED, "bogus import RVA returned %d", st);
    CHECK(im.detail && strstr(im.detail, "no section") != NULL, "detail '%s'",
          im.detail);
    free(f.b);

    /* Descriptor with a NULL DLL name RVA */
    fix_default(&s); f = build(&s);
    bpatch32(&f, s.desc_off + 12u, 0u);
    st = pe_load(f.b, f.len, &im);
    CHECK(st == PE_MALFORMED, "NULL DLL name RVA returned %d", st);
    free(f.b);

    /* A descriptor claiming neither ILT nor IAT */
    fix_default(&s); f = build(&s);
    bpatch32(&f, s.desc_off + 0u, 0u);
    bpatch32(&f, s.desc_off + 16u, 0u);
    st = pe_load(f.b, f.len, &im);
    CHECK(st == PE_MALFORMED, "descriptor with no thunks returned %d", st);
    CHECK(im.detail && strstr(im.detail, "neither") != NULL, "detail '%s'",
          im.detail);
    free(f.b);
}

static void test_unterminated_name(void)
{
    fix s; buf f; pe_image im; pe_status st;

    printf("a name that is never terminated inside the image\n");
    fix_default(&s); s.unterminated_name = 1;
    f = build(&s);
    st = pe_load(f.b, f.len, &im);
    CHECK(st == PE_MALFORMED, "unterminated DLL name returned %d (%s)", st,
          im.detail ? im.detail : "(null)");
    CHECK(im.detail && strstr(im.detail, "NUL") != NULL,
          "detail '%s' does not say the name is unterminated", 
          im.detail ? im.detail : "(null)");
    /* The bytes really are at the end with no zero after them - otherwise this
     * test would be passing for the wrong reason. */
    CHECK(f.len >= 12 && memcmp(f.b + f.len - 12, "QQQQQQQQQQQQ", 12) == 0,
          "fixture does not end with the unterminated name");
    CHECK(f.b[f.len - 1] != 0, "fixture ends with a NUL after all");
    free(f.b);
}

static void test_out_always_written(void)
{
    fix s; buf f; pe_image im;
    fix_default(&s); f = build(&s);

    printf("out is cleared even when the parse fails early\n");
    memset(&im, 0xCD, sizeof(im));
    CHECK(pe_load("MZ", 2, &im) != PE_OK, "a 2-byte image parsed");
    CHECK(im.num_dlls == 0 && im.num_sections == 0 && im.num_funcs == 0,
          "failure left stale counts: dlls=%u sec=%u funcs=%u",
          im.num_dlls, im.num_sections, im.num_funcs);
    CHECK(im.detail != NULL, "detail NULL after an early failure");

    memset(&im, 0xCD, sizeof(im));
    if (!parsed(pe_load(f.b, f.len, &im), &im, "good image failed")) { free(f.b); return; }
    CHECK(im.num_dlls == 2, "good image did not fill in");

    CHECK(pe_load(f.b, f.len, NULL) == PE_MALFORMED,
          "NULL out was not rejected");
    free(f.b);
}

/* The mapping a runtime hands to X19. The property under test is the one a naive
 * loader gets wrong: sections go at their VIRTUAL address, not at their file
 * offset, and this fixture is built so that the two differ. Copying to the file
 * offset instead produces a mapping where every global is at the wrong address -
 * and since the wrong address is still inside the mapping, reads return bytes
 * rather than faulting. */
static void test_map_image_lays_sections_at_their_rvas(void)
{
    fix s; buf f; pe_image im; void *base; size_t sz = 0; uint32_t i;

    printf("mapping an image at its virtual addresses\n");
    fix_default(&s);
    f = build(&s);
    if (!parsed(pe_load(f.b, f.len, &im), &im, "good image failed to parse")) {
        free(f.b);
        return;
    }

    base = pe_map_image(f.b, f.len, &im, &sz);
    CHECK(base != NULL, "pe_map_image returned NULL for a valid image");
    if (!base) { free(f.b); return; }

    CHECK(sz == im.size_of_image, "mapping is %zu bytes, size_of_image says %u",
          sz, im.size_of_image);
    CHECK(((const uint8_t *)base)[0] == 'M' && ((const uint8_t *)base)[1] == 'Z',
          "the headers were not copied to the start of the mapping");

    for (i = 0; i < im.num_sections; i++) {
        const pe_section *sc = &im.sections[i];
        size_t cmp;
        if (sc->raw_size == 0) continue;
        cmp = sc->raw_size < 32u ? sc->raw_size : 32u;
        CHECK(memcmp((const uint8_t *)base + sc->virtual_addr,
                     f.b + sc->raw_ptr, cmp) == 0,
              "section %s at RVA %08X does not hold its file contents from %08X",
              sc->name, sc->virtual_addr, sc->raw_ptr);
    }
    /* The fixture is only exercising the interesting case if these differ. */
    CHECK(im.sections[1].virtual_addr != im.sections[1].raw_ptr,
          "the fixture no longer exercises RVA != file offset, so the checks above "
          "would pass even for a loader that copies to the wrong place");

    /* Refusals: a partial mapping is worse than none, because the missing part
     * reads as zeros instead of failing. */
    {
        pe_image bad = im;
        bad.size_of_image = 0;
        CHECK(pe_map_image(f.b, f.len, &bad, &sz) == NULL,
              "an image with size_of_image 0 was mapped instead of refused");
    }
    {
        pe_image bad = im;
        bad.sections[0].raw_size = (uint32_t)f.len + 4096u;
        CHECK(pe_map_image(f.b, f.len, &bad, &sz) == NULL,
              "a section claiming raw data past the end of the file was mapped "
              "instead of refused");
    }
    {
        pe_image bad = im;
        bad.sections[0].virtual_addr = bad.size_of_image;
        CHECK(pe_map_image(f.b, f.len, &bad, &sz) == NULL,
              "a section placed past size_of_image was mapped instead of refused");
    }
    CHECK(pe_map_image(NULL, f.len, &im, &sz) == NULL, "a NULL image was mapped");

    munmap(base, sz);
    free(f.b);
}

int main(int argc, char **argv)
{
    /* Writes the default fixture to a file so pe_info can be run over it. The
     * suite asserts on pe_info's output through the Makefile, which is what
     * makes the CLI part of the tested surface rather than a script that
     * happens to compile. */
    if (argc == 3 && strcmp(argv[1], "--write-fixture") == 0) {
        fix   sp;
        buf   f;
        FILE *fp;
        fix_default(&sp);
        f = build(&sp);
        fp = fopen(argv[2], "wb");
        if (!fp) { perror(argv[2]); free(f.b); return 1; }
        if (fwrite(f.b, 1, f.len, fp) != f.len) {
            fprintf(stderr, "short write to %s\n", argv[2]);
            fclose(fp); free(f.b); return 1;
        }
        fclose(fp);
        printf("wrote %zu bytes to %s\n", f.len, argv[2]);
        free(f.b);
        return 0;
    }
    if (argc != 1) {
        fprintf(stderr, "usage: test_pe [--write-fixture <path>]\n");
        return 1;
    }

    printf("=== PE image parser ===\n");
    test_good_image();


    test_imports();
    test_ordinal_only_dll();
    test_over_long_name();
    test_dll_shape();
    test_many_sections();
    test_unsupported_shapes();
    test_bound_imports();
    test_tls_reported();
    test_corruption();
    test_unterminated_name();
    test_out_always_written();
    test_rva_is_not_an_offset();
    test_map_image_lays_sections_at_their_rvas();

    printf("\n%d checks, %d failure(s)\n", checks, failures);
    return failures ? 1 : 0;
}
