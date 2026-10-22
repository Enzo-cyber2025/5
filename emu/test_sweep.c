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
    0x48, 0x89, 0x5C, 0x24, 0x08,
    0xE8, 0x06, 0x00, 0x00, 0x00,
    0xEB, 0x0A,
    0x90, 0x90, 0x90, 0x90,
    0x33, 0xC0,
    0xC3,
    0x90, 0x90, 0x90,
    0x74, 0x04,
    0xC3,
    0x90, 0x90, 0x90,
    0xFF, 0x25, 0x00, 0x00, 0x00, 0x00,
    0xC3
};

#define VA_ENTRY   (IMAGE_BASE + 0x1000u)
#define VA_CALLEE  (IMAGE_BASE + 0x1010u)
#define VA_COND    (IMAGE_BASE + 0x1016u)
#define VA_RET1    (IMAGE_BASE + 0x1018u)
#define VA_IND     (IMAGE_BASE + 0x101Cu)
#define VA_EXPORT  (IMAGE_BASE + 0x1022u)
#define VA_PAD1    (IMAGE_BASE + 0x100Cu)
#define VA_PAD2    (IMAGE_BASE + 0x1013u)
#define VA_PAD3    (IMAGE_BASE + 0x1019u)

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
    size_t e_lfanew = 0x80, hdr = 0x200;
    size_t exp_dir = 0, aof = 0, aon = 0, aoo = 0, nmA = 0, nmB = 0, nmDll = 0;
    int  i;

    memset(&out, 0, sizeof(out));
    memset(&rd, 0, sizeof(rd));

    if (with_exports) {
        exp_dir = btell(&rd); bzero(&rd, 40);
        aof = btell(&rd); bu32(&rd, 0x1022u); bu32(&rd, 0x1018u);
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
            for (k = 0; k < 4; k++) d[20 + k] = (uint8_t)(2u >> (8 * k));   /* NumberOfFunctions */
            for (k = 0; k < 4; k++) d[24 + k] = (uint8_t)(2u >> (8 * k));   /* NumberOfNames */
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
    bu16(&out, 3);                                 /* sections */
    bu32(&out, 0x60000000u); bu32(&out, 0); bu32(&out, 0);
    bu16(&out, 240);                               /* SizeOfOptionalHeader */
    bu16(&out, with_exports ? 0x2022u : 0x0022u);  /* DLL | EXECUTABLE | LARGE */

    bu16(&out, PE_MAGIC_PE32PLUS);
    bu8(&out, 14); bu8(&out, 0);
    bu32(&out, 0x200); bu32(&out, (uint32_t)rd.len); bu32(&out, 0);
    bu32(&out, TEXT_VA);                           /* AddressOfEntryPoint */
    bu32(&out, TEXT_VA);                           /* BaseOfCode */
    bu64(&out, IMAGE_BASE);
    bu32(&out, 0x1000u); bu32(&out, 0x200u);       /* section / file alignment */
    bu16(&out, 6); bu16(&out, 0); bu16(&out, 0); bu16(&out, 0);
    bu16(&out, 6); bu16(&out, 0);
    bu32(&out, 0);
    bu32(&out, 0x4000u);                           /* SizeOfImage */
    bu32(&out, (uint32_t)hdr);                     /* SizeOfHeaders */
    bu32(&out, 0);                                 /* CheckSum */
    bu16(&out, PE_SUBSYS_GUI); bu16(&out, 0x0160u);
    bu64(&out, 0x100000); bu64(&out, 0x1000);
    bu64(&out, 0x100000); bu64(&out, 0x1000);
    bu32(&out, 0);
    bu32(&out, PE_DIR_COUNT);
    for (i = 0; i < PE_DIR_COUNT; i++) {
        if (i == PE_DIR_EXPORT && with_exports) { bu32(&out, RDATA_VA); bu32(&out, 40); }
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

    bzero(&out, hdr - btell(&out));
    bput(&out, CODE, sizeof(CODE));
    bzero(&out, 0x200u - sizeof(CODE));
    if (rd.len) bput(&out, rd.b, rd.len);
    bzero(&out, 0x200u - rd.len);
    /* Decoy: a valid RET in a non-executable section. Decoding it would mean the
     * sweep is scanning data, which is exactly what it must not do. */
    bu8(&out, 0xC3);
    bzero(&out, 0x200u - 1u);

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
                           &r.pe) == 1,
          "queued entry points != 1");
    CHECK(sweep_run(r.job, NULL, NULL) == 1, "run did not report completion");
    sweep_get_progress(r.job, &p);

    CHECK(p.phase == SWEEP_DONE, "phase %s", sweep_phase_name(p.phase));
    CHECK(p.blocks == 5, "blocks %u, expected 5", p.blocks);
    CHECK(p.entry_points == 1, "entry_points %u", p.entry_points);
    CHECK(p.decode_calls == 8, "decode_calls %llu, expected 8",
          (unsigned long long)p.decode_calls);
    /* 12 + 3 + 2 + 1 + 6. The nine padding bytes are excluded, which is the
     * difference between recursive traversal and a linear scan. */
    CHECK(p.guest_bytes == 24, "guest_bytes %llu, expected 24",
          (unsigned long long)p.guest_bytes);
    CHECK(p.indirect_unresolved == 1, "indirect_unresolved %u, expected 1",
          p.indirect_unresolved);
    CHECK(p.decode_refusals == 0, "decode_refusals %u, expected 0",
          p.decode_refusals);

    b = find_block(r.job, VA_ENTRY);
    CHECK(b && b->len == 12 && b->kind == BLK_JUMP_DIRECT,
          "entry block: len=%u kind=%s", b ? b->len : 0,
          b ? sweep_block_kind_name(b->kind) : "(absent)");
    b = find_block(r.job, VA_CALLEE);
    CHECK(b && b->len == 3 && b->kind == BLK_RET,
          "callee block: len=%u kind=%s", b ? b->len : 0,
          b ? sweep_block_kind_name(b->kind) : "(absent)");
    b = find_block(r.job, VA_COND);
    CHECK(b && b->len == 2 && b->kind == BLK_COND,
          "conditional block: len=%u kind=%s", b ? b->len : 0,
          b ? sweep_block_kind_name(b->kind) : "(absent)");
    b = find_block(r.job, VA_RET1);
    CHECK(b && b->len == 1 && b->kind == BLK_RET,
          "single-byte ret block missing or wrong length");
    b = find_block(r.job, VA_IND);
    CHECK(b && b->len == 6 && b->kind == BLK_JUMP_INDIRECT,
          "indirect block: len=%u kind=%s", b ? b->len : 0,
          b ? sweep_block_kind_name(b->kind) : "(absent)");

    /* The negative assertions: unreachable padding has no block, and neither
     * does the export-only tail, which the entry point cannot reach. */
    CHECK(find_block(r.job, VA_PAD1) == NULL, "padding at 100C was decoded");
    CHECK(find_block(r.job, VA_PAD2) == NULL, "padding at 1013 was decoded");
    CHECK(find_block(r.job, VA_PAD3) == NULL, "padding at 1019 was decoded");
    CHECK(find_block(r.job, VA_EXPORT) == NULL,
          "an export target was reached from the entry point of an exe");

    rig_teardown(&r);
}

