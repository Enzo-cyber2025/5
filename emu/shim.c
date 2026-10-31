/* Host stand-ins for the Win32 functions a translated guest calls first.
 *
 * Three functions, and the choice is not arbitrary: they are what a minimal console
 * program's entry point uses, which makes them the smallest set that lets a real
 * compiler-produced executable do something observable. Each takes four parameters or
 * fewer because that is all the host ABI bridge marshals - x86-64 passes the fifth
 * argument onward on the guest stack, and nothing reads it yet. A shim needing more
 * supplies the rest itself, and where that happens it is said in the shim rather than
 * left to look faithful. */

#include "shim.h"

#include <stdio.h>
#include <string.h>

/* The mappings the shims translate guest pointers through, keyed by guest base.
 * File scope because the bridge marshals four arguments and leaves no parameter for a
 * context. Keyed rather than single because a sweep sees a module as the file buffer
 * it was read into while execution sees it as a mapping produced later, and both have
 * the same guest base - so the second registration for a base replaces the first
 * instead of sitting alongside it and being found first. */
#define SHIM_MAX_MAPS 64u
typedef struct { uint8_t *image; size_t len; uint64_t base_va; } shim_map;
static shim_map shim_maps[SHIM_MAX_MAPS];
static size_t   shim_nmaps;

static shim_map *shim_map_for(uint64_t base_va)
{
    size_t i;
    for (i = 0; i < shim_nmaps; i++)
        if (shim_maps[i].base_va == base_va) return &shim_maps[i];
    if (shim_nmaps < SHIM_MAX_MAPS) {
        shim_maps[shim_nmaps].base_va = base_va;
        return &shim_maps[shim_nmaps++];
    }
    return NULL;
}

/* Slots shim_fill_iat recorded, so shim_resolve can answer for exactly those. The
 * base is stored per slot rather than looked up in the mapping table: a sweep records
 * slots without a mapping - it has the file, not an image - and a resolver that only
 * answers for bases it has already seen a mapping for would answer for none of them.
 * That is precisely the failure this replaces: the slot list was correct and complete
 * and the resolver still returned 0 for every slot in it. */
static uint64_t shim_slot_va[SHIM_MAX_SLOTS];
static uint64_t shim_slot_base[SHIM_MAX_SLOTS];
static size_t   shim_slot_n;

/* Recorded rather than acted on. A real ExitProcess does not return, and honouring
 * that from inside generated code would need a longjmp out of it or an actual process
 * to end - while the harness still has to collect a return value to assert on. */
static uint64_t shim_exit_code;
static int      shim_exit_called;

/* --------------------------------------------------------------------------- */

/* A guest pointer to a host one, or NULL. The bound is the same one the emitted code
 * checks before a memory access, so a shim cannot be handed an address the translator
 * would have trapped on: out of the image means out of the model, and dereferencing a
 * guest VA as if it were a host pointer would read whatever the host happens to have
 * at that number. */
static uint8_t *shim_guest_ptr(uint64_t va, uint64_t need)
{
    size_t i;

    if (need == 0) return NULL;
    for (i = 0; i < shim_nmaps; i++) {
        const shim_map *m = &shim_maps[i];
        if (m->image == NULL || va < m->base_va) continue;
        if (need > (uint64_t)m->len) continue;
        if (va - m->base_va > (uint64_t)m->len - need) continue;
        return m->image + (va - m->base_va);
    }
    return NULL;
}

/* HANDLE GetStdHandle(DWORD nStdHandle)
 *
 * The parameter is a DWORD, and x86-64 zero-extends a 32-bit write into the full
 * register, so STD_OUTPUT_HANDLE (-11) arrives as 0x00000000FFFFFFF5. Reading it as a
 * 64-bit signed value sees 4294967285 and refuses the request - every negative
 * constant in the Win32 API breaks the same way, which is most of them. */
static uint64_t shim_GetStdHandle(uint64_t nStdHandle, uint64_t b, uint64_t c,
                                  uint64_t d)
{
    int32_t which = (int32_t)(uint32_t)nStdHandle;

    (void)b; (void)c; (void)d;
    if (which == -11) return 1u;           /* STD_OUTPUT_HANDLE */
    if (which == -12) return 2u;           /* STD_ERROR_HANDLE  */
    if (which == -10) return 3u;           /* STD_INPUT_HANDLE  */
    return 0u;                             /* anything else: an invalid handle */
}

/* BOOL WriteFile(HANDLE, LPCVOID, DWORD, LPDWORD) - lpOverlapped is the fifth
 * parameter and does not arrive, so it is taken to be NULL. That is correct for
 * synchronous console output and wrong for overlapped I/O, which is a limitation of
 * the bridge and not of this shim. */
static uint64_t shim_WriteFile(uint64_t hFile, uint64_t lpBuffer,
                               uint64_t nBytes, uint64_t lpWritten)
{
    const uint8_t *buf;
    size_t         want;

    if (hFile == 0u || nBytes == 0u) return 0u;
    buf = shim_guest_ptr(lpBuffer, nBytes);
    if (buf == NULL) return 0u;

    want = (size_t)nBytes;
    /* stdout, not the handle: there is no Windows console here, and the point is that
     * the guest's own bytes reach somewhere the CI log can see. Flushed before
     * returning because the child may exit without another write. */
    if (fwrite(buf, 1u, want, stdout) != want) return 0u;
    fflush(stdout);

    if (lpWritten != 0u) {
        uint8_t *w = shim_guest_ptr(lpWritten, 4u);
        if (w != NULL) {
            uint32_t n = (uint32_t)want;
            memcpy(w, &n, sizeof n);
        }
    }
    return 1u;
}

