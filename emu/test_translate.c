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
 *   mini.dll  AddThree(rcx) -> rax        app.exe  entry() -> rax
 *     add rcx, 3                            mov rcx, 42
 *     mov rax, rcx                          call [rip -> IAT for AddThree]
 *     ret                                   add rax, 1
 *                                           ret
 *
 * 42 + 3 + 1 = 46, asserted on real ARM64 hardware and under QEMU.
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

#include "a64_emit.h"
#include "pe_load.h"
#include "ptc.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

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

/* guest code: mini.dll!AddThree */
static const uint8_t DLL_CODE[] = {
    0x48, 0x83, 0xC1, 0x03,          /* add rcx, 3            */
    0x48, 0x89, 0xC8,                /* mov rax, rcx          */
    0xC3                             /* ret                   */
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
static void bzero(buf *f, size_t n)
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
    bzero(o, 0x3Cu - 2u);            /* e_lfanew lives at 0x3C */
    bu32(o, 0x80u);
    bzero(o, 0x80u - btell(o));      /* DOS stub */

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

    bzero(o, HDR_SIZE - btell(o));
}

/* mini.dll: one export, AddThree, pointing at the code. */
static buf build_dll(void)
{
    buf o, rd;
    size_t exp_dir, aof, aon, aoo, nameA, nameDll;
    memset(&o, 0, sizeof(o)); memset(&rd, 0, sizeof(rd));

    exp_dir = btell(&rd); bzero(&rd, 40);
    aof     = btell(&rd); bu32(&rd, TEXT_VA);          /* AddThree's RVA */
    aon     = btell(&rd); bzero(&rd, 4);               /* patched below */
    aoo     = btell(&rd); bu16(&rd, 0);
    nameA   = btell(&rd); bstr(&rd, "AddThree");
    nameDll = btell(&rd); bstr(&rd, "mini.dll");
    bp32(&rd, aon, (uint32_t)(RDATA_VA + nameA));
    bp32(&rd, exp_dir + 12u, (uint32_t)(RDATA_VA + nameDll));  /* Name */
    bp32(&rd, exp_dir + 16u, 1u);                              /* Base */
    bp32(&rd, exp_dir + 20u, 1u);                              /* NumberOfFunctions */
    bp32(&rd, exp_dir + 24u, 1u);                              /* NumberOfNames */
    bp32(&rd, exp_dir + 28u, (uint32_t)(RDATA_VA + aof));
    bp32(&rd, exp_dir + 32u, (uint32_t)(RDATA_VA + aon));
    bp32(&rd, exp_dir + 36u, (uint32_t)(RDATA_VA + aoo));

    write_headers(&o, 1, RDATA_VA, 40u, 0u, 0u, (uint32_t)rd.len);
    bput(&o, DLL_CODE, sizeof(DLL_CODE));
    bzero(&o, 0x200u - sizeof(DLL_CODE));
    bput(&o, rd.b, rd.len);
    bzero(&o, 0x200u - rd.len);
    bzero(&o, 0x200u);
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
    ibn   = btell(&rd); bu16(&rd, 0x0042); bstr(&rd, "AddThree");
    nmDll = btell(&rd); bstr(&rd, "mini.dll");
    bzero(&rd, 8u - (btell(&rd) % 8u));        /* align the descriptor array */
    desc  = btell(&rd);
    bu32(&rd, (uint32_t)(RDATA_VA + ilt));     /* OriginalFirstThunk (names) */
    bu32(&rd, 0);                              /* TimeDateStamp */
    bu32(&rd, 0xFFFFFFFFu);                    /* ForwarderChain */
    bu32(&rd, (uint32_t)(RDATA_VA + nmDll));   /* Name */
    bu32(&rd, (uint32_t)(RDATA_VA + iat));     /* FirstThunk (the IAT) */
    bzero(&rd, 20);                            /* terminating descriptor */
    bp32(&rd, ilt, (uint32_t)(RDATA_VA + ibn));

    /* mov rcx, 42 ; call [rip -> IAT] ; add rax, 1 ; ret */
    code[0]=0x48; code[1]=0xC7; code[2]=0xC1;
    code[3]=0x2A; code[4]=0x00; code[5]=0x00; code[6]=0x00;
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
    bzero(&o, 0x200u - sizeof(code));
    bput(&o, rd.b, rd.len);
    bzero(&o, 0x200u - rd.len);
    bzero(&o, 0x200u);
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
    CHECK(pd.num_exports == 1, "dll exports %u, expected 1", pd.num_exports);
    CHECK(pd.exports[0].name && strcmp(pd.exports[0].name, "AddThree") == 0,
          "export name '%s'", pd.exports[0].name ? pd.exports[0].name : "(null)");
    CHECK(pd.exports[0].rva == TEXT_VA, "export rva %08x", pd.exports[0].rva);
    CHECK(pd.exports[0].forwarded == 0, "export reported as a forwarder");

    CHECK(px.num_dlls == 1, "exe imports from %u dll(s), expected 1", px.num_dlls);
    CHECK(px.dlls[0].dll_name && strcmp(px.dlls[0].dll_name, "mini.dll") == 0,
          "imported dll '%s'", px.dlls[0].dll_name ? px.dlls[0].dll_name : "(null)");
    CHECK(px.funcs[0].name && strcmp(px.funcs[0].name, "AddThree") == 0,
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

    /* With the import resolved, the call target becomes a constant and the whole
     * entry point translates. */
    memset(&rs, 0, sizeof(rs));
    rs.iat_guest_va = IMAGE_BASE + EXE_IAT_RVA;
    rs.host_addr = 0x00000000DEADB000ULL;   /* two non-zero 16-bit chunks */
    st = tr_translate_run(exe.b + HDR_SIZE, 18u, IMAGE_BASE + TEXT_VA,
                          resolve_cb, &rs, &o);
    CHECK(st == TR_OK, "exe translation returned %s: %s", tr_status_name(st),
          o.detail ? o.detail : "?");
    CHECK(rs.queries == 1, "resolver queried %d times, expected 1", rs.queries);
    /* mov rcx,42 (1) + movz x16 + movk x16 lsl32 + blr x16 (3) + add rax,1 + ret */
    CHECK(o.n == 6, "exe emitted %zu words, expected 6", o.n);
    CHECK(o.guest_insns == 4, "exe translated %u instructions, expected 4",
          o.guest_insns);
    if (o.n == 6) {
        CHECK(o.words[0] == a64_movz_x(1, 42), "mov rcx,42 -> 0x%08X", o.words[0]);
        CHECK(o.words[0] == 0xD2800541u, "movz x1,#42 encoding drifted");
        CHECK(o.words[1] == a64_movz_x(16, 0xB000u), "low chunk -> 0x%08X", o.words[1]);
        /* 0x00000000DEADB000: 0xB000 occupies bits 15:0 and 0xDEAD bits 31:16,
         * so the keep belongs at LSL #16. Deriving the chunk position from the
         * value rather than assuming it is the point of pinning the encoding. */
        CHECK(o.words[2] == a64_movk_x(16, 0xDEADu, 16), "high chunk -> 0x%08X",
              o.words[2]);
        CHECK(o.words[3] == a64_blr(16), "blr -> 0x%08X", o.words[3]);
        CHECK(o.words[4] == 0x91000400u, "add x0,x0,#1 -> 0x%08X", o.words[4]);
        CHECK(o.words[5] == 0xD65F03C0u, "ret -> 0x%08X", o.words[5]);
    }

    free(dll.b); free(exe.b);
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

/* Runs the whole pipeline: load, resolve, translate, execute, persist, reload. */
static void test_pipeline(void)
{
    buf dll = build_dll(), exe = build_exe();
    pe_image pd, px;
    ptc_cache *cache;
    uint64_t dll_mid = 0, exe_mid = 0;
    tr_output od, ox;
    resolver  rs;
    uint64_t  dll_va, exe_va, iat_va;
    int       saved = 0;

    printf("the whole pipeline, ending in the persistent cache\n");
    mark("parsing both images");

    CHECK(pe_load(dll.b, dll.len, &pd) == PE_OK, "dll parse");
    CHECK(pe_load(exe.b, exe.len, &px) == PE_OK, "exe parse");
    dll_va = pd.image_base + pd.exports[0].rva;
    exe_va = px.image_base + px.entry_rva;
    iat_va = px.image_base + px.dlls[0].iat_rva;

    mark("translating mini.dll!AddThree");
    /* Translate the DLL first: a loader resolves imports before running code,
     * which is what makes the call target a constant here. */
    CHECK(tr_translate_run(DLL_CODE, sizeof(DLL_CODE), dll_va, NULL, NULL, &od)
          == TR_OK, "dll did not translate");

    cache = ptc_create(PTC_ISA_AARCH64, PTC_ISA_X86_64, 4096u);
    CHECK(cache != NULL, "ptc_create failed");
    if (!cache) { free(dll.b); free(exe.b); return; }
    CHECK(ptc_add_module(cache, "mini.dll", dll.len, 1u,
                         ptc_hash_bytes(dll.b, dll.len), &dll_mid) == 0,
          "could not register mini.dll");

#if defined(__aarch64__)
    {
        size_t map_len = 0;
        void *dll_host;
        mark("mapping the translated dll");
        dll_host = code_page(od.words, od.n, &map_len);
        CHECK(dll_host != NULL, "could not map an executable page for the dll");
        if (!dll_host) { ptc_free(cache); free(dll.b); free(exe.b); return; }

        memset(&rs, 0, sizeof(rs));
        rs.iat_guest_va = iat_va;
        rs.host_addr = (uint64_t)(uintptr_t)dll_host;   /* the real host address */
        CHECK(tr_translate_run(exe.b + HDR_SIZE, 18u, exe_va, resolve_cb, &rs, &ox)
              == TR_OK, "exe did not translate once the import was resolved");
        /* The word count depends on how many 16-bit chunks of the real host
         * address happen to be non-zero, so asserting a fixed count would fail
         * for a reason that is not a bug. Assert the shape, and reconstruct the
         * constant from the emitted MOVZ/MOVK words to prove it round-trips. */
        verdict.exe_words = ox.n;
        CHECK(ox.n >= 5u && ox.n <= 8u, "exe emitted %zu words, expected 5..8", ox.n);
        if (ox.n >= 5u) {
            size_t k;
            uint64_t rebuilt = 0;
            CHECK(ox.words[0] == a64_movz_x(1, 42), "mov rcx,42 -> 0x%08X",
                  ox.words[0]);
            CHECK(ox.words[ox.n - 3u] == a64_blr(16), "blr -> 0x%08X",
                  ox.words[ox.n - 3u]);
            CHECK(ox.words[ox.n - 2u] == a64_add_x_imm(0, 0, 1),
                  "add rax,1 -> 0x%08X", ox.words[ox.n - 2u]);
            CHECK(ox.words[ox.n - 1u] == a64_ret(), "ret -> 0x%08X",
                  ox.words[ox.n - 1u]);
            for (k = 1u; k + 3u < ox.n; k++) {
                uint32_t w = ox.words[k];
                unsigned rd = w & 31u;
                uint16_t chunk = (uint16_t)((w >> 5) & 0xFFFFu);
                unsigned hw = (w >> 21) & 3u;
                CHECK(rd == 16u, "constant word %zu targets X%u, expected X16", k, rd);
                if ((w & 0xFF800000u) == 0xD2800000u) {
                    rebuilt = chunk;                       /* MOVZ: hw must be 0 */
                    CHECK(hw == 0u, "MOVZ used hw=%u", hw);
                } else if ((w & 0xFF800000u) == 0xF2800000u) {
                    rebuilt |= (uint64_t)chunk << (hw * 16u);
                } else {
                    CHECK(0, "word %zu is neither MOVZ nor MOVK: 0x%08X", k, w);
                }
            }
            verdict.rebuilt_matches = (rebuilt == rs.host_addr);
            CHECK(rebuilt == rs.host_addr,
                  "emitted constant materialises 0x%llx, not the dll host address "
                  "0x%llx - the call would jump somewhere else",
                  (unsigned long long)rebuilt, (unsigned long long)rs.host_addr);
        }

        mark("translating the exe against the resolved import");
        /* Persist both translations, keyed by module identity and guest bytes. */
        CHECK(ptc_insert(cache, dll_mid, dll_va, DLL_CODE, (uint32_t)sizeof(DLL_CODE),
                         od.words, (uint32_t)(od.n * 4u), 0u) == 0,
              "could not cache the dll block");
        CHECK(ptc_add_module(cache, "app.exe", exe.len, 1u,
                             ptc_hash_bytes(exe.b, exe.len), &exe_mid) == 0,
              "could not register app.exe");
        CHECK(ptc_insert(cache, exe_mid, exe_va, exe.b + HDR_SIZE, 18u,
                         ox.words, (uint32_t)(ox.n * 4u), 0u) == 0,
              "could not cache the exe block");
        mark("saving the cache");
        saved = (ptc_save(cache, CACHE_PATH) == 0);
        CHECK(saved, "ptc_save failed");

        mark("mapping and executing the translated exe");
        {
            uint64_t (*entry)(void) = (uint64_t (*)(void))
                code_page(ox.words, ox.n, NULL);
            CHECK(entry != NULL, "could not map the executable entry page");
            if (entry) {
                uint64_t r = 0;
                int      to = 0, sig = 0, ok;
                mark("calling the generated entry point (child, 5s alarm)");
                ok = exec_generated(entry, &r, &to, &sig);
                verdict.executed_at_all = 1;
                verdict.first_ok = ok;
                verdict.first_timed_out = to;
                verdict.first_sig = sig;
                verdict.first_result = r;
                mark("the generated entry point returned control");
                CHECK(ok, "executing the translated exe failed%s%s",
                      to ? ": it did not terminate within 5s" : "",
                      (!ok && !to && sig) ? ": killed by a signal" : "");
                if (!ok && sig)
                    printf("  terminated by signal %d%s\n", sig,
                           to ? " (SIGALRM: the generated code never returned)" : "");
                CHECK(ok && r == 46u, "entry() returned %llu, expected 46 (42+3+1)",
                      (unsigned long long)r);
                if (ok)
                    printf("  EXECUTED ON aarch64: app.exe entry -> %llu, having called "
                           "mini.dll!AddThree through its import table\n",
                           (unsigned long long)r);
            }
        }
        ptc_free(cache);
        cache = NULL;

        /* Now the point of persisting: reopen the cache and run the stored host
         * code without translating anything again. */
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
                host = ptc_lookup(re, rx_id, exe_va, exe.b + HDR_SIZE, 18u, &clen);
                CHECK(host != NULL, "the exe block missed the reopened cache");
                CHECK(clen == (uint32_t)(ox.n * 4u),
                      "reloaded %u bytes of host code, expected %zu",
                      clen, ox.n * 4u);
                if (host && clen == ox.n * 4u && memcmp(host, ox.words, clen) == 0) {
                    uint64_t (*e2)(void) = (uint64_t (*)(void))
                        code_page((const uint32_t *)host, ox.n, NULL);
                    CHECK(e2 != NULL, "could not map the reloaded code");
                    if (e2) {
                        uint64_t r2 = 0;
                        int to2 = 0, sig2 = 0;
                        mark("executing the host code reloaded from the cache");
                        if (exec_generated(e2, &r2, &to2, &sig2)) {
                            verdict.cached_ok = 1;
                            verdict.cached_result = r2;
                            CHECK(r2 == 46u,
                                  "code loaded from the cache returned %llu, expected 46",
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
                host = ptc_lookup(re, rd_id, dll_va, DLL_CODE,
                                  (uint32_t)sizeof(DLL_CODE), &clen);
                CHECK(host != NULL, "the dll block missed the reopened cache");
                CHECK(ptc_record_count(re) == 2, "reopened cache holds %zu records",
                      ptc_record_count(re));
                ptc_free(re);
            }
            remove(CACHE_PATH);
        }
    }
#else
    (void)dll_mid; (void)exe_mid; (void)saved;
    /* Off ARM64 the translations are still checked word for word, and the cache
    * round trip is still checked as bytes - only execution is unavailable. */
    mark("translating app.exe against a synthetic host address");
    memset(&rs, 0, sizeof(rs));
    rs.iat_guest_va = iat_va;
    rs.host_addr = 0x00000000DEADB000ULL;
    CHECK(tr_translate_run(exe.b + HDR_SIZE, 18u, exe_va, resolve_cb, &rs, &ox)
          == TR_OK, "exe did not translate");
    /* Fill the verdict off ARM64 too, so the line means the same thing on every
     * host instead of reporting zeros that were never measured. */
    verdict.exe_words = ox.n;
    {
        size_t k; uint64_t rebuilt = 0;
        for (k = 1u; k + 3u < ox.n; k++) {
            uint32_t w = ox.words[k];
            uint16_t chunk = (uint16_t)((w >> 5) & 0xFFFFu);
            unsigned hw = (w >> 21) & 3u;
            if ((w & 0xFF800000u) == 0xD2800000u) rebuilt = chunk;
            else if ((w & 0xFF800000u) == 0xF2800000u)
                rebuilt |= (uint64_t)chunk << (hw * 16u);
        }
        verdict.rebuilt_matches = (rebuilt == rs.host_addr);
        CHECK(verdict.rebuilt_matches,
              "emitted constant materialises 0x%llx, not 0x%llx",
              (unsigned long long)rebuilt, (unsigned long long)rs.host_addr);
    }
    CHECK(ptc_insert(cache, dll_mid, dll_va, DLL_CODE, (uint32_t)sizeof(DLL_CODE),
                     od.words, (uint32_t)(od.n * 4u), 0u) == 0,
          "could not cache the dll block");
    CHECK(ptc_add_module(cache, "app.exe", exe.len, 1u,
                         ptc_hash_bytes(exe.b, exe.len), &exe_mid) == 0,
          "could not register app.exe");
    CHECK(ptc_insert(cache, exe_mid, exe_va, exe.b + HDR_SIZE, 18u,
                     ox.words, (uint32_t)(ox.n * 4u), 0u) == 0,
          "could not cache the exe block");
    mark("saving the cache");
    saved = (ptc_save(cache, CACHE_PATH) == 0);
    CHECK(saved, "ptc_save failed");
    if (saved) {
        ptc_open_result why = PTC_OPEN_OK;
        ptc_cache *re;
        mark("reopening the cache");
        re = ptc_open(CACHE_PATH, PTC_ISA_AARCH64, PTC_ISA_X86_64, &why);
        CHECK(re != NULL, "could not reopen the cache");
        if (re) {
            uint32_t clen = 0;
            const void *host = ptc_lookup(re, exe_mid, exe_va, exe.b + HDR_SIZE,
                                          18u, &clen);
            CHECK(host != NULL && clen == (uint32_t)(ox.n * 4u) &&
                  memcmp(host, ox.words, clen) == 0,
                  "the exe block did not survive the cache round trip as bytes");
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

int main(void)
{
    printf("=== exe + dll translation, end to end ===\n");
    test_images_are_real();
    test_translation();
    test_unsupported_is_refused();
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
