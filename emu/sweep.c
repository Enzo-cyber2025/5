/* Pre-translation sweep - see sweep.h for the design rules.
 *
 * Discovery is recursive traversal, not linear scan. Linear sweeping of x86
 * produces plausible-looking instructions at offsets that are really the middle
 * of another instruction or of data, and a translator that warmed its cache with
 * those would be storing fiction. Following direct branches from real entry
 * points only ever decodes at addresses control flow can actually reach.
 *
 * The cost of that choice is honest and reported: an indirect jump ends a block
 * and its target is counted as unresolved, because it is not knowable
 * statically. Those paths stay cold and get translated at run time.
 */
#define _POSIX_C_SOURCE 199309L

#include "sweep.h"

#include "a64_emit.h"
#include "translate.h"
#include "x86_decode.h"

#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef struct {
    uint32_t mod;
    uint64_t va;
} wl_entry;

typedef struct {
    const uint8_t *image;
    size_t         len;
    uint64_t       module_id;
    const pe_image *pe;
    const char    *name;
    uint64_t       base;              /* image_base: guest VA = base + rva */
    uint64_t       va_lo, va_hi;      /* span of executable VA, for the bitmap */
    uint8_t       *visited;           /* one bit per byte in [va_lo, va_hi) */
    size_t         visited_bytes;
} smod;

struct sweep_job {
    ptc_cache *cache;

    smod  *mods;  size_t nmods, capmods;
    wl_entry *wl; size_t wl_n, wl_cap, wl_head;
    sweep_block *blocks; size_t nblocks, capblocks;

    /* Entry points, kept separately from the discovery worklist because they are
     * also the units of pre-translation. The worklist is consumed by discovery and
     * would be empty by the time translation starts. */
    struct { uint32_t mod; uint64_t va; } *entries;
    size_t      nentries, capentries;

    uint32_t    reason_hist[TRR_COUNT];
    uint32_t    opcode_hist[4][256];
    uint32_t    refused_at_first_insn;
    uint32_t    refused_deeper;
    uint32_t    deepest_refusal;

    sweep_phase phase;
    size_t      translate_idx;
    int         finished;

    uint32_t entry_points;
    uint32_t indirect_unresolved;
    uint32_t decode_refusals;
    uint32_t functions_attempted;
    uint32_t functions_translated;
    uint32_t functions_refused;
    uint64_t host_code_bytes;
    uint64_t guest_bytes;
    uint64_t decode_calls;

    uint64_t t_start_ns;
    uint64_t t_phase_ns;
};

/* ------------------------------------------------------------------ timing */

static uint64_t now_ns(void)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) return 0;
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}

const char *sweep_phase_name(sweep_phase p)
{
    switch (p) {
    case SWEEP_DISCOVER:  return "discover";
    case SWEEP_TRANSLATE: return "translate";
    case SWEEP_DONE:      return "done";
    default:              return "?";
    }
}

const char *sweep_block_kind_name(block_kind k)
{
    switch (k) {
    case BLK_FALLTHROUGH:   return "fallthrough";
    case BLK_RET:           return "ret";
    case BLK_JUMP_DIRECT:   return "jump-direct";
    case BLK_JUMP_INDIRECT: return "jump-indirect";
    case BLK_COND:          return "conditional";
    case BLK_CALL_DIRECT:   return "call-direct";
    case BLK_CALL_INDIRECT: return "call-indirect";
    case BLK_REFUSED:       return "refused";
    default:                return "?";
    }
}

/* ------------------------------------------------------------ growables */

static void *xrealloc(void *p, size_t n)
{
    void *r = realloc(p, n ? n : 1u);
    if (!r) { /* allocation failure is fatal here: there is no partial sweep */
        free(p);
        return NULL;
    }
    return r;
}

