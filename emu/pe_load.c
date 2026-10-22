/* PE image parser - see pe_load.h for the design rules.
 *
 * Little-endian only, which is not a limitation: PE is defined as
 * little-endian on every architecture Windows ships it for.
 *
 * No struct casting is used anywhere in this file. Fields are read with
 * explicit little-endian accessors that take a bounds-checked offset, because
 * casting a byte buffer to a struct assumes both the compiler's padding and
 * that the buffer is really as long as the struct claims. For untrusted input
 * the second assumption is exactly what must not be made.
 */
#include "pe_load.h"

#include <string.h>

/* ---- bounded little-endian access -------------------------------------- */

typedef struct {
    const uint8_t *b;
    size_t         len;
    int            ok;   /* sticky: cleared on the first out-of-range read */
} pec;

static int fits(const pec *c, size_t off, size_t n)
{
    return off <= c->len && n <= c->len - off;
}

static uint16_t rd16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

static uint32_t rd32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint64_t rd64(const uint8_t *p)
{
    return (uint64_t)rd32(p) | ((uint64_t)rd32(p + 4) << 32);
}

static uint16_t g16(pec *c, size_t off)
{
    if (!fits(c, off, 2)) { c->ok = 0; return 0; }
    return rd16(c->b + off);
}

static uint32_t g32(pec *c, size_t off)
{
    if (!fits(c, off, 4)) { c->ok = 0; return 0; }
    return rd32(c->b + off);
}

static uint64_t g64(pec *c, size_t off)
{
    if (!fits(c, off, 8)) { c->ok = 0; return 0; }
    return rd64(c->b + off);
}

/* Reads a byte only after confirming it exists. Used for string scans, where
 * reading one byte past the image is the whole bug. */
static int gbyte(pec *c, size_t off, uint8_t *out)
{
    if (!fits(c, off, 1)) { c->ok = 0; return 0; }
    *out = c->b[off];
    return 1;
}

/* ---- string helpers ---------------------------------------------------- */

/* Returns the length of a NUL-terminated ASCII string at off, or -1 when no
 * terminator appears before the end of the image. A -1 is a hard error: the
 * alternative would be returning a pointer to memory that is not terminated,
 * and every consumer that later calls strlen on it would read out of bounds. */
static long slen(pec *c, size_t off)
{
    size_t i = off;
    uint8_t ch;
    while (i < c->len) {
        if (!gbyte(c, i, &ch)) return -1;
        if (ch == 0) return (long)(i - off);
        i++;
    }
    return -1;
}

const char *pe_machine_name(uint16_t machine)
{
    switch (machine) {
    case PE_MACHINE_I386:  return "x86 (i386)";
    case PE_MACHINE_AMD64: return "x64 (AMD64)";
    case PE_MACHINE_ARM:   return "ARM (32-bit)";
    case PE_MACHINE_ARM64: return "ARM64 (AArch64)";
    default:               return "?";
    }
}

uint32_t pe_total_imports(const pe_image *im)
{
    return im ? im->num_funcs : 0u;
}

uint32_t pe_rva_to_off(const pe_image *im, uint32_t rva, size_t len, int *ok)
{
    uint32_t i;
    if (ok) *ok = 0;
    if (!im) return 0;
    for (i = 0; i < im->num_sections; i++) {
        const pe_section *s = &im->sections[i];
        uint32_t span = s->virtual_size ? s->virtual_size : s->raw_size;
        if (s->virtual_size == 0) continue;
        if (rva < s->virtual_addr) continue;
        if (rva - s->virtual_addr >= span) continue;
        /* The tail of a section whose raw data is shorter than its virtual
         * size is zero-filled by the loader at run time. It has no file
         * offset, so it is reported as unmappable rather than clamped to the
         * last real byte - clamping would read unrelated data as if it were
         * the target. */
        if (rva - s->virtual_addr >= s->raw_size) return 0;
        if (s->raw_ptr >= len) return 0;
        if (ok) *ok = 1;
        return s->raw_ptr + (rva - s->virtual_addr);
    }
    return 0;
}

/* ---- import table walk ------------------------------------------------- */

/* Adds one imported function. Returns 0 when a cap was hit, so the caller can
 * record that the enumeration is incomplete instead of pretending it is not. */
static int add_func(pe_image *o, const char *name, uint16_t ordinal, int by_ord)
{
    pe_import_func *f;
    if (o->num_funcs >= PE_FUNC_MAX) return 0;
    f = &o->funcs[o->num_funcs++];
    f->name = name;
    f->ordinal = ordinal;
    f->by_ordinal = by_ord;
    f->name_truncated = (name && strlen(name) > PE_NAME_MAX) ? 1 : 0;
    return 1;
}

