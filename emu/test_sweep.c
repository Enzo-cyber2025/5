/* Tests for the pre-translation sweep.
 *
 * The guest here is a hand-written PE image whose control-flow graph is known
 * exactly, so every assertion below is about a specific expected block rather
 * than about "some blocks were found". That matters because the two properties
 * worth proving are negative ones:
 *
 *   - padding between functions must NOT be decoded. A linear sweep would decode
 *     it and warm the cache with instructions no control flow reaches. Three
 *     unreachable addresses are asserted to have no block.
 *   - a block with no correct translation must NOT be cached. A placeholder
 *     would be served later as a cache hit and executed, and nothing downstream
 *     could tell. Four untranslatable blocks are asserted to miss.
 *
 * Interrupt and resume is tested by comparing a chunked run against a single
 * uninterrupted one and requiring identical counters, which is the only way to
 * show that stopping costs nothing but time.
 */
#define _POSIX_C_SOURCE 199309L

#include "sweep.h"

#include "a64_emit.h"
#include "pe_load.h"
#include "ptc.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static int checks, failures;

#define CHECK(cond, ...) do { \
    checks++; \
    if (!(cond)) { failures++; printf("  FAIL %s:%d: ", __FILE__, __LINE__); \
                   printf(__VA_ARGS__); printf("\n"); } \
} while (0)

#define IMAGE_BASE 0x140000000ULL
#define TEXT_VA    0x1000u
#define RDATA_VA   0x2000u
#define DATA_VA    0x3000u
#define IDATA_VA   0x4000u   /* only present when g_with_imports is set */

/* The guest code, laid out so that the reachable graph is exactly five blocks
 * and the gaps between them are padding that nothing jumps to:
 *
 *   1000  48 89 5C 24 08   mov [rsp+8], rbx     \
 *   1005  E8 06 00 00 00   call 1010             | block 1, 12 bytes,
 *   100A  EB 0A            jmp  1016            /   ends in a direct jump
 *   100C  90 90 90 90      <- unreachable padding
 *   1010  33 C0            xor eax, eax         \  block 2, 3 bytes, ret
 *   1012  C3               ret                  /
 *   1013  90 90 90         <- unreachable padding
 *   1016  74 04            jz   101C               block 3, 2 bytes, conditional
 *   1018  C3               ret                     block 4, 1 byte  <- the only
 *   1019  90 90 90         <- unreachable padding     provably translatable one
 *   101C  FF 25 00000000   jmp  [rip+0]            block 5, 6 bytes, indirect
 *   1022  C3               ret                     an export target, not
 *                                                   reachable from the entry
 */
static const uint8_t CODE[] = {
    /* 1000 */ 0x48, 0xC7, 0xC1, 0x05, 0x00, 0x00, 0x00,  /* mov rcx, 5      */
    /* 1007 */ 0x48, 0x31, 0xC0,                          /* xor rax, rax    */
    /* 100A */ 0x48, 0x01, 0xC8,                          /* add rax, rcx  <-loop */
    /* 100D */ 0x48, 0x83, 0xE9, 0x01,                    /* sub rcx, 1      */
    /* 1011 */ 0x48, 0x83, 0xF9, 0x00,                    /* cmp rcx, 0      */
    /* 1015 */ 0x75, 0xF3,                                /* jnz 100A        */
    /* 1017 */ 0xC3,                                      /* ret             */
    /* 1018 */ 0xC3,                                      /* ret  <- export B */
    /* 1019 */ 0x90, 0x90, 0x90,                          /* unreachable pad */
    /* 101C */ 0xFF, 0x25, 0x00, 0x00, 0x00, 0x00,        /* jmp [rip+0] <- C */
    /* 1022 */ 0xC3,                                      /* unreachable ret */
    /* Appended for g_call_entry. Nothing above jumps here, so with the knob off
     * these bytes are unreachable and every existing expectation still holds. The
     * section's virtual_size is 0x30, and this ends at 0x102A. */
    /* 1023 */ 0xE8, 0x01, 0x00, 0x00, 0x00,              /* call 1029       */
    /* 1028 */ 0xC3,                                      /* ret             */
    /* 1029 */ 0xC3                                       /* ret <- callee   */
};

/* Test-only knob: make the export directory claim far more entries than its
 * section can hold. That is how a parser bounding its reads against the file
 * instead of the section fabricates exports out of whatever data follows, and how
 * a sweep then queues entry points that are not code. */
static int g_big_exports;

/* Test-only knob: move the entry point to the caller/callee pair appended at the end
 * of CODE, so a sweep reaches a `call rel32` without any export machinery. The
 * callee is deliberately NOT an entry point - being found by the call is the thing
 * under test. */
static int g_call_entry;

/* Test-only knob: add a fourth section holding one function that makes a single
 * import call, plus the import descriptor and IAT that call goes through. The
 * section is marked CODE|EXECUTE|READ - deliberately, because that is what real
 * linkers do and it is the shape that made an IAT slot look like a function. */
static int g_with_imports;

/* Test-only knob, used with g_with_imports: make the section's function do
 * `call rel32` at the IAT slot instead of `call [rip+disp32]` through it. Same
 * address, different question - which is the whole point of asking. */
static int g_call_the_slot;

#define VA_CALLER  (IMAGE_BASE + 0x1023u)   /* call VA_CALLEE; ret */
#define VA_CALLEE  (IMAGE_BASE + 0x1029u)   /* ret - reached only by that call */

#define VA_ENTRY   (IMAGE_BASE + 0x1000u)   /* a whole function, with a loop */
#define VA_LOOP    (IMAGE_BASE + 0x100Au)   /* its backward branch target */
#define VA_RET1    (IMAGE_BASE + 0x1017u)   /* the fall-through ret */
#define VA_RET2    (IMAGE_BASE + 0x1018u)   /* export B: a bare ret */
#define VA_IND     (IMAGE_BASE + 0x101Cu)   /* export C: indirect, refused */
#define VA_PAD     (IMAGE_BASE + 0x1019u)   /* unreachable padding */
#define VA_TAIL    (IMAGE_BASE + 0x1022u)   /* unreachable ret after the jmp */

/* ------------------------------------------------------------ image writer */

typedef struct { uint8_t *b; size_t len, cap; } buf;

static void bgrow(buf *f, size_t need)
{
    if (f->len + need <= f->cap) return;
    while (f->len + need > f->cap) f->cap = f->cap ? f->cap * 2 : 4096;
    f->b = realloc(f->b, f->cap);
    if (!f->b) { fprintf(stderr, "out of memory\n"); exit(1); }
}
static void bput(buf *f, const void *p, size_t n)
{ bgrow(f, n); memcpy(f->b + f->len, p, n); f->len += n; }
static void bzero(buf *f, size_t n)
{ bgrow(f, n); memset(f->b + f->len, 0, n); f->len += n; }
static void bu16(buf *f, uint16_t v)
{ uint8_t t[2] = { (uint8_t)v, (uint8_t)(v >> 8) }; bput(f, t, 2); }
static void bu32(buf *f, uint32_t v)
{ uint8_t t[4] = { (uint8_t)v, (uint8_t)(v >> 8), (uint8_t)(v >> 16),
                   (uint8_t)(v >> 24) }; bput(f, t, 4); }