/* void ExitProcess(UINT uExitCode) */
static uint64_t shim_ExitProcess(uint64_t uExitCode, uint64_t b, uint64_t c,
                                 uint64_t d)
{
    (void)b; (void)c; (void)d;
    shim_exit_code   = uExitCode;
    shim_exit_called = 1;
    return uExitCode;
}

/* --------------------------------------------------------------------------- */

typedef struct {
    const char *name;
    uint64_t  (*fn)(uint64_t, uint64_t, uint64_t, uint64_t);
} shim_entry;

/* Every shim is declared with the same four-word signature even where the Win32
 * function takes fewer, because the bridge always fills X0..X3 and the extra
 * parameters are simply ignored. One shape keeps the table below from needing casts,
 * and a cast here would hide exactly the mismatch the compiler just caught. */
static const shim_entry shims[] = {
    { "GetStdHandle", shim_GetStdHandle },
    { "WriteFile",    shim_WriteFile    },
    { "ExitProcess",  shim_ExitProcess  },
};

size_t shim_count(void) { return sizeof shims / sizeof shims[0]; }

static const shim_entry *shim_find(const char *name)
{
    size_t i;

    if (name == NULL) return NULL;
    for (i = 0; i < sizeof shims / sizeof shims[0]; i++)
        if (strcmp(shims[i].name, name) == 0) return &shims[i];
    return NULL;
}

size_t shim_fill_iat(const pe_image *im, uint8_t *image, size_t image_len,
                     uint64_t base_va, size_t *out_known, size_t *out_unknown)
{
    size_t filled = 0, known = 0, unknown = 0;
    uint32_t d, k;

    if (out_known)    *out_known = 0;
    if (out_unknown)  *out_unknown = 0;
    if (im == NULL || base_va == 0) return 0;

    /* image may be NULL, and that is not an error. An RVA is an offset from the base
     * only in a MAPPED image, where the loader has laid the sections out at their
     * virtual addresses. In the raw file buffer the same RVA sits at
     * PointerToRawData, which is file-aligned rather than 0x1000-aligned, so indexing
     * a file buffer by RVA reads the wrong bytes and bounding an RVA by the file's
     * length rejects slots that are perfectly reachable once mapped.
     *
     * The first run of this validated iat_rva 0x3040 against the length of hello.exe
     * and filled nothing, while every input it needed was correct - pe_load had
     * parsed one DLL with two functions named GetStdHandle and WriteFile. With a NULL
     * image this records which slots a resolver may answer for and writes nowhere,
     * which is all a sweep needs: only the RVA goes into the emitted code. The write
     * happens later, against the mapping, where RVA and offset agree. */
    if (image != NULL) {
        shim_map *m = shim_map_for(base_va);
        if (m == NULL) return 0;
        m->image = image;
        m->len   = image_len;
    }
    shim_exit_code   = 0;
    shim_exit_called = 0;
    /* Slots accumulate across modules: a bundle has one import table per DLL and a
     * resolver that forgot the previous module's slots would silently stop answering
     * for them. */

    for (d = 0; d < (size_t)im->num_dlls; d++) {
        const pe_import_dll *dll = &im->dlls[d];

        for (k = 0; k < (size_t)dll->func_count; k++) {
            const pe_import_func *f = &im->funcs[dll->first_func + k];
            const shim_entry     *e = shim_find(f->name);
            uint64_t              slot_rva;
            uint64_t              addr;
            uint8_t              *slot;

            if (e == NULL) { unknown++; continue; }
            known++;

            /* PE32+ thunks are 8 bytes. */
            slot_rva = (uint64_t)dll->iat_rva + 8u * (uint64_t)k;

            if (image != NULL) {
                /* Bound the write against the mapping, which is the only thing whose
                 * length an RVA can be compared to. */
                if (slot_rva + 8u > (uint64_t)image_len) { unknown++; known--; continue; }
                slot = image + slot_rva;
                addr = (uint64_t)(uintptr_t)e->fn;
                memcpy(slot, &addr, sizeof addr);
            }

            if (shim_slot_n < SHIM_MAX_SLOTS) {
                shim_slot_va[shim_slot_n]   = base_va + slot_rva;
                shim_slot_base[shim_slot_n] = base_va;
                shim_slot_n++;
                filled++;
            }
        }
    }

    if (out_known)   *out_known = known;
    if (out_unknown) *out_unknown = unknown;
    return filled;
}

uint64_t shim_resolve(uint64_t guest_iat_va, void *user)
{
    size_t k;

    (void)user;
    for (k = 0; k < shim_slot_n; k++)
        if (shim_slot_va[k] == guest_iat_va)
            return (guest_iat_va - shim_slot_base[k]) | TR_ABI_HOST | TR_ABI_INDIRECT;
    return 0;
}
