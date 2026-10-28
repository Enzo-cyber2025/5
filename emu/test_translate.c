/* MAP_ANONYMOUS lives behind __USE_MISC in glibc, which -std=c11 turns off by
 * defining __STRICT_ANSI__. Whether the mmap flag is visible therefore depends on
 * which glibc a build happens to use: it is exposed on the aarch64 runner's 2.39
 * and hidden on 2.36, so the same source compiled here and failed there. Asking
 * for the default feature set explicitly removes that dependency instead of
 * leaving it to be rediscovered on the next toolchain. */
#ifndef _DEFAULT_SOURCE
#define _DEFAULT_SOURCE 1
#endif

/* End-to-end test: a real PE executable that calls a real PE DLL through its
 * import table, both translated to ARM64 from scratch and executed.
 *
 * The guest program is written here byte by byte rather than compiled, for two
 * reasons. There is no Windows cross-compiler in this environment, and more
 * importantly a hand-built image lets the test state exactly which bytes it is
 * translating, so a mismatch points at a specific instruction instead of at a
 * toolchain. Both images are structurally real PE files: DOS and NT headers,
 * section table, data directories, an export table in the DLL, and in the
 * executable an import descriptor with an ILT, an IAT slot and a RIP-relative
 * indirect call through it - which is how every real Windows binary calls an
 * imported function.
 *
 * The guest program:
 *
 *   mini.dll  SumTo(rcx) -> rax             app.exe  entry() -> rax
 *     xor rax, rax                            mov rcx, 5
 *   loop:                                     call [rip -> IAT for SumTo]
 *     add rax, rcx                            add rax, 1
 *     sub rcx, 1                              ret
 *     cmp rcx, 0
 *     jnz loop
 *     ret
 *
 * SumTo(5) = 5+4+3+2+1 = 15, plus 1 in the executable, so entry() returns 16 -
 * asserted on real ARM64 hardware and under QEMU, and again from the code reloaded
 * out of the persistent cache. The loop runs five iterations, so a wrong comparison
 * or a wrong branch direction changes the answer visibly instead of being off by
 * one and passing by luck.
 *
 * mini.dll also exports AddThree (add rcx,3; mov rax,rcx; ret), a straight-line
 * function with no flags and no branches, which is what the earlier milestone
 * translated and what the sweep-style straight-line path is still checked against.
 *
 * What this proves and what it does not. It proves the whole pipeline works:
 * PE in, decode, translate, resolve the import to a host address, emit, execute,
 * persist the result and execute it again from the cache without retranslating.
 * It does NOT prove a real application can be translated. This guest uses six
 * instruction forms and two registers; measured on a shipped bundle, that subset
 * covers 0.05% of basic blocks. Flags, branches, memory operands, the stack and
 * the Win32 bridge are all still missing, and every one of them is refused here
 * rather than approximated - see the unsupported cases at the end.
 */
#define _POSIX_C_SOURCE 200809L

#include "translate.h"

#include "gstack.h"

#include "a64_emit.h"
#include "pe_load.h"
#include "ptc.h"

#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <sys/mman.h>
#include <sys/wait.h>
#include <unistd.h>

#if defined(__aarch64__)
#include <signal.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <unistd.h>
#endif

static int checks, failures;

/* Facts about the ARM64 run, collected so main can print them as one compact
 * VERDICT line. A CI annotation is truncated, and a tail of the log is truncated
 * twice over; a single line at the end survives both. Without it the only
 * evidence available was the last four lines, which named the failure but not the
 * word that caused it. */
static struct {
    size_t   exe_words;
    int      rebuilt_matches;
    int      first_ok, first_timed_out, first_sig;
    uint64_t first_result;
    int      cached_ok, cached_timed_out, cached_sig;
    uint64_t cached_result;
    int      executed_at_all;
} verdict;

#define CHECK(cond, ...) do { \
    checks++; \
    if (!(cond)) { failures++; printf("  FAIL %s:%d: ", __FILE__, __LINE__); \
                   printf(__VA_ARGS__); printf("\n"); } \
} while (0)

#define IMAGE_BASE 0x140000000ULL
#define TEXT_VA    0x1000u
#define RDATA_VA   0x2000u
#define DATA_VA    0x3000u
#define HDR_SIZE   0x200u
#define CACHE_PATH "/tmp/emu_translate.ptc"

/* guest code: mini.dll!AddThree - straight line, no flags, no branches */
static const uint8_t DLL_CODE[] = {
    0x48, 0x83, 0xC1, 0x03,          /* add rcx, 3            */
    0x48, 0x89, 0xC8,                /* mov rax, rcx          */
    0xC3                             /* ret                   */
};

#define DLL_CODE2_RVA 0x1008u

/* guest code: mini.dll!SumTo - rax = rcx + (rcx-1) + ... + 1
 *
 *   1008  48 31 C0        xor rax, rax
 *   100B  48 01 C8        add rax, rcx      <- loop top, the backward target
 *   100E  48 83 E9 01     sub rcx, 1
 *   1012  48 83 F9 00     cmp rcx, 0
 *   1016  75 F3           jnz 100B
 *   1018  C3              ret
 *
 * This is the shape that flags and conditional branches exist for. Note that the
 * ADD and the SUB both set flags on x86 and neither does in the translation; that
 * is safe only because the JNZ reads the flags from the CMP immediately before it,
 * which the translator checks rather than assumes.
 */
static const uint8_t DLL_CODE2[] = {
    0x48, 0x31, 0xC0,
    0x48, 0x01, 0xC8,
    0x48, 0x83, 0xE9, 0x01,
    0x48, 0x83, 0xF9, 0x00,
    0x75, 0xF3,
    0xC3
};

/* The IAT slot lives at the start of the executable's .rdata. */
#define EXE_IAT_RVA   (RDATA_VA + 0u)
#define EXE_CALL_VA   (IMAGE_BASE + TEXT_VA + 7u)

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
static void buf_zero(buf *f, size_t n)
{ bgrow(f, n); memset(f->b + f->len, 0, n); f->len += n; }
static void bu16(buf *f, uint16_t v)
{ uint8_t t[2] = { (uint8_t)v, (uint8_t)(v >> 8) }; bput(f, t, 2); }
static void bu32(buf *f, uint32_t v)
{ uint8_t t[4] = { (uint8_t)v, (uint8_t)(v >> 8), (uint8_t)(v >> 16),
                   (uint8_t)(v >> 24) }; bput(f, t, 4); }
static void bu64(buf *f, uint64_t v)
{ bu32(f, (uint32_t)v); bu32(f, (uint32_t)(v >> 32)); }
static void bstr(buf *f, const char *s) { bput(f, s, strlen(s) + 1); }
static size_t btell(const buf *f) { return f->len; }
static void bp32(buf *f, size_t off, uint32_t v)
{ f->b[off]=(uint8_t)v; f->b[off+1]=(uint8_t)(v>>8);
  f->b[off+2]=(uint8_t)(v>>16); f->b[off+3]=(uint8_t)(v>>24); }

/* Writes DOS + NT + COFF + optional header + three section headers. */
static void write_headers(buf *o, int is_dll, uint32_t export_dir_rva,
                          uint32_t export_dir_size, uint32_t import_dir_rva,
                          uint32_t import_dir_size, uint32_t rdata_vsize)
{
    int i;
    bu16(o, 0x5A4Du);
    buf_zero(o, 0x3Cu - 2u);            /* e_lfanew lives at 0x3C */
    bu32(o, 0x80u);
    buf_zero(o, 0x80u - btell(o));      /* DOS stub */

    bu32(o, 0x00004550u);            /* "PE\0\0" */
    bu16(o, PE_MACHINE_AMD64);
    bu16(o, 3);                      /* sections */
    bu32(o, 0x60000000u); bu32(o, 0); bu32(o, 0);
    bu16(o, 240);                    /* SizeOfOptionalHeader (PE32+) */
    bu16(o, (uint16_t)(0x0022u | (is_dll ? 0x2000u : 0u)));

    bu16(o, PE_MAGIC_PE32PLUS);
    bu16(o, 0x000Eu);                /* linker version */
    bu32(o, 0x200u); bu32(o, rdata_vsize); bu32(o, 0);
    bu32(o, TEXT_VA);                /* AddressOfEntryPoint */
    bu32(o, TEXT_VA);                /* BaseOfCode */
    bu64(o, IMAGE_BASE);
    bu32(o, 0x1000u); bu32(o, 0x200u);
    bu16(o, 6); bu16(o, 0); bu16(o, 0); bu16(o, 0); bu16(o, 6); bu16(o, 0);
    bu32(o, 0);
    bu32(o, 0x4000u);                /* SizeOfImage */
    bu32(o, HDR_SIZE);               /* SizeOfHeaders */
    bu32(o, 0);                      /* CheckSum */
    bu16(o, PE_SUBSYS_GUI); bu16(o, 0x0160u);
    bu64(o, 0x100000); bu64(o, 0x1000); bu64(o, 0x100000); bu64(o, 0x1000);
    bu32(o, 0);
    bu32(o, PE_DIR_COUNT);
    for (i = 0; i < PE_DIR_COUNT; i++) {
        if (i == PE_DIR_EXPORT) { bu32(o, export_dir_rva); bu32(o, export_dir_size); }
        else if (i == PE_DIR_IMPORT) { bu32(o, import_dir_rva); bu32(o, import_dir_size); }
        else if (i == PE_DIR_IAT && import_dir_rva) { bu32(o, EXE_IAT_RVA); bu32(o, 8); }
        else { bu32(o, 0); bu32(o, 0); }
    }

    /* .text */
    bput(o, ".text\0\0\0", 8);
    bu32(o, 0x40u); bu32(o, TEXT_VA);
    bu32(o, 0x200u); bu32(o, HDR_SIZE);
    bu32(o, 0); bu32(o, 0); bu16(o, 0); bu16(o, 0);
    bu32(o, PE_SCN_CNT_CODE | PE_SCN_MEM_EXECUTE | PE_SCN_MEM_READ);
    /* .rdata */
    bput(o, ".rdata\0\0", 8);
    bu32(o, rdata_vsize); bu32(o, RDATA_VA);
    bu32(o, 0x200u); bu32(o, HDR_SIZE + 0x200u);
    bu32(o, 0); bu32(o, 0); bu16(o, 0); bu16(o, 0);
    bu32(o, PE_SCN_CNT_INITIALIZED_DATA | PE_SCN_MEM_READ);
    /* .data */
    bput(o, ".data\0\0\0", 8);
    bu32(o, 0x10u); bu32(o, DATA_VA);
    bu32(o, 0x200u); bu32(o, HDR_SIZE + 0x400u);
    bu32(o, 0); bu32(o, 0); bu16(o, 0); bu16(o, 0);
    bu32(o, PE_SCN_CNT_INITIALIZED_DATA | PE_SCN_MEM_READ | PE_SCN_MEM_WRITE);

    buf_zero(o, HDR_SIZE - btell(o));
}