static void bu64(buf *f, uint64_t v)
{ bu32(f, (uint32_t)v); bu32(f, (uint32_t)(v >> 32)); }
static void bu8(buf *f, uint8_t v) { bput(f, &v, 1); }
static void bstr(buf *f, const char *s) { bput(f, s, strlen(s) + 1); }
static size_t btell(const buf *f) { return f->len; }

/* Builds the guest image. With exports it also carries two entry points that
 * are not reachable from the entry point, which is the whole reason a DLL has
 * to be swept from its export table. */
static buf build_guest(int with_exports)
{
    buf  out, rd;
    /* With three sections the header area is exactly 0x200 bytes - DOS stub 0x80,
     * PE signature 4, COFF 20, optional header 240, three section headers 120 - so
     * there is no room for a fourth. SizeOfHeaders has to be a multiple of
     * FileAlignment, which is 0x200, so a fourth section moves every raw pointer
     * down by a whole 0x200 rather than by 40 bytes. */
    size_t e_lfanew = 0x80, hdr = g_with_imports ? 0x400u : 0x200u;
    size_t exp_dir = 0, aof = 0, aon = 0, aoo = 0, nmA = 0, nmB = 0, nmDll = 0;
    int  i;

    memset(&out, 0, sizeof(out));
    memset(&rd, 0, sizeof(rd));

    if (with_exports) {
        exp_dir = btell(&rd); bzero(&rd, 40);
        aof = btell(&rd); bu32(&rd, 0x1018u); bu32(&rd, 0x101Cu);
        aon = btell(&rd); bzero(&rd, 8);            /* patched once names exist */
        aoo = btell(&rd); bu16(&rd, 0); bu16(&rd, 1);
        nmA = btell(&rd); bstr(&rd, "FuncA");
        nmB = btell(&rd); bstr(&rd, "FuncB");
        nmDll = btell(&rd); bstr(&rd, "testmod.dll");
        /* The name array holds RVAs, and hardcoding them here would silently
         * drift the moment anything above changes size. */
        {
            /* The fixture is little-endian throughout, like every PE. */
            uint32_t na = (uint32_t)(RDATA_VA + nmA), nb = (uint32_t)(RDATA_VA + nmB);
            memcpy(rd.b + aon + 0u, &na, 4);
            memcpy(rd.b + aon + 4u, &nb, 4);
        }
        /* Patch the directory now that every RVA is known. */
        {
            uint8_t d[40];
            size_t  k;
            memset(d, 0, sizeof(d));
            d[0] = 0;                              /* Characteristics */
            for (k = 0; k < 4; k++) d[12 + k] = (uint8_t)((RDATA_VA + nmDll) >> (8 * k));
            for (k = 0; k < 4; k++) d[16 + k] = (uint8_t)(1u >> (8 * k));   /* Base */
            for (k = 0; k < 4; k++) d[20 + k] = (uint8_t)((g_big_exports ? 200u : 2u) >> (8 * k));
            for (k = 0; k < 4; k++) d[24 + k] = (uint8_t)((g_big_exports ? 200u : 2u) >> (8 * k));
            for (k = 0; k < 4; k++) d[28 + k] = (uint8_t)((RDATA_VA + aof) >> (8 * k));
            for (k = 0; k < 4; k++) d[32 + k] = (uint8_t)((RDATA_VA + aon) >> (8 * k));
            for (k = 0; k < 4; k++) d[36 + k] = (uint8_t)((RDATA_VA + aoo) >> (8 * k));
            memcpy(rd.b + exp_dir, d, sizeof(d));
        }
    }

    /* DOS header, with e_lfanew at 0x3C where every reader looks for it. */
    bu16(&out, 0x5A4Du);
    bzero(&out, 0x3Cu - 2u);
    bu32(&out, (uint32_t)e_lfanew);
    bzero(&out, e_lfanew - btell(&out));

    bu32(&out, 0x00004550u);                       /* "PE\0\0" */
    bu16(&out, PE_MACHINE_AMD64);
    bu16(&out, g_with_imports ? 4 : 3);            /* sections */
    bu32(&out, 0x60000000u); bu32(&out, 0); bu32(&out, 0);
    bu16(&out, 240);                               /* SizeOfOptionalHeader */
    bu16(&out, with_exports ? 0x2022u : 0x0022u);  /* DLL | EXECUTABLE | LARGE */

    bu16(&out, PE_MAGIC_PE32PLUS);
    bu8(&out, 14); bu8(&out, 0);
    bu32(&out, 0x200); bu32(&out, (uint32_t)rd.len); bu32(&out, 0);
    bu32(&out, g_with_imports ? IDATA_VA :
               (g_call_entry ? 0x1023u : TEXT_VA));  /* AddressOfEntryPoint */
    bu32(&out, TEXT_VA);                           /* BaseOfCode */
    bu64(&out, IMAGE_BASE);
    bu32(&out, 0x1000u); bu32(&out, 0x200u);       /* section / file alignment */
    bu16(&out, 6); bu16(&out, 0); bu16(&out, 0); bu16(&out, 0);
    bu16(&out, 6); bu16(&out, 0);
    bu32(&out, 0);
    bu32(&out, g_with_imports ? 0x5000u : 0x4000u); /* SizeOfImage */
    bu32(&out, (uint32_t)hdr);                     /* SizeOfHeaders */
    bu32(&out, 0);                                 /* CheckSum */
    bu16(&out, PE_SUBSYS_GUI); bu16(&out, 0x0160u);
    bu64(&out, 0x100000); bu64(&out, 0x1000);
    bu64(&out, 0x100000); bu64(&out, 0x1000);
    bu32(&out, 0);
    bu32(&out, PE_DIR_COUNT);
    for (i = 0; i < PE_DIR_COUNT; i++) {
        if (i == PE_DIR_EXPORT && with_exports) { bu32(&out, RDATA_VA); bu32(&out, 40); }
        else if (i == PE_DIR_IMPORT && g_with_imports) {
            bu32(&out, IDATA_VA + 0x40u); bu32(&out, 40);
        }
        else { bu32(&out, 0); bu32(&out, 0); }
    }

    /* .text */
    bput(&out, ".text\0\0\0", 8);
    bu32(&out, 0x30u); bu32(&out, TEXT_VA);
    bu32(&out, 0x200u); bu32(&out, (uint32_t)hdr);
    bu32(&out, 0); bu32(&out, 0); bu16(&out, 0); bu16(&out, 0);
    bu32(&out, PE_SCN_CNT_CODE | PE_SCN_MEM_EXECUTE | PE_SCN_MEM_READ);
    /* .rdata */
    bput(&out, ".rdata\0\0", 8);
    bu32(&out, (uint32_t)rd.len); bu32(&out, RDATA_VA);
    bu32(&out, 0x200u); bu32(&out, (uint32_t)(hdr + 0x200u));
    bu32(&out, 0); bu32(&out, 0); bu16(&out, 0); bu16(&out, 0);
    bu32(&out, PE_SCN_CNT_INITIALIZED_DATA | PE_SCN_MEM_READ);
    /* .data - executable-looking bytes placed where they must NOT be decoded */
    bput(&out, ".data\0\0\0", 8);
    bu32(&out, 0x10u); bu32(&out, DATA_VA);
    bu32(&out, 0x200u); bu32(&out, (uint32_t)(hdr + 0x400u));
    bu32(&out, 0); bu32(&out, 0); bu16(&out, 0); bu16(&out, 0);
    bu32(&out, PE_SCN_CNT_INITIALIZED_DATA | PE_SCN_MEM_READ | PE_SCN_MEM_WRITE);
    if (g_with_imports) {
        /* .idata */
        bput(&out, ".idata\0\0", 8);
        bu32(&out, 0x200u); bu32(&out, IDATA_VA);
        bu32(&out, 0x200u); bu32(&out, (uint32_t)(hdr + 0x600u));
        bu32(&out, 0); bu32(&out, 0); bu16(&out, 0); bu16(&out, 0);
        bu32(&out, PE_SCN_CNT_CODE | PE_SCN_MEM_EXECUTE | PE_SCN_MEM_READ);
    }

    bzero(&out, hdr - btell(&out));
    bput(&out, CODE, sizeof(CODE));
    bzero(&out, 0x200u - sizeof(CODE));
    if (rd.len) bput(&out, rd.b, rd.len);
    bzero(&out, 0x200u - rd.len);
    /* Decoy: a valid RET in a non-executable section. Decoding it would mean the
     * sweep is scanning data, which is exactly what it must not do. */
    bu8(&out, 0xC3);
    bzero(&out, 0x200u - 1u);

    if (g_with_imports) {
        /* Raw .idata, at file offset hdr + 0x600. The IAT sits in section offset
         * 0x100, so from the byte after the six-byte call at offset 0 the
         * displacement is 0x100 - 0x06. The thunk is an ordinal (top bit set) so
         * the loader does not chase a name RVA through a section that has none. */
        /* btell is already hdr + 0x600 here: .text, .rdata and .data each pad
         * themselves out to a full 0x200, so .idata's raw starts exactly here. Every
         * pad below is measured from sec_at rather than written as a fixed delta,
         * because the two forms of the function are different lengths and a fixed
         * delta makes the section's raw data end one byte short of the file - which
         * the loader reports as raw data running past the end of the image. */
        size_t sec_at = btell(&out);
        if (g_call_the_slot) {
            bu8(&out, 0xE8);
            bu32(&out, 0x100u - 0x05u);               /* call rel32 at the IAT slot */
        } else {
            bu8(&out, 0xFF); bu8(&out, 0x15);
            bu32(&out, 0x100u - 0x06u);               /* call [rip+0xFA] */
        }
        bu8(&out, 0xC3);
        bzero(&out, 0x40u - (btell(&out) - sec_at));
        bu32(&out, 0);                                /* OriginalFirstThunk */
        bu32(&out, 0);                                /* TimeDateStamp    */
        bu32(&out, 0);                                /* ForwarderChain   */
        bu32(&out, IDATA_VA + 0x80u);                 /* Name             */
        bu32(&out, IDATA_VA + 0x100u);                /* FirstThunk (IAT) */
        bzero(&out, 20);                              /* null descriptor  */
        bzero(&out, 0x80u - (btell(&out) - sec_at));
        bstr(&out, "test.dll");
        bzero(&out, 0x100u - (btell(&out) - sec_at));
        bu64(&out, 0x8000000000000001ULL);            /* one ordinal thunk */
        bu64(&out, 0);                                /* terminator        */
        bzero(&out, 0x200u - (btell(&out) - sec_at));
    }

    free(rd.b);
    return out;
}