/* Walks one DLL's thunk array. PE32+ thunks are 8 bytes and mark an ordinal
 * with the top bit of a 64-bit word; PE32 thunks are 4 bytes with the top bit
 * of a 32-bit word. Using the wrong width misreads every entry after the
 * first, so the width comes from the optional header magic and nowhere else. */
static pe_status walk_thunks(pec *c, pe_image *o, const pe_import_dll *d,
                             int pe32plus)
{
    uint32_t thunk_rva = d->ilt_rva ? d->ilt_rva : d->iat_rva;
    size_t   pos, step = pe32plus ? 8u : 4u;
    int      mapped = 0;

    if (thunk_rva == 0) {
        o->detail = "import descriptor with neither ILT nor IAT";
        return PE_MALFORMED;
    }
    pos = pe_rva_to_off(o, thunk_rva, c->len, &mapped);
    if (!mapped) {
        o->detail = "import thunk RVA maps to no section";
        return PE_MALFORMED;
    }

    for (;;) {
        uint64_t thunk;
        uint32_t name_rva;
        int      name_mapped = 0;
        size_t   name_off;
        long     n;

        if (!fits(c, pos, step)) {
            /* A thunk array that runs off the image without its zero
             * terminator is malformed, not merely short. */
            o->detail = "import thunk array runs past end of image";
            return PE_MALFORMED;
        }
        thunk = pe32plus ? rd64(c->b + pos) : (uint64_t)rd32(c->b + pos);
        if (thunk == 0) return PE_OK;         /* proper terminator */
        pos += step;

        if (pe32plus ? (thunk >> 63) : ((thunk >> 31) & 1u)) {
            if (!add_func(o, NULL, (uint16_t)(thunk & 0xFFFFu), 1)) {
                o->imports_truncated = 1;
                return PE_OK;
            }
            continue;
        }

        name_rva = (uint32_t)(thunk & 0x7FFFFFFFu);
        name_off = pe_rva_to_off(o, name_rva, c->len, &name_mapped);
        if (!name_mapped) {
            o->detail = "IMAGE_IMPORT_BY_NAME RVA maps to no section";
            return PE_MALFORMED;
        }
        /* 2-byte hint, then the NUL-terminated name. */
        if (!fits(c, name_off + 2u, 1)) {
            o->detail = "import name entry truncated before the name";
            return PE_TRUNCATED;
        }
        n = slen(c, name_off + 2u);
        if (n < 0) {
            o->detail = "import name is not NUL-terminated inside the image";
            return PE_MALFORMED;
        }
        if (!add_func(o, (const char *)(c->b + name_off + 2u), 0, 0)) {
            o->imports_truncated = 1;
            return PE_OK;
        }
    }
}

static pe_status walk_imports(pec *c, pe_image *o)
{
    uint32_t dir_rva = o->dir_rva[PE_DIR_IMPORT];
    size_t   pos;
    int      mapped = 0;

    if (dir_rva == 0) { o->has_imports = 0; return PE_OK; }
    o->has_imports = 1;

    pos = pe_rva_to_off(o, dir_rva, c->len, &mapped);
    if (!mapped) {
        o->detail = "import directory RVA maps to no section";
        return PE_MALFORMED;
    }

    for (;;) {
        uint32_t oft, ts, fwd, name_rva, ft;
        size_t   name_off;
        long     n;
        int      name_mapped = 0;
        pe_import_dll *d;

        /* 20 bytes per descriptor; an all-zero descriptor terminates. */
        if (!fits(c, pos, 20)) {
            o->detail = "import descriptor array runs past end of image";
            return PE_MALFORMED;
        }
        oft      = rd32(c->b + pos + 0u);
        ts       = rd32(c->b + pos + 4u);
        fwd      = rd32(c->b + pos + 8u);
        name_rva = rd32(c->b + pos + 12u);
        ft       = rd32(c->b + pos + 16u);
        (void)ts; (void)fwd;   /* read for structure; not needed to enumerate */

        if (oft == 0 && ts == 0 && fwd == 0 && name_rva == 0 && ft == 0)
            return PE_OK;      /* proper terminator */
        pos += 20;

        if (o->num_dlls >= PE_DLL_MAX) { o->imports_truncated = 1; return PE_OK; }

        if (name_rva == 0) {
            o->detail = "import descriptor with a NULL DLL name RVA";
            return PE_MALFORMED;
        }
        name_off = pe_rva_to_off(o, name_rva, c->len, &name_mapped);
        if (!name_mapped) {
            o->detail = "import DLL name RVA maps to no section";
            return PE_MALFORMED;
        }
        n = slen(c, name_off);
        if (n < 0) {
            o->detail = "import DLL name is not NUL-terminated inside the image";
            return PE_MALFORMED;
        }

        d = &o->dlls[o->num_dlls];
        d->dll_name  = (const char *)(c->b + name_off);
        d->ilt_rva   = oft;
        d->iat_rva   = ft;
        d->first_func = o->num_funcs;
        d->func_count = 0;
        o->num_dlls++;

        {
            uint32_t before = o->num_funcs;
            pe_status st = walk_thunks(c, o, d,
                                       o->opt_magic == PE_MAGIC_PE32PLUS);
            if (st != PE_OK) return st;
            d->func_count = o->num_funcs - before;
        }
    }
}