static void test_translation_and_cache(void)
{
    rig r; sweep_progress p;
    uint32_t code_len = 0;
    const void *host;
    uint8_t ret_byte = 0xC3;
    uint8_t three[3] = { 0x33, 0xC0, 0xC3 };
    rig_setup(&r, 0, "test.exe");
    sweep_add_module(r.job, "test.exe", r.module_id, r.img.b, r.img.len, &r.pe);
    sweep_run(r.job, NULL, NULL);
    sweep_get_progress(r.job, &p);

    printf("only a provably correct translation is cached\n");
    CHECK(p.blocks_translated == 1, "translated %u, expected exactly 1",
          p.blocks_translated);
    CHECK(p.blocks_untranslatable == 4, "untranslatable %u, expected 4",
          p.blocks_untranslatable);
    CHECK(p.blocks_stored == 1, "stored %u, expected 1", p.blocks_stored);
    CHECK(ptc_record_count(r.cache) == 1,
          "cache holds %zu records, expected 1 - something untranslatable was stored",
          ptc_record_count(r.cache));

    host = ptc_lookup(r.cache, r.module_id, VA_RET1, &ret_byte, 1u, &code_len);
    CHECK(host != NULL, "the one translated block missed the cache");
    CHECK(code_len == 4u, "host code length %u, expected 4", code_len);
    if (host && code_len == 4u) {
        uint32_t word;
        memcpy(&word, host, 4);
        CHECK(word == a64_ret(), "host word 0x%08x != RET 0x%08x", word,
              a64_ret());
        CHECK(word == 0xD65F03C0u, "RET encoding drifted from 0xD65F03C0");
    }

    /* The 3-byte block that also ends in RET must NOT be cached: translating it
     * needs xor eax,eax, which needs a register and flag model. */
    code_len = 0;
    host = ptc_lookup(r.cache, r.module_id, VA_CALLEE, three, 3u, &code_len);
    CHECK(host == NULL,
          "a block with no correct translation was served from the cache");

    /* Nor may an address that was never a block at all. */
    code_len = 0;
    host = ptc_lookup(r.cache, r.module_id, VA_PAD1, &ret_byte, 1u, &code_len);
    CHECK(host == NULL, "padding was served from the cache");

    rig_teardown(&r);
}