/* ------------------------------------------------------------- test rig */

typedef struct {
    buf        img;
    pe_image   pe;
    ptc_cache *cache;
    uint64_t   module_id;
    sweep_job *job;
} rig;

static void rig_setup(rig *r, int with_exports, const char *what)
{
    memset(r, 0, sizeof(*r));
    r->img = build_guest(with_exports);
    if (pe_load(r->img.b, r->img.len, &r->pe) != PE_OK) {
        printf("  FAIL fixture %s did not parse: %s\n", what,
               r->pe.detail ? r->pe.detail : "(null)");
        failures++; checks++;
        exit(1);
    }
    r->cache = ptc_create(PTC_ISA_AARCH64, PTC_ISA_X86_64, 4096u);
    if (!r->cache) { printf("  FAIL ptc_create\n"); exit(1); }
    if (ptc_add_module(r->cache, what, r->img.len, 1u,
                       ptc_hash_bytes(r->img.b, r->img.len),
                       &r->module_id) != 0) {
        printf("  FAIL ptc_add_module\n"); exit(1);
    }
    r->job = sweep_begin(r->cache);
    if (!r->job) { printf("  FAIL sweep_begin\n"); exit(1); }
}

static void rig_teardown(rig *r)
{
    sweep_free(r->job);
    ptc_free(r->cache);
    free(r->img.b);
}

static const sweep_block *find_block(const sweep_job *j, uint64_t va)
{
    uint32_t i, n = sweep_block_count(j);
    for (i = 0; i < n; i++) {
        const sweep_block *b = sweep_block_at(j, i);
        if (b && b->guest_va == va) return b;
    }
    return NULL;
}

/* --------------------------------------------------------------- tests */

static void test_discovery(void)
{
    rig r; sweep_progress p;
    const sweep_block *b;
    rig_setup(&r, 0, "test.exe");

    printf("recursive discovery from the entry point\n");
    CHECK(sweep_add_module(r.job, "test.exe", r.module_id, r.img.b, r.img.len,
                           &r.pe) == 1, "queued entry points != 1");
    CHECK(sweep_run(r.job, NULL, NULL) == 1, "run did not report completion");
    sweep_get_progress(r.job, &p);

    CHECK(p.phase == SWEEP_DONE, "phase %s", sweep_phase_name(p.phase));
    /* The entry block runs to its conditional branch, then the fall-through ret.
     * The loop body is inside the first block, so it is not a block of its own. */
    CHECK(p.blocks == 2, "blocks %u, expected 2", p.blocks);
    CHECK(p.entry_points == 1, "entry_points %u", p.entry_points);
    CHECK(p.decode_calls == 7, "decode_calls %llu, expected 7",
          (unsigned long long)p.decode_calls);
    /* 23 bytes to the jnz, plus the 1-byte ret. The three padding bytes and the
     * ret after the indirect jump are never reached. */
    CHECK(p.guest_bytes == 24, "guest_bytes %llu, expected 24",
          (unsigned long long)p.guest_bytes);
    CHECK(p.decode_refusals == 0, "decode_refusals %u", p.decode_refusals);

    b = find_block(r.job, VA_ENTRY);
    CHECK(b && b->len == 23 && b->kind == BLK_COND,
          "entry block: len=%u kind=%s", b ? b->len : 0,
          b ? sweep_block_kind_name(b->kind) : "(absent)");
    b = find_block(r.job, VA_RET1);
    CHECK(b && b->len == 1 && b->kind == BLK_RET, "fall-through ret missing");

    /* Unreachable bytes must have no block: this is recursive traversal, not a
     * linear scan, and the difference is exactly these addresses. */
    CHECK(find_block(r.job, VA_LOOP) == NULL,
          "the loop body was reported as a separate block");
    CHECK(find_block(r.job, VA_PAD) == NULL, "padding was decoded");
    CHECK(find_block(r.job, VA_TAIL) == NULL, "a ret after an indirect jmp was decoded");
    CHECK(find_block(r.job, VA_IND) == NULL,
          "an export-only address was reached without exports");
    CHECK(find_block(r.job, VA_RET2) == NULL, "an export-only ret was reached");

    rig_teardown(&r);
}