static int wl_push(sweep_job *j, uint32_t mod, uint64_t va)
{
    if (j->wl_n + 1u > j->wl_cap) {
        size_t  nc = j->wl_cap ? j->wl_cap * 2u : 256u;
        wl_entry *nw = xrealloc(j->wl, nc * sizeof(*nw));
        if (!nw) return 0;
        j->wl = nw; j->wl_cap = nc;
    }
    j->wl[j->wl_n].mod = mod;
    j->wl[j->wl_n].va  = va;
    j->wl_n++;
    return 1;
}

static int entry_push(sweep_job *j, uint32_t mod, uint64_t va)
{
    if (j->nentries + 1u > j->capentries) {
        size_t nc = j->capentries ? j->capentries * 2u : 64u;
        void  *ne = xrealloc(j->entries, nc * sizeof(*j->entries));
        if (!ne) return 0;
        j->entries = ne;
        j->capentries = nc;
    }
    j->entries[j->nentries].mod = mod;
    j->entries[j->nentries].va  = va;
    j->nentries++;
    return 1;
}

static int block_push(sweep_job *j, const sweep_block *b)
{
    if (j->nblocks + 1u > j->capblocks) {
        size_t nc = j->capblocks ? j->capblocks * 2u : 256u;
        sweep_block *nb = xrealloc(j->blocks, nc * sizeof(*nb));
        if (!nb) return 0;
        j->blocks = nb; j->capblocks = nc;
    }
    j->blocks[j->nblocks++] = *b;
    return 1;
}

/* ------------------------------------------------------- module geometry */

static int in_span(const smod *m, uint64_t va)
{
    return va >= m->va_lo && va < m->va_hi;
}

static int vis_get(const smod *m, uint64_t va)
{
    uint64_t i;
    if (!m->visited || !in_span(m, va)) return 0;
    i = va - m->va_lo;
    return (int)((m->visited[i >> 3] >> (i & 7u)) & 1u);
}

static void vis_set(smod *m, uint64_t va)
{
    uint64_t i;
    if (!m->visited || !in_span(m, va)) return;
    i = va - m->va_lo;
    m->visited[i >> 3] |= (uint8_t)(1u << (i & 7u));
}

/* Finds the executable section holding rva and reports how far into it rva is.
 * Only sections marked executable are searched: decoding bytes from a data
 * section would invent instructions that no control flow ever reaches. */
static const pe_section *find_exec(const pe_image *pe, uint32_t rva,
                                   uint32_t *within)
{
    uint32_t i;
    for (i = 0; i < pe->num_sections; i++) {
        const pe_section *s = &pe->sections[i];
        uint32_t span = s->virtual_size;
        if (!(s->characteristics & PE_SCN_MEM_EXECUTE)) continue;
        if (span == 0 || rva < s->virtual_addr) continue;
        if (rva - s->virtual_addr >= span) continue;
        /* The zero-filled tail of a section has no file bytes to decode. */
        if (rva - s->virtual_addr >= s->raw_size) continue;
        *within = rva - s->virtual_addr;
        return s;
    }
    return NULL;
}

/* ------------------------------------------------------------------ setup */

sweep_job *sweep_begin(ptc_cache *cache)
{
    sweep_job *j = calloc(1, sizeof(*j));
    if (!j) return NULL;
    j->cache = cache;
    j->phase = SWEEP_DISCOVER;
    return j;
}

void sweep_free(sweep_job *j)
{
    size_t i;
    if (!j) return;
    for (i = 0; i < j->nmods; i++) free(j->mods[i].visited);
    free(j->mods);
    free(j->entries);
    free(j->wl);
    free(j->blocks);
    free(j);
}

