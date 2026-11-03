#ifndef _DEFAULT_SOURCE
#define _DEFAULT_SOURCE   /* MAP_ANONYMOUS: glibc hides it without this,
                         * and it differs between glibc versions, so the
                         * omission compiles on one host and not another */
#endif

/* prewarm - runs the pre-translation sweep and reports progress honestly.
 *
 *   prewarm [--cache <path>] [--idle-ms <n>] [--max-seconds <n>] <file> [<file>...]
 *
 * --idle-ms models the screen-off window rather than pretending it does not
 * exist. Each window is a time budget: when it expires the sweep yields, prints
 * where it got to, and the next window resumes from exactly that point. That is
 * the shape the Android side will have under WorkManager with
 * setRequiresDeviceIdle, and it is why the percentage and the remaining-time
 * estimate are worth printing at all - they are what a background job reports to
 * whoever is watching it.
 *
 * The percentage is marked with '~' while it is provisional. During discovery
 * the denominator grows as the worklist drains, so it can move backwards; that
 * is the truth about static discovery and it is flagged instead of smoothed.
 * During translation the block count is known and the number is exact.
 *
 * The remaining-time estimate is extrapolated from the rate observed in the
 * current phase. It assumes the work left costs what the work so far cost, which
 * is not guaranteed - blocks vary in size and some paths refuse immediately. It
 * is an estimate and is labelled as one.
 */
#define _POSIX_C_SOURCE 200809L

#include "sweep.h"
#include "shim.h"

#include "translate.h"

#include "pe_load.h"
#include "ptc.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <ucontext.h>
#include <time.h>

#define MAX_IMAGE (256u * 1024u * 1024u)

/* Why an entry point is not inside translatable code. Separate counters, because
 * a module whose exports are data, a section the loader would not mark
 * executable, and a section whose raw data is shorter than its virtual size all
 * collapse into the sweep's single "not in code" refusal. */
typedef struct {
    uint32_t total;
    uint32_t in_code;
    uint32_t no_section;      /* the RVA is inside no section at all */
    uint32_t not_executable;  /* inside a section not marked executable */
    uint32_t past_raw;        /* inside an executable section's zero-filled tail */
    uint32_t zero_bytes;      /* in code, but the first byte is 0x00 */
} entry_diag;
#define MAX_MODULES 256   /* a real application bundle can carry this many */

static uint64_t now_ns(void)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) return 0;
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}

/* ---- the idle window --------------------------------------------------- */

typedef struct {
    uint64_t deadline_ns;
    int      expired;
} window;

static int window_stop(void *user)
{
    window *w = user;
    if (now_ns() >= w->deadline_ns) { w->expired = 1; return 1; }
    return 0;
}

/* ---- formatting -------------------------------------------------------- */

static void fmt_duration(char *out, size_t n, uint64_t ns)
{
    double s = (double)ns / 1e9;
    if (ns == 0)          snprintf(out, n, "0s");
    else if (s < 1.0)     snprintf(out, n, "%.0fms", s * 1e3);
    else if (s < 60.0)    snprintf(out, n, "%.1fs", s);
    else if (s < 3600.0)  snprintf(out, n, "%.1fm", s / 60.0);
    else                  snprintf(out, n, "%.1fh", s / 3600.0);
}

static void print_progress(const sweep_progress *p, int window_closed)
{
    char eta[32], elapsed[32];
    fmt_duration(eta, sizeof(eta), p->eta_ns);
    fmt_duration(elapsed, sizeof(elapsed), p->elapsed_ns);
    printf("[%s%-9s] %5.1f%%%s  remaining ~%-7s  blocks=%-7u pending=%-7u "
           "rate=%.0f/s  elapsed %s%s\n",
           window_closed ? "yield " : "      ",
           sweep_phase_name(p->phase),
           (double)p->percent_x10 / 10.0,
           p->provisional ? "~" : " ",
           eta, p->blocks, p->worklist_pending, p->blocks_per_sec, elapsed,
           p->provisional ? "   (provisional: discovery still growing)" : "");
    fflush(stdout);
}

static void print_summary(const sweep_progress *p, const ptc_cache *cache,
                          const sweep_job *job)
{
    char elapsed[32];
    double pct_t;
    fmt_duration(elapsed, sizeof(elapsed), p->elapsed_ns);
    pct_t = p->functions_attempted
          ? 100.0 * (double)p->functions_translated / (double)p->functions_attempted
          : 0.0;

    printf("\n--- pre-translation summary ---\n");
    printf("modules registered:        %u\n", p->modules);
    printf("entry points queued:       %u\n", p->entry_points);
    printf("blocks discovered:         %u\n", p->blocks);
    printf("guest bytes decoded:       %llu\n", (unsigned long long)p->guest_bytes);
    printf("decode calls:              %llu\n", (unsigned long long)p->decode_calls);
    printf("functions attempted:       %u\n", p->functions_attempted);
    printf("functions pre-translated:  %u  (%.2f%% of attempted)\n",
           p->functions_translated, pct_t);
    printf("functions refused:         %u\n", p->functions_refused);
    printf("  of those, needing a guest stack arena at call time: %u\n",
           p->functions_needing_gstack);
    printf("  refused at the entry point's first instruction: %u\n",
           p->refused_at_first_insn);
    printf("  refused after translating further in:           %u (deepest: %u "
           "instructions)\n", p->refused_deeper, p->deepest_refusal);
    printf("ARM64 code written:        %llu bytes\n",
           (unsigned long long)p->host_code_bytes);
    printf("indirect branches unresolved: %u\n", p->indirect_unresolved);
    printf("decode refusals:           %u\n", p->decode_refusals);
    printf("elapsed:                   %s\n", elapsed);
    if (cache)
        printf("cache records:             %zu   code bytes: %zu\n",
               ptc_record_count(cache), ptc_code_bytes(cache));

    {
        uint32_t rank;
        printf("\nWhat the coverage number means: a function is cached only when a\n"
               "provably correct ARM64 translation exists for all of it. Anything\n"
               "else is counted and deliberately NOT cached, because a placeholder\n"
               "would later be served as a cache hit and executed, and nothing\n"
               "downstream could detect it.\n");
        printf("\nWhat is blocking the rest, ranked - this is the work queue, not\n"
               "a complaint:\n");
        for (rank = 0; rank < 12; rank++) {
            uint8_t m = 0, op = 0;
            uint32_t c = sweep_top_opcode(job, rank, &m, &op);
            if (!c) break;
            printf("  %4u function(s) stopped at opcode %s%02X\n", c,
                   m == 1 ? "0F " : (m == 2 ? "0F38 " : (m == 3 ? "0F3A " : "")), op);
        }
        for (rank = 0; rank < TRR_COUNT; rank++) {
            uint32_t c = sweep_reason_count(job, (tr_reason)rank);
            if (c) printf("  %4u refused: %s\n", c, tr_reason_name((tr_reason)rank));
        }
    }
    printf("Indirect branches (%u) are not knowable statically and stay cold;\n"
           "they are translated at run time. This warms the cache, it does not\n"
           "replace the JIT.\n", p->indirect_unresolved);
}

/* ---- file reading ------------------------------------------------------ */

static int read_file(const char *path, uint8_t **out, size_t *out_len,
                     uint64_t *out_mtime)
{
    FILE      *fp;
    struct stat sb;
    uint8_t   *b;
    long       sz;

    fp = fopen(path, "rb");
    if (!fp) { printf("  skip %s: cannot open\n", path); return 0; }
    if (fseek(fp, 0, SEEK_END) != 0) { fclose(fp); return 0; }
    sz = ftell(fp);
    rewind(fp);
    if (sz < 0 || (unsigned long)sz > MAX_IMAGE) {
        printf("  skip %s: size %ld out of range\n", path, sz);
        fclose(fp);
        return 0;
    }
    b = malloc((size_t)sz ? (size_t)sz : 1u);
    if (!b) { fclose(fp); return 0; }
    if (sz > 0 && fread(b, 1, (size_t)sz, fp) != (size_t)sz) {
        printf("  skip %s: short read\n", path);
        free(b); fclose(fp);
        return 0;
    }
    fclose(fp);
    *out = b;
    *out_len = (size_t)sz;
    *out_mtime = (stat(path, &sb) == 0) ? (uint64_t)sb.st_mtime : 0u;
    return 1;
}