static void test_exports_are_entry_points(void)
{
    rig r; sweep_progress p;
    rig_setup(&r, 1, "testmod.dll");

    printf("a DLL is swept from its exports, not only from DllMain\n");
    CHECK(r.pe.num_exports == 2, "fixture exports %u, expected 2",
          r.pe.num_exports);
    CHECK(sweep_add_module(r.job, "testmod.dll", r.module_id, r.img.b, r.img.len,
                           &r.pe) == 3,
          "queued entry points != 3 (entry + 2 exports)");
    sweep_run(r.job, NULL, NULL);
    sweep_get_progress(r.job, &p);

    CHECK(p.entry_points == 3, "entry_points %u, expected 3", p.entry_points);
    CHECK(p.blocks == 6, "blocks %u, expected 6", p.blocks);
    CHECK(find_block(r.job, VA_EXPORT) != NULL,
          "the export-only block was never discovered");
    CHECK(p.blocks_translated == 2, "translated %u, expected 2",
          p.blocks_translated);
    CHECK(ptc_record_count(r.cache) == 2, "cache holds %zu records, expected 2",
          ptc_record_count(r.cache));

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
           prev->blocks_stored == now->blocks_stored &&
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
    CHECK(pb.blocks_translated == pa.blocks_translated,
          "translated differ: %u vs %u", pb.blocks_translated,
          pa.blocks_translated);
    CHECK(pb.blocks_stored == pa.blocks_stored, "stored differ");
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

    printf("  final: %.1f%%  blocks=%u translated=%u untranslatable=%u  %.3fs\n",
           (double)p.percent_x10 / 10.0, p.blocks, p.blocks_translated,
           p.blocks_untranslatable, (double)p.elapsed_ns / 1e9);

    rig_teardown(&r);
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

int main(int argc, char **argv)
{
    /* Writes a guest image to disk so prewarm can be run over a real file. The
     * Makefile asserts on prewarm's output, which keeps the CLI inside the
     * tested surface instead of being a program that merely compiles. */
    if (argc >= 3 && strcmp(argv[1], "--write-fixture") == 0) {
        int  with_exports = (argc >= 4 && strcmp(argv[3], "--exports") == 0);
        buf  f = build_guest(with_exports);
        FILE *fp = fopen(argv[2], "wb");
        if (!fp) { perror(argv[2]); free(f.b); return 1; }
        if (fwrite(f.b, 1, f.len, fp) != f.len) {
            fprintf(stderr, "short write to %s\n", argv[2]);
            fclose(fp); free(f.b); return 1;
        }
        fclose(fp);
        printf("wrote %zu bytes to %s (exports=%d)\n", f.len, argv[2],
               with_exports);
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
    test_refusals();
    printf("\n%d checks, %d failure(s)\n", checks, failures);
    return failures ? 1 : 0;
}