int sweep_add_module(sweep_job *j, const char *name, uint64_t module_id,
                     const uint8_t *image, size_t len, const pe_image *pe)
{
    smod    *m;
    uint64_t lo = 0, hi = 0, span;
    uint32_t i, queued = 0;
    int      first = 1;

    if (!j || !image || !pe) return -1;

    /* Executable VA span, for the visited bitmap. */
    for (i = 0; i < pe->num_sections; i++) {
        const pe_section *s = &pe->sections[i];
        uint64_t a, b;
        if (!(s->characteristics & PE_SCN_MEM_EXECUTE)) continue;
        if (s->virtual_size == 0 || s->raw_size == 0) continue;
        a = pe->image_base + s->virtual_addr;
        b = a + s->virtual_size;
        if (first) { lo = a; hi = b; first = 0; }
        else { if (a < lo) lo = a; if (b > hi) hi = b; }
    }
    if (first) return -1;                 /* no executable section at all */
    span = hi - lo;
    if (span > SWEEP_VA_SPAN_MAX) return -1;

    if (j->nmods + 1u > j->capmods) {
        size_t nc = j->capmods ? j->capmods * 2u : 8u;
        smod  *nm = xrealloc(j->mods, nc * sizeof(*nm));
        if (!nm) return -1;
        j->mods = nm; j->capmods = nc;
    }
    m = &j->mods[j->nmods];
    memset(m, 0, sizeof(*m));
    m->image = image; m->len = len; m->module_id = module_id;
    m->pe = pe; m->name = name ? name : "?";
    m->base = pe->image_base; m->va_lo = lo; m->va_hi = hi;
    m->visited_bytes = (size_t)((span + 7u) / 8u);
    m->visited = calloc(m->visited_bytes, 1u);
    if (!m->visited) return -1;
    j->nmods++;

    /* Entry points. An executable has one; a DLL has as many as it exports, and
     * starting from DllMain alone would leave most of a DLL undiscovered. */
    if (pe->entry_rva != 0) {
        if (wl_push(j, (uint32_t)(j->nmods - 1u), pe->image_base + pe->entry_rva))
            queued++;
        entry_push(j, (uint32_t)(j->nmods - 1u), pe->image_base + pe->entry_rva);
    }
    for (i = 0; i < pe->num_exports; i++) {
        const pe_export_fn *e = &pe->exports[i];
        if (e->forwarded || e->rva == 0) continue;
        if (wl_push(j, (uint32_t)(j->nmods - 1u), pe->image_base + e->rva))
            queued++;
        entry_push(j, (uint32_t)(j->nmods - 1u), pe->image_base + e->rva);
    }
    j->entry_points += queued;
    return (int)queued;
}

/* ------------------------------------------------------------- discovery */

static void discover_one(sweep_job *j, uint32_t mi, uint64_t va)
{
    smod        *m = &j->mods[mi];
    uint64_t     cur = va;
    uint32_t     blk_len = 0;
    block_kind   kind = BLK_FALLTHROUGH;
    sweep_block  b;

    while (blk_len < SWEEP_BLOCK_MAX_BYTES) {
        uint32_t rva = (uint32_t)(cur - m->base);
        uint32_t within = 0;
        const pe_section *sec;
        x86_insn ins;
        x86_status st;
        size_t avail, need;
        uint8_t k;

        if (vis_get(m, cur)) { kind = BLK_FALLTHROUGH; break; }  /* tail merge */
        sec = find_exec(m->pe, rva, &within);
        if (!sec) { kind = BLK_REFUSED; j->decode_refusals++; break; }

        avail = (size_t)sec->raw_size - within;
        need  = avail > 15u ? 15u : avail;
        st = x86_decode(m->image + sec->raw_ptr + within, need, cur, &ins);
        j->decode_calls++;
        if (st != X86_OK || ins.len == 0 || ins.len > need) {
            kind = BLK_REFUSED; j->decode_refusals++; break;
        }
        for (k = 0; k < ins.len; k++) vis_set(m, cur + k);
        cur += ins.len;
        blk_len += ins.len;
        j->guest_bytes += ins.len;

        if (ins.flags & X86F_RET) { kind = BLK_RET; break; }

        if (ins.flags & X86F_BRANCH) {
            int is_call = (ins.flags & X86F_CALL) != 0;
            int is_ind  = (ins.flags & X86F_INDIRECT) != 0;
            int is_cond = (ins.flags & X86F_COND) != 0;

            if (is_ind) {
                j->indirect_unresolved++;
                if (is_call) {
                    /* An indirect call returns, so the block continues; only the
                     * callee is unknown. */
                    kind = BLK_CALL_INDIRECT;
                    continue;
                }
                kind = BLK_JUMP_INDIRECT;
                break;
            }
            /* For rel8/rel32 the decoder stores imm sign-extended, and the
             * displacement is relative to the end of the instruction. */
            {
                uint64_t target = cur + (uint64_t)(int64_t)ins.imm;
                if (is_call) {
                    if (in_span(m, target)) wl_push(j, mi, target);
                    else j->decode_refusals++;
                    kind = BLK_CALL_DIRECT;
                    continue;              /* the call returns; keep decoding */
                }
                if (is_cond) {
                    if (in_span(m, target)) wl_push(j, mi, target);
                    else j->decode_refusals++;
                    if (in_span(m, cur)) wl_push(j, mi, cur);
                    kind = BLK_COND;
                    break;
                }
                if (in_span(m, target)) wl_push(j, mi, target);
                else j->decode_refusals++;
                kind = BLK_JUMP_DIRECT;
                break;
            }
        }
    }

    memset(&b, 0, sizeof(b));
    b.guest_va = va;
    b.module   = mi;
    b.len      = blk_len;
    b.kind     = blk_len ? kind : BLK_REFUSED;
    block_push(j, &b);
}