/* ---- section table ----------------------------------------------------- */

static pe_status walk_sections(pec *c, pe_image *o, size_t sec_off,
                               uint16_t count)
{
    uint16_t i;
    uint32_t n = count;

    if (n > PE_SCN_MAX) { n = PE_SCN_MAX; o->sections_truncated = 1; }

    for (i = 0; i < n; i++) {
        size_t   base = sec_off + (size_t)i * 40u;
        pe_section *s;
        uint32_t vsize, va, rsize, rptr;

        if (!fits(c, base, 40)) {
            o->detail = "section table runs past end of image";
            return PE_TRUNCATED;
        }
        s = &o->sections[o->num_sections];
        memcpy(s->name, c->b + base, 8);
        s->name[8] = '\0';        /* PE names are 8 bytes and may not end in 0 */

        vsize = rd32(c->b + base + 8u);
        va    = rd32(c->b + base + 12u);
        rsize = rd32(c->b + base + 16u);
        rptr  = rd32(c->b + base + 20u);
        s->characteristics = rd32(c->b + base + 36u);

        /* A section whose raw data claims to start past the end of the file
         * cannot be mapped. Rejecting it here is what keeps pe_rva_to_off from
         * returning an offset that callers would then read through. */
        if (rsize != 0 && rptr > c->len) {
            o->detail = "section PointerToRawData is past end of image";
            return PE_TRUNCATED;
        }
        if (rsize != 0 && rsize > c->len - rptr) {
            o->detail = "section raw data runs past end of image";
            return PE_TRUNCATED;
        }
        s->virtual_size = vsize;
        s->virtual_addr = va;
        s->raw_size     = rsize;
        s->raw_ptr      = rptr;
        o->num_sections++;
    }
    return PE_OK;
}

/* ---- top level --------------------------------------------------------- */

