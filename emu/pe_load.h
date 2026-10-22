/* PE image parser for x86-64 Windows executables - written from scratch.
 *
 * Why this comes before any translation: a translator cannot run a .exe it
 * cannot load. The import directory is where "real DLLs" actually appear - it
 * is the list of external functions the guest expects to exist, and every one
 * of them is a hole the translator must fill with a native implementation or a
 * bridge. Enumerating that list is the first honest measurement of how much
 * work running a given binary really is.
 *
 * Design rule, inherited from the decoder: never guess. This parser treats the
 * image as untrusted input, bounds-checks every declared offset, and reports a
 * specific failure instead of returning a plausible-looking partial result. A
 * PE parser that reads past a truncated buffer or follows a bogus RVA does not
 * merely produce wrong output - it is a memory-safety hole in the emulator, and
 * the emulator will be handed files it does not control.
 *
 * Two distinctions that are easy to get backwards, and that matter here:
 *
 *   - RVA is not a file offset. Data directories are relative virtual
 *     addresses, which must be mapped through the section table because
 *     VirtualAddress and PointerToRawData differ in real files (alignment). A
 *     parser that uses an RVA as an offset happens to work on some images and
 *     silently reads garbage from others.
 *
 *   - OriginalFirstThunk is not FirstThunk. The ILT (OriginalFirstThunk) holds
 *     the import names as they exist in the file. The IAT (FirstThunk) is the
 *     same shape but the OS loader overwrites it with resolved addresses at run
 *     time; it is what the guest actually calls through. Names come from the
 *     ILT, falling back to the IAT only when OriginalFirstThunk is zero.
 *
 * Data directory 4 (SECURITY / certificate table) is a raw file offset, not an
 * RVA. It is the one exception, and treating it like the others points outside
 * the intended data.
 */
#ifndef PE_LOAD_H
#define PE_LOAD_H

#include <stddef.h>
#include <stdint.h>

typedef enum {
    PE_OK = 0,        /* parsed; the fields below are trustworthy */
    PE_BAD_MAGIC,     /* not MZ, or no PE signature where e_lfanew points */
    PE_TRUNCATED,     /* a declared field extends past the end of the image */
    PE_UNSUPPORTED,   /* a valid PE, but not a 64-bit native x86-64 image */
    PE_MALFORMED      /* internally inconsistent: unterminated list, bogus RVA */
} pe_status;

/* COFF machine types this parser recognises well enough to report. Anything
 * else is surfaced by number rather than guessed at. */
#define PE_MACHINE_I386   0x014Cu
#define PE_MACHINE_ARM    0x01C0u
#define PE_MACHINE_ARM64  0xAA64u
#define PE_MACHINE_AMD64  0x8664u

/* Optional header magic. */
#define PE_MAGIC_PE32     0x10Bu   /* 32-bit: 4-byte thunks, 224-byte header */
#define PE_MAGIC_PE32PLUS 0x20Bu   /* 64-bit: 8-byte thunks, 240-byte header */

#define PE_SUBSYS_UNKNOWN 0u
#define PE_SUBSYS_GUI     2u
#define PE_SUBSYS_CUI     3u

/* Data directory indices. */
#define PE_DIR_EXPORT     0   /* a DLL's exports are its entry points */
#define PE_DIR_IMPORT     1
#define PE_DIR_RESOURCE   2
#define PE_DIR_EXCEPTION  3
#define PE_DIR_SECURITY   4   /* raw file offset, NOT an RVA */
#define PE_DIR_BASERELOC  5
#define PE_DIR_DEBUG      6
#define PE_DIR_TLS        9
#define PE_DIR_LOADCFG   10
#define PE_DIR_BOUNDIMP  11
#define PE_DIR_IAT       12
#define PE_DIR_DELAYIMP  13
#define PE_DIR_CLR       14   /* present => managed (.NET), not native */
#define PE_DIR_COUNT     16

/* Section characteristics that change how a translator must treat a page. */
#define PE_SCN_CNT_CODE             0x00000020u
#define PE_SCN_CNT_INITIALIZED_DATA 0x00000040u
#define PE_SCN_MEM_DISCARDABLE      0x02000000u
#define PE_SCN_MEM_EXECUTE          0x20000000u
#define PE_SCN_MEM_READ             0x40000000u
#define PE_SCN_MEM_WRITE            0x80000000u

#define PE_SCN_MAX        96   /* real binaries stay far below this */
#define PE_DLL_MAX        64
#define PE_FUNC_MAX      512
#define PE_NAME_MAX       64   /* truncation is reported, never overflowed */
#define PE_EXPORT_MAX    512