/* ----------------------------------------------------------- translation */

/* Pre-translates one FUNCTION, starting at an entry point.
 *
 * The earlier version of this translated single basic blocks, and could only ever
 * handle a block consisting of one bare RET: a block in isolation has no defined
 * entry state and no way to leave, so there is nothing correct to emit for almost
 * any of them. It reported 7 blocks translated out of 12770 on a real bundle,
 * which measured the size of the shortcut rather than the state of the translator.
 * A function is the smallest unit that is actually callable and cacheable.
 *
 * Imports are deliberately not resolved here. A pre-translation sweep runs before
 * anything is loaded, so no host address exists for an imported function yet; a
 * function that calls one is recorded as refused with TRR_NEEDS_TARGET rather than
 * translated against a guess. Fixing that needs an indirection cell patched at
 * load time, which is a runtime feature and not something a cache-warming pass can
 * invent on its own.
 */
static int translate_entry(sweep_job *j, uint32_t mi, uint64_t va)
{
    smod    *m = &j->mods[mi];
    uint32_t rva = (uint32_t)(va - m->base);
    uint32_t within = 0;
    const pe_section *sec;
    tr_func  f;
    tr_status st;
    size_t   avail;

    sec = find_exec(m->pe, rva, &within);
    if (!sec) {
        /* Reported separately from a branch leaving the buffer, because the two
         * have completely different causes and completely different fixes. Lumping
         * them together produced a histogram whose largest entry was ambiguous, and
         * an ambiguous work queue is worse than none: it sends the next change at
         * the wrong thing. It did exactly that here. */
        j->reason_hist[TRR_NO_CODE]++;
        j->functions_refused++;
        return 0;
    }
    avail = (size_t)sec->raw_size - within;
    if (avail == 0) {
        j->reason_hist[TRR_NO_CODE]++;
        j->functions_refused++;
        return 0;
    }

    /* The whole section is the buffer and the entry point is where discovery
     * starts. Bounding the buffer to the entry instead refuses any function that
     * branches backwards into shared code, which is most of them. */
    st = tr_translate_function_at(m->image + sec->raw_ptr, (size_t)sec->raw_size,
                                  m->base + sec->virtual_addr, within,
                                  NULL, NULL, &f);
    if (st != TR_OK) {
        tr_reason r = (f.reason < TRR_COUNT) ? f.reason : TRR_INTERNAL;
        j->reason_hist[r]++;
        /* Count an opcode only when the refusal actually came from planning that
         * instruction. Counting one for a later refusal attributes the failure to
         * whatever was decoded last, which is how a histogram ends up naming an
         * opcode no function contained - and then sends the next change after the
         * wrong thing. */
        if (!f.fail_from_plan && f.fail_map < 4u && f.fail_op_len > 0)
            j->opcode_hist[f.fail_map][f.fail_op[0]]++;
        if (f.fail_insns == 0) j->refused_at_first_insn++;
        else                   j->refused_deeper++;
        if (f.fail_insns > j->deepest_refusal) j->deepest_refusal = f.fail_insns;
        j->functions_refused++;
        return 0;
    }
    if (f.n == 0 || f.hi_off <= f.lo_off || f.hi_off > (uint32_t)sec->raw_size) {
        j->reason_hist[TRR_INTERNAL]++;
        j->functions_refused++;
        return 0;
    }

    if (j->cache) {
        /* Keyed on the whole extent, not on the sum of instruction lengths: a
         * function with branches has gaps, and hashing only the instruction bytes
         * would let two different functions with the same instructions collide. */
        /* Keyed on the entry point, but hashed over exactly the bytes the
         * function occupies. Those are not the same address once a function
         * branches back before its own entry, and hashing the whole window from
         * the section start would make unrelated code part of the identity. */
        if (ptc_insert(j->cache, m->module_id, va,
                       m->image + sec->raw_ptr + f.lo_off,
                       f.hi_off - f.lo_off,
                       f.words, (uint32_t)(f.n * 4u), 0u) != 0) {
            j->reason_hist[TRR_INTERNAL]++;
            j->functions_refused++;
            return 0;
        }
    }
    j->functions_translated++;
    j->host_code_bytes += (uint64_t)f.n * 4u;
    return 1;
}