static void test_translation_and_cache(void)
{
    rig r; sweep_progress p;
    uint32_t code_len = 0;
    const void *host;
    rig_setup(&r, 0, "test.exe");
    sweep_add_module(r.job, "test.exe", r.module_id, r.img.b, r.img.len, &r.pe);
    sweep_run(r.job, NULL, NULL);
    sweep_get_progress(r.job, &p);

    printf("a whole function is pre-translated and cached, not one block\n");
    CHECK(p.functions_attempted == 1, "attempted %u functions, expected 1",
          p.functions_attempted);
    CHECK(p.functions_translated == 1, "translated %u, expected 1",
          p.functions_translated);
    CHECK(p.functions_refused == 0, "refused %u, expected 0", p.functions_refused);
    CHECK(ptc_record_count(r.cache) == 1, "cache holds %zu records, expected 1",
          ptc_record_count(r.cache));
    /* 7 words: mov rcx,5 / xor rax,rax / add / sub / cmp / b.ne / ret */
    CHECK(p.host_code_bytes == 28, "host code %llu bytes, expected 28",
          (unsigned long long)p.host_code_bytes);

    host = ptc_lookup(r.cache, r.module_id, VA_ENTRY, r.img.b + 0x200, 24u,
                      &code_len);
    CHECK(host != NULL, "the pre-translated function missed the cache");
    CHECK(code_len == 28u, "host code length %u, expected 28", code_len);
    if (host && code_len == 28u) {
        const uint32_t *w = host;
        CHECK(w[0] == 0xD28000A1u, "mov rcx,5 -> 0x%08X", w[0]);
        CHECK(w[1] == 0xD2800000u, "xor rax,rax -> 0x%08X", w[1]);
        CHECK(w[2] == 0x8B010000u, "add rax,rcx -> 0x%08X", w[2]);
        CHECK(w[3] == 0xD1000421u, "sub rcx,1 -> 0x%08X", w[3]);
        CHECK(w[4] == 0xF100003Fu, "cmp rcx,0 -> 0x%08X", w[4]);
        /* jnz sits at word 5, the loop top at word 2: offset -3 */
        CHECK(w[5] == 0x54FFFFA1u, "jnz loop -> 0x%08X, expected B.NE -3", w[5]);
        CHECK(w[6] == 0xD65F03C0u, "ret -> 0x%08X", w[6]);
    }

    /* An address that is not a function entry must miss: the cache is keyed per
     * entry point, and a hit in the middle of a function would be a lie. */
    code_len = 0;
    host = ptc_lookup(r.cache, r.module_id, VA_LOOP, r.img.b + 0x20A, 14u,
                      &code_len);
    CHECK(host == NULL, "a mid-function address was served from the cache");

    rig_teardown(&r);
}

static void test_exports_are_entry_points(void)
{
    rig r; sweep_progress p;
    uint8_t top_map = 0xFF, top_op = 0;
    rig_setup(&r, 1, "testmod.dll");

    printf("a DLL is swept from its exports, and refusals are accounted for\n");
    CHECK(r.pe.num_exports == 2, "fixture exports %u, expected 2", r.pe.num_exports);
    CHECK(sweep_add_module(r.job, "testmod.dll", r.module_id, r.img.b, r.img.len,
                           &r.pe) == 3, "queued entry points != 3");
    sweep_run(r.job, NULL, NULL);
    sweep_get_progress(r.job, &p);

    CHECK(p.entry_points == 3, "entry_points %u, expected 3", p.entry_points);
    CHECK(p.blocks == 4, "blocks %u, expected 4", p.blocks);
    CHECK(p.indirect_unresolved == 1, "indirect_unresolved %u, expected 1",
          p.indirect_unresolved);
    CHECK(p.functions_attempted == 3, "attempted %u, expected 3",
          p.functions_attempted);
    /* The loop, and the bare ret. The indirect jump is refused. */
    CHECK(p.functions_translated == 2, "translated %u, expected 2",
          p.functions_translated);
    CHECK(p.functions_refused == 1, "refused %u, expected 1", p.functions_refused);
    CHECK(ptc_record_count(r.cache) == 2, "cache holds %zu records, expected 2",
          ptc_record_count(r.cache));
    CHECK(p.host_code_bytes == 32, "host code %llu bytes, expected 32 (28 + 4)",
          (unsigned long long)p.host_code_bytes);

    /* The refusal has to say what blocked it, or the coverage number is a dead
     * end instead of a work queue. */
    CHECK(sweep_reason_count(r.job, TRR_UNSUPPORTED_OP) == 1,
          "unsupported-opcode refusals %u, expected 1",
          sweep_reason_count(r.job, TRR_UNSUPPORTED_OP));
    CHECK(sweep_reason_count(r.job, TRR_FLAGS) == 0, "a flags refusal was reported");
    CHECK(sweep_top_opcode(r.job, 0, &top_map, &top_op) == 1,
          "the top blocking opcode was not reported");
    CHECK(top_map == 0 && top_op == 0xFFu,
          "top blocking opcode %02X in map %u, expected FF in map 0", top_op, top_map);
    CHECK(sweep_top_opcode(r.job, 1, &top_map, &top_op) == 0,
          "a second blocking opcode was invented");
    /* The indirect jump is the entry point's first instruction, so the refusal is
     * at depth 0 and its opcode is real. If this ever reports a deeper refusal,
     * discovery has wandered past the entry point. */
    CHECK(p.refused_at_first_insn == 1, "refused at first instruction: %u, expected 1",
          p.refused_at_first_insn);
    CHECK(p.refused_deeper == 0, "refused deeper: %u, expected 0", p.refused_deeper);
    CHECK(p.deepest_refusal == 0, "deepest refusal %u, expected 0", p.deepest_refusal);

    rig_teardown(&r);
}

/* ------------------------------------------------------------ interruption */

/* The callback is consulted before each block, so "stop now" must be asked only
 * after some work has been allowed through - otherwise the sweep correctly does
 * nothing at all and a loop that ignores its own stop condition spins forever.
 * An idle window closing looks exactly like this: a few blocks get done, then the
 * caller asks to yield. */
typedef struct {
    int      work_per_resume;   /* blocks to allow before asking to stop */
    int      work_done;
    int      calls;
    int      stops;
    uint64_t burn_ns;           /* simulate the cost of being interrupted */
} stopper;

static int stop_cb(void *user)
{
    stopper *s = user;
    if (s->work_done < s->work_per_resume) { s->work_done++; return 0; }
    s->calls++;
    s->stops++;
    s->work_done = 0;
    if (s->burn_ns) {
        struct timespec ts;
        ts.tv_sec  = (time_t)(s->burn_ns / 1000000000ULL);
        ts.tv_nsec = (long)(s->burn_ns % 1000000000ULL);
        nanosleep(&ts, NULL);
    }
    return 1;
}

