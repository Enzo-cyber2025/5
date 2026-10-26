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

#include "translate.h"

#include "pe_load.h"
#include "ptc.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
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

int main(int argc, char **argv)
{
    const char *cache_path = NULL;
    const char *paths[MAX_MODULES];
    uint8_t    *imgs[MAX_MODULES];
    size_t      lens[MAX_MODULES];
    uint64_t    mtimes[MAX_MODULES];
    pe_image    pes[MAX_MODULES];
    int         npaths = 0, nmods = 0, i;
    unsigned    idle_ms = 250u, max_seconds = 600u;
    int         diagnose = 0;
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
                "[--max-seconds <n>] [--diagnose-entries] <file> [<file>...]\n");
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
        queued = sweep_add_module(job, paths[i], mid, imgs[i], lens[i], &pes[i]);
        if (queued < 0) printf("  warning: %s has no sweepable code\n", paths[i]);
        else            printf("  queued %d entry point(s) from %s\n", queued,
                               paths[i]);
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

    sweep_free(job);
    ptc_free(cache);
    for (i = 0; i < nmods; i++) free(imgs[i]);

    return prog.phase == SWEEP_DONE ? 0 : 3;
}