uint32_t sweep_reason_count(const sweep_job *j, tr_reason r)
{
    if (!j || r >= TRR_COUNT) return 0;
    return j->reason_hist[r];
}

uint32_t sweep_top_opcode(const sweep_job *j, uint32_t rank,
                          uint8_t *out_map, uint8_t *out_opcode)
{
    uint32_t best_map = 0, best_op = 0, best = 0, seen = 0;
    uint8_t  taken_map[64];
    uint8_t  taken_op[64];
    uint32_t m, o, k;

    if (!j) return 0;
    if (rank >= 64u) return 0;
    memset(taken_map, 0xFF, sizeof(taken_map));
    memset(taken_op, 0xFF, sizeof(taken_op));

    /* Selection by repeated maximum. The table is 1024 entries and the rank
     * requested is small, so this is cheaper than sorting and has no allocation. */
    for (k = 0; k <= rank; k++) {
        best = 0;
        for (m = 0; m < 4u; m++) {
            for (o = 0; o < 256u; o++) {
                uint32_t c = j->opcode_hist[m][o];
                int dup = 0;
                if (c == 0) continue;
                for (seen = 0; seen < k; seen++)
                    if (taken_map[seen] == m && taken_op[seen] == o) { dup = 1; break; }
                if (dup) continue;
                if (c > best) { best = c; best_map = m; best_op = o; }
            }
        }
        if (best == 0) return 0;
        taken_map[k] = (uint8_t)best_map;
        taken_op[k] = (uint8_t)best_op;
    }
    if (out_map) *out_map = (uint8_t)best_map;
    if (out_opcode) *out_opcode = (uint8_t)best_op;
    return best;
}

/* ------------------------------------------------------------------- run */

int sweep_run(sweep_job *j, sweep_stop_fn stop, void *user)
{
    if (!j) return 1;
    if (j->phase == SWEEP_DONE) return 1;
    if (j->t_start_ns == 0) j->t_start_ns = now_ns();

    if (j->phase == SWEEP_DISCOVER) {
        while (j->wl_head < j->wl_n) {
            wl_entry e;
            if (stop && stop(user)) return 0;
            e = j->wl[j->wl_head++];
            if (!in_span(&j->mods[e.mod], e.va)) { j->decode_refusals++; continue; }
            if (vis_get(&j->mods[e.mod], e.va)) continue;   /* already covered */
            discover_one(j, e.mod, e.va);
        }
        j->phase = SWEEP_TRANSLATE;
        j->t_phase_ns = now_ns();
        j->translate_idx = 0;
    }

    if (j->phase == SWEEP_TRANSLATE) {
        while (j->translate_idx < j->nentries) {
            size_t e;
            /* The stop check comes BEFORE the entry is consumed, matching the
             * discovery loop. Consuming first and checking second loses an entry
             * every time the window closes: the index has moved on, so the next
             * resume skips a function that was never translated. That is silent
             * work loss in exactly the component whose whole purpose is to survive
             * being interrupted, and only the equivalence test against an
             * uninterrupted run catches it. */
            if (stop && stop(user)) return 0;
            e = j->translate_idx++;
            j->functions_attempted++;
            translate_entry(j, j->entries[e].mod, j->entries[e].va);
        }
        j->phase = SWEEP_DONE;
        j->finished = 1;
    }
    return 1;
}