/* Detects a resume that accomplished nothing, so a regression in the stop
 * protocol fails in milliseconds instead of after a hundred thousand retries. */
static int stalled(const sweep_progress *prev, const sweep_progress *now)
{
    return prev->blocks == now->blocks &&
           prev->percent_x10 == now->percent_x10 &&
           prev->functions_translated == now->functions_translated &&
           prev->phase == now->phase;
}

static void test_interrupt_resume(void)
{
    rig a, b;
    sweep_progress pa, pb;
    int resumes = 0, finished;

    printf("interrupting and resuming costs nothing but time\n");

    /* Reference: one uninterrupted run. */
    rig_setup(&a, 1, "testmod.dll");
    sweep_add_module(a.job, "testmod.dll", a.module_id, a.img.b, a.img.len, &a.pe);
    CHECK(sweep_run(a.job, NULL, NULL) == 1, "reference run did not finish");
    sweep_get_progress(a.job, &pa);

    /* Same work, stopped after every single block. */
    rig_setup(&b, 1, "testmod.dll");
    sweep_add_module(b.job, "testmod.dll", b.module_id, b.img.b, b.img.len, &b.pe);
    {
        stopper s; sweep_progress prev, cur;
        int stalls = 0;
        memset(&s, 0, sizeof(s));
        s.work_per_resume = 1;              /* exactly one block per resume */
        sweep_get_progress(b.job, &prev);
        do {
            finished = sweep_run(b.job, stop_cb, &s);
            if (!finished) resumes++;
            sweep_get_progress(b.job, &cur);
            if (!finished && stalled(&prev, &cur)) {
                if (++stalls > 20) {
                    CHECK(0, "resuming made no progress at all (phase %s)",
                          sweep_phase_name(cur.phase));
                    break;
                }
            } else {
                stalls = 0;
            }
            prev = cur;
        } while (!finished && resumes < 100000);
        CHECK(resumes > 0, "the stop callback never interrupted the sweep");
        CHECK(finished == 1, "resume did not converge");
        CHECK(s.stops > 0, "stop count not recorded");
        CHECK(s.calls == s.stops, "callback accounting inconsistent");
    }
    sweep_get_progress(b.job, &pb);

    CHECK(pb.phase == SWEEP_DONE, "resumed run ended in phase %s",
          sweep_phase_name(pb.phase));
    CHECK(pb.blocks == pa.blocks, "blocks differ: %u vs %u", pb.blocks, pa.blocks);
    CHECK(pb.decode_calls == pa.decode_calls,
          "decode_calls differ: %llu vs %llu - a resumed sweep re-decoded work",
          (unsigned long long)pb.decode_calls, (unsigned long long)pa.decode_calls);
    CHECK(pb.guest_bytes == pa.guest_bytes, "guest_bytes differ: %llu vs %llu",
          (unsigned long long)pb.guest_bytes, (unsigned long long)pa.guest_bytes);
    CHECK(pb.functions_translated == pa.functions_translated,
          "translated differ: %u vs %u", pb.functions_translated,
              pa.functions_translated);
    CHECK(pb.host_code_bytes == pa.host_code_bytes,
          "host code bytes differ: %llu vs %llu",
          (unsigned long long)pb.host_code_bytes,
          (unsigned long long)pa.host_code_bytes);
    CHECK(pb.indirect_unresolved == pa.indirect_unresolved,
          "unresolved differ");
    CHECK(pb.decode_refusals == pa.decode_refusals, "refusals differ");
    CHECK(ptc_record_count(b.cache) == ptc_record_count(a.cache),
          "cache contents differ: %zu vs %zu", ptc_record_count(b.cache),
          ptc_record_count(a.cache));

    /* Resuming after completion must be a no-op, not a second pass. */
    {
        uint64_t before = pb.decode_calls;
        CHECK(sweep_run(b.job, NULL, NULL) == 1, "run after done failed");
        sweep_get_progress(b.job, &pb);
        CHECK(pb.decode_calls == before,
              "running again after completion did more work");
        CHECK(ptc_record_count(b.cache) == ptc_record_count(a.cache),
              "running again after completion duplicated cache records");
    }

    rig_teardown(&a);
    rig_teardown(&b);
}

static void test_progress_and_eta(void)
{
    rig r;
    sweep_progress p;
    uint32_t last = 0;
    int monotonic = 1, saw_provisional = 0, saw_eta = 0;
    stopper s;

    printf("percentage and remaining time\n");
    rig_setup(&r, 1, "testmod.dll");
    sweep_add_module(r.job, "testmod.dll", r.module_id, r.img.b, r.img.len, &r.pe);

    memset(&s, 0, sizeof(s));
    s.work_per_resume = 1;
    s.burn_ns = 2000000ULL;      /* 2 ms per stop, so a rate can be measured */

    {
        int stalls = 0;
        sweep_progress prev;
        sweep_get_progress(r.job, &prev);
        last = prev.percent_x10;
        for (;;) {
        int done = sweep_run(r.job, stop_cb, &s);
        sweep_get_progress(r.job, &p);
        if (!done && stalled(&prev, &p)) {
            if (++stalls > 20) { CHECK(0, "progress loop stalled"); break; }
        } else {
            stalls = 0;
        }
        prev = p;
        if (p.phase == SWEEP_DISCOVER) {
            CHECK(p.provisional == 1, "discovery did not flag its percent provisional");
            saw_provisional = 1;
        } else if (p.phase == SWEEP_TRANSLATE) {
            if (p.provisional != 0) monotonic = 0;
            if (p.percent_x10 < last) monotonic = 0;
            last = p.percent_x10;
            if (p.blocks_per_sec > 0.0 && p.eta_ns > 0) saw_eta = 1;
        }
        if (done) break;
        if (s.stops > 100000) { CHECK(0, "did not converge"); break; }
        }
    }

    CHECK(saw_provisional == 1, "the discovery phase was never observed");
    CHECK(monotonic == 1, "percentage went backwards during the exact phase");
    CHECK(p.phase == SWEEP_DONE, "final phase %s", sweep_phase_name(p.phase));
    CHECK(p.percent_x10 == 1000u, "final percent %u, expected 1000",
          p.percent_x10);
    CHECK(p.provisional == 0, "still provisional at completion");
    CHECK(p.eta_ns == 0, "eta %llu ns at completion, expected 0",
          (unsigned long long)p.eta_ns);
    CHECK(p.elapsed_ns > 0, "elapsed time not measured");
    CHECK(saw_eta == 1,
          "no non-zero ETA was ever observed while work remained");
    CHECK(p.blocks_per_sec > 0.0, "final rate not computed");

    printf("  final: %.1f%%  blocks=%u functions=%u/%u translated  %.3fs\n",
           (double)p.percent_x10 / 10.0, p.blocks, p.functions_translated,
           p.functions_attempted, (double)p.elapsed_ns / 1e9);

    rig_teardown(&r);
}

