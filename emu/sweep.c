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

    sweep_phase phase;
    size_t      translate_idx;
    int         finished;

    uint32_t entry_points;
    uint32_t indirect_unresolved;
    uint32_t decode_refusals;
    uint32_t blocks_translated;
    uint32_t blocks_untranslatable;
    uint32_t blocks_stored;
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
    }
    for (i = 0; i < pe->num_exports; i++) {
        const pe_export_fn *e = &pe->exports[i];
        if (e->forwarded || e->rva == 0) continue;
        if (wl_push(j, (uint32_t)(j->nmods - 1u), pe->image_base + e->rva))
            queued++;
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

/* Translates one block into host code, or returns 0 when it cannot.
 *
 * The only shape with a provably correct translation today is a block that is a
 * single 0xC3 RET: ARM64 RET has the same meaning, both return to the link
 * register / return address the caller set up, and no register or flag state is
 * touched. Everything else needs a lifter and a register allocation that do not
 * exist yet. Emitting a placeholder instead would not be a small shortcut - the
 * cache would later return a hit for it and the emulator would execute code that
 * has nothing to do with the guest bytes, with nothing to detect it. So the
 * honest result for those blocks is "not translated", counted and reported.
 */
static int translate_block(sweep_job *j, sweep_block *b)
{
    const smod *m = &j->mods[b->module];
    uint32_t    rva = (uint32_t)(b->guest_va - m->base);
    uint32_t    within = 0;
    const pe_section *sec;
    uint32_t    host[1];
    size_t      hlen = 0;

    if (b->kind != BLK_RET || b->len != 1) return 0;
    sec = find_exec(m->pe, rva, &within);
    if (!sec) return 0;
    if (m->image[sec->raw_ptr + within] != 0xC3u) return 0;

    if (!a64_emit(host, 1u, &hlen, a64_ret())) return 0;
    if (hlen != 1u) return 0;

    if (j->cache) {
        if (ptc_insert(j->cache, m->module_id, b->guest_va,
                       m->image + sec->raw_ptr + within, b->len,
                       host, (uint32_t)(hlen * 4u), 0u) != 0)
            return 0;
    }
    return 1;
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
        while (j->translate_idx < j->nblocks) {
            sweep_block *b;
            if (stop && stop(user)) return 0;
            b = &j->blocks[j->translate_idx++];
            if (translate_block(j, b)) {
                b->translated = 1;
                b->stored = j->cache ? 1 : 0;
                j->blocks_translated++;
                if (b->stored) j->blocks_stored++;
            } else {
                j->blocks_untranslatable++;
            }
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
    out->blocks_translated = j->blocks_translated;
    out->blocks_untranslatable = j->blocks_untranslatable;
    out->blocks_stored = j->blocks_stored;
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