typedef struct {
    char     name[9];        /* PE names are 8 bytes and not NUL-terminated */
    uint32_t virtual_size;
    uint32_t virtual_addr;
    uint32_t raw_size;
    uint32_t raw_ptr;
    uint32_t characteristics;
} pe_section;

/* One imported function. name is NULL when the import is by ordinal only;
 * by_ordinal then says which case applies, so a NULL name is never ambiguous.
 * Both pointers reference the caller's image buffer and stay valid only as
 * long as that buffer does. */
typedef struct {
    const char *name;
    uint16_t    ordinal;
    int         by_ordinal;
    int         name_truncated;
} pe_import_func;

/* One exported function. For a DLL these are the entry points a pre-translation
 * sweep has to start from: an .exe has one entry point, a DLL has as many as it
 * exports, and starting only from DllMain would leave most of the code
 * undiscovered. name is NULL for an ordinal-only export. */
typedef struct {
    const char *name;
    uint32_t    rva;          /* 0 or inside the image: forwarders point at a
                               * string instead of code, flagged below */
    uint16_t    ordinal;
    int         forwarded;    /* export forwards to another DLL; rva is a name */
} pe_export_fn;

typedef struct {
    const char *dll_name;    /* references the image buffer */
    uint32_t    first_func;  /* index into pe_image.funcs */
    uint32_t    func_count;
    uint32_t    ilt_rva;     /* names as stored in the file */
    uint32_t    iat_rva;     /* what the guest calls through at run time */
} pe_import_dll;

typedef struct {
    /* headers */
    int      is_dll;
    int      is_exe;
    uint16_t machine;
    uint16_t subsystem;
    uint16_t opt_magic;
    uint32_t entry_rva;         /* 0 means no entry point (some DLLs) */
    uint64_t image_base;
    uint32_t size_of_image;
    uint32_t section_align;
    uint32_t file_align;
    uint32_t num_dirs;          /* as declared; may be < PE_DIR_COUNT */

    /* directories, as declared: rva and size pairs, plus presence flags for
     * the ones a translator has to act on */
    uint32_t dir_rva[PE_DIR_COUNT];
    uint32_t dir_size[PE_DIR_COUNT];
    int      has_exports;
    int      has_imports;
    int      has_relocs;
    int      has_tls;           /* TLS callbacks run BEFORE the entry point */
    int      has_clr;           /* managed image: no CPU translation applies */
    int      has_debug;
    int      has_bound_imports; /* a bound IAT must not be trusted for names */
    int      has_delay_imports; /* parsed separately; reported, not walked */

    /* sections */
    uint32_t   num_sections;
    pe_section sections[PE_SCN_MAX];
    int        sections_truncated;  /* more than PE_SCN_MAX: count is capped */

    /* exports */
    uint32_t     num_exports;
    pe_export_fn exports[PE_EXPORT_MAX];
    int          exports_truncated;

    /* imports */
    uint32_t       num_dlls;
    pe_import_dll  dlls[PE_DLL_MAX];
    uint32_t       num_funcs;
    pe_import_func funcs[PE_FUNC_MAX];
    int            imports_truncated; /* caps reached; the list is incomplete */

    /* diagnostics: set on failure, and on success when something was refused
     * rather than approximated. Never NULL after a parse attempt. */
    const char *detail;
} pe_image;

/* Parses a PE image held entirely in memory. img points at the first byte of
 * the file (the DOS header), len is its exact length. Nothing is copied out of
 * the buffer except into the fixed arrays above; string results point into it.
 *
 * Returns PE_OK only for a 64-bit native x86-64 image whose import table was
 * walked to completion. A valid PE that is 32-bit, ARM, or managed returns
 * PE_UNSUPPORTED with the reason in out->detail and the header fields that were
 * read still filled in, because "what is this file" is useful even when "load
 * it" is not.
 *
 * out is always written: cleared first, then filled as far as the parse got. */
pe_status pe_load(const void *img, size_t len, pe_image *out);

/* Maps an RVA to an offset in the file image using the section table.
 * Returns 0 and sets *ok to 0 when the RVA falls in no section, which is what
 * makes a bad directory entry detectable instead of silently reading the wrong
 * bytes. A section's raw data may be shorter than its virtual size; the tail is
 * zero-filled by the loader at run time and has no file offset, so an RVA there
 * is reported as unmappable rather than clamped. */
uint32_t pe_rva_to_off(const pe_image *im, uint32_t rva, size_t len, int *ok);

/* Number of imported functions across all DLLs, for reporting. */
uint32_t pe_total_imports(const pe_image *im);

/* Machine type as a readable string; "?" for one this parser does not name. */
const char *pe_machine_name(uint16_t machine);

#endif /* PE_LOAD_H */