static void test_exports_past_section(void)
{
    buf f; pe_image im; pe_status st;

    printf("an export array that does not fit its section is refused, not read on\n");
    g_big_exports = 0;
    f = build_guest(1);
    st = pe_load(f.b, f.len, &im);
    CHECK(st == PE_OK, "the baseline export fixture failed to parse: %s",
          im.detail ? im.detail : "?");
    CHECK(im.num_exports == 2, "baseline exports %u, expected 2", im.num_exports);
    free(f.b);

    /* Same image, but the directory claims 200 names while the array has room for
     * a handful. Every entry past that would be read out of whatever file data
     * follows. The reads stay inside the buffer, so nothing crashes - the parser
     * would simply report exports the file never had, and a sweep would queue
     * entry points that are not code. */
    g_big_exports = 1;
    f = build_guest(1);
    st = pe_load(f.b, f.len, &im);
    CHECK(st == PE_MALFORMED,
          "an over-claimed export array returned %d (%s), expected PE_MALFORMED",
          st, im.detail ? im.detail : "?");
    CHECK(im.detail && strstr(im.detail, "past the section") != NULL,
          "detail '%s' does not say the array left its section",
          im.detail ? im.detail : "?");
    CHECK(im.num_exports == 0,
          "fabricated %u exports out of unrelated file data", im.num_exports);
    free(f.b);
    g_big_exports = 0;
}

static void test_refusals(void)
{
    rig r;
    buf img;
    pe_image pe;
    rig_setup(&r, 0, "test.exe");

    printf("a module the sweep cannot use is refused, not half-swept\n");
    /* A NULL image and a NULL parse result must both be rejected. */
    CHECK(sweep_add_module(r.job, "x", 1, NULL, 0, &r.pe) == -1,
          "NULL image accepted");
    CHECK(sweep_add_module(r.job, "x", 1, r.img.b, r.img.len, NULL) == -1,
          "NULL pe accepted");
    CHECK(sweep_add_module(NULL, "x", 1, r.img.b, r.img.len, &r.pe) == -1,
          "NULL job accepted");

    /* An image with no executable section has nothing to sweep. */
    img = build_guest(0);
    memset(&pe, 0, sizeof(pe));
    if (pe_load(img.b, img.len, &pe) == PE_OK) {
        uint32_t i;
        for (i = 0; i < pe.num_sections; i++)
            pe.sections[i].characteristics &= ~PE_SCN_MEM_EXECUTE;
        CHECK(sweep_add_module(r.job, "noexec", 99, img.b, img.len, &pe) == -1,
              "an image with no executable section was accepted");
    }
    free(img.b);

    /* Running with no modules must terminate immediately and report done. */
    {
        sweep_job *empty = sweep_begin(NULL);
        sweep_progress p;
        CHECK(sweep_run(empty, NULL, NULL) == 1, "empty job did not finish");
        sweep_get_progress(empty, &p);
        CHECK(p.blocks == 0 && p.phase == SWEEP_DONE,
              "empty job reported %u blocks in phase %s", p.blocks,
              sweep_phase_name(p.phase));
        sweep_free(empty);
    }
    sweep_free(NULL);
    checks++;   /* reaching here at all is the assertion: NULL must be survived */

    rig_teardown(&r);
}

/* A `call rel32` is 46% of what a real binary refuses, and translating it is only
 * half of the work: the callee has to end up translated too, and the caller's code
 * has to reach it through a slot whose number survives being written to disk. */
static void test_guest_call_gets_a_slot(void)
{
    rig r;
    sweep_progress p;
    size_t slot, slots, found_caller = 0, found_callee = 0;
    int saw_table_call = 0;

    printf("a call rel32 gets a call-table slot and drags its callee along\n");
    g_call_entry = 1;
    rig_setup(&r, 0, "with a guest-to-guest call");
    CHECK(sweep_add_module(r.job, "test.exe", r.module_id, r.img.b, r.img.len,
                           &r.pe) == 1,
          "the module offers exactly one entry point, the caller");
    CHECK(sweep_run(r.job, NULL, NULL) == 1, "the sweep should finish uninterrupted");
    sweep_get_progress(r.job, &p);

    CHECK(p.entry_points == 1, "the callee is not an entry point: got %u", p.entry_points);
    CHECK(ptc_calltab_count(r.cache) == 1,
          "exactly one call target should have been given a slot, got %zu",
          ptc_calltab_count(r.cache));
    CHECK(ptc_calltab_find(r.cache, r.module_id, VA_CALLEE) == 0,
          "and that slot must be the callee's");
    CHECK(ptc_calltab_find(r.cache, r.module_id, VA_CALLER) == PTC_CALLTAB_NONE,
          "a caller is not a call target and must not consume a slot");
    CHECK(p.functions_attempted == 2,
          "the callee must be attempted in the same run, not left for a later one: "
          "attempted %u", p.functions_attempted);
    CHECK(p.functions_translated == 2,
          "caller and callee both translate, got %u translated of %u attempted",
          p.functions_translated, p.functions_attempted);

    /* Both functions must be in the cache, and the caller's words must consult the
     * table. The four-word sequence is what P_CALL_TABLE emits for slot 0:
     * MOVZ X17,#0; ADD X17,X21,X17; LDUR X16,[X17]; BLR X16. Asserting it is what
     * distinguishes "the call was resolved" from "the call was resolved to an address
     * baked into the code", which is the thing the whole call table exists to avoid. */
    slots = ptc_record_slots(r.cache);
    for (slot = 0; slot < slots; slot++) {
        uint64_t mid = 0, gpc = 0;
        const void *code = NULL;
        const uint32_t *ws;
        uint32_t clen = 0, nw, w;
        if (!ptc_record_at(r.cache, slot, &mid, &gpc, &code, &clen)) continue;
        if (mid != r.module_id) continue;
        if (gpc == VA_CALLEE) { found_callee = 1; continue; }
        if (gpc != VA_CALLER) continue;
        found_caller = 1;
        ws = (const uint32_t *)code;
        nw = clen / 4u;
        for (w = 0; w + 4u <= nw; w++) {
            if (ws[w] == 0xD2800011u && ws[w + 1u] == 0x8B1102B1u &&
                ws[w + 2u] == 0xF8400230u && ws[w + 3u] == 0xD63F0200u)
                saw_table_call = 1;
        }
    }
    CHECK(found_caller, "the caller is in the cache");
    CHECK(found_callee, "the callee is in the cache: a slot pointing at nothing would "
                        "make every call to it a trap");
    CHECK(saw_table_call,
          "the caller's words must load the target out of the call table "
          "(MOVZ X17,#0 / ADD X17,X21,X17 / LDUR X16,[X17] / BLR X16), not embed an "
          "address that will be wrong in the next process");

    rig_teardown(&r);
    g_call_entry = 0;
}

/* An FF /2 import call is the other question the resolver gets asked, and answering
 * it with the call-table shape is what put a tag into a branch target: the sweep
 * handed TR_GUEST_CALL to a site that strips only the host-ABI bits, so bit 61 was
 * materialised into X16 and BLR jumped to the slot offset alone. Sixteen records on
 * a real 19-module bundle died exactly that way. The fixture here is built the way
 * real linkers build it - the IAT inside a section marked executable - because
 * "in an executable section" is what made an import slot look like a function. */