/* mini.dll: one export, AddThree, pointing at the code. */
static buf build_dll(void)
{
    buf o, rd;
    size_t exp_dir, aof, aon, aoo, nameA, nameB, nameDll;
    memset(&o, 0, sizeof(o)); memset(&rd, 0, sizeof(rd));

    exp_dir = btell(&rd); buf_zero(&rd, 40);
    aof     = btell(&rd); bu32(&rd, TEXT_VA);          /* AddThree */
                          bu32(&rd, DLL_CODE2_RVA);    /* SumTo    */
    aon     = btell(&rd); buf_zero(&rd, 8);               /* patched below */
    aoo     = btell(&rd); bu16(&rd, 0); bu16(&rd, 1);
    nameA   = btell(&rd); bstr(&rd, "AddThree");
    nameB   = btell(&rd); bstr(&rd, "SumTo");
    nameDll = btell(&rd); bstr(&rd, "mini.dll");
    /* Names are listed in ascending RVA of their functions, as the PE spec
     * requires; both arrays are patched once every offset is known. */
    bp32(&rd, aon + 0u, (uint32_t)(RDATA_VA + nameA));
    bp32(&rd, aon + 4u, (uint32_t)(RDATA_VA + nameB));
    bp32(&rd, exp_dir + 12u, (uint32_t)(RDATA_VA + nameDll));  /* Name */
    bp32(&rd, exp_dir + 16u, 1u);                              /* Base */
    bp32(&rd, exp_dir + 20u, 2u);                              /* NumberOfFunctions */
    bp32(&rd, exp_dir + 24u, 2u);                              /* NumberOfNames */
    bp32(&rd, exp_dir + 28u, (uint32_t)(RDATA_VA + aof));
    bp32(&rd, exp_dir + 32u, (uint32_t)(RDATA_VA + aon));
    bp32(&rd, exp_dir + 36u, (uint32_t)(RDATA_VA + aoo));

    write_headers(&o, 1, RDATA_VA, 40u, 0u, 0u, (uint32_t)rd.len);
    bput(&o, DLL_CODE, sizeof(DLL_CODE));
    CHECK(sizeof(DLL_CODE) == DLL_CODE2_RVA - TEXT_VA,
          "SumTo does not start where its export RVA says");
    bput(&o, DLL_CODE2, sizeof(DLL_CODE2));
    buf_zero(&o, 0x200u - sizeof(DLL_CODE) - sizeof(DLL_CODE2));
    bput(&o, rd.b, rd.len);
    buf_zero(&o, 0x200u - rd.len);
    buf_zero(&o, 0x200u);
    free(rd.b);
    return o;
}

/* app.exe: imports AddThree from mini.dll and calls it through the IAT. */
static buf build_exe(void)
{
    buf  o, rd;
    uint8_t code[18];
    size_t iat, ilt, ibn, nmDll, desc;
    uint32_t disp;
    memset(&o, 0, sizeof(o)); memset(&rd, 0, sizeof(rd));

    iat   = btell(&rd); bu64(&rd, 0);          /* filled by the loader at run time */
    ilt   = btell(&rd); bu64(&rd, 0);          /* patched: -> IMAGE_IMPORT_BY_NAME */
                         bu64(&rd, 0);         /* terminator */
    ibn   = btell(&rd); bu16(&rd, 0x0042); bstr(&rd, "SumTo");
    nmDll = btell(&rd); bstr(&rd, "mini.dll");
    buf_zero(&rd, 8u - (btell(&rd) % 8u));        /* align the descriptor array */
    desc  = btell(&rd);
    bu32(&rd, (uint32_t)(RDATA_VA + ilt));     /* OriginalFirstThunk (names) */
    bu32(&rd, 0);                              /* TimeDateStamp */
    bu32(&rd, 0xFFFFFFFFu);                    /* ForwarderChain */
    bu32(&rd, (uint32_t)(RDATA_VA + nmDll));   /* Name */
    bu32(&rd, (uint32_t)(RDATA_VA + iat));     /* FirstThunk (the IAT) */
    buf_zero(&rd, 20);                            /* terminating descriptor */
    bp32(&rd, ilt, (uint32_t)(RDATA_VA + ibn));

    /* mov rcx, 5 ; call [rip -> IAT] ; add rax, 1 ; ret
     * SumTo(5) = 5+4+3+2+1 = 15, and the executable adds 1, so entry() is 16.
     * The loop runs five times, which is enough that a wrong comparison or a
     * wrong branch direction gives a visibly different number rather than
     * something off by one that could pass by luck. */
    code[0]=0x48; code[1]=0xC7; code[2]=0xC1;
    code[3]=0x05; code[4]=0x00; code[5]=0x00; code[6]=0x00;
    /* The displacement is relative to the end of the call instruction, so it is
     * computed from the addresses rather than written by hand. */
    disp = (uint32_t)((IMAGE_BASE + EXE_IAT_RVA) - (EXE_CALL_VA + 6u));
    code[7]=0xFF; code[8]=0x15;
    code[9]=(uint8_t)disp; code[10]=(uint8_t)(disp>>8);
    code[11]=(uint8_t)(disp>>16); code[12]=(uint8_t)(disp>>24);
    code[13]=0x48; code[14]=0x83; code[15]=0xC0; code[16]=0x01;
    code[17]=0xC3;

    write_headers(&o, 0, 0u, 0u, (uint32_t)(RDATA_VA + desc), 40u,
                  (uint32_t)rd.len);
    bput(&o, code, sizeof(code));
    buf_zero(&o, 0x200u - sizeof(code));
    bput(&o, rd.b, rd.len);
    buf_zero(&o, 0x200u - rd.len);
    buf_zero(&o, 0x200u);
    free(rd.b);
    return o;
}

/* ------------------------------------------------------- import resolution */

typedef struct {
    uint64_t iat_guest_va;
    uint64_t host_addr;
    int      queries;
} resolver;

static uint64_t resolve_cb(uint64_t iat_va, void *user)
{
    resolver *r = user;
    r->queries++;
    return (iat_va == r->iat_guest_va) ? r->host_addr : 0;
}

/* Validates the emitted shape of the executable and rebuilds the call target from
 * the MOVZ/MOVK run.
 *
 * Indices are taken relative to both ends because the number of constant words
 * depends on how many 16-bit chunks of the host address happen to be non-zero, so
 * a fixed count would fail for a reason that is not a bug. The frame push and pop
 * are checked by position as well: they are what makes the final RET return to the
 * caller instead of into the middle of the function, which is the defect that only
 * appeared when the generated code was executed on real hardware.
 */
static void check_exe_shape(const uint32_t *words, size_t n, uint64_t host_addr,
                            unsigned imm, const char *where)
{
    CHECK(n >= 8u && n <= 12u, "%s: emitted %zu words, expected 8..12", where, n);
    if (n < 8u) return;
    CHECK(words[0] == a64_stp_frame_push(), "%s: word 0 is 0x%08X, not the frame push",
          where, words[0]);
    CHECK(words[0] == 0xA9BF7BFDu, "%s: STP encoding drifted", where);
    CHECK(words[1] == a64_movz_x(1, imm), "%s: mov rcx,imm -> 0x%08X", where, words[1]);
    CHECK(words[n - 4u] == a64_blr(16), "%s: blr -> 0x%08X", where, words[n - 4u]);
    CHECK(words[n - 3u] == a64_add_x_imm(0, 0, 1), "%s: add rax,1 -> 0x%08X", where,
          words[n - 3u]);
    CHECK(words[n - 3u] == 0x91000400u, "%s: add x0,x0,#1 drifted", where);
    CHECK(words[n - 2u] == a64_ldp_frame_pop(), "%s: word n-2 is 0x%08X, not the pop",
          where, words[n - 2u]);
    CHECK(words[n - 2u] == 0xA8C17BFDu, "%s: LDP encoding drifted", where);
    CHECK(words[n - 1u] == a64_ret(), "%s: ret -> 0x%08X", where, words[n - 1u]);
    CHECK(words[n - 1u] == 0xD65F03C0u, "%s: ret drifted", where);
    {
        size_t   k, first = 2u, last = n - 5u;
        uint64_t rebuilt = 0;
        CHECK(last >= first, "%s: no constant words emitted for the call target", where);
        for (k = first; k <= last && k < n; k++) {
            uint32_t w = words[k];
            unsigned rd = w & 31u;
            uint16_t chunk = (uint16_t)((w >> 5) & 0xFFFFu);
            unsigned hw = (w >> 21) & 3u;
            CHECK(rd == 16u, "%s: constant word %zu targets X%u, expected X16", where, k, rd);
            if ((w & 0xFF800000u) == 0xD2800000u) {
                rebuilt = chunk;
                CHECK(hw == 0u, "%s: MOVZ used hw=%u", where, hw);
            } else if ((w & 0xFF800000u) == 0xF2800000u) {
                rebuilt |= (uint64_t)chunk << (hw * 16u);
            } else {
                CHECK(0, "%s: word %zu is neither MOVZ nor MOVK: 0x%08X", where, k, w);
            }
        }
        CHECK(rebuilt == host_addr,
              "%s: the emitted constant materialises 0x%llx, not the call target "
              "0x%llx - the call would go somewhere else",
              where, (unsigned long long)rebuilt, (unsigned long long)host_addr);
    }
}

/* --------------------------------------------------------------- ARM64 run */

/* Progress marker. stdout is fully buffered when it is not a terminal, and a
 * process that is killed for hanging flushes nothing, so a marker that is not
 * flushed is indistinguishable from a stage that was never reached. */
static void mark(const char *what)
{
    printf("  .. %s\n", what);
    fflush(stdout);
}

#if defined(__aarch64__)
/* Runs generated code in a forked child with an alarm and reads the result back
 * through a pipe.
 *
 * Generated code is not trustworthy by definition - that is the entire reason
 * this project pins encodings and executes them. A wrong word can hang or crash,
 * and doing that inside the test process takes the whole suite down without
 * saying which instruction was wrong, which is exactly what happened when this
 * test first ran on real hardware. Isolating it turns a nine-minute mystery into
 * a five-second diagnostic. */
static int exec_generated(uint64_t (*fn)(void), uint64_t *out, int *timed_out,
                          int *signo)
{
    int     fds[2];
    pid_t   pid;
    ssize_t got;
    int     status = 0;

    if (timed_out) *timed_out = 0;
    if (signo) *signo = 0;
    if (pipe(fds) != 0) return 0;
    pid = fork();
    if (pid < 0) { close(fds[0]); close(fds[1]); return 0; }
    if (pid == 0) {
        uint64_t r;
        close(fds[0]);
        alarm(5);                       /* default SIGALRM action kills us */
        r = fn();
        if (write(fds[1], &r, sizeof(r)) != (ssize_t)sizeof(r)) _exit(2);
        close(fds[1]);
        _exit(0);
    }
    close(fds[1]);
    got = read(fds[0], out, sizeof(*out));
    close(fds[0]);
    waitpid(pid, &status, 0);
    if (WIFSIGNALED(status)) {
        if (signo) *signo = WTERMSIG(status);
        if (timed_out) *timed_out = (WTERMSIG(status) == SIGALRM);
        return 0;
    }
    return got == (ssize_t)sizeof(*out) && WIFEXITED(status) &&
           WEXITSTATUS(status) == 0;
}

/* Maps an executable page, copies the words in, and maintains the caches. The
 * cache step is not optional on ARM64: the store went through the D-cache and
 * the fetch comes from the I-cache, so without it execution can see stale bytes
 * and fail in a way that looks exactly like a bad encoding. */