/* Classifies one entry point against the module's own section table. This is the
 * same test the sweep applies, spelled out, so that "not in code" stops being a
 * single opaque bucket. */
static void diagnose_entry(const pe_image *im, const uint8_t *img, size_t img_len,
                           uint32_t rva, entry_diag *d, const char *label)
{
    uint32_t i;
    d->total++;
    for (i = 0; i < im->num_sections; i++) {
        const pe_section *s = &im->sections[i];
        if (s->virtual_size == 0 || rva < s->virtual_addr) continue;
        if (rva - s->virtual_addr >= s->virtual_size) continue;
        if (!(s->characteristics & PE_SCN_MEM_EXECUTE)) {
            d->not_executable++;
            printf("    %-22s rva=%08X  section %-9s NOT EXECUTABLE [0x%08X]\n",
                   label, rva, s->name, s->characteristics);
            return;
        }
        if (rva - s->virtual_addr >= s->raw_size) {
            d->past_raw++;
            printf("    %-22s rva=%08X  section %-9s PAST RAW DATA "
                   "(raw %u < vsize %u)\n", label, rva, s->name, s->raw_size,
                   s->virtual_size);
            return;
        }
        {
            size_t off = (size_t)s->raw_ptr + (rva - s->virtual_addr);
            if (img && off < img_len && img[off] == 0x00) {
                d->zero_bytes++;
                printf("    %-22s rva=%08X  section %-9s first byte is 0x00\n",
                       label, rva, s->name);
                return;
            }
        }
        d->in_code++;
        return;
    }
    d->no_section++;
    printf("    %-22s rva=%08X  IN NO SECTION\n", label, rva);
}

static void diagnose_module(const char *path, const uint8_t *img, size_t img_len,
                            const pe_image *im)
{
    entry_diag d;
    uint32_t i, shown = 0;
    char lbl[24];
    memset(&d, 0, sizeof(d));

    printf("  --- %s ---\n", path);
    printf("    %s %s  sections=%u  exports=%u%s\n",
           im->is_dll ? "DLL" : "exe", pe_machine_name(im->machine),
           im->num_sections, im->num_exports,
           im->exports_truncated ? "  (CAPPED at PE_EXPORT_MAX)" : "");
    for (i = 0; i < im->num_sections; i++) {
        const pe_section *s = &im->sections[i];
        printf("      %-9s va=%08X vsize=%08X raw=%08X/%08X %c%c%c%s\n",
               s->name, s->virtual_addr, s->virtual_size, s->raw_ptr, s->raw_size,
               (s->characteristics & PE_SCN_MEM_READ) ? 'R' : '-',
               (s->characteristics & PE_SCN_MEM_WRITE) ? 'W' : '-',
               (s->characteristics & PE_SCN_MEM_EXECUTE) ? 'X' : '-',
               (s->characteristics & PE_SCN_CNT_CODE) ? " CODE" : "");
    }
    if (im->entry_rva) {
        diagnose_entry(im, img, img_len, im->entry_rva, &d, "entry");
        shown = 1;
    }
    for (i = 0; i < im->num_exports; i++) {
        if (im->exports[i].forwarded || im->exports[i].rva == 0) continue;
        /* Print the first few refusals in full; a real module can have hundreds
         * and repeating the same line proves nothing after the third. */
        if (shown < 8) {
            snprintf(lbl, sizeof(lbl), "%s",
                     im->exports[i].name ? im->exports[i].name : "(ordinal)");
            diagnose_entry(im, img, img_len, im->exports[i].rva, &d, lbl);
            shown++;
        } else {
            diagnose_entry(im, img, img_len, im->exports[i].rva, &d, "");
        }
    }
    printf("    ENTRIES module=%s total=%u in_code=%u no_section=%u "
           "not_executable=%u past_raw=%u zero_first_byte=%u exports=%u capped=%d\n",
           path, d.total, d.in_code, d.no_section, d.not_executable, d.past_raw,
           d.zero_bytes, im->num_exports, im->exports_truncated);
}

/* ========================================================================
 * Executing what the sweep translated.
 *
 * A coverage percentage on its own is a claim about the translator, not evidence
 * about the code it produced. This runs the ARM64 the sweep actually wrote, on the
 * host it was written for, against the module it came from.
 *
 * What it is NOT: running the application. A function translated in isolation is
 * called with an argument nobody chose, its imports are unresolved (any function
 * that had one was refused, which is why this is safe to do at all), and the
 * operating system around it does not exist. What it proves is narrower and still
 * worth proving - that the emitted words are executable, terminate, and do not
 * fault, with the module's own image mapped underneath them.
 * ======================================================================== */
#if defined(__aarch64__)
#include "a64_emit.h"
#include "gstack.h"
#include <sys/mman.h>
#include <sys/wait.h>
#include <unistd.h>

#define EXEC_MAX_RECORDS 2000u   /* a cap so a large cache cannot run for hours */

/* Appends the MOVZ/MOVK run that puts a 64-bit constant into rd. Four copies of this
 * lived inline in the trampoline builder, one per register, which is how the call
 * table's X21 got added to the test harness but not here. */
static size_t tr_const(uint32_t *prog, size_t n, unsigned rd, uint64_t v)
{
    prog[n++] = a64_movz_x(rd, (uint16_t)(v & 0xFFFFu));
    if ((v >> 16) & 0xFFFFu) prog[n++] = a64_movk_x(rd, (uint16_t)((v >> 16) & 0xFFFFu), 16);
    if ((v >> 32) & 0xFFFFu) prog[n++] = a64_movk_x(rd, (uint16_t)((v >> 32) & 0xFFFFu), 32);
    if ((v >> 48) & 0xFFFFu) prog[n++] = a64_movk_x(rd, (uint16_t)((v >> 48) & 0xFFFFu), 48);
    return n;
}