static void test_import_slot_is_data_not_a_callee(void)
{
    rig r;
    sweep_progress p;
    size_t slot, slots, found = 0;
    int saw_host_indirect = 0, saw_table_form = 0, imm_ok = 0;
    uint32_t iat_rva = IDATA_VA + 0x100u;
    int iat_in_exec_section = 0;
    unsigned i;

    printf("an import slot resolves as a host-ABI cell and consumes no call-table slot\n");
    g_with_imports = 1;
    rig_setup(&r, 0, "with an import table");

    /* The precondition first. If the fixture did not actually parse an import
     * directory, every assertion below would pass for the wrong reason - the
     * resolver would simply never be asked about a slot. */
    CHECK(r.pe.num_dlls == 1,
          "the fixture must carry exactly one imported DLL, got %u (%s)",
          r.pe.num_dlls, r.pe.detail ? r.pe.detail : "no detail");
    if (r.pe.num_dlls != 1) { rig_teardown(&r); g_with_imports = 0; return; }
    CHECK(r.pe.dlls[0].iat_rva == iat_rva,
          "and its IAT must be at RVA 0x%X, got 0x%X", iat_rva, r.pe.dlls[0].iat_rva);
    CHECK(r.pe.dlls[0].func_count == 1,
          "with one imported function, got %u", r.pe.dlls[0].func_count);

    /* And the shape that made this a bug at all: the IAT lives in a section the
     * linker marked executable, so an address test alone cannot tell a thunk from
     * a function. Stating it is what makes the test about classification rather
     * than about this fixture happening to put data somewhere non-executable. */
    for (i = 0; i < r.pe.num_sections; i++) {
        const pe_section *sc = &r.pe.sections[i];
        if (iat_rva >= sc->virtual_addr &&
            iat_rva < sc->virtual_addr + sc->virtual_size &&
            (sc->characteristics & PE_SCN_MEM_EXECUTE))
            iat_in_exec_section = 1;
    }
    CHECK(iat_in_exec_section,
          "the IAT must sit in a section marked executable, which is the case that "
          "made find_exec alone answer 'function' for an import slot");

    CHECK(sweep_add_module(r.job, "test.exe", r.module_id, r.img.b, r.img.len,
                           &r.pe) == 1,
          "the module offers exactly one entry point, the import caller");
    CHECK(sweep_run(r.job, NULL, NULL) == 1, "the sweep should finish uninterrupted");
    sweep_get_progress(r.job, &p);

    CHECK(p.functions_attempted == 1, "one function, got %u", p.functions_attempted);
    CHECK(p.functions_translated == 1,
          "an import call through a known IAT slot is translatable, not a refusal: "
          "translated %u of %u attempted", p.functions_translated, p.functions_attempted);

    /* The core of it: the slot consumed nothing. A slot here is a promise that
     * somebody will translate a function at that address, and an import slot is
     * data - so it would stay empty forever and every call to it would trap. */
    CHECK(ptc_calltab_count(r.cache) == 0,
          "an import slot must not be given a call-table slot, got %zu",
          ptc_calltab_count(r.cache));
    CHECK(ptc_calltab_find(r.cache, r.module_id, IMAGE_BASE + iat_rva) ==
              PTC_CALLTAB_NONE,
          "and the slot address itself must not be findable as a call target");

    /* What the emitted code must do instead: reach the cell through the image
     * base and branch to whatever the loader put there. MOVZ X17,#rva /
     * ADD X17,X19,X17 / LDUR X16,[X17] / BLR X16. The MOVZ immediate is decoded
     * rather than compared against a hand-computed word, so this asserts that the
     * displacement is the slot's RVA and carries no tag bits. */
    slots = ptc_record_slots(r.cache);
    for (slot = 0; slot < slots; slot++) {
        uint64_t mid = 0, gpc = 0;
        const void *code = NULL;
        const uint32_t *ws;
        uint32_t clen = 0, nw, w;
        if (!ptc_record_at(r.cache, slot, &mid, &gpc, &code, &clen)) continue;
        if (mid != r.module_id || gpc != IMAGE_BASE + IDATA_VA) continue;
        found = 1;
        ws = (const uint32_t *)code;
        nw = clen / 4u;
        for (w = 0; w + 3u <= nw; w++) {
            /* ADD X17,X19,X17: the table form is 0x8B1102B1 with Rn=21 in bits
             * 9..5; the import form is the same instruction with Rn=19. */
            if (ws[w] == 0x8B110271u && ws[w + 1u] == 0xF8400230u &&
                ws[w + 2u] == 0xD63F0200u) {
                saw_host_indirect = 1;
                if (w > 0u && (ws[w - 1u] & 0xFFE0001Fu) == 0xD2800011u &&
                    ((ws[w - 1u] >> 5) & 0xFFFFu) == iat_rva)
                    imm_ok = 1;
            }
            if (ws[w] == 0x8B1102B1u)
                saw_table_form = 1;   /* ADD X17,X21,X17: the call-table shape */
        }
    }
    CHECK(found, "the import caller is in the cache");
    CHECK(saw_host_indirect,
          "the caller's words must load the cell through the image base "
          "(ADD X17,X19,X17 / LDUR X16,[X17] / BLR X16)");
    CHECK(imm_ok,
          "and the displacement must be the slot's RVA 0x%X with no tag bits in it",
          iat_rva);
    CHECK(!saw_table_form,
          "the caller must not consult the call table for an import: that is the "
          "shape whose tag ended up inside the branch target");

    rig_teardown(&r);
    g_with_imports = 0;
}

/* The reason histogram says which rule fired and the opcode histogram says which
 * instruction it stopped at, but a single opcode can be refused for a dozen
 * different reasons - and on a real bundle "1016 functions stopped at FF" is at
 * least three separate findings. This level has to be right before it can aim
 * anything, so its counts are asserted exactly, on a fixture with one refusal. */