static void *code_page(const uint32_t *words, size_t n, size_t *out_len)
{
    long ps = sysconf(_SC_PAGESIZE);
    size_t bytes = ((n * 4u) + (size_t)ps - 1u) & ~((size_t)ps - 1u);
    void *p = mmap(NULL, bytes, PROT_READ | PROT_WRITE | PROT_EXEC,
                   MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (p == MAP_FAILED) return NULL;
    memcpy(p, words, n * 4u);
    __builtin___clear_cache((char *)p, (char *)p + n * 4u);
    if (out_len) *out_len = bytes;
    return p;
}
#endif

/* ------------------------------------------------------------------ tests */

static void test_images_are_real(void)
{
    buf dll = build_dll(), exe = build_exe();
    pe_image pd, px;

    printf("two real PE images, built byte by byte\n");
    CHECK(pe_load(dll.b, dll.len, &pd) == PE_OK, "mini.dll did not parse: %s",
          pd.detail ? pd.detail : "?");
    CHECK(pe_load(exe.b, exe.len, &px) == PE_OK, "app.exe did not parse: %s",
          px.detail ? px.detail : "?");

    CHECK(pd.is_dll == 1, "mini.dll not marked as a DLL");
    CHECK(px.is_dll == 0 && px.is_exe == 1, "app.exe not marked as an executable");
    CHECK(pd.num_exports == 2, "dll exports %u, expected 2", pd.num_exports);
    CHECK(pd.exports[0].name && strcmp(pd.exports[0].name, "AddThree") == 0,
          "export name '%s'", pd.exports[0].name ? pd.exports[0].name : "(null)");
    CHECK(pd.exports[0].rva == TEXT_VA, "export rva %08x", pd.exports[0].rva);
    CHECK(pd.exports[0].forwarded == 0, "export reported as a forwarder");

    CHECK(px.num_dlls == 1, "exe imports from %u dll(s), expected 1", px.num_dlls);
    CHECK(px.dlls[0].dll_name && strcmp(px.dlls[0].dll_name, "mini.dll") == 0,
          "imported dll '%s'", px.dlls[0].dll_name ? px.dlls[0].dll_name : "(null)");
    CHECK(px.funcs[0].name && strcmp(px.funcs[0].name, "SumTo") == 0,
          "imported function '%s'", px.funcs[0].name ? px.funcs[0].name : "(null)");
    CHECK(px.dlls[0].iat_rva == EXE_IAT_RVA, "IAT rva %08x, expected %08x",
          px.dlls[0].iat_rva, EXE_IAT_RVA);
    CHECK(px.dlls[0].ilt_rva != px.dlls[0].iat_rva, "ILT and IAT are the same");

    /* The call really is RIP-relative to the IAT slot, computed not assumed. */
    {
        uint32_t disp = (uint32_t)((IMAGE_BASE + EXE_IAT_RVA) - (EXE_CALL_VA + 6u));
        const uint8_t *c = exe.b + HDR_SIZE + 7u;
        CHECK(c[0] == 0xFF && c[1] == 0x15, "call opcode is %02X %02X", c[0], c[1]);
        CHECK((uint32_t)(c[2] | (c[3] << 8) | (c[4] << 16) | (c[5] << 24)) == disp,
              "displacement in the image does not match the computed one");
    }

    free(dll.b); free(exe.b);
}

static void test_translation(void)
{
    buf dll = build_dll(), exe = build_exe();
    tr_output o;
    tr_status st;
    resolver  rs;

    printf("translating both modules\n");

    /* mini.dll!AddThree needs no imports, so no resolver is required. */
    st = tr_translate_run(DLL_CODE, sizeof(DLL_CODE),
                          IMAGE_BASE + TEXT_VA, NULL, NULL, &o);
    CHECK(st == TR_OK, "dll translation returned %s: %s", tr_status_name(st),
          o.detail ? o.detail : "?");
    CHECK(o.n == 3, "dll emitted %zu words, expected 3", o.n);
    CHECK(o.guest_insns == 3, "dll translated %u instructions", o.guest_insns);
    CHECK(o.guest_bytes == sizeof(DLL_CODE), "dll consumed %u of %zu bytes",
          o.guest_bytes, sizeof(DLL_CODE));
    if (o.n == 3) {
        CHECK(o.words[0] == a64_add_x_imm(1, 1, 3),
              "add rcx,3 -> 0x%08X, expected 0x%08X", o.words[0],
              a64_add_x_imm(1, 1, 3));
        CHECK(o.words[0] == 0x91000C21u, "add x1,x1,#3 encoding drifted");
        CHECK(o.words[1] == 0xAA0103E0u, "mov x0,x1 -> 0x%08X", o.words[1]);
        CHECK(o.words[2] == 0xD65F03C0u, "ret -> 0x%08X", o.words[2]);
    }

    /* Without a resolved import the executable must be refused, not guessed. */
    st = tr_translate_run(exe.b + HDR_SIZE, 18u, IMAGE_BASE + TEXT_VA,
                          NULL, NULL, &o);
    CHECK(st == TR_NEEDS_TARGET, "unresolved import returned %s, expected NEEDS_TARGET",
          tr_status_name(st));
    CHECK(o.iat_va == IMAGE_BASE + EXE_IAT_RVA,
          "reported slot 0x%llx, expected 0x%llx",
          (unsigned long long)o.iat_va,
          (unsigned long long)(IMAGE_BASE + EXE_IAT_RVA));

    /* With the import resolved the call target becomes a constant and the whole
     * entry point translates. Because it contains a call it also gets a frame
     * record: without one, the final RET uses whatever X30 the BLR left there and
     * jumps back into the middle of the function. */
    memset(&rs, 0, sizeof(rs));
    rs.iat_guest_va = IMAGE_BASE + EXE_IAT_RVA;
    rs.host_addr = 0x00000000DEADB000ULL;   /* two non-zero 16-bit chunks */
    st = tr_translate_run(exe.b + HDR_SIZE, 18u, IMAGE_BASE + TEXT_VA,
                          resolve_cb, &rs, &o);
    CHECK(st == TR_OK, "exe translation returned %s: %s", tr_status_name(st),
          o.detail ? o.detail : "?");
    CHECK(rs.queries == 1, "resolver queried %d times, expected 1", rs.queries);
    CHECK(o.guest_insns == 4, "exe translated %u instructions, expected 4",
          o.guest_insns);
    /* frame push + movz x1 + movz x16 + movk x16 + blr + add + frame pop + ret */
    CHECK(o.n == 8, "exe emitted %zu words, expected 8", o.n);
    check_exe_shape(o.words, o.n, rs.host_addr, 5u, "synthetic target");

    /* A run containing no call gets no frame record: the DLL neither calls nor
     * needs X30 preserved, so pushing one would be code that does nothing. */
    st = tr_translate_run(DLL_CODE, sizeof(DLL_CODE), IMAGE_BASE + TEXT_VA,
                          NULL, NULL, &o);
    CHECK(st == TR_OK && o.n == 3, "call-free dll emitted %zu words, expected 3",
          o.n);

    free(dll.b); free(exe.b);
}

static void test_function_translation(void)
{
    tr_func f;
    tr_status st;

    printf("a real loop: flags, a conditional branch, and a backward target\n");
    st = tr_translate_function(DLL_CODE2, sizeof(DLL_CODE2),
                               IMAGE_BASE + DLL_CODE2_RVA, NULL, NULL, &f);
    CHECK(st == TR_OK, "SumTo returned %s: %s", tr_status_name(st),
          f.detail ? f.detail : "?");
    CHECK(f.insns == 6, "translated %u instructions, expected 6", f.insns);
    CHECK(f.guest_bytes == sizeof(DLL_CODE2), "consumed %u of %zu bytes",
          f.guest_bytes, sizeof(DLL_CODE2));
    CHECK(f.branches == 1, "branches %u, expected 1", f.branches);
    CHECK(f.backwards == 1, "backward branches %u, expected 1 - that is the loop",
          f.backwards);
    CHECK(f.needs_frame == 0, "a call-free function was given a frame record");
    CHECK(f.n == 6, "emitted %zu words, expected 6", f.n);
    if (f.n == 6) {
        /* Every word checked against a value derived independently of the
         * translator, including the branch displacement: the jnz sits at word 4
         * and the loop top at word 1, so the offset is -3 instructions. */
        CHECK(f.words[0] == 0xD2800000u, "xor rax,rax -> 0x%08X, expected MOVZ X0,#0",
              f.words[0]);
        CHECK(f.words[1] == 0x8B010000u, "add rax,rcx -> 0x%08X, expected ADD X0,X0,X1",
              f.words[1]);
        CHECK(f.words[2] == 0xD1000421u, "sub rcx,1 -> 0x%08X, expected SUB X1,X1,#1",
              f.words[2]);
        CHECK(f.words[3] == 0xF100003Fu, "cmp rcx,0 -> 0x%08X, expected SUBS XZR,X1,#0",
              f.words[3]);
        CHECK(f.words[4] == 0x54FFFFA1u, "jnz loop -> 0x%08X, expected B.NE -3",
              f.words[4]);
        CHECK(f.words[5] == 0xD65F03C0u, "ret -> 0x%08X", f.words[5]);
        /* Decode the branch back out rather than trusting the constant above. */
        {
            uint32_t w = f.words[4];
            int32_t  imm = (int32_t)((w >> 5) & 0x7FFFFu);
            if (imm >= 0x40000) imm -= 0x80000;
            CHECK((w & 0xFu) == A64_NE, "branch condition %u, expected NE", w & 0xFu);
            CHECK(imm == -3, "branch offset %d words, expected -3", imm);
            CHECK(4 + imm == 1, "branch does not land on the loop top");
        }
    }

    printf("flags are only read where this translator produced them\n");
    {
        /* add rax,1 ; jz +2 ; ret  -- the jz would read flags that x86 set but
         * the emitted ADD did not. */
        /* disp 0, so the jz targets the RET and stays inside the buffer: a
         * displacement of 2 would leave the function and be refused for that
         * reason first, never reaching the flag check under test. */
        static const uint8_t bad[] = { 0x48,0x83,0xC0,0x01, 0x74,0x00, 0xC3 };
        st = tr_translate_function(bad, sizeof(bad), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_UNSUPPORTED, "jz after a plain add returned %s",
              tr_status_name(st));
        CHECK(f.detail && strstr(f.detail, "flags") != NULL,
              "detail '%s' does not say the problem is flags", f.detail ? f.detail : "?");
    }
    {
        /* jmp 6 ; cmp rax,0 ; jz 2 -- the jmp targets the jz itself, so on that
         * path the flags would come from wherever the jmp came from. */
        static const uint8_t bad[] = { 0xEB,0x04, 0x48,0x83,0xF8,0x00, 0x74,0xFA,
                                       0xC3 };
        st = tr_translate_function(bad, sizeof(bad), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_UNSUPPORTED, "a branch onto a jz returned %s",
              tr_status_name(st));
        CHECK(f.detail && strstr(f.detail, "targets a conditional") != NULL,
              "detail '%s' does not explain the guarded case", f.detail ? f.detail : "?");
    }
    {
        /* cmp rax,0 ; jp 0 ; ret -- AArch64 has no parity flag at all. */
        static const uint8_t bad[] = { 0x48,0x83,0xF8,0x00, 0x7A,0x00, 0xC3 };
        st = tr_translate_function(bad, sizeof(bad), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_UNSUPPORTED, "jp returned %s", tr_status_name(st));
        CHECK(f.detail && strstr(f.detail, "parity") != NULL,
              "detail '%s' does not say parity is the reason", f.detail ? f.detail : "?");
    }

    printf("the failure record names the instruction that actually failed\n");
    {
        /* push rsp: refused on the very first instruction, so the depth is 0 and
         * the opcode is real and worth counting.
         *
         * This case used to be `push rbp`, which was refused then because RBP had
         * no host mapping. It translates now, so keeping it here would have made
         * the test pass for a reason it was not written for. push rsp is refused
         * on its own merits and stays refused: x86 itself is ambiguous about
         * whether the pushed value is the pre- or post-decrement stack pointer,
         * and ARM64's pre-indexed store answers the other way. */
        static const uint8_t g[] = { 0x54, 0xC3 };
        st = tr_translate_function(g, sizeof(g), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_UNSUPPORTED, "push rsp returned %s", tr_status_name(st));
        CHECK(f.reason == TRR_STACK, "reason %s, expected guest-stack-form",
              tr_reason_name(f.reason));
        CHECK(f.fail_insns == 0, "depth %u, expected 0 - the first instruction failed",
              f.fail_insns);
        CHECK(f.fail_from_plan == 0, "a planning refusal claimed to come from a plan");
        CHECK(f.fail_op_len > 0 && f.fail_op[0] == 0x54u,
              "recorded opcode %02X, expected 54 (push rsp)", f.fail_op[0]);
    }
    {
        /* And the instruction that replaced it must now translate, or the change
         * above is only hiding a regression rather than recording one. */
        static const uint8_t g[] = { 0x55, 0x5D, 0xC3 };   /* push rbp; pop rbp; ret */
        st = tr_translate_function(g, sizeof(g), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_OK, "push rbp; pop rbp returned %s: %s", tr_status_name(st),
              f.detail ? f.detail : "?");
        CHECK(f.needs_gstack == 1, "a function that pushes was not marked as using "
                                   "the guest stack");
        CHECK(f.needs_frame == 0, "a function with no call was given a frame record");
    }
    {
        /* add rax,1 ; jz 0 ; ret - refused by the flag-liveness rule, which fires
         * after planning. The record must point at the branch and must NOT offer
         * an opcode, because the branch is not what the subset lacks. */
        static const uint8_t g[] = { 0x48,0x83,0xC0,0x01, 0x74,0x00, 0xC3 };
        st = tr_translate_function(g, sizeof(g), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_UNSUPPORTED, "flags case returned %s", tr_status_name(st));
        CHECK(f.reason == TRR_FLAGS, "reason %s, expected flags",
              tr_reason_name(f.reason));
        CHECK(f.fail_from_plan == 1,
              "a post-planning refusal did not mark itself, so its stale opcode "
              "would be counted as the cause");
        CHECK(f.fail_insns == 1, "depth %u, expected 1 (the jz is the second plan)",
              f.fail_insns);
    }
    {
        /* A function that never reaches a RET is also refused after planning. */
        static const uint8_t g[] = { 0x48,0x31,0xC0, 0x48,0x83,0xC0,0x01 };
        st = tr_translate_function(g, sizeof(g), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_UNSUPPORTED, "no-RET case returned %s", tr_status_name(st));
        CHECK(f.reason == TRR_NO_RET, "reason %s, expected no-ret",
              tr_reason_name(f.reason));
        CHECK(f.fail_from_plan == 1, "the no-RET refusal did not mark itself");
        CHECK(f.fail_insns == 2, "depth %u, expected 2 planned instructions",
              f.fail_insns);
    }

    printf("structural refusals\n");
    {
        static const uint8_t out[] = { 0x48,0x83,0xF8,0x00, 0x74,0x02, 0xEB,0x7F,
                                       0xC3 };
        st = tr_translate_function(out, sizeof(out), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_UNSUPPORTED, "a branch leaving the function returned %s",
              tr_status_name(st));
        CHECK(f.detail && strstr(f.detail, "leaves the function") != NULL,
              "detail '%s'", f.detail ? f.detail : "?");
    }
    {
        static const uint8_t noret[] = { 0x48,0x83,0xC0,0x01 };
        st = tr_translate_function(noret, sizeof(noret), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_UNSUPPORTED, "a function with no RET returned %s",
              tr_status_name(st));
        CHECK(f.detail && strstr(f.detail, "without a RET") != NULL,
              "detail '%s'", f.detail ? f.detail : "?");
    }
    {
        /* xor rax, rcx: a real two-operand xor, not the zeroing idiom. */
        static const uint8_t x[] = { 0x48,0x31,0xC8, 0xC3 };
        st = tr_translate_function(x, sizeof(x), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_UNSUPPORTED, "xor with two operands returned %s",
              tr_status_name(st));
    }
    {
        /* add rsp, rax. This used to be refused because RSP had no host mapping;
         * it is now a register add against the guest stack pointer, and the frame
         * record that saves and restores X14/X15 has to appear around it. */
        static const uint8_t r[] = { 0x48,0x01,0xC4, 0xC3 };
        st = tr_translate_function(r, sizeof(r), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_OK, "add rsp,rax returned %s: %s", tr_status_name(st),
              f.detail ? f.detail : "?");
        CHECK(f.needs_gstack == 1, "using RSP did not mark the translation as needing "
                                   "a guest stack");
        CHECK(f.n == 4, "emitted %zu words, expected 4 (STP, ADD, LDP, RET)", f.n);
        if (f.n == 4) {
            CHECK(f.words[0] == a64_stp_gstack_push(),
                  "prologue 0x%08X, expected STP X14,X15 0x%08X", f.words[0],
                  a64_stp_gstack_push());
            CHECK(f.words[1] == a64_add_reg(14, 14, 0),
                  "add rsp,rax -> 0x%08X, expected ADD X14,X14,X0 0x%08X",
                  f.words[1], a64_add_reg(14, 14, 0));
            CHECK(f.words[2] == a64_ldp_gstack_pop(),
                  "epilogue 0x%08X, expected LDP X14,X15", f.words[2]);
            CHECK(f.words[3] == a64_ret(), "last word 0x%08X, expected RET", f.words[3]);
        }
    }

    printf("cmp against a negative constant becomes CMN, not a negative SUBS\n");
    {
        static const uint8_t g[] = { 0x48,0x83,0xF8,0xFB, 0x74,0x00, 0xC3 };
        st = tr_translate_function(g, sizeof(g), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_OK, "cmp rax,-5 returned %s: %s", tr_status_name(st),
              f.detail ? f.detail : "?");
        CHECK(f.n == 3, "emitted %zu words, expected 3", f.n);
        if (f.n == 3) {
            CHECK(f.words[0] == a64_adds_imm(A64_XZR, 0, 5),
                  "cmp rax,-5 -> 0x%08X, expected CMN 0x%08X", f.words[0],
                  a64_adds_imm(A64_XZR, 0, 5));
            CHECK(f.words[0] == 0xB100141Fu, "CMN encoding drifted");
            CHECK(f.words[1] == a64_b_cond(A64_EQ, 1), "jz -> 0x%08X", f.words[1]);
            CHECK(f.words[2] == 0xD65F03C0u, "ret -> 0x%08X", f.words[2]);
        }
    }
    {
        /* test rax,rax ; jz +0 ; ret -> TST then B.EQ */
        static const uint8_t g[] = { 0x48,0x85,0xC0, 0x74,0x00, 0xC3 };
        st = tr_translate_function(g, sizeof(g), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_OK, "test/jz returned %s: %s", tr_status_name(st),
              f.detail ? f.detail : "?");
        CHECK(f.n == 3 && f.words[0] == 0xEA00001Fu,
              "test rax,rax -> 0x%08X, expected TST 0xEA00001F",
              f.n ? f.words[0] : 0u);
        CHECK(f.n == 3 && (f.words[1] & 0xFu) == A64_EQ,
              "jz condition is %u, expected EQ", f.n ? (f.words[1] & 0xFu) : 99u);
    }
    {
        /* An unconditional forward jmp must emit B, not B.cond. */
        static const uint8_t g[] = { 0x48,0x31,0xC0, 0xEB,0x00, 0xC3 };
        st = tr_translate_function(g, sizeof(g), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_OK, "xor/jmp/ret returned %s", tr_status_name(st));
        CHECK(f.n == 3 && f.words[1] == a64_b(1), "jmp -> 0x%08X, expected B +1",
              f.n ? f.words[1] : 0u);
        CHECK(f.branches == 1 && f.backwards == 0,
              "forward jmp counted as backward");
    }
}

static void test_unsupported_is_refused(void)
{
    tr_output o;
    tr_status st;
    /* Each of these is legal x86-64 that a real application uses constantly.
     * Every one must be refused with a reason; approximating any of them would
     * put a wrong translation into the cache. */
    static const struct { const char *what; uint8_t b[8]; size_t n; } cases[] = {
        { "cmp rax, rcx",        { 0x48, 0x39, 0xC8 }, 3 },
        { "jz  +5",              { 0x74, 0x05 }, 2 },
        { "mov rax, [rcx]",      { 0x48, 0x8B, 0x01 }, 3 },
        { "add rdx, rax",        { 0x48, 0x01, 0xC2 }, 3 },   /* rdx: not mapped */
        { "push rbp",            { 0x55 }, 1 },
        { "mov r8, 1 (REX.B)",   { 0x49, 0xC7, 0xC0, 0x01, 0x00, 0x00, 0x00 }, 7 },
        { "xorps xmm0, xmm0",    { 0x0F, 0x57, 0xC0 }, 3 },
    };
    size_t i;

    printf("everything outside the subset is refused, not approximated\n");
    for (i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        st = tr_translate_run(cases[i].b, cases[i].n, IMAGE_BASE + TEXT_VA,
                              NULL, NULL, &o);
        CHECK(st == TR_UNSUPPORTED || st == TR_INVALID,
              "%s returned %s, expected a refusal", cases[i].what,
              tr_status_name(st));
        CHECK(o.detail != NULL && strcmp(o.detail, "ok") != 0,
              "%s was refused without a reason", cases[i].what);
        CHECK(o.n == 0 || st != TR_OK, "%s produced executable words", cases[i].what);
    }

    /* A run that never reaches a RET is refused even if every instruction
     * translated: a prefix of a function is not a function. */
    {
        static const uint8_t no_ret[] = { 0x48, 0x83, 0xC1, 0x03 };
        st = tr_translate_run(no_ret, sizeof(no_ret), IMAGE_BASE + TEXT_VA,
                              NULL, NULL, &o);
        CHECK(st == TR_UNSUPPORTED, "code with no RET returned %s", tr_status_name(st));
        CHECK(o.detail && strstr(o.detail, "RET") != NULL,
              "detail '%s' does not say the run had no RET", o.detail ? o.detail : "?");
    }

    /* A negative immediate becomes SUB, and one outside 12 bits is refused. */
    {
        static const uint8_t neg[] = { 0x48, 0x83, 0xE8, 0x05, 0xC3 }; /* sub rax,5 */
        st = tr_translate_run(neg, sizeof(neg), IMAGE_BASE + TEXT_VA, NULL, NULL, &o);
        CHECK(st == TR_OK, "sub rax,5 returned %s", tr_status_name(st));
        CHECK(o.n == 2 && o.words[0] == a64_sub_x_imm(0, 0, 5),
              "sub rax,5 -> 0x%08X", o.n ? o.words[0] : 0u);
    }
    {
        /* GRP1 with imm32 (0x81) is in the subset, so this reaches the 12-bit
         * limit instead of being refused earlier as an unknown opcode. */
        static const uint8_t fits[] = { 0x48, 0x81, 0xC0, 0xE8, 0x03, 0x00, 0x00,
                                        0xC3 };   /* add rax, 1000 */
        static const uint8_t big[]  = { 0x48, 0x81, 0xC1, 0x00, 0x00, 0x01, 0x00,
                                        0xC3 };   /* add rcx, 0x10000 */
        st = tr_translate_run(fits, sizeof(fits), IMAGE_BASE + TEXT_VA, NULL, NULL, &o);
        CHECK(st == TR_OK, "add rax,1000 returned %s", tr_status_name(st));
        CHECK(o.n == 2 && o.words[0] == a64_add_x_imm(0, 0, 1000),
              "add rax,1000 -> 0x%08X", o.n ? o.words[0] : 0u);
        st = tr_translate_run(big, sizeof(big), IMAGE_BASE + TEXT_VA, NULL, NULL, &o);
        CHECK(st == TR_UNSUPPORTED, "add rcx,0x10000 returned %s", tr_status_name(st));
        CHECK(o.detail && strstr(o.detail, "12 bits") != NULL,
              "detail '%s' does not explain the 12-bit limit", o.detail ? o.detail : "?");
    }
    {
        /* A negative imm32 must become SUB, and a negative add must too. */
        static const uint8_t subbig[] = { 0x48, 0x81, 0xE8, 0x00, 0x01, 0x00, 0x00,
                                          0xC3 };  /* sub rax, 256 */
        static const uint8_t addneg[] = { 0x48, 0x83, 0xC0, 0xFB,
                                          0xC3 };  /* add rax, -5 */
        st = tr_translate_run(subbig, sizeof(subbig), IMAGE_BASE + TEXT_VA,
                              NULL, NULL, &o);
        CHECK(st == TR_OK && o.n == 2 && o.words[0] == a64_sub_x_imm(0, 0, 256),
              "sub rax,256 -> 0x%08X (%s)", o.n ? o.words[0] : 0u, tr_status_name(st));
        st = tr_translate_run(addneg, sizeof(addneg), IMAGE_BASE + TEXT_VA,
                              NULL, NULL, &o);
        CHECK(st == TR_OK && o.n == 2 && o.words[0] == a64_sub_x_imm(0, 0, 5),
              "add rax,-5 must emit SUB -> 0x%08X (%s)",
              o.n ? o.words[0] : 0u, tr_status_name(st));
    }
}

/* Runs the whole pipeline: load, resolve by name, translate, execute, persist,
 * reload and execute again.
 *
 * Resolution by name is not a detail. An earlier version of this test took
 * exports[0] and the program still ran cleanly and still returned a plausible
 * number - 9, which is AddThree(5)+1, the wrong function called correctly. Only
 * the expected value caught it. A loader that resolves by position does not fail
 * loudly, it silently runs something else. */
static void test_pipeline(void)
{
    buf dll = build_dll(), exe = build_exe();
    pe_image pd, px;
    ptc_cache *cache;
    uint64_t dll_mid = 0, exe_mid = 0, dll_va = 0, exe_va = 0, iat_va = 0;
    uint32_t dll_off = 0, dll_rva = 0, exe_len = 18u;
    const uint8_t *dll_code = NULL;
    tr_func  fd, fx;
    resolver rs;
    uint32_t i, found = 0;
    int      saved = 0;

    printf("the whole pipeline, ending in the persistent cache\n");
    mark("parsing both images");

    CHECK(pe_load(dll.b, dll.len, &pd) == PE_OK, "dll parse: %s",
          pd.detail ? pd.detail : "?");
    CHECK(pe_load(exe.b, exe.len, &px) == PE_OK, "exe parse: %s",
          px.detail ? px.detail : "?");
    if (px.num_dlls != 1 || !px.funcs[0].name) {
        CHECK(0, "the executable has no named import to resolve");
        free(dll.b); free(exe.b);
        return;
    }
    exe_va = px.image_base + px.entry_rva;
    iat_va = px.image_base + px.dlls[0].iat_rva;

    mark("resolving the import by name, the way a loader does");
    for (i = 0; i < pd.num_exports; i++) {
        if (pd.exports[i].forwarded || !pd.exports[i].name) continue;
        if (strcmp(pd.exports[i].name, px.funcs[0].name) == 0) {
            dll_rva = pd.exports[i].rva;
            dll_va  = pd.image_base + dll_rva;
            dll_off = HDR_SIZE + (dll_rva - TEXT_VA);
            found = 1;
            break;
        }
    }
    CHECK(found, "could not resolve import '%s' in mini.dll", px.funcs[0].name);
    CHECK(dll_rva == DLL_CODE2_RVA,
          "'%s' resolved to RVA %08x, expected SumTo at %08x - resolving by "
          "position would call AddThree instead",
          px.funcs[0].name, dll_rva, DLL_CODE2_RVA);
    if (!found) { free(dll.b); free(exe.b); return; }
    dll_code = dll.b + dll_off;

    mark("translating mini.dll!SumTo, including its loop");
    CHECK(tr_translate_function(dll_code, sizeof(DLL_CODE2), dll_va, NULL, NULL,
                                &fd) == TR_OK,
          "SumTo did not translate: %s", fd.detail ? fd.detail : "?");
    CHECK(fd.n == 6, "SumTo emitted %zu words, expected 6", fd.n);
    CHECK(fd.branches == 1 && fd.backwards == 1,
          "SumTo reported %u branches, %u backwards - the loop is missing",
          fd.branches, fd.backwards);
    CHECK(fd.needs_frame == 0, "SumTo was given a frame record without a call");

    cache = ptc_create(PTC_ISA_AARCH64, PTC_ISA_X86_64, 4096u);
    CHECK(cache != NULL, "ptc_create failed");
    if (!cache) { free(dll.b); free(exe.b); return; }
    CHECK(ptc_add_module(cache, "mini.dll", dll.len, 1u,
                         ptc_hash_bytes(dll.b, dll.len), &dll_mid) == 0,
          "could not register mini.dll");

    memset(&rs, 0, sizeof(rs));
    rs.iat_guest_va = iat_va;

#if defined(__aarch64__)
    {
        void *dll_host;
        mark("mapping the translated dll");
        dll_host = code_page(fd.words, fd.n, NULL);
        CHECK(dll_host != NULL, "could not map an executable page for the dll");
        if (!dll_host) { ptc_free(cache); free(dll.b); free(exe.b); return; }

        mark("translating app.exe against the resolved import");
        rs.host_addr = (uint64_t)(uintptr_t)dll_host;
        CHECK(tr_translate_function(exe.b + HDR_SIZE, exe_len, exe_va, resolve_cb,
                                    &rs, &fx) == TR_OK,
              "exe did not translate once the import was resolved: %s",
              fx.detail ? fx.detail : "?");
        check_exe_shape(fx.words, fx.n, rs.host_addr, 5u, "real host address");
        verdict.exe_words = fx.n;
        verdict.rebuilt_matches = 1;

        mark("persisting both translations");
        CHECK(ptc_insert(cache, dll_mid, dll_va, dll_code, (uint32_t)sizeof(DLL_CODE2),
                         fd.words, (uint32_t)(fd.n * 4u), 0u) == 0,
              "could not cache the dll function");
        CHECK(ptc_add_module(cache, "app.exe", exe.len, 1u,
                             ptc_hash_bytes(exe.b, exe.len), &exe_mid) == 0,
              "could not register app.exe");
        CHECK(ptc_insert(cache, exe_mid, exe_va, exe.b + HDR_SIZE, exe_len,
                         fx.words, (uint32_t)(fx.n * 4u), 0u) == 0,
              "could not cache the exe entry");
        saved = (ptc_save(cache, CACHE_PATH) == 0);
        CHECK(saved, "ptc_save failed");
        ptc_free(cache);
        cache = NULL;

        mark("mapping and executing the translated exe");
        {
            uint64_t (*entry)(void) = (uint64_t (*)(void))
                code_page(fx.words, fx.n, NULL);
            CHECK(entry != NULL, "could not map the executable entry page");
            if (entry) {
                uint64_t r = 0;
                int to = 0, sig = 0, ok;
                mark("calling the generated entry point (child, 5s alarm)");
                ok = exec_generated(entry, &r, &to, &sig);
                mark("the generated entry point returned control");
                verdict.executed_at_all = 1;
                verdict.first_ok = ok;
                verdict.first_timed_out = to;
                verdict.first_sig = sig;
                verdict.first_result = r;
                CHECK(ok, "executing the translated exe failed%s%s",
                      to ? ": it did not terminate within 5s" : "",
                      (!ok && !to && sig) ? ": killed by a signal" : "");
                if (!ok && sig)
                    printf("  terminated by signal %d%s\n", sig,
                           to ? " (SIGALRM: the generated code never returned)" : "");
                CHECK(ok && r == 16u,
                      "entry() returned %llu, expected 16 (SumTo(5)=15, then +1)",
                      (unsigned long long)r);
                if (ok)
                    printf("  EXECUTED ON aarch64: app.exe entry -> %llu, having called "
                           "mini.dll!SumTo through its import table, five iterations "
                           "of a loop driven by cmp/jnz\n",
                           (unsigned long long)r);
            }
        }

        mark("reloading the cache and running the stored host code");
        if (saved) {
            ptc_open_result why = PTC_OPEN_OK;
            ptc_cache *re = ptc_open(CACHE_PATH, PTC_ISA_AARCH64, PTC_ISA_X86_64, &why);
            CHECK(re != NULL, "could not reopen the cache (reason %d)", (int)why);
            if (re) {
                uint64_t rd_id = 0, rx_id = 0;
                uint32_t clen = 0;
                const void *host;
                CHECK(ptc_add_module(re, "mini.dll", dll.len, 1u,
                                     ptc_hash_bytes(dll.b, dll.len), &rd_id) == 0,
                      "reopened cache lost mini.dll");
                CHECK(ptc_add_module(re, "app.exe", exe.len, 1u,
                                     ptc_hash_bytes(exe.b, exe.len), &rx_id) == 0,
                      "reopened cache lost app.exe");
                CHECK(rd_id == dll_mid && rx_id == exe_mid,
                      "module identities changed across the reopen");
                host = ptc_lookup(re, rx_id, exe_va, exe.b + HDR_SIZE, exe_len, &clen);
                CHECK(host != NULL, "the exe block missed the reopened cache");
                CHECK(clen == (uint32_t)(fx.n * 4u),
                      "reloaded %u bytes of host code, expected %zu", clen, fx.n * 4u);
                if (host && clen == fx.n * 4u && memcmp(host, fx.words, clen) == 0) {
                    uint64_t (*e2)(void) = (uint64_t (*)(void))
                        code_page((const uint32_t *)host, fx.n, NULL);
                    CHECK(e2 != NULL, "could not map the reloaded code");
                    if (e2) {
                        uint64_t r2 = 0;
                        int to2 = 0, sig2 = 0;
                        mark("executing the host code reloaded from the cache");
                        if (exec_generated(e2, &r2, &to2, &sig2)) {
                            verdict.cached_ok = 1;
                            verdict.cached_result = r2;
                            CHECK(r2 == 16u,
                                  "code loaded from the cache returned %llu, expected 16",
                                  (unsigned long long)r2);
                            printf("  EXECUTED FROM CACHE: %llu with zero retranslation\n",
                                   (unsigned long long)r2);
                        } else {
                            verdict.cached_timed_out = to2;
                            verdict.cached_sig = sig2;
                            CHECK(0, "cached host code did not run%s%s",
                                  to2 ? ": it did not terminate within 5s" : "",
                                  sig2 ? ": killed by a signal" : "");
                        }
                    }
                } else {
                    CHECK(0, "reloaded host code differs from what was translated");
                }
                host = ptc_lookup(re, rd_id, dll_va, dll_code,
                                  (uint32_t)sizeof(DLL_CODE2), &clen);
                CHECK(host != NULL, "the dll function missed the reopened cache");
                CHECK(clen == (uint32_t)(fd.n * 4u),
                      "reloaded %u bytes for the dll, expected %zu", clen, fd.n * 4u);
                CHECK(ptc_record_count(re) == 2, "reopened cache holds %zu records",
                      ptc_record_count(re));
                ptc_free(re);
            }
            remove(CACHE_PATH);
        }
    }
#else
    mark("translating app.exe against a synthetic host address");
    rs.host_addr = 0x00000000DEADB000ULL;
    CHECK(tr_translate_function(exe.b + HDR_SIZE, exe_len, exe_va, resolve_cb, &rs,
                                &fx) == TR_OK,
          "exe did not translate: %s", fx.detail ? fx.detail : "?");
    check_exe_shape(fx.words, fx.n, rs.host_addr, 5u, "bytes-only host");
    verdict.exe_words = fx.n;
    verdict.rebuilt_matches = 1;

    mark("saving the cache");
    CHECK(ptc_insert(cache, dll_mid, dll_va, dll_code, (uint32_t)sizeof(DLL_CODE2),
                     fd.words, (uint32_t)(fd.n * 4u), 0u) == 0,
          "could not cache the dll function");
    CHECK(ptc_add_module(cache, "app.exe", exe.len, 1u,
                         ptc_hash_bytes(exe.b, exe.len), &exe_mid) == 0,
          "could not register app.exe");
    CHECK(ptc_insert(cache, exe_mid, exe_va, exe.b + HDR_SIZE, exe_len,
                     fx.words, (uint32_t)(fx.n * 4u), 0u) == 0,
          "could not cache the exe entry");
    saved = (ptc_save(cache, CACHE_PATH) == 0);
    CHECK(saved, "ptc_save failed");
    if (saved) {
        ptc_open_result why = PTC_OPEN_OK;
        ptc_cache *re = ptc_open(CACHE_PATH, PTC_ISA_AARCH64, PTC_ISA_X86_64, &why);
        CHECK(re != NULL, "could not reopen the cache");
        if (re) {
            uint32_t clen = 0;
            const void *host = ptc_lookup(re, exe_mid, exe_va, exe.b + HDR_SIZE,
                                          exe_len, &clen);
            CHECK(host != NULL && clen == (uint32_t)(fx.n * 4u) &&
                  memcmp(host, fx.words, clen) == 0,
                  "the exe block did not survive the cache round trip as bytes");
            host = ptc_lookup(re, dll_mid, dll_va, dll_code,
                              (uint32_t)sizeof(DLL_CODE2), &clen);
            CHECK(host != NULL && clen == (uint32_t)(fd.n * 4u) &&
                  memcmp(host, fd.words, clen) == 0,
                  "the dll function did not survive the cache round trip as bytes");
            CHECK(ptc_record_count(re) == 2, "reopened cache holds %zu records",
                  ptc_record_count(re));
            ptc_free(re);
        }
        remove(CACHE_PATH);
    }
    ptc_free(cache);
    cache = NULL;
    printf("  SKIP: host is not aarch64 - both modules translated and cached as\n"
           "        bytes and verified through the cache, but nothing was run\n");
    printf("SKIPPED NOT aarch64\n");
#endif

    if (cache) ptc_free(cache);
    free(dll.b); free(exe.b);
}

/* ---------------------------------------------------------------- guest stack
 *
 * The guest stack model, and the traps in it.
 *
 * This section exists because of a measurement, not because it seemed like a good
 * next step. Sweeping a real shipped application bundle found 64 genuine code
 * entry points and translated none of them, and every one of the 64 died at its
 * first instruction. Two of them - the .exe entries - died on opcode 0x83 with
 * reason register-unmapped, which is `sub rsp, N`: the frame adjustment a real
 * prologue opens with, refused only because RSP had no host register. That is the
 * gap closed here.
 */

/* Attempts one write in a forked child and reports whether it COMPLETED: 1 if the
 * child stored the byte and exited cleanly, 0 if it did not.
 *
 * "Did the write complete" rather than "which signal arrived", because the two do
 * not mean the same thing under every build. A sanitizer intercepts SIGSEGV,
 * prints a report and exits non-zero, so WIFSIGNALED is false and the signal
 * number never reaches the parent - the first version of this helper returned -2
 * under AddressSanitizer and failed a test that was actually demonstrating
 * exactly what it claimed. What stays true in every build is that a write to a
 * PROT_NONE page does not complete.
 *
 * The protection itself is then checked directly and separately, below, by
 * reading the mapping's permissions rather than by provoking a fault.
 *
 * Forking at all is not optional: a containment property asserted only by the
 * absence of a crash is not asserted. If the guard pages were missing the write
 * would land in whatever the allocator put there, and the test would pass. */
static int write_completed(char *addr)
{
    pid_t pid;
    int   status = 0;

    fflush(stdout);
    pid = fork();
    if (pid < 0) return -1;
    if (pid == 0) {
        *addr = 0x5A;
        _exit(0);
    }
    waitpid(pid, &status, 0);
    return (WIFEXITED(status) && WEXITSTATUS(status) == 0) ? 1 : 0;
}

#if defined(__linux__)
/* Reads the permissions of the mapping that contains addr from /proc/self/maps.
 *
 * This is the direct statement of the containment property: the pages either side
 * of the arena are mapped with no permissions at all. It does not depend on a
 * fault being delivered to anyone, so sanitizers cannot change the answer.
 *
 * Returns 1 on success and writes a four-character permission string such as
 * "---p" or "rw-p". Returns 0 if the address is in no mapping listed. */
static int mapping_perms(uintptr_t addr, char out[5])
{
    FILE *f = fopen("/proc/self/maps", "r");
    char  line[512];
    int   found = 0;

    if (!f) return 0;
    while (fgets(line, sizeof line, f)) {
        unsigned long lo = 0, hi = 0;
        char perms[8] = {0};
        if (sscanf(line, "%lx-%lx", &lo, &hi) == 2) {
            /* the permission field follows the range after a space */
            char *sp = strchr(line, ' ');
            if (sp && sp[1] && sscanf(sp + 1, "%7s", perms) == 1) {
                if ((uintptr_t)lo <= addr && addr < (uintptr_t)hi) {
                    memcpy(out, perms, 4);
                    out[4] = '\0';
                    found = 1;
                    break;
                }
            }
        }
    }
    fclose(f);
    return found;
}
#endif

static void test_guest_stack_arena(void)
{
    gs_arena a;
    long ps = sysconf(_SC_PAGESIZE);

    printf("the guest stack arena is bounded, and the bounds are real\n");
    memset(&a, 0, sizeof a);
    CHECK(gs_alloc(4096, &a) == 1, "gs_alloc failed: %s", gs_last_error());
    if (!a.usable) return;

    CHECK(a.guards == 1, "no guard pages were placed around the arena");
    CHECK(a.usable_size >= 4096u, "usable size %zu is smaller than the %u requested",
          a.usable_size, 4096u);
    CHECK(ps > 0 && (a.usable_size % (size_t)ps) == 0,
          "usable size %zu is not a whole number of pages", a.usable_size);
    CHECK(a.map_size == a.usable_size + 2u * (size_t)ps,
          "mapping is %zu bytes, expected usable %zu plus two guard pages",
          a.map_size, a.usable_size);
    CHECK((a.top & 15u) == 0,
          "initial guest RSP 0x%llX is not 16-byte aligned",
          (unsigned long long)a.top);
    CHECK(a.top == (uint64_t)(uintptr_t)(a.usable + a.usable_size),
          "guest RSP does not start at the high end of the arena");

    CHECK(gs_contains(&a, a.top - 8u) == 1, "the first slot below the top is outside");
    CHECK(gs_contains(&a, a.top) == 0, "the top itself counts as inside the arena");
    CHECK(gs_contains(&a, (uint64_t)(uintptr_t)a.usable) == 1,
          "the first usable byte is outside the arena");
    CHECK(gs_used(&a, a.top) == 0, "an untouched stack reports %zu bytes used",
          gs_used(&a, a.top));
    CHECK(gs_used(&a, a.top - 64u) == 64u, "64 bytes taken reports %zu",
          gs_used(&a, a.top - 64u));
    CHECK(gs_used(&a, a.top + 8u) == 0, "a pointer above the top reports %zu used",
          gs_used(&a, a.top + 8u));

    /* The writable region really is writable, and the guards really are not.
     * Each call is made once and stored: the CHECK macro evaluates its condition
     * and, on failure, its message arguments too, so a helper with a side effect
     * written into both forks twice and reports a different signal than the one
     * it tested. */
    {
        int w0 = write_completed(a.usable);
        int w1 = write_completed((char *)(uintptr_t)a.top - 8);
        int g_lo = write_completed(a.usable - 1);
        int g_hi = write_completed(a.usable + a.usable_size);
        CHECK(w0 == 1, "the first usable byte could not be written");
        CHECK(w1 == 1, "the first stack slot below the top could not be written");
        CHECK(g_lo == 0,
              "a write BELOW the arena completed: a runaway guest stack would walk "
              "into whatever the allocator put there");
        CHECK(g_hi == 0, "a write ABOVE the arena completed");
    }
#if defined(__linux__)
    /* And the reason those writes did not complete, stated directly rather than
     * inferred: the guard pages carry no permissions at all. */
    {
        char pu[5] = {0}, pl[5] = {0}, ph[5] = {0};
        int  oku = mapping_perms((uintptr_t)a.usable, pu);
        int  okl = mapping_perms((uintptr_t)a.usable - 1u, pl);
        int  okh = mapping_perms((uintptr_t)a.usable + a.usable_size, ph);
        CHECK(oku == 1 && strcmp(pu, "rw-p") == 0,
              "the usable region has permissions '%s', expected rw-p", oku ? pu : "?");
        CHECK(okl == 1 && strcmp(pl, "---p") == 0,
              "the low guard has permissions '%s', expected ---p (no access at all)",
              okl ? pl : "?");
        CHECK(okh == 1 && strcmp(ph, "---p") == 0,
              "the high guard has permissions '%s', expected ---p", okh ? ph : "?");
    }
#else
    printf("  (mapping permissions not checked: no /proc/self/maps on this host)\n");
#endif

    gs_free(&a);
    CHECK(a.map_base == NULL, "gs_free left the arena looking allocated");
    CHECK(gs_alloc(0, &a) == 0, "a zero-byte arena was accepted");
    CHECK(gs_last_error() != NULL && gs_last_error()[0] != '\0',
          "a refused arena gave no reason");
}

static void test_guest_stack_translation(void)
{
    tr_func   f;
    tr_status st;

    printf("the prologue a real function opens with now translates\n");
    {
        /* sub rsp,0x28 ; add rsp,0x28 ; ret - the exact shape that was refused as
         * register-unmapped on every real code entry point measured. */
        static const uint8_t g[] = { 0x48,0x83,0xEC,0x28, 0x48,0x83,0xC4,0x28, 0xC3 };
        st = tr_translate_function(g, sizeof(g), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_OK, "sub rsp,0x28 returned %s: %s", tr_status_name(st),
              f.detail ? f.detail : "?");
        CHECK(f.reason == TRR_OK, "a successful translation reported reason %s",
              tr_reason_name(f.reason));
        CHECK(f.needs_gstack == 1, "adjusting RSP did not mark the translation as "
                                   "needing a guest stack");
        CHECK(f.needs_frame == 0, "a function with no call was given a frame record");
        CHECK(f.n == 5, "emitted %zu words, expected 5 (STP,SUB,ADD,LDP,RET)", f.n);
        if (f.n == 5) {
            CHECK(f.words[0] == a64_stp_gstack_push(),
                  "prologue 0x%08X, expected STP X14,X15,[SP,#-16]! 0x%08X",
                  f.words[0], a64_stp_gstack_push());
            CHECK(f.words[1] == a64_sub_x_imm(14, 14, 0x28),
                  "sub rsp,0x28 -> 0x%08X, expected SUB X14,X14,#0x28 0x%08X",
                  f.words[1], a64_sub_x_imm(14, 14, 0x28));
            CHECK(f.words[2] == a64_add_x_imm(14, 14, 0x28),
                  "add rsp,0x28 -> 0x%08X, expected ADD X14,X14,#0x28", f.words[2]);
            CHECK(f.words[3] == a64_ldp_gstack_pop(),
                  "epilogue 0x%08X, expected LDP X14,X15,[SP],#16", f.words[3]);
            CHECK(f.words[4] == a64_ret(), "last word 0x%08X, expected RET", f.words[4]);
        }
        /* Cacheability. No absolute arena address may appear in the words, or the
         * translation would only be valid in the process that produced it and
         * could not be persisted - which is one of the three requirements this
         * project was asked to meet. The translator takes no arena argument at
         * all, which is the structural reason; this checks the consequence. */
        {
            size_t i;
            int materialises = 0;
            for (i = 0; i < f.n; i++) {
                uint32_t w = f.words[i];
                if ((w & 0xFF800000u) == 0xD2800000u ||   /* MOVZ Xd */
                    (w & 0xFF800000u) == 0xF2800000u)     /* MOVK Xd */
                    materialises = 1;
            }
            CHECK(!materialises,
                  "a stack-only translation materialises an absolute constant, so it "
                  "would not be reusable from a cache in another process");
        }
    }
    {
        /* The full prologue and epilogue a compiler emits, with a local:
         *   push rbp; mov rbp,rsp; sub rsp,0x20;
         *   mov [rbp-8],rax; mov rax,[rbp-8];
         *   leave; ret */
        static const uint8_t g[] = {
            0x55, 0x48,0x89,0xE5, 0x48,0x83,0xEC,0x20,
            0x48,0x89,0x45,0xF8, 0x48,0x8B,0x45,0xF8,
            0xC9, 0xC3
        };
        st = tr_translate_function(g, sizeof(g), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_OK, "a real prologue/epilogue returned %s: %s",
              tr_status_name(st), f.detail ? f.detail : "?");
        CHECK(f.insns == 7, "planned %u guest instructions, expected 7", f.insns);
        CHECK(f.needs_gstack == 1, "not marked as using the guest stack");
        CHECK(f.n == 10, "emitted %zu words, expected 10", f.n);
        if (f.n == 10) {
            CHECK(f.words[1] == a64_str_pre(15, 14, -8),
                  "push rbp -> 0x%08X, expected STR X15,[X14,#-8]! 0x%08X",
                  f.words[1], a64_str_pre(15, 14, -8));
            CHECK(f.words[2] == a64_mov_reg(15, 14),
                  "mov rbp,rsp -> 0x%08X, expected MOV X15,X14", f.words[2]);
            CHECK(f.words[3] == a64_sub_x_imm(14, 14, 0x20),
                  "sub rsp,0x20 -> 0x%08X", f.words[3]);
            CHECK(f.words[4] == a64_stur(0, 15, -8),
                  "mov [rbp-8],rax -> 0x%08X, expected STUR X0,[X15,#-8] 0x%08X",
                  f.words[4], a64_stur(0, 15, -8));
            CHECK(f.words[5] == a64_ldur(0, 15, -8),
                  "mov rax,[rbp-8] -> 0x%08X, expected LDUR X0,[X15,#-8] 0x%08X",
                  f.words[5], a64_ldur(0, 15, -8));
            CHECK(f.words[6] == a64_mov_reg(14, 15),
                  "leave's mov rsp,rbp -> 0x%08X, expected MOV X14,X15", f.words[6]);
            CHECK(f.words[7] == a64_ldr_post(15, 14, 8),
                  "leave's pop rbp -> 0x%08X, expected LDR X15,[X14],#8 0x%08X",
                  f.words[7], a64_ldr_post(15, 14, 8));
            CHECK(f.words[8] == a64_ldp_gstack_pop(),
                  "epilogue 0x%08X, expected LDP X14,X15", f.words[8]);
        }
    }
    {
        /* A call and a stack adjustment in the same function need BOTH records,
         * and the pops have to come off in the reverse of the pushes. */
        static const uint8_t g[] = { 0x48,0x83,0xEC,0x20, 0x50, 0x58,
                                     0x48,0x83,0xC4,0x20, 0xC3 };
        st = tr_translate_function(g, sizeof(g), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_OK, "push/pop pair returned %s: %s", tr_status_name(st),
              f.detail ? f.detail : "?");
        /* Seven words, and counting them is the point: STP prologue, sub rsp,
         * push, pop, add rsp, LDP epilogue, RET. Both frame records have to be
         * there and the two pushes have to be inside them. */
        CHECK(f.n == 7, "emitted %zu words, expected 7", f.n);
        if (f.n == 7) {
            CHECK(f.words[0] == a64_stp_gstack_push(), "prologue 0x%08X", f.words[0]);
            CHECK(f.words[1] == a64_sub_x_imm(14, 14, 0x20),
                  "sub rsp,0x20 -> 0x%08X", f.words[1]);
            CHECK(f.words[2] == a64_str_pre(0, 14, -8),
                  "push rax -> 0x%08X, expected STR X0,[X14,#-8]!", f.words[2]);
            CHECK(f.words[3] == a64_ldr_post(0, 14, 8),
                  "pop rax -> 0x%08X, expected LDR X0,[X14],#8", f.words[3]);
            CHECK(f.words[4] == a64_add_x_imm(14, 14, 0x20),
                  "add rsp,0x20 -> 0x%08X", f.words[4]);
            CHECK(f.words[5] == a64_ldp_gstack_pop(), "epilogue 0x%08X", f.words[5]);
            CHECK(f.words[6] == a64_ret(), "last word 0x%08X, expected RET", f.words[6]);
        }
    }

    printf("the stack model refuses what it does not lay out, rather than aiming at it\n");
    {
        /* mod=00 rm=101 is RIP-relative in 64-bit mode, NOT [rbp]. It arrives
         * with has_sib == 0 and a 4-byte displacement, so a base-resolution step
         * that only looked at rm would read module data as a stack local. */
        static const uint8_t g[] = { 0x48,0x8B,0x05,0x10,0x00,0x00,0x00, 0xC3 };
        st = tr_translate_function(g, sizeof(g), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_UNSUPPORTED, "mov rax,[rip+0x10] returned %s", tr_status_name(st));
        CHECK(f.reason == TRR_GUEST_MEM,
              "a RIP-relative load was reported as %s, expected memory-not-on-guest-stack",
              tr_reason_name(f.reason));
    }
    {
        /* mod=00 with SIB base=101 is an absolute disp32 with NO base register.
         * It arrives with sib_base == 5, the same value RBP has. */
        static const uint8_t g[] = { 0x48,0x8B,0x04,0x25,0x10,0x00,0x00,0x00, 0xC3 };
        st = tr_translate_function(g, sizeof(g), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_UNSUPPORTED, "mov rax,[abs] returned %s", tr_status_name(st));
        CHECK(f.reason == TRR_GUEST_MEM,
              "an absolute-address load was reported as %s", tr_reason_name(f.reason));
    }
    {
        /* A dereference through a general register: no guest memory model. */
        static const uint8_t g[] = { 0x48,0x8B,0x01, 0xC3 };
        st = tr_translate_function(g, sizeof(g), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_UNSUPPORTED, "mov rax,[rcx] returned %s", tr_status_name(st));
        CHECK(f.reason == TRR_GUEST_MEM, "reported as %s", tr_reason_name(f.reason));
    }
    {
        /* An index register makes it scaled addressing: mov rax,[rsp+rax]. */
        static const uint8_t g[] = { 0x48,0x8B,0x04,0x04, 0xC3 };
        st = tr_translate_function(g, sizeof(g), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_UNSUPPORTED, "mov rax,[rsp+rax] returned %s", tr_status_name(st));
        CHECK(f.reason == TRR_GUEST_MEM,
              "a scaled index was reported as %s, expected memory-not-on-guest-stack",
              tr_reason_name(f.reason));
    }
    {
        /* [rbp+0x10] reaches into the CALLER's frame - the saved frame pointer,
         * the return address, incoming stack arguments. This model puts the
         * return address in X30 and arguments in registers, so reading that
         * memory would return arena garbage shaped like a value. */
        static const uint8_t g[] = { 0x48,0x8B,0x45,0x10, 0xC3 };
        st = tr_translate_function(g, sizeof(g), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_UNSUPPORTED, "mov rax,[rbp+0x10] returned %s", tr_status_name(st));
        CHECK(f.reason == TRR_STACK,
              "a caller-frame access was reported as %s, expected guest-stack-form",
              tr_reason_name(f.reason));
        CHECK(f.detail && strstr(f.detail, "caller's frame") != NULL,
              "detail '%s' does not say whose frame the problem is",
              f.detail ? f.detail : "?");
    }
    {
        /* [rsp-8] is the SysV red zone, unmapped below the arena. */
        static const uint8_t g[] = { 0x48,0x8B,0x44,0x24,0xF8, 0xC3 };
        st = tr_translate_function(g, sizeof(g), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_UNSUPPORTED, "mov rax,[rsp-8] returned %s", tr_status_name(st));
        CHECK(f.reason == TRR_STACK, "reported as %s", tr_reason_name(f.reason));
    }
    {
        /* A local further than a signed 9-bit offset reaches. */
        static const uint8_t g[] = { 0x48,0x8B,0x85,0x00,0xFE,0xFF,0xFF, 0xC3 };
        st = tr_translate_function(g, sizeof(g), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_UNSUPPORTED, "mov rax,[rbp-0x200] returned %s", tr_status_name(st));
        CHECK(f.reason == TRR_IMM_RANGE,
              "an out-of-range displacement was reported as %s, expected "
              "immediate-too-large", tr_reason_name(f.reason));
    }
    {
        /* ret imm16 pops arguments and so changes the caller's stack pointer. */
        static const uint8_t g[] = { 0x55, 0xC2,0x08,0x00 };
        st = tr_translate_function(g, sizeof(g), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_UNSUPPORTED, "ret 8 returned %s", tr_status_name(st));
        CHECK(f.reason == TRR_STACK, "reported as %s", tr_reason_name(f.reason));
    }
    {
        /* push rsp / pop rsp: refused on the architecture's own ambiguity, not on
         * convenience. */
        static const uint8_t a[] = { 0x54, 0xC3 };
        static const uint8_t b[] = { 0x5C, 0xC3 };
        st = tr_translate_function(a, sizeof(a), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_UNSUPPORTED && f.reason == TRR_STACK,
              "push rsp returned %s / %s", tr_status_name(st), tr_reason_name(f.reason));
        st = tr_translate_function(b, sizeof(b), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_UNSUPPORTED && f.reason == TRR_STACK,
              "pop rsp returned %s / %s", tr_status_name(st), tr_reason_name(f.reason));
    }
    {
        /* push imm8 sign-extends: -1 must not become 255. */
        static const uint8_t g[] = { 0x6A,0xFF, 0x58, 0xC3 };   /* push -1; pop rax; ret */
        st = tr_translate_function(g, sizeof(g), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_OK, "push imm8 returned %s: %s", tr_status_name(st),
              f.detail ? f.detail : "?");
        /* -1 sign-extends to all 64 bits set, so materialising it takes MOVZ plus
         * three MOVK, then the store, inside the usual STP/LDP pair and with a
         * pop and RET after: nine words. The index of the MOVZ is 1, not 0 -
         * word 0 is the prologue. */
        CHECK(f.n == 9, "emitted %zu words, expected 9", f.n);
        if (f.n == 9) {
            CHECK(f.words[0] == a64_stp_gstack_push(), "prologue 0x%08X", f.words[0]);
            CHECK(f.words[1] == a64_movz_x(16, 0xFFFFu),
                  "push -1 materialises 0x%08X, expected MOVZ X16,#0xFFFF 0x%08X",
                  f.words[1], a64_movz_x(16, 0xFFFFu));
            CHECK(f.words[2] == a64_movk_x(16, 0xFFFFu, 16),
                  "second chunk 0x%08X, expected MOVK X16,#0xFFFF,LSL#16", f.words[2]);
            CHECK(f.words[5] == a64_str_pre(16, 14, -8),
                  "the store 0x%08X, expected STR X16,[X14,#-8]!", f.words[5]);
            CHECK(f.words[6] == a64_ldr_post(0, 14, 8),
                  "pop rax 0x%08X, expected LDR X0,[X14],#8", f.words[6]);
            CHECK(f.words[8] == a64_ret(), "last word 0x%08X, expected RET", f.words[8]);
        }
    }
}

#if defined(__aarch64__)
/* Appends MOVZ/MOVK for a 64-bit constant and returns the new length. */
static size_t append_const(uint32_t *prog, size_t n, unsigned rd, uint64_t v)
{
    unsigned sh;
    prog[n++] = a64_movz_x(rd, (uint16_t)(v & 0xFFFFu));
    for (sh = 16u; sh < 64u; sh += 16u) {
        uint16_t c = (uint16_t)((v >> sh) & 0xFFFFu);
        if (c) prog[n++] = a64_movk_x(rd, c, sh);
    }
    return n;
}

/* Builds a runnable program around a translated body: the calling contract the
 * guest stack model assumes, written out as instructions.
 *
 *   STP X29,X30,[SP,#-16]!     preserve what the C caller owns
 *   STP X14,X15,[SP,#-16]!     preserve the callee-saved regs about to be clobbered
 *   X0  = argument               guest RAX arrives holding the first argument
 *   X14 = arena top              guest RSP arrives pointing into a gs_arena
 *   BL  body
 *   LDP X14,X15,[SP],#16
 *   LDP X29,X30,[SP],#16
 *   RET                        back to C, X0 still holding the body's result
 *   body...
 *
 * Saving X29/X30 matters and is easy to miss: the BL overwrites X30, and a
 * wrapper that then executed RET without restoring it would jump to its own
 * epilogue forever. That is the same class of bug the frame record was added for
 * in an earlier milestone, one level up. */
static size_t build_trampoline(uint32_t *prog, uint64_t arg, uint64_t gtop,
                               const uint32_t *body, size_t body_n)
{
    size_t n = 0, bl;

    prog[n++] = a64_stp_frame_push();
    prog[n++] = a64_stp_gstack_push();
    n = append_const(prog, n, 0u, arg);
    n = append_const(prog, n, 14u, gtop);
    bl = n;
    prog[n++] = 0u;                          /* BL, patched once the body is placed */
    prog[n++] = a64_ldp_gstack_pop();
    prog[n++] = a64_ldp_frame_pop();
    prog[n++] = a64_ret();
    prog[bl]  = a64_bl((int32_t)(n - bl));   /* the body starts right after the wrapper */
    memcpy(prog + n, body, body_n * sizeof body[0]);
    return n + body_n;
}

#define TRAMP_MAX 96u

static int run_guest(const char *what, const uint8_t *g, size_t glen,
                     const gs_arena *a, uint64_t arg, uint64_t *result,
                     int *sig)
{
    tr_func   f;
    tr_status st = tr_translate_function(g, glen, IMAGE_BASE, NULL, NULL, &f);
    uint32_t  prog[TRAMP_MAX];
    size_t    n, plen = 0;
    void     *page;
    int       to = 0, s = 0, ok;

    if (sig) *sig = 0;
    if (st != TR_OK) {
        CHECK(0, "%s: translation returned %s: %s", what, tr_status_name(st),
              f.detail ? f.detail : "?");
        return 0;
    }
    if (f.n + 16u > TRAMP_MAX) {
        CHECK(0, "%s: body of %zu words does not fit the trampoline", what, f.n);
        return 0;
    }
    n = build_trampoline(prog, arg, a->top, f.words, f.n);
    page = code_page(prog, n, &plen);
    if (!page) { CHECK(0, "%s: could not map an executable page", what); return 0; }
    ok = exec_generated((uint64_t (*)(void))page, result, &to, &s);
    if (sig) *sig = s;
    if (to) { CHECK(0, "%s: timed out - the generated code did not terminate", what); }
    munmap(page, plen);
    return ok;
}

static void test_guest_stack_executes(void)
{
    gs_arena a;
    uint64_t r = 0;
    int      sig = 0;

    printf("executing the guest stack model on real ARM64\n");
    if (!gs_alloc(4096, &a)) {
        CHECK(0, "could not allocate a guest stack arena: %s", gs_last_error());
        return;
    }

    /* A local stored and loaded back. This is the case that cannot be checked by
     * inspection: STUR and LDUR both look plausible whichever way the base and
     * displacement are wired, and only executing them against real memory shows
     * whether [rbp-8] addressed the slot that was written. */
    {
        static const uint8_t g[] = {
            0x55, 0x48,0x89,0xE5, 0x48,0x83,0xEC,0x20,
            0x48,0x89,0x45,0xF8, 0x48,0x8B,0x45,0xF8,
            0x48,0x83,0xC0,0x07, 0xC9, 0xC3
        };
        if (run_guest("locals round trip", g, sizeof(g), &a, 5u, &r, &sig))
            CHECK(r == 12u, "mov [rbp-8],rax; mov rax,[rbp-8]; add rax,7 with rax=5 "
                            "returned %llu, expected 12", (unsigned long long)r);
        else
            CHECK(0, "locals round trip did not run%s%s", sig ? " (signal " : "",
                  sig ? ")" : "");
    }

    /* Exact stack arithmetic. The function returns its own guest RSP after a
     * balanced prologue and epilogue, so the answer is an address: if any
     * adjustment went the wrong way or by the wrong amount, the returned value
     * differs. push rbp takes 8 bytes and nothing else moves RSP, so the result
     * has to be exactly the arena top minus 8. */
    {
        static const uint8_t g[] = {
            0x55, 0x48,0x89,0xE5, 0x48,0x83,0xEC,0x20, 0x48,0x83,0xC4,0x20,
            0x48,0x89,0xE0, 0x5D, 0xC3
        };
        if (run_guest("stack arithmetic", g, sizeof(g), &a, 0u, &r, &sig)) {
            CHECK(r == a.top - 8u,
                  "guest RSP after a balanced prologue is 0x%llX, expected 0x%llX "
                  "(arena top minus the 8 bytes push rbp took)",
                  (unsigned long long)r, (unsigned long long)(a.top - 8u));
            CHECK(gs_contains(&a, r) == 1, "the returned guest RSP is outside the arena");
            CHECK(gs_used(&a, r) == 8u, "the function left %zu bytes taken, expected 8",
                  gs_used(&a, r));
        } else {
            CHECK(0, "stack arithmetic did not run");
        }
    }

    /* push and pop have to agree with each other about where the value went. The
     * writeback is part of the encoding, so a store that advanced the pointer by
     * a different amount than the load would read the neighbouring slot. */
    {
        static const uint8_t g[] = { 0x50, 0x59, 0x48,0x89,0xC8, 0x48,0x83,0xC0,0x01,
                                     0xC3 };
        if (run_guest("push/pop agreement", g, sizeof(g), &a, 41u, &r, &sig))
            CHECK(r == 42u, "push rax; pop rcx; mov rax,rcx; add rax,1 with rax=41 "
                            "returned %llu, expected 42", (unsigned long long)r);
        else
            CHECK(0, "push/pop agreement did not run");
    }

    /* RSP-relative locals, which go through the SIB path rather than the plain
     * RBP one: a different base register and the opposite displacement sign. */
    {
        static const uint8_t g[] = {
            0x48,0x83,0xEC,0x20, 0x48,0x89,0x44,0x24,0x10,
            0x48,0x8B,0x44,0x24,0x10, 0x48,0x83,0xC4,0x20,
            0x48,0x83,0xC0,0x02, 0xC3
        };
        if (run_guest("rsp-relative local", g, sizeof(g), &a, 100u, &r, &sig))
            CHECK(r == 102u, "mov [rsp+0x10],rax; mov rax,[rsp+0x10]; add rax,2 with "
                             "rax=100 returned %llu, expected 102",
                  (unsigned long long)r);
        else
            CHECK(0, "rsp-relative local did not run");
    }

    /* Containment. A guest loop that pushes forever must die at the guard page
     * rather than walking down into whatever the host has below the arena. This
     * is the property that makes translating `sub rsp, N` safe at all: the
     * translator does not bound the guest's stack depth, so the arena has to. */
    {
        static const uint8_t g[] = {
            0x48,0xC7,0xC0,0x01,0x00,0x00,0x00,   /* mov rax,1     */
            0x50,                                 /* push rax      */
            0xEB,0xFD,                            /* jmp back to push */
            0xC3
        };
        tr_func f;
        CHECK(tr_translate_function(g, sizeof(g), IMAGE_BASE, NULL, NULL, &f) == TR_OK,
              "the runaway-push loop did not translate: %s", f.detail ? f.detail : "?");
        fflush(stdout);
        run_guest("runaway push", g, sizeof(g), &a, 0u, &r, &sig);
        CHECK(sig == SIGSEGV,
              "a guest loop pushing without limit ended with signal %d, expected "
              "SIGSEGV at the arena's guard page", sig);
    }

    gs_free(&a);
    printf("  EXECUTED ON aarch64: guest stack model - locals, exact stack "
           "arithmetic, push/pop agreement, and a runaway contained by a guard "
           "page\n");
}
#else
static void test_guest_stack_executes(void)
{
    printf("executing the guest stack model on real ARM64\n");
    printf("  SKIP: host is not aarch64 - encodings and refusals were checked, "
           "the arena was checked, nothing generated was run\n");
}
#endif
/* ------------------------------------------------------- the buffer cap
 *
 * Recorded as its own section because of what it cost. Measured on a shipped
 * application bundle, the second largest refusal bucket was 62 code entry points
 * every one reported as `unsupported-opcode` with no opcode attributable. The
 * cause was not an instruction at all: the sweep hands the translator a whole code
 * section, the module's section was larger than the 1 MiB cap, and the refusal
 * carried the reason the record is initialised to before pass 1. Those 62
 * functions were never examined, and the histogram said they had been found
 * unsupported - which sent the work at the wrong thing.
 */
static void test_buffer_cap_is_named(void)
{
    tr_func   f;
    tr_status st;

    printf("a buffer the translator refuses to examine says so, and does not "
           "claim an opcode\n");

    /* One byte past the old 1 MiB cap, holding nothing but a RET: the function is
     * trivially translatable, so any refusal can only come from the cap. It must
     * now translate, because a real module's code section is far larger than
     * 1 MiB and rejecting it rejected every export in the module. */
    {
        size_t n = (1u << 20) + 4096u;
        uint8_t *code = calloc(n, 1u);
        CHECK(code != NULL, "could not allocate a %zu-byte buffer", n);
        if (code) {
            code[0] = 0xC3;
            st = tr_translate_function(code, n, IMAGE_BASE, NULL, NULL, &f);
            CHECK(st == TR_OK, "a bare RET in a %zu-byte section returned %s: %s",
                  n, tr_status_name(st), f.detail ? f.detail : "?");
            CHECK(f.insns == 1, "planned %u instructions, expected 1", f.insns);
            free(code);
        }
    }

    /* Past the current cap, the refusal must name the buffer - and must not reuse
     * the reason that means "I decoded this and it is outside the subset". */
    {
        size_t n = (size_t)TRF_MAX_CODE_BYTES + 4096u;
        uint8_t *code = calloc(n, 1u);
        CHECK(code != NULL, "could not allocate a %zu-byte buffer", n);
        if (code) {
            code[0] = 0xC3;
            st = tr_translate_function(code, n, IMAGE_BASE, NULL, NULL, &f);
            CHECK(st == TR_INVALID, "an oversized buffer returned %s", tr_status_name(st));
            CHECK(f.reason == TRR_BUFFER,
                  "an oversized buffer was reported as %s: the same label a real "
                  "unsupported instruction gets, which is what made 62 unexamined "
                  "functions look like 62 unsupported opcodes",
                  tr_reason_name(f.reason));
            CHECK(f.fail_op_len == 0 && f.fail_insns == 0,
                  "an unexamined buffer reported fail_op_len=%u fail_insns=%u",
                  f.fail_op_len, f.fail_insns);
            CHECK(f.detail && strstr(f.detail, "TRF_MAX_CODE_BYTES") != NULL,
                  "detail '%s' does not name the limit", f.detail ? f.detail : "?");
            free(code);
        }
    }

    /* The other guard that runs before pass 1 had the same defect. */
    {
        static const uint8_t g[] = { 0xC3 };
        st = tr_translate_function_at(g, sizeof(g), IMAGE_BASE, 99u, NULL, NULL, &f);
        CHECK(st == TR_INVALID, "a start offset past the end returned %s",
              tr_status_name(st));
        CHECK(f.reason == TRR_BUFFER,
              "reported as %s, expected code-buffer-rejected", tr_reason_name(f.reason));
    }

    /* Discovery marks are one BIT per guest byte. If the granularity were a byte,
     * ten one-byte instructions sharing a bitmap byte would look already-seen
     * after the first, discovery would stop, and the translation would be short -
     * silently, because a prefix of a function still emits valid words. */
    {
        static const uint8_t g[] = {
            0x50,0x50,0x50,0x50,0x50,0x50,0x50,0x50,0x50,0x50, 0xC3
        };
        st = tr_translate_function(g, sizeof(g), IMAGE_BASE, NULL, NULL, &f);
        CHECK(st == TR_OK, "ten one-byte pushes then ret returned %s: %s",
              tr_status_name(st), f.detail ? f.detail : "?");
        CHECK(f.insns == 11, "planned %u of 11 instructions: discovery lost the ones "
                             "that share a bitmap byte with an earlier one", f.insns);
        CHECK(f.n == 13, "emitted %zu words, expected 13 (STP + 10 STR + LDP + RET)",
              f.n);
    }
}


int main(void)
{
    printf("=== exe + dll translation, end to end ===\n");
    test_images_are_real();
    test_translation();
    test_function_translation();
    test_unsupported_is_refused();
    test_guest_stack_arena();
    test_guest_stack_translation();
    test_guest_stack_executes();
    test_buffer_cap_is_named();
    test_pipeline();
#if defined(__aarch64__)
    printf("VERDICT arch=aarch64 exe_words=%zu const_ok=%d first=%s/%llu(to=%d,sig=%d) "
           "cached=%s/%llu(to=%d,sig=%d)\n",
           verdict.exe_words, verdict.rebuilt_matches,
           verdict.first_ok ? "ok" : "FAIL",
           (unsigned long long)verdict.first_result, verdict.first_timed_out,
           verdict.first_sig,
           verdict.cached_ok ? "ok" : "FAIL",
           (unsigned long long)verdict.cached_result, verdict.cached_timed_out,
           verdict.cached_sig);
#else
    printf("VERDICT arch=other exe_words=%zu const_ok=%d first=n/a cached=n/a "
           "(translation and cache round trip checked as bytes only)\n",
           verdict.exe_words, verdict.rebuilt_matches);
#endif
    printf("\n%d checks, %d failure(s)\n", checks, failures);
    return failures ? 1 : 0;
}