/* One executable page holding a trampoline and the translated body. */
static void *place_code(const uint32_t *prog, size_t n, size_t *out_len)
{
    long   ps = sysconf(_SC_PAGESIZE);
    size_t bytes = (size_t)((n * 4u + (size_t)ps - 1u) / (size_t)ps) * (size_t)ps;
    void  *p;
    if (ps <= 0) ps = 4096;
    if (bytes == 0) bytes = (size_t)ps;
    p = mmap(NULL, bytes, PROT_READ | PROT_WRITE | PROT_EXEC,
             MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (p == MAP_FAILED) return NULL;
    memcpy(p, prog, n * 4u);
    __builtin___clear_cache((char *)p, (char *)p + n * 4u);
    if (out_len) *out_len = bytes;
    return p;
}

typedef enum {
    EXC_RETURNED = 0,   /* ran to its RET and handed back a value */
    EXC_FAULTED,        /* killed by a signal other than the alarm */
    EXC_TIMED_OUT,      /* killed by the alarm: it did not terminate */
    EXC_COULD_NOT_RUN   /* never started: too large, or a mapping failed */
} exec_outcome;

typedef struct {
    uint32_t ran, returned, faulted, timed_out, could_not_run;
    /* faulted split by cause. The bounds check a register-base access emits stops
     * with BRK, which raises SIGTRAP, and that is the mechanism working: the guest
     * pointer was outside the module's image and the code refused to read whatever
     * the host has there instead. Anything else - SIGSEGV above all - means the
     * emitted words are wrong. Reporting the two as one number would make a
     * safety mechanism indistinguishable from a code-generation bug, and the total
     * alone cannot say which one moved. */
    uint32_t trapped, crashed;
    /* Per-signal, because "the last one was SIGTRAP" is not an answer. The split
     * above found 19 records dying of something other than the bounds-check trap
     * while the last signal still read 5, which is exactly how a real bug hides
     * behind an aggregate that is expected to grow. A histogram cannot hide it. */
    uint32_t sig_hist[32];
    uint32_t exit_nonzero;
    int      last_signal;
} exec_tally;

static const char *outcome_name(exec_outcome o)
{
    switch (o) {
    case EXC_RETURNED:      return "returned";
    case EXC_FAULTED:       return "faulted";
    case EXC_TIMED_OUT:     return "timed out";
    case EXC_COULD_NOT_RUN: return "could not run";
    }
    return "?";
}

/* What a faulting child reports back. Two hypotheses about the SIGSEGVs have already
 * been falsified by changing one thing and watching the count not move, which is what
 * happens when the measurement is coarser than the bug. The signal number alone cannot
 * separate a null dereference from a guest pointer into unmapped host memory from the
 * emitted code branching somewhere wrong, and those three have three different fixes.
 * So the handler reports the address the CPU faulted on and the instruction that
 * faulted, and the parent says where each of them is. */
#define FAULT_MAGIC 0x31544C46u   /* "FLT1", little-endian */

/* Set in the child only, after fork, so the handler knows which pipe to write to. A
 * file-scope variable rather than a parameter because a sigaction handler takes none. */
static int fault_pipe_fd = -1;

typedef struct {
    uint32_t magic;
    int32_t  signo;
    int32_t  si_code;
    uint32_t pad;
    uint64_t addr;      /* si_addr: what the faulting instruction tried to reach */
    uint64_t pc;        /* the faulting instruction itself */
} fault_msg;

/* Written from a signal handler, so only async-signal-safe calls: write and _exit.
 * SA_RESETHAND means a fault inside here restores the default action and kills the
 * child the way it did before this handler existed, so the parent's existing
 * signal classification stays as the fallback rather than being replaced. */
static void fault_handler(int signo, siginfo_t *si, void *uc)
{
    fault_msg m;
    (void)uc;   /* unused when the syntax gate forces __aarch64__ onto x86 headers */
    int       fd = fault_pipe_fd;
    m.magic = FAULT_MAGIC;
    m.signo = signo;
    m.si_code = si ? si->si_code : 0;
    m.pad = 0;
    m.addr = (si && si->si_addr) ? (uint64_t)(uintptr_t)si->si_addr : 0u;
    m.pc = 0;
    /* Guarded on __x86_64__ being absent as well, and that is not redundancy. The
     * build's syntax gate compiles this file with -D__aarch64__ forced on an x86-64
     * compiler to check the aarch64-only code paths, so __aarch64__ alone is true
     * there while the real headers are still x86-64 and mcontext_t has no pc member.
     * A compiler defining __aarch64__ genuinely never defines __x86_64__, so the pair
     * separates "the aarch64 code path" from "an aarch64 toolchain". */
#if defined(__aarch64__) && !defined(__x86_64__)
    if (uc) m.pc = (uint64_t)((ucontext_t *)uc)->uc_mcontext.pc;
#endif
    if (fd >= 0) {
        ssize_t w = write(fd, &m, sizeof m);
        (void)w;
    }
    _exit(3);
}

/* Runs one placed translated function in a forked child with an alarm.
 *
 * The body already lives in its own executable page, because a guest-to-guest call
 * reaches it through the call table and that pointer has to outlive this one call. So
 * the trampoline no longer contains the body: it loads the body's address into X16 and
 * branches there. BL is not an option - it encodes a 26-bit signed WORD offset, so
 * +-128 MiB, and two independent mmaps are under no obligation to be that close.
 *
 * Forked because the code is untrusted in the ordinary sense: it was produced from
 * someone else's binary and there is no proof it terminates. A fault or a hang has
 * to cost one child and not the measurement. The alarm's default action kills the
 * child, which the parent sees as SIGALRM and reports as a timeout rather than as
 * a crash - the distinction matters because a runaway loop and a bad address are
 * different bugs. */
static exec_outcome exec_one(void *body, uint32_t body_len, void *imgbase,
                             uint64_t gtop, const uint64_t *calltab,
                             exec_tally *t, uint64_t *out_val, fault_msg *out_fault)
{
    uint32_t  prog[64];
    size_t    n = 0, plen = 0;
    void     *page;
    int       fds[2], ffds[2];
    pid_t     pid;
    int       status = 0;

    (void)body_len;
    if (out_fault) memset(out_fault, 0, sizeof *out_fault);
    t->ran++;
    if (!body) {
        t->could_not_run++;
        return EXC_COULD_NOT_RUN;
    }

    /* The same frame discipline the translation itself uses, so every register the
     * emitted words read is established before the body runs and restored after it. */
    prog[n++] = a64_stp_frame_push();
    prog[n++] = a64_stp_gstack_push();
    prog[n++] = a64_stp_imgbase_push();
    prog[n++] = a64_str_pre(21u, 31u, -16);
    n = tr_const(prog, n, 0u, 0u);                       /* X0 = 0 argument */
    n = tr_const(prog, n, 14u, gtop);
    /* Guest RBP, same value as guest RSP - see build_trampoline in test_translate.c.
     * A function that reads [rbp-8] without establishing a frame would otherwise
     * dereference whatever this process left in X15. */
    n = tr_const(prog, n, 15u, gtop);
    n = tr_const(prog, n, 19u, (uint64_t)(uintptr_t)imgbase);
    /* X21: the call table. Every P_CALL_TABLE in the body loads its target from here,
     * so a function that calls another guest function branches to whatever this
     * process left in X21 without it - and that is a live host pointer, not zero,
     * which is why it would look like a crash in the emitted code rather than a
     * missing initialisation. NULL is passed when the cache has no table at all. */
    n = tr_const(prog, n, 21u, (uint64_t)(uintptr_t)calltab);
    n = tr_const(prog, n, 16u, (uint64_t)(uintptr_t)body);
    prog[n++] = a64_blr(16u);
    prog[n++] = a64_ldr_post(21u, 31u, 16);   /* exact reverse of the push order */
    prog[n++] = a64_ldp_imgbase_pop();
    prog[n++] = a64_ldp_gstack_pop();
    prog[n++] = a64_ldp_frame_pop();
    prog[n++] = a64_ret();
    if (n > sizeof prog / sizeof prog[0]) {
        t->could_not_run++;
        return EXC_COULD_NOT_RUN;
    }

    page = place_code(prog, n, &plen);
    if (!page) { t->could_not_run++; return EXC_COULD_NOT_RUN; }

    if (pipe(fds) != 0) { munmap(page, plen); t->could_not_run++; return EXC_COULD_NOT_RUN; }
    if (pipe(ffds) != 0) {
        close(fds[0]); close(fds[1]); munmap(page, plen);
        t->could_not_run++;
        return EXC_COULD_NOT_RUN;
    }
    pid = fork();
    if (pid < 0) {
        close(fds[0]); close(fds[1]); close(ffds[0]); close(ffds[1]); munmap(page, plen);
        t->could_not_run++;
        return EXC_COULD_NOT_RUN;
    }
    if (pid == 0) {
        uint64_t r;
        close(fds[0]);
        close(ffds[0]);
        /* Installed before the call and only for the signals that mean the code went
         * wrong. SIGALRM is deliberately left alone: its default action kills the
         * child, which is the only thing that stops a translated loop that never
         * ends, and catching it here would turn every timeout into a report of a
         * fault that was really a hang. */
        fault_pipe_fd = ffds[1];
        {
            static const int caught[] = { SIGSEGV, SIGTRAP, SIGBUS, SIGILL, SIGFPE };
            struct sigaction sa;
            size_t k;
            memset(&sa, 0, sizeof sa);
            sa.sa_sigaction = fault_handler;
            sa.sa_flags = SA_SIGINFO | SA_RESETHAND;
            sigfillset(&sa.sa_mask);
            for (k = 0; k < sizeof caught / sizeof caught[0]; k++)
                sigaction(caught[k], &sa, NULL);
        }
        /* Armed before the call, not after. The default SIGALRM action kills the
         * child, which is the only thing that stops a translated loop that never
         * ends - and an alarm set on the way out would leave that loop running
         * forever with the parent blocked in waitpid. */
        alarm(5);
        r = ((uint64_t (*)(void))page)();
        if (write(fds[1], &r, sizeof r) != (ssize_t)sizeof r) _exit(2);
        close(fds[1]);
        close(ffds[1]);
        _exit(0);
    }
    close(fds[1]);
    close(ffds[1]);   /* the write end belongs to the child now */
    alarm(8);                       /* the parent's own escape if waitpid blocks */
    {
        ssize_t got = read(fds[0], out_val, sizeof *out_val);
        if (got != (ssize_t)sizeof *out_val) *out_val = 0;
    }
    close(fds[0]);
    {   /* Both writes are far under PIPE_BUF, so each arrives in one read and the
         * fault message cannot be interleaved with the return value. */
        fault_msg fm;
        ssize_t got = read(ffds[0], &fm, sizeof fm);
        if (got == (ssize_t)sizeof fm && fm.magic == FAULT_MAGIC && out_fault)
            *out_fault = fm;
    }
    close(ffds[0]);
    if (waitpid(pid, &status, 0) < 0) status = 0;
    alarm(0);
    munmap(page, plen);

    if (WIFEXITED(status) && WEXITSTATUS(status) == 0) {
        t->returned++;
        return EXC_RETURNED;
    }
    /* Counted from the message rather than from the wait status, and into exactly the
     * same fields the signal path used. The child now exits 3 instead of dying, so
     * without this a fault would arrive as "exited non-zero" and the tally's
     * trapped + crashed == faulted invariant - which the CI assertion checks - would
     * silently stop holding. */
    if (out_fault && out_fault->magic == FAULT_MAGIC) {
        int sg = out_fault->signo;
        t->faulted++;
        t->last_signal = sg;
        if (sg == SIGTRAP) t->trapped++;
        else               t->crashed++;
        if (sg >= 0 && sg < 32) t->sig_hist[sg]++;
        return EXC_FAULTED;
    }
    if (WIFSIGNALED(status) && WTERMSIG(status) == SIGALRM) {
        t->timed_out++;
        return EXC_TIMED_OUT;
    }
    /* Reached only when the handler did not report: SA_RESETHAND restored the default
     * action after a second fault, or the signal was one nobody installed for. */
    t->faulted++;
    t->last_signal = WIFSIGNALED(status) ? WTERMSIG(status) : -1;
    if (WIFSIGNALED(status) && WTERMSIG(status) == SIGTRAP) t->trapped++;
    else                                                    t->crashed++;
    if (WIFSIGNALED(status)) {
        int sg = WTERMSIG(status);
        if (sg >= 0 && sg < 32) t->sig_hist[sg]++;
    } else {
        t->exit_nonzero++;
    }
    return EXC_FAULTED;
}

/* Which region a faulting address is in. Split this finely because the regions have
 * different fixes and the coarse version already cost two falsified hypotheses: the
 * signal number said SIGSEGV and nothing said where.
 *
 * The arena's guard pages are their own category rather than being lumped with the
 * usable stack. A fault inside the usable region means something is wrong with the
 * arena itself; a fault on a guard means the guest walked off the end of it, which is
 * a frame larger than the arena or a stack that never stops growing - containment
 * working, and a different problem entirely. */
typedef enum {
    FC_NULLISH = 0,     /* below 64 KiB: an uninitialised or truncated guest pointer */
    FC_IN_IMAGE,        /* inside a mapped module: a bounds check should have caught it */
    FC_IN_STACK,        /* inside the arena's usable pages */
    /* The two guards, split because they are opposite bugs. The arena has a PROT_NONE
     * page on each side: below, a runaway guest stack pointer walks off the bottom;
     * above, a pop or a positive displacement reads past the top. One says the guest
     * kept growing its stack, the other says something moved the pointer the wrong way,
     * and a single "guard page" count cannot tell them apart - which is why 86 faults
     * in that bucket said nothing actionable. */
    FC_GUARD_LOW,       /* below the arena: the guest stack ran off the bottom */
    FC_GUARD_HIGH,      /* above the arena: past the initial guest RSP */
    FC_IN_CODE,         /* inside emitted code: a branch or a load went to the wrong place */
    /* The stub every unfilled call-table slot points at. Its own region because it is
     * the one fault here that is a feature working: the sweep found a callee, nobody
     * translated it, and the call stopped on a deliberate trap instead of branching to
     * whatever the slot happened to hold. Without this category those faults land in
     * FC_ELSEWHERE - the stub is a separate mmap that no placed body covers - and read
     * as "the emitted words invented a pointer", which is the opposite conclusion. */
    FC_UNTRANSLATED,
    FC_ELSEWHERE,       /* none of the above: the emitted words invented this pointer */
    FC_COUNT
} fault_class;

static const char *fault_class_name(fault_class c)
{
    switch (c) {
    case FC_NULLISH:   return "null-ish";
    case FC_IN_IMAGE:  return "inside a mapped guest image";
    case FC_IN_STACK:  return "inside the guest stack";
    case FC_GUARD_LOW:  return "below the guest stack (ran off the bottom)";
    case FC_GUARD_HIGH: return "above the guest stack (past its entry value)";
    case FC_IN_CODE:   return "inside emitted code";
    case FC_UNTRANSLATED: return "on the untranslated-call stub";
    case FC_ELSEWHERE: return "nowhere this process mapped for the guest";
    case FC_COUNT:     break;
    }
    return "unknown";
}

/* A translated function sitting in executable memory, and the guest address it is the
 * translation of. The call table is built out of these. */
typedef struct {
    uint64_t  module_id;
    uint64_t  guest_pc;
    uint32_t  code_len;
    void     *page;
    size_t    page_len;
} placed_fn;

/* Separate from the execution cap and larger, because a function that is never itself
 * executed still has to be placed if anything calls it. Capping placement at the
 * execution cap would leave slots unfilled for callees that no test entry point
 * reaches, which is most of them. */
#define PLACE_MAX_RECORDS 4000u

/* Points every import-table slot that no shim answers for at the trap stub.
 *
 * shim_fill_iat fills the slots whose imported name has a shim and leaves the rest
 * holding whatever the file held - an RVA, or zero. Cached code reaches an import with
 * `LDUR X16,[X17]; BLR X16` through that slot, so an unfilled one is a branch to an RVA
 * or to address 0. Neither is a controlled stop, and both arrive as SIGSEGV, which the
 * tally reports as emitted code going wrong. On a real game module that was 17 records,
 * every one with addr=0 and a pc outside every translated body.
 *
 * shim_resolve is asked per slot rather than a new accessor being added to shim.h: it
 * already returns 0 for a slot it does not own, which is exactly the question. Returns
 * how many slots were stubbed. */
static size_t stub_unknown_iat(const pe_image *im, uint8_t *base, size_t sz,
                               const void *stub, size_t *out_no_iat)
{
    uint64_t stubval = (uint64_t)(uintptr_t)stub;
    size_t   d, k, n = 0, no_iat = 0;

    for (d = 0; d < im->num_dlls; d++) {
        const pe_import_dll *dl = &im->dlls[d];
        /* An iat_rva of 0 is not an IAT at the start of the image, it is the absence of
         * one, and treating it as an address writes stub values across the DOS header,
         * the PE header and the section table - corrupting the very structures the rest
         * of the loader reads, while leaving the real slots untouched. Counted rather
         * than skipped silently: if this is common, the count says the slot enumeration
         * is not reaching the imports at all, which is a different bug from the one
         * being fixed and would otherwise be invisible behind a large "slots stubbed"
         * number that looked like success. */
        if (dl->iat_rva == 0) { no_iat++; continue; }
        for (k = 0; k < dl->func_count; k++) {
            uint64_t slot_rva = (uint64_t)dl->iat_rva + (uint64_t)k * 8u;
            if (slot_rva + 8u > (uint64_t)sz) continue;
            if (shim_resolve(im->image_base + slot_rva, NULL) != 0)
                continue;                 /* a shim owns this slot and already filled it */
            memcpy(base + slot_rva, &stubval, sizeof stubval);
            n++;
        }
    }
    if (out_no_iat) *out_no_iat = no_iat;
    return n;
}

static fault_class classify_addr(uint64_t addr, void *const *bases,
                                 const size_t *bsizes, int nmods,
                                 const gs_arena *a,
                                 const placed_fn *pf, size_t nplaced,
                                 const void *trap, size_t trap_len)
{
    int    i;
    size_t q;
    uint64_t tb = (uint64_t)(uintptr_t)trap;

    if (addr < 0x10000u)
        return FC_NULLISH;
    if (trap && addr >= tb && addr < tb + trap_len)
        return FC_UNTRANSLATED;
    for (i = 0; i < nmods; i++) {
        uint64_t b;
        if (!bases[i]) continue;
        b = (uint64_t)(uintptr_t)bases[i];
        if (addr >= b && addr < b + bsizes[i]) return FC_IN_IMAGE;
    }
    if (gs_contains(a, addr))
        return FC_IN_STACK;
    if (a->map_base &&
        addr >= (uint64_t)(uintptr_t)a->map_base &&
        addr <  (uint64_t)(uintptr_t)a->map_base + a->map_size)
        return addr < (uint64_t)(uintptr_t)a->usable ? FC_GUARD_LOW : FC_GUARD_HIGH;
    /* Every placed body, not just the one that was called: a guest-to-guest call means
     * the fault can be in a different function's code than the entry point's. */
    for (q = 0; q < nplaced; q++) {
        uint64_t b = (uint64_t)(uintptr_t)pf[q].page;
        if (addr >= b && addr < b + pf[q].page_len) return FC_IN_CODE;
    }
    return FC_ELSEWHERE;
}

/* Walks every live cache record, puts each one in executable memory, fills the call
 * table so a guest function can call another one, and then runs them.
 *
 * Records whose module did not map are counted separately rather than skipped
 * silently: "executed 0" and "had nothing executable" are different statements and
 * the summary should not blur them. */
static void execute_translated(ptc_cache *cache, int nmods, const uint64_t *mids,
                               uint8_t *const *imgs, const size_t *lens,
                               const pe_image *pes, const char *const *paths)
{
    exec_tally  t;
    gs_arena    a;
    placed_fn  *pf = NULL;
    void      **bases = NULL;
    size_t     *bsizes = NULL;
    uint64_t   *ct = NULL;
    void       *trap = NULL;
    size_t      trap_len = 0, ct_n = 0, ct_filled = 0;
    size_t      slots, slot, mapped = 0, unmatched = 0, capped = 0;
    size_t      nplaced = 0, not_placed = 0, iat_stubbed = 0, iat_no_iat = 0, i, q;
    size_t      fc_hist[FC_COUNT];
    /* Region crossed with signal, because the region histogram alone cannot answer the
     * only question that matters here. The tally calls a SIGTRAP "the bounds check
     * working" and everything else "emitted code going wrong", and 40 records faulting
     * on the guest stack's guard page could be either: a SIGSEGV there is the arena
     * containing a runaway stack pointer, which is containment, while the same address
     * reached by a SIGTRAP would mean something else entirely. Reporting the regions
     * without the signals would leave that guess, and this count has already been
     * guessed at twice. */
    size_t      fc_trap[FC_COUNT], fc_other[FC_COUNT];
    /* Per-record detail for the faults that are NOT bounds-check traps, bounded and
     * collapsed onto one line. The aggregate regions say which mechanism is operating
     * but not which instruction, and reclassifying a category as "the harness's fault,
     * not the emitted code's" on the strength of an aggregate is exactly how the 86
     * above-the-stack faults came to be explained as a runaway stack pointer for as
     * long as they were. The guest address and the word index into the body are what
     * make the claim checkable against the bytes. */
    char        other_detail[1400];
    size_t      other_len = 0, other_n = 0;
    int         arena_ok = 0;

    other_detail[0] = '\0';

    memset(&t, 0, sizeof t);
    memset(fc_hist, 0, sizeof fc_hist);
    memset(fc_trap, 0, sizeof fc_trap);
    memset(fc_other, 0, sizeof fc_other);
    printf("\n--- executing what was translated ---\n");

    /* 8 MiB, not the 64 KiB this used to be. Each translated function is called in
     * isolation with guest RSP at the top of this arena, so its whole frame has to
     * fit: a C++ function that opens a large frame with `sub rsp, N` and then writes
     * a local walks straight off the bottom into the PROT_NONE guard page and takes
     * a SIGSEGV. That is containment working, not a wild write, but it is
     * indistinguishable in the tally from emitted code being wrong - and 19 records
     * on a real game module died that way with no explanation. Enlarging the arena
     * is the cheap experiment that separates the two: if the count falls, frame size
     * was the cause. */
    if (!gs_alloc(8u * 1024u * 1024u, &a)) {
        printf("  could not allocate a guest stack arena: %s\n", gs_last_error());
        printf("  EXECUTED NOTHING: no guest stack arena\n");
        return;
    }
    arena_ok = 1;

    slots = ptc_record_slots(cache);
    bases  = calloc((size_t)nmods, sizeof *bases);
    bsizes = calloc((size_t)nmods, sizeof *bsizes);
    pf     = calloc(slots ? slots : 1u, sizeof *pf);
    if (!bases || !bsizes || !pf) {
        printf("  EXECUTED NOTHING: could not allocate the placement tables\n");
        goto cleanup;
    }

    /* One shared stub for every call target nobody can supply: an unfilled call-table
     * slot, and - below - an import no shim answers for. A slot holding 0 makes the call
     * a branch to address 0, which is a SIGSEGV and, in a tally that separates traps
     * from crashes precisely so a code-generation bug cannot hide, indistinguishable
     * from the emitted words being wrong. Measured, not hypothetical: 17 records on a
     * real game module faulted with addr=0 and a pc outside every translated body,
     * which is control arriving at address 0 - an indirect call through an IAT slot
     * this loader never filled. A BRK with its own immediate is a controlled stop that
     * says which of the two happened. */
    {
        uint32_t stub[1];
        stub[0] = a64_brk(A64_BRK_UNTRANSLATED);
        trap = place_code(stub, 1u, &trap_len);
        if (!trap) {
            printf("  EXECUTED NOTHING: could not place the unresolved-call stub\n");
            goto cleanup;
        }
    }

    /* Every module is mapped up front and stays mapped. They used to be mapped and
     * unmapped one at a time, which was fine while each record ran alone and cannot
     * work now: a call-table slot may point at a function in a different module, so
     * every mapping has to be alive for as long as any of them can be called. */
    for (i = 0; i < (size_t)nmods; i++) {
        size_t sz = 0;
        void  *base = pe_map_image(imgs[i], lens[i], &pes[i], &sz);
        if (!base) {
            printf("  %s: image could not be mapped, its translations are not runnable\n",
                   paths[i]);
            continue;
        }
        bases[i] = base;
        bsizes[i] = sz;
        mapped++;
        printf("  %s: image mapped at %p, size %zu, base RVA 0 there\n",
               paths[i], base, sz);

        /* Rebind this module's slots to the real mapping and write the shim addresses
         * into it. The cached code loads its call target out of the slot at run time,
         * so the slot has to hold a host address by the time the body executes - and
         * nothing in the cached words changed, which is the whole reason the target
         * lives in the image instead of in the code. */
        {   size_t known = 0, unknown = 0;
            shim_fill_iat(&pes[i], (uint8_t *)base, sz, pes[i].image_base,
                          &known, &unknown);
            {   size_t no_iat = 0;
                iat_stubbed += stub_unknown_iat(&pes[i], (uint8_t *)base, sz, trap,
                                                &no_iat);
                iat_no_iat += no_iat;
            }
        }
    }

    ct_n = ptc_calltab_count(cache);
    if (ct_n) {
        ct = calloc(ct_n, sizeof *ct);
        if (!ct) {
            printf("  EXECUTED NOTHING: could not allocate the call table\n");
            goto cleanup;
        }
    }

    /* Place every record belonging to a module that mapped. */
    for (slot = 0; slot < slots; slot++) {
        uint64_t    mid = 0, gpc = 0;
        const void *code = NULL;
        uint32_t    clen = 0;
        void       *page;
        size_t      plen = 0;
        int         have_base = 0;
        if (!ptc_record_at(cache, slot, &mid, &gpc, &code, &clen)) continue;
        for (i = 0; i < (size_t)nmods; i++)
            if (mids[i] == mid && bases[i]) { have_base = 1; break; }
        if (!have_base) continue;
        if (nplaced >= PLACE_MAX_RECORDS) { not_placed++; continue; }
        page = place_code((const uint32_t *)code, clen / 4u, &plen);
        if (!page) { not_placed++; continue; }
        pf[nplaced].module_id = mid;
        pf[nplaced].guest_pc  = gpc;
        pf[nplaced].code_len  = clen;
        pf[nplaced].page      = page;
        pf[nplaced].page_len  = plen;
        nplaced++;
    }

    /* Fill the table. Slot order came out of the cache, so an offset baked into a
     * body loaded from disk names the same callee here that it named in the process
     * that translated it - which is the entire reason the numbering is persisted and
     * never compacted. */
    for (q = 0; ct && q < ct_n; q++) {
        uint64_t mid = 0, va = 0;
        int      dead = 0;
        if (!ptc_calltab_at(cache, q, &mid, &va, &dead)) continue;
        if (!dead) {
            for (i = 0; i < nplaced; i++) {
                if (pf[i].module_id != mid || pf[i].guest_pc != va) continue;
                ct[q] = (uint64_t)(uintptr_t)pf[i].page;
                ct_filled++;
                break;
            }
        }
        if (!ct[q]) ct[q] = (uint64_t)(uintptr_t)trap;
    }

    for (i = 0; i < (size_t)nmods; i++) {
        if (!bases[i]) continue;
        for (q = 0; q < nplaced; q++) {
            uint64_t      val = 0;
            fault_msg     fm;
            exec_outcome  oc;
            if (pf[q].module_id != mids[i]) continue;
            if (t.ran >= EXEC_MAX_RECORDS) { capped++; continue; }
            memset(&fm, 0, sizeof fm);
            oc = exec_one(pf[q].page, pf[q].code_len, bases[i], a.top, ct, &t, &val, &fm);
            /* The returned value is printed because it is the only evidence that
             * the code did something rather than merely not crashing. It is NOT
             * checked against anything: the argument is arbitrary and the function
             * was written for a caller that does not exist here. */
            printf("    guest_pc=%08llX  %3u bytes of ARM64  ->  %-13s%s%llu\n",
                   (unsigned long long)pf[q].guest_pc, pf[q].code_len, outcome_name(oc),
                   oc == EXC_RETURNED ? "value 0x" : "",
                   (unsigned long long)(oc == EXC_RETURNED ? val : 0u));

            /* Printed per record rather than only in aggregate, because the aggregate
             * is what two hypotheses were falsified against and the per-record line is
             * what says which pointer was wrong. Worded to avoid every substring the
             * CI assertion greps for, which takes the LAST match of each pattern. */
            if (fm.magic == FAULT_MAGIC) {
                fault_class fc = classify_addr(fm.addr, bases, bsizes, nmods, &a,
                                               pf, nplaced, trap, trap_len);
                fc_hist[fc]++;
                if (fm.signo == SIGTRAP) fc_trap[fc]++;
                else                     fc_other[fc]++;
                printf("      fault at %016llX (%s), sig %d code %d",
                       (unsigned long long)fm.addr, fault_class_name(fc),
                       fm.signo, fm.si_code);
                /* How far the guest stack pointer travelled from its entry value. This
                 * is the number that settles an argument the arena-size experiment
                 * could not: growing the arena from 64 KiB to 8 MiB left the count
                 * unchanged, which rules out large frames, and the distance says so
                 * directly - a frame would be kilobytes, a stack that never stops
                 * growing is the whole arena. */
                if (fc == FC_GUARD_LOW && a.top > fm.addr)
                    printf(", stack ran %llu bytes below its entry value",
                           (unsigned long long)(a.top - fm.addr));
                if (fm.pc) {
                    size_t   w;
                    int      located = 0;
                    uint64_t located_gpc = 0, located_word = 0;
                    for (w = 0; w < nplaced; w++) {
                        uint64_t b = (uint64_t)(uintptr_t)pf[w].page;
                        if (fm.pc < b || fm.pc >= b + pf[w].page_len) continue;
                        printf(", pc word %llu of the body at guest_pc=%08llX\n",
                               (unsigned long long)((fm.pc - b) / 4u),
                               (unsigned long long)pf[w].guest_pc);
                        located = 1;
                        located_gpc = pf[w].guest_pc;
                        located_word = (uint64_t)((fm.pc - b) / 4u);
                        break;
                    }
                    /* The informative case: control was somewhere that is not
                     * translated code at all, so the fault is not in a body. */
                    if (!located)
                        printf(", pc %016llX is outside every placed body\n",
                               (unsigned long long)fm.pc);
                    /* Collected for BOTH cases, and collecting only the located ones was
                     * a hole in the instrumentation rather than a choice. The first
                     * version of this reported "1 shown of 17" and the one shown was the
                     * least interesting of them: 16 faults had a pc outside every placed
                     * body - control somewhere that is not translated code at all - and
                     * those were exactly the ones dropped, because the collection sat
                     * inside the branch that only runs when the pc IS in a body. The
                     * unexplained majority went unreported while the explained minority
                     * was printed. */
                    if (fm.signo != SIGTRAP && other_n < 12u &&
                        other_len + 128u < sizeof other_detail) {
                        if (located)
                            other_len += (size_t)snprintf(other_detail + other_len,
                                        sizeof other_detail - other_len,
                                        "%sgpc=%08llX w=%llu addr=%llX",
                                        other_n ? " | " : "",
                                        (unsigned long long)located_gpc,
                                        (unsigned long long)located_word,
                                        (unsigned long long)fm.addr);
                        else
                            other_len += (size_t)snprintf(other_detail + other_len,
                                        sizeof other_detail - other_len,
                                        "%spc=%llX (no body) addr=%llX",
                                        other_n ? " | " : "",
                                        (unsigned long long)fm.pc,
                                        (unsigned long long)fm.addr);
                        other_n++;
                    }
                } else {
                    printf(", pc unavailable\n");
                }
            }
        }
    }

    /* records belonging to no module that was offered */
    for (slot = 0; slot < slots; slot++) {
        uint64_t mid = 0;
        int found = 0;
        if (!ptc_record_at(cache, slot, &mid, NULL, NULL, NULL)) continue;
        for (i = 0; i < (size_t)nmods; i++) if (mids[i] == mid) { found = 1; break; }
        if (!found) unmatched++;
    }

    printf("  modules mapped: %zu of %d\n", mapped, nmods);
    printf("  records executed: %u   returned: %u   faulted: %u   timed out: %u"
           "   could not run: %u\n",
           t.ran, t.returned, t.faulted, t.timed_out, t.could_not_run);
    if (ct_n)
        /* The number that says whether guest-to-guest calls can work at all. A slot
         * left on the stub is a callee the sweep found and nobody translated, so this
         * is the distance between "the translator can emit a call" and "the program
         * can make one". */
        printf("  call table: %zu slot(s), %zu filled with translated code, "
               "%zu left on the untranslated stub\n",
               ct_n, ct_filled, ct_n - ct_filled);
    if (not_placed)
        printf("  records not placed in executable memory: %zu\n", not_placed);
    if (iat_stubbed || iat_no_iat)
        printf("  import slots pointed at the stub: %zu, import directories with no "
               "IAT RVA: %zu\n", iat_stubbed, iat_no_iat);
    if (t.faulted) {
        /* Split out, because the two causes call for opposite reactions: a trap is
         * the bounds check declining to invent a value, a crash is a bug in what
         * was emitted. */
        /* Worded to avoid every substring the CI assertion already greps for.
         * "faulted: <n>" here would be matched by that step's 'faulted: *[0-9]+'
         * pattern, and because it takes the LAST match it would silently change
         * which line the assertion reads. */
        printf("  fault causes: %u trap(s) from the bounds check, "
               "%u other fault(s)\n", t.trapped, t.crashed);
        /* Every distinct cause, not just the last. Named where the name is
         * unambiguous on Linux, because "signal 11" reads as noise in a log. */
        for (int sg = 1; sg < 32; sg++) {
            if (!t.sig_hist[sg]) continue;
            printf("  fault signal %2d (%s): %u record(s)\n", sg,
                   sg == SIGSEGV ? "SIGSEGV" : sg == SIGTRAP ? "SIGTRAP" :
                   sg == SIGBUS  ? "SIGBUS"  : sg == SIGILL  ? "SIGILL"  :
                   sg == SIGFPE  ? "SIGFPE"  : sg == SIGABRT ? "SIGABRT" : "other",
                   t.sig_hist[sg]);
        }
        if (t.exit_nonzero)
            printf("  exited non-zero without a signal: %u record(s)\n",
                   t.exit_nonzero);
        printf("  last fault signal: %d\n", t.last_signal);
    }
    /* Every region that faulted, with counts. This is the line that turns "N records
     * died of SIGSEGV" into a work queue: a guard-page count says frames are bigger
     * than the arena, a null-ish count says a guest register was never initialised,
     * and a count in the last category says the emitted words produced a pointer that
     * corresponds to nothing in this process. */
    for (i = 0; i < FC_COUNT; i++) {
        if (!fc_hist[i]) continue;
        printf("  fault address region: %-42s %zu record(s), %zu SIGTRAP, %zu other\n",
               fault_class_name((fault_class)i), fc_hist[i], fc_trap[i], fc_other[i]);
    }
    if (other_n)
        printf("  non-trap fault detail: %zu shown of %u, %s\n",
               other_n, t.crashed, other_detail);
    if (unmatched) printf("  records belonging to no offered module: %zu\n", unmatched);
    if (capped)    printf("  records skipped by the %u cap: %zu\n", EXEC_MAX_RECORDS, capped);
    if (t.ran == 0)
        printf("  EXECUTED NOTHING: no translated function was runnable here\n");
    else
        printf("  EXECUTED ON aarch64: %u translated function(s) from a real "
               "shipped module ran on this host, %u returned\n",
               t.ran, t.returned);

cleanup:
    for (q = 0; q < nplaced; q++)
        if (pf && pf[q].page) munmap(pf[q].page, pf[q].page_len);
    if (trap) munmap(trap, trap_len);
    free(ct);
    free(pf);
    for (i = 0; bases && i < (size_t)nmods; i++)
        if (bases[i]) munmap(bases[i], bsizes[i]);
    free(bases);
    free(bsizes);
    if (arena_ok) gs_free(&a);
}

#else
static void execute_translated(ptc_cache *cache, int nmods, const uint64_t *mids,
                               uint8_t *const *imgs, const size_t *lens,
                               const pe_image *pes, const char *const *paths)
{
    (void)cache; (void)nmods; (void)mids; (void)imgs; (void)lens; (void)pes;
    (void)paths;
    printf("\n--- executing what was translated ---\n");
    printf("  SKIP: host is not aarch64, so there is no instruction set to run the\n"
           "  emitted words on. Coverage was measured; nothing was executed.\n");
    printf("  EXECUTED NOTHING: host is not aarch64\n");
}
#endif /* __aarch64__ */

int main(int argc, char **argv)
{
    const char *cache_path = NULL;
    const char *paths[MAX_MODULES];
    uint8_t    *imgs[MAX_MODULES];
    size_t      lens[MAX_MODULES];
    uint64_t    mtimes[MAX_MODULES];
    pe_image    pes[MAX_MODULES];
    uint64_t    mids[MAX_MODULES];
    int         npaths = 0, nmods = 0, i;
    unsigned    idle_ms = 250u, max_seconds = 600u;
    int         diagnose = 0, execute = 0;
    ptc_cache  *cache = NULL;
    sweep_job  *job = NULL;
    sweep_progress prog;
    int         done = 0;
    uint64_t    t0, hard_deadline;
    int         refused = 0;

    for (i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--cache") == 0 && i + 1 < argc)
            cache_path = argv[++i];
        else if (strcmp(argv[i], "--idle-ms") == 0 && i + 1 < argc)
            idle_ms = (unsigned)strtoul(argv[++i], NULL, 10);
        else if (strcmp(argv[i], "--execute") == 0)
            execute = 1;
        else if (strcmp(argv[i], "--diagnose-entries") == 0)
            diagnose = 1;
        else if (strcmp(argv[i], "--max-seconds") == 0 && i + 1 < argc)
            max_seconds = (unsigned)strtoul(argv[++i], NULL, 10);
        else if (argv[i][0] == '-') {
            fprintf(stderr, "unknown option %s\n", argv[i]);
            return 1;
        } else if (npaths < MAX_MODULES) {
            paths[npaths++] = argv[i];
        } else {
            fprintf(stderr, "too many modules (max %d)\n", MAX_MODULES);
            return 1;
        }
    }
    if (npaths == 0) {
        fprintf(stderr,
                "usage: prewarm [--cache <path>] [--idle-ms <n>] "
                "[--max-seconds <n>] [--diagnose-entries] [--execute] "
                "<file> [<file>...]\n"
                "  --execute  map each module's image and run the ARM64 the sweep "
                "wrote, in a forked child with an alarm\n");
        return 1;
    }

    /* Load and parse every module first: a module that turns out to be 32-bit,
     * ARM or managed is reported and skipped, and the rest still get swept. */
    printf("--- loading modules ---\n");
    for (i = 0; i < npaths; i++) {
        pe_status st;
        if (!read_file(paths[i], &imgs[nmods], &lens[nmods], &mtimes[nmods]))
            continue;
        st = pe_load(imgs[nmods], lens[nmods], &pes[nmods]);
        if (st != PE_OK) {
            printf("  skip %s: %s - %s\n", paths[i],
                   st == PE_UNSUPPORTED ? "refused" : "unreadable",
                   pes[nmods].detail ? pes[nmods].detail : "?");
            if (st == PE_UNSUPPORTED) {
                printf("       machine=%s format=%s managed=%s "
                       "(identified, but not loadable here)\n",
                       pe_machine_name(pes[nmods].machine),
                       pes[nmods].opt_magic == PE_MAGIC_PE32PLUS ? "PE32+" :
                       pes[nmods].opt_magic == PE_MAGIC_PE32 ? "PE32" : "?",
                       pes[nmods].has_clr ? "yes" : "no");
            }
            free(imgs[nmods]);
            refused++;
            continue;
        }
        printf("  ok   %s: %s %s, %u section(s), %u imported function(s), "
               "%u export(s)\n",
               paths[i], pes[nmods].is_dll ? "DLL" : "exe",
               pe_machine_name(pes[nmods].machine), pes[nmods].num_sections,
               pe_total_imports(&pes[nmods]), pes[nmods].num_exports);
        if (diagnose)
            diagnose_module(paths[i], imgs[nmods], lens[nmods], &pes[nmods]);
        nmods++;
    }
    if (nmods == 0) {
        printf("\nnothing loadable was found; %d file(s) refused\n", refused);
        return 1;
    }

    cache = ptc_create(PTC_ISA_AARCH64, PTC_ISA_X86_64, 4096u);
    if (!cache) { fprintf(stderr, "ptc_create failed\n"); return 1; }
    job = sweep_begin(cache);
    if (!job) { fprintf(stderr, "sweep_begin failed\n"); return 1; }

    for (i = 0; i < nmods; i++) {
        uint64_t mid = 0;
        int      queued;
        if (ptc_add_module(cache, paths[i], lens[i], mtimes[i],
                           ptc_hash_bytes(imgs[i], lens[i]), &mid) != 0) {
            printf("  warning: could not register %s in the cache\n", paths[i]);
            continue;
        }
        mids[i] = mid;
        queued = sweep_add_module(job, paths[i], mid, imgs[i], lens[i], &pes[i]);
        if (queued < 0) printf("  warning: %s has no sweepable code\n", paths[i]);
        else            printf("  queued %d entry point(s) from %s\n", queued,
                               paths[i]);

        /* Fill this module's IAT slots for the Win32 functions shim.c implements and
         * let the sweep resolve through them. The guest base is the PE's declared
         * ImageBase, which is what the sweep translates against, so the RVA a resolver
         * answers with is the same one the execute phase will reach through X19.
         *
         * This writes host addresses into the file buffer, which is harmless and not
         * the point: only the RVAs are used during the sweep. The execute phase calls
         * this again against the real mapping, and that call is the one that matters. */
        {   size_t known = 0, unknown = 0, got;
            /* pe_load has to run HERE. pes[i] is otherwise first filled by
             * pe_map_image, which happens in the execute phase - after this sweep -
             * so at this point the struct is still zeroed and num_dlls is 0. The
             * first run of this filled no slots at all and every import stayed
             * unresolved, which looks exactly like the resolver being broken rather
             * than like a header nobody parsed. Calling pe_load again later is
             * harmless: it fills the same struct from the same bytes. */
            {   pe_status ps = pe_load(imgs[i], lens[i], &pes[i]);
                /* One line, one marker, everything that decides whether a slot can be
                 * filled. "IAT slots filled 0" is consistent with a header nobody
                 * parsed, an import directory the walk did not finish, a DLL count of
                 * zero, a name that does not match the shim table and an ImageBase of
                 * zero, and those have different fixes. The job log is not reachable
                 * from everywhere, so this goes to stdout where the workflow can lift
                 * it into an annotation. */
                printf("  SHIMDIAG %s pe_load=%d detail=%s image_base=0x%llx "
                       "has_imports=%d num_dlls=%u total_imports=%u truncated=%d\n",
                       paths[i], (int)ps, pes[i].detail ? pes[i].detail : "-",
                       (unsigned long long)pes[i].image_base, (int)pes[i].has_imports,
                       (unsigned)pes[i].num_dlls,
                       (unsigned)pe_total_imports(&pes[i]),
                       (int)pes[i].imports_truncated);
                if (ps != PE_OK)
                    printf("  %s: PE did not parse to PE_OK, its imports may be "
                           "incomplete\n", paths[i]);
            }
            /* NULL image on purpose: this is the raw file buffer, where an RVA is not
             * an offset. Only the slot RVAs are wanted here, so the resolver can
             * answer during the sweep; the addresses get written into the mapping in
             * the execute phase, where RVA and offset agree. */
            got = shim_fill_iat(&pes[i], NULL, 0u, pes[i].image_base, &known,
                                &unknown);
            printf("  %s: IAT slots filled %zu, imported functions recognised %zu, "
                   "not implemented %zu\n", paths[i], got, known, unknown);
            /* The names the file actually asks for, so a table that does not match is
             * visible as a mismatch rather than inferred from a zero. */
            for (uint32_t d = 0; d < pes[i].num_dlls && d < 8u; d++) {
                const pe_import_dll *dl = &pes[i].dlls[d];
                printf("  SHIMDLL %s iat_rva=0x%x funcs=%u\n",
                       dl->dll_name ? dl->dll_name : "-", (unsigned)dl->iat_rva,
                       (unsigned)dl->func_count);
                for (uint32_t k = 0; k < dl->func_count && k < 12u; k++) {
                    const pe_import_func *fn = &pes[i].funcs[dl->first_func + k];
                    printf("  SHIMFUNC %s ordinal=%u by_ordinal=%d\n",
                           fn->name ? fn->name : "(null)", (unsigned)fn->ordinal,
                           (int)fn->by_ordinal);
                }
            }
        }
    }

    /* Installed only if at least one slot was filled. With no resolver the sweep keeps
     * its historical behaviour and refuses every function that calls an import, which
     * is the honest state for a bundle whose APIs are not implemented. */
    if (shim_count() > 0) {
        sweep_set_resolver(shim_resolve, NULL);
        printf("  import resolver installed: %zu Win32 function(s) implemented\n",
               shim_count());
    }

    printf("\n--- sweep (idle window %u ms) ---\n", idle_ms);
    t0 = now_ns();
    hard_deadline = t0 + (uint64_t)max_seconds * 1000000000ULL;

    while (!done) {
        window w;
        w.expired = 0;
        if (idle_ms == 0) {
            done = sweep_run(job, NULL, NULL);
        } else {
            w.deadline_ns = now_ns() + (uint64_t)idle_ms * 1000000ULL;
            done = sweep_run(job, window_stop, &w);
        }
        sweep_get_progress(job, &prog);
        print_progress(&prog, !done);
        if (!done && now_ns() >= hard_deadline) {
            printf("  stopping: --max-seconds %u reached with work outstanding\n",
                   max_seconds);
            break;
        }
        /* An idle window that closed before a single block was done would loop
         * forever if the deadline were already in the past. */
        if (!done && idle_ms == 0) break;
    }

    sweep_get_progress(job, &prog);
    print_summary(&prog, cache, job);

    if (cache_path && prog.functions_translated > 0) {
        if (ptc_save(cache, cache_path) == 0)
            printf("\ncache written to %s (%zu records)\n", cache_path,
                   ptc_record_count(cache));
        else
            printf("\nwarning: could not write the cache to %s\n", cache_path);
    } else if (cache_path) {
        printf("\nnothing was translated, so no cache file was written\n");
    }

    if (execute)
        execute_translated(cache, nmods, mids, imgs, lens, pes, paths);

    sweep_free(job);
    ptc_free(cache);
    for (i = 0; i < nmods; i++) free(imgs[i]);

    return prog.phase == SWEEP_DONE ? 0 : 3;
}