pe_status pe_load(const void *img, size_t len, pe_image *out)
{
    pec c;
    uint32_t e_lfanew, num_sec, opt_size, chars, ndirs, dir_base, i;
    uint16_t machine, magic;
    size_t   nt, opt, sec_off;
    int      pe32plus;

    if (!out) return PE_MALFORMED;
    memset(out, 0, sizeof(*out));
    out->detail = "ok";

    if (!img || len < 64) {
        out->detail = "image shorter than a DOS header";
        return PE_TRUNCATED;
    }
    c.b = (const uint8_t *)img;
    c.len = len;
    c.ok = 1;

    if (rd16(c.b) != 0x5A4Du) {          /* 'MZ' little-endian */
        out->detail = "missing MZ signature";
        return PE_BAD_MAGIC;
    }
    e_lfanew = g32(&c, 0x3Cu);
    if (!c.ok) { out->detail = "image truncated at e_lfanew"; return PE_TRUNCATED; }
    if (e_lfanew < 4 || (size_t)e_lfanew > len - 4u) {
        out->detail = "e_lfanew points outside the image";
        return PE_BAD_MAGIC;
    }
    nt = e_lfanew;
    if (rd32(c.b + nt) != 0x00004550u) {  /* "PE\0\0" little-endian */
        out->detail = "missing PE signature at e_lfanew";
        return PE_BAD_MAGIC;
    }

    /* COFF file header: 20 bytes immediately after the signature. */
    if (!fits(&c, nt + 4u, 20u)) {
        out->detail = "image truncated inside the COFF header";
        return PE_TRUNCATED;
    }
    machine  = rd16(c.b + nt + 4u);
    num_sec  = (uint32_t)rd16(c.b + nt + 6u);
    opt_size = (uint32_t)rd16(c.b + nt + 20u);
    chars    = rd16(c.b + nt + 22u);
    out->machine = machine;
    out->is_dll  = (chars & 0x2000u) ? 1 : 0;
    out->is_exe  = out->is_dll ? 0 : 1;

    opt = nt + 24u;
    if (opt_size < 2 || !fits(&c, opt, opt_size)) {
        out->detail = "optional header extends past end of image";
        return PE_TRUNCATED;
    }
    magic = rd16(c.b + opt);
    out->opt_magic = magic;
    pe32plus = (magic == PE_MAGIC_PE32PLUS);

    if (magic != PE_MAGIC_PE32 && magic != PE_MAGIC_PE32PLUS) {
        out->detail = "unknown optional header magic (not PE32 or PE32+)";
        return PE_UNSUPPORTED;
    }

    out->entry_rva = g32(&c, opt + 16u);
    /* ImageBase is 8 bytes at 24 in PE32+ and 4 bytes at 28 in PE32. Reading
     * the wrong one yields a base address that is off by four billion. */
    out->image_base = pe32plus ? g64(&c, opt + 24u) : (uint64_t)g32(&c, opt + 28u);
    out->section_align = g32(&c, opt + 32u);
    out->file_align    = g32(&c, opt + 36u);
    out->size_of_image = g32(&c, opt + 56u);
    out->subsystem     = g16(&c, opt + 68u);
    if (!c.ok) {
        out->detail = "optional header truncated before its fixed fields";
        return PE_TRUNCATED;
    }

    ndirs = g32(&c, opt + (pe32plus ? 108u : 92u));
    if (!c.ok) { out->detail = "truncated at NumberOfRvaAndSizes"; return PE_TRUNCATED; }
    if (ndirs > PE_DIR_COUNT) ndirs = PE_DIR_COUNT;
    out->num_dirs = ndirs;

    dir_base = (uint32_t)(opt + (pe32plus ? 112u : 96u));
    for (i = 0; i < ndirs; i++) {
        size_t d = dir_base + (size_t)i * 8u;
        if (!fits(&c, d, 8u)) break;      /* fewer directories than declared */
        out->dir_rva[i]  = rd32(c.b + d);
        out->dir_size[i] = rd32(c.b + d + 4u);
    }
    out->has_relocs        = out->dir_rva[PE_DIR_BASERELOC] != 0;
    out->has_tls           = out->dir_rva[PE_DIR_TLS] != 0;
    out->has_clr           = out->dir_rva[PE_DIR_CLR] != 0;
    out->has_debug         = out->dir_rva[PE_DIR_DEBUG] != 0;
    out->has_bound_imports = out->dir_rva[PE_DIR_BOUNDIMP] != 0;
    out->has_delay_imports = out->dir_rva[PE_DIR_DELAYIMP] != 0;

    sec_off = opt + opt_size;
    {
        pe_status st = walk_sections(&c, out, sec_off, (uint16_t)num_sec);
        if (st != PE_OK) return st;
    }
    if (out->sections_truncated) {
        /* The section table is what makes RVA mapping correct, so a capped
         * table means RVA lookups can no longer be trusted as complete. */
        out->detail = "more sections than PE_SCN_MAX; RVA mapping incomplete";
        return PE_UNSUPPORTED;
    }

    /* From here the header is readable. Anything below is a reason not to
     * translate this image, reported after the fields above are filled in. */
    if (out->has_clr) {
        out->detail = "managed (.NET) image: CLR directory present, no native code to translate";
        return PE_UNSUPPORTED;
    }
    /* Format before machine: a 32-bit image is refused for being 32-bit
     * whatever its machine, and saying so is the more useful reason. The
     * machine is still reported in out->machine either way. */
    if (!pe32plus) {
        out->detail = "32-bit (PE32) image; only 64-bit guests are modelled";
        return PE_UNSUPPORTED;
    }
    if (machine != PE_MACHINE_AMD64) {
        out->detail = "machine is not x86-64; this translator emits ARM64 from x86-64 guests only";
        return PE_UNSUPPORTED;
    }

    {
        pe_status st = walk_imports(&c, out);
        if (st != PE_OK) return st;
    }

    if (out->has_bound_imports) {
        /* A bound image carries pre-resolved addresses in the IAT. The names
         * were still read from the ILT, so this is a warning rather than an
         * error - but the IAT contents must not be treated as names. */
        out->detail = "bound imports present; IAT holds pre-resolved addresses";
    } else if (out->imports_truncated) {
        out->detail = "import enumeration hit an internal cap; list is incomplete";
    } else {
        out->detail = "ok";
    }
    return PE_OK;
}