static void test_refusal_details_are_counted_exactly(void)
{
    rig r;
    sweep_progress p;
    const char *top = NULL, *second = NULL;
    uint32_t c0, c1, sum = 0, rank;

    printf("refusal sentences are histogrammed exactly, not approximately\n");
    rig_setup(&r, 1, "with exports");
    CHECK(sweep_add_module(r.job, "test.exe", r.module_id, r.img.b, r.img.len,
                           &r.pe) == 3,
          "the entry point plus two exports");
    CHECK(sweep_run(r.job, NULL, NULL) == 1, "the sweep should finish uninterrupted");
    sweep_get_progress(r.job, &p);

    /* One function of the three is refused: FuncB is `jmp [rip+0]`, an indirect
     * jump with no statically knowable target. So exactly one sentence, once. */
    CHECK(p.functions_refused == 1,
          "the fixture refuses exactly one function, got %u", p.functions_refused);
    { extern void sweep_dbg_note_twice(void*); }
    CHECK(sweep_detail_kinds(r.job) == 1,
          "one refusal must make one histogram entry, got %u",
          sweep_detail_kinds(r.job));
    c0 = sweep_top_detail(r.job, 0, &top);
    CHECK(c0 == 1, "and its count must be 1, got %u", c0);
    CHECK(top != NULL && top[0] != '\0',
          "the sentence must be reported, not just counted");
    if (top) printf("  top refusal sentence: %s\n", top);

    /* Rank 1 must be empty rather than repeating rank 0: a ranking that runs off
     * the end of the table would report the same finding twice and double it. */
    c1 = sweep_top_detail(r.job, 1, &second);
    CHECK(c1 == 0, "there is no second sentence, got count %u", c1);

    /* Every rank's count sums to no more than the refusals, because a refusal is
     * bucketed once. A detail recorded per attempt rather than per refusal would
     * pass the checks above and still inflate this. */
    for (rank = 0; rank < 64u; rank++) {
        const char *t = NULL;
        uint32_t c = sweep_top_detail(r.job, rank, &t);
        if (!c) break;
        sum += c;
    }
    CHECK(sum == p.functions_refused,
          "the sentences must account for the refusals exactly: summed %u of %u",
          sum, p.functions_refused);
    CHECK(sweep_detail_overflow(r.job) == 0,
          "a three-function fixture cannot overflow a %u-slot histogram, got %u",
          SWEEP_DETAIL_MAX, sweep_detail_overflow(r.job));

    /* Two modules in one job, each refusing one function for the same reason. This
     * is the half the single-module case above cannot reach: with one refusal there
     * are no repeats, so a histogram that counted a sentence only the first time it
     * was seen - and silently dropped every later one - would pass every assertion
     * above. Bucketing by the sentence's identity across modules is exactly what
     * makes the top-N ranking mean anything on a real bundle, where the same
     * sentence accounts for hundreds of refusals in dozens of modules. */
    {
        rig a, b;
        sweep_progress p2;
        uint64_t mid2 = 0;
        const char *t0 = NULL;
        rig_setup(&a, 1, "testmod.dll");
        rig_setup(&b, 1, "second.dll");
        /* The images are byte-identical; the module name is part of the identity
         * ptc_add_module derives, so this is a genuinely second module. */
        CHECK(ptc_add_module(a.cache, "second.dll", b.img.len, 1u,
                             ptc_hash_bytes(b.img.b, b.img.len), &mid2) == 0,
              "a second module with the same bytes but a different name registers");
        CHECK(mid2 != a.module_id, "and gets its own id");
        CHECK(sweep_add_module(a.job, "testmod.dll", a.module_id, a.img.b, a.img.len,
                               &a.pe) == 3, "first module offers three entry points");
        CHECK(sweep_add_module(a.job, "second.dll", mid2, b.img.b, b.img.len,
                               &b.pe) == 3, "second module offers three entry points");
        CHECK(sweep_run(a.job, NULL, NULL) == 1, "the two-module sweep should finish");
        sweep_get_progress(a.job, &p2);
        CHECK(p2.functions_refused == 2,
              "one refusal per module, got %u", p2.functions_refused);
        CHECK(sweep_detail_kinds(a.job) == 1,
              "the same sentence from two modules must share one bucket, got %u",
              sweep_detail_kinds(a.job));
        CHECK(sweep_top_detail(a.job, 0, &t0) == 2,
              "and that bucket must count both, got %u",
              sweep_top_detail(a.job, 0, &t0));
        CHECK(sweep_top_detail(a.job, 1, &t0) == 0, "and there is no second bucket");
        rig_teardown(&a);
        rig_teardown(&b);
    }
}

/* Same address, other question. `call rel32` asks which function is here, and the
 * answer for an import slot is "none": eight bytes of pointer are not a function, so
 * giving them a call-table slot would promise a translation that can never exist and
 * leave the slot on the trap stub forever - looking exactly like a coverage gap in
 * the report, which is how ~498 unfilled slots came to be read as work not yet done
 * rather than as slots that should never have been assigned. */
static void test_call_rel32_at_an_import_slot_gets_no_slot(void)
{
    rig r;
    sweep_progress p;
    const char *top = NULL;

    printf("a call rel32 aimed at an import slot is refused, not given a slot\n");
    g_with_imports = 1;
    g_call_the_slot = 1;
    rig_setup(&r, 0, "calling an import slot as a function");
    CHECK(r.pe.num_dlls == 1, "the fixture must still carry one imported DLL, got %u",
          r.pe.num_dlls);
    CHECK(sweep_add_module(r.job, "test.exe", r.module_id, r.img.b, r.img.len,
                           &r.pe) == 1, "one entry point");
    CHECK(sweep_run(r.job, NULL, NULL) == 1, "the sweep should finish uninterrupted");
    sweep_get_progress(r.job, &p);

    CHECK(p.functions_translated == 0,
          "the caller cannot be translated: its target is data, got %u translated",
          p.functions_translated);
    CHECK(ptc_calltab_count(r.cache) == 0,
          "an import slot must not be given a call-table slot, got %zu",
          ptc_calltab_count(r.cache));
    CHECK(ptc_calltab_find(r.cache, r.module_id, IMAGE_BASE + IDATA_VA + 0x100u) ==
              PTC_CALLTAB_NONE,
          "and the slot address must not be findable as a call target");
    /* The sentence matters as much as the outcome: a refusal that says "no
     * call-table slot is known" is a different finding from one that says the
     * instruction is unsupported, and the histogram is what keeps them apart. */
    CHECK(sweep_top_detail(r.job, 0, &top) == 1, "one refusal, one sentence");
    CHECK(top != NULL && strstr(top, "call rel32") != NULL,
          "and it must be refused as a call rel32 with no target, got: %s",
          top ? top : "(none)");

    rig_teardown(&r);
    g_with_imports = 0;
    g_call_the_slot = 0;
}

int main(int argc, char **argv)
{
    /* Writes a guest image to disk so prewarm can be run over a real file. The
     * Makefile asserts on prewarm's output, which keeps the CLI inside the
     * tested surface instead of being a program that merely compiles. */
    if (argc >= 3 && strcmp(argv[1], "--write-fixture") == 0) {
        int  with_exports = (argc >= 4 && strcmp(argv[3], "--exports") == 0);
        buf  f;
        if (argc >= 5 && strcmp(argv[4], "--imports") == 0) g_with_imports = 1;
        f = build_guest(with_exports);
        FILE *fp = fopen(argv[2], "wb");
        if (!fp) { perror(argv[2]); free(f.b); return 1; }
        if (fwrite(f.b, 1, f.len, fp) != f.len) {
            fprintf(stderr, "short write to %s\n", argv[2]);
            fclose(fp); free(f.b); return 1;
        }
        fclose(fp);
        printf("wrote %zu bytes to %s (exports=%d imports=%d)\n", f.len, argv[2],
               with_exports, g_with_imports);
        free(f.b);
        return 0;
    }
    if (argc != 1) {
        fprintf(stderr,
                "usage: test_sweep [--write-fixture <path> [--exports]]\n");
        return 1;
    }

    printf("=== pre-translation sweep ===\n");
    test_discovery();
    test_translation_and_cache();
    test_exports_are_entry_points();
    test_interrupt_resume();
    test_progress_and_eta();
    test_exports_past_section();
    test_refusals();
    test_guest_call_gets_a_slot();
    test_import_slot_is_data_not_a_callee();
    test_call_rel32_at_an_import_slot_gets_no_slot();
    test_refusal_details_are_counted_exactly();
    printf("\n%d checks, %d failure(s)\n", checks, failures);
    return failures ? 1 : 0;
}