/* -------------------------------------------------------------- progress */

void sweep_get_progress(const sweep_job *j, sweep_progress *out)
{
    uint64_t now, elapsed, phase_elapsed;
    double   rate;
    uint64_t pending, done, total;

    if (!out) return;
    memset(out, 0, sizeof(*out));
    if (!j) return;

    now = now_ns();
    elapsed = (j->t_start_ns && now > j->t_start_ns) ? now - j->t_start_ns : 0u;
    out->phase = j->phase;
    out->modules = (uint32_t)j->nmods;
    out->entry_points = j->entry_points;
    out->blocks = (uint32_t)j->nblocks;
    out->functions_attempted = j->functions_attempted;
    out->functions_translated = j->functions_translated;
    out->functions_refused = j->functions_refused;
    out->refused_at_first_insn = j->refused_at_first_insn;
    out->refused_deeper = j->refused_deeper;
    out->deepest_refusal = j->deepest_refusal;
    out->host_code_bytes = j->host_code_bytes;
    out->indirect_unresolved = j->indirect_unresolved;
    out->decode_refusals = j->decode_refusals;
    out->guest_bytes = j->guest_bytes;
    out->decode_calls = j->decode_calls;
    out->elapsed_ns = elapsed;
    out->worklist_pending = (uint32_t)(j->wl_n - j->wl_head);

    pending = j->wl_n - j->wl_head;
    total   = j->nblocks;
    done    = j->translate_idx;

    if (j->phase == SWEEP_DISCOVER) {
        /* The denominator grows while the worklist is drained, so this is
         * provisional and can move backwards. Discovery occupies 0-50%. */
        uint64_t denom = total + pending;
        out->provisional = 1;
        out->percent_x10 = denom ? (uint32_t)(total * 500u / denom) : 0u;
        phase_elapsed = elapsed;
        rate = phase_elapsed ? (double)total * 1e9 / (double)phase_elapsed : 0.0;
        out->blocks_per_sec = rate;
        out->eta_ns = (rate > 0.0 && pending)
                    ? (uint64_t)((double)pending / rate * 1e9) : 0u;
    } else if (j->phase == SWEEP_TRANSLATE) {
        out->provisional = 0;
        out->percent_x10 = 500u + (total ? (uint32_t)(done * 500u / total) : 500u);
        phase_elapsed = (j->t_phase_ns && now > j->t_phase_ns)
                      ? now - j->t_phase_ns : 0u;
        rate = phase_elapsed ? (double)done * 1e9 / (double)phase_elapsed : 0.0;
        out->blocks_per_sec = rate;
        out->eta_ns = (rate > 0.0 && done < total)
                    ? (uint64_t)((double)(total - done) / rate * 1e9) : 0u;
    } else {
        out->provisional = 0;
        out->percent_x10 = 1000u;
        out->eta_ns = 0u;
        phase_elapsed = elapsed;
        rate = phase_elapsed ? (double)total * 1e9 / (double)phase_elapsed : 0.0;
        out->blocks_per_sec = rate;
    }
}

uint32_t sweep_block_count(const sweep_job *j)
{
    return j ? (uint32_t)j->nblocks : 0u;
}

const sweep_block *sweep_block_at(const sweep_job *j, uint32_t i)
{
    if (!j || i >= j->nblocks) return NULL;
    return &j->blocks[i];
}
