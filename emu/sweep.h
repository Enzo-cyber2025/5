/* Pre-translation sweep - the part of "translate while the screen is off".
 *
 * What this is. On Android the screen-off window is a WorkManager job with
 * setRequiresDeviceIdle, or a foreground service. The useful work inside that
 * window is a static sweep: start from the entry points, walk the code that is
 * reachable by following direct branches, decode it into basic blocks, translate
 * what can be translated, and put the result in the persistent cache so that
 * when the app is actually used the blocks are already there.
 *
 * What this is not. It does not replace the JIT. Indirect jumps, code generated
 * at run time and self-modifying code are not knowable statically, so they are
 * still translated during execution. This warms the cache.
 *
 * Two properties matter more than speed, and both are testable:
 *
 *   - It must be INTERRUPTIBLE and RESUMABLE. An idle window ends without
 *     warning: the screen comes on, the device gets hot, the battery drops, the
 *     OS reclaims the job. A sweep that cannot stop and continue later is
 *     useless in that window, and a sweep that restarts from scratch wastes the
 *     whole point of running it in the background. So sweep_run() returns when
 *     told and the job keeps its state; the next call continues exactly where it
 *     stopped, and no block is decoded twice.
 *
 *   - It must NOT store a translation it does not have. Storing a placeholder
 *     for a block that could not be translated would be worse than storing
 *     nothing: the cache would later return a hit, the emulator would execute
 *     code that does not correspond to the guest bytes, and nothing would
 *     detect it. Blocks with no correct translation are counted and reported,
 *     never cached.
 *
 * Progress reporting is deliberately explicit about what it does not know.
 * During discovery the denominator grows as the worklist is drained, so the
 * percentage is provisional and can move backwards; that is the truth about
 * static discovery and it is flagged rather than smoothed over. During
 * translation the block count is known and the percentage is exact.
 */
#ifndef SWEEP_H
#define SWEEP_H

#include <stddef.h>
#include <stdint.h>

#include "pe_load.h"
#include "ptc.h"
#include "translate.h"

typedef enum {
    SWEEP_DISCOVER = 0,   /* draining the worklist, decoding basic blocks */
    SWEEP_TRANSLATE,      /* translating and storing the discovered blocks */
    SWEEP_DONE
} sweep_phase;

typedef enum {
    BLK_FALLTHROUGH = 0,  /* ran into already-decoded code or a length cap */
    BLK_RET,
    BLK_JUMP_DIRECT,
    BLK_JUMP_INDIRECT,    /* target not knowable statically */
    BLK_COND,
    BLK_CALL_DIRECT,
    BLK_CALL_INDIRECT,
    BLK_REFUSED           /* the decoder refused somewhere inside the block */
} block_kind;

/* One discovered basic block. The bytes stay in the caller's image, so the
 * image must outlive the job. */
typedef struct {
    uint64_t   guest_va;     /* image_base + rva, the address the guest sees */
    uint32_t   module;       /* index into the job's module list */
    uint32_t   len;
    block_kind kind;
    int        translated;   /* a correct host translation exists */
    int        stored;       /* and it was written into the cache */
} sweep_block;

typedef struct {
    sweep_phase phase;
    int         provisional;      /* 1 while the denominator can still grow */
    uint32_t    percent_x10;      /* 0..1000 = tenths of a percent */
    uint64_t    eta_ns;           /* 0 when done, or before a rate exists */
    double      blocks_per_sec;

    uint32_t    modules;
    uint32_t    entry_points;
    uint32_t    blocks;           /* discovered, for measuring reachable code */

    /* The unit of pre-translation is a FUNCTION, not a basic block: a block on its
     * own has no entry state and no way to leave, so translating one in isolation
     * produces something the cache can serve but nothing can call. Counting blocks
     * is still how reachable code is measured, which is a different question from
     * how much was pre-translated. */
    uint32_t    functions_attempted;
    uint32_t    functions_translated;
    uint32_t    functions_refused;
    /* Refused at the entry point's first instruction, or after translating for a
     * while. Different causes, different fixes: the first says the subset does not
     * cover the prologue, the second says discovery reached something further in -
     * possibly data lying inside a code section. */
    uint32_t    refused_at_first_insn;
    uint32_t    refused_deeper;
    uint32_t    deepest_refusal;
    /* Of the functions that did translate, how many use the guest stack and so
     * need an arena in X14 at call time. Reported because it is the difference
     * between "we produced N translations" and "we can run N translations". */
    uint32_t    functions_needing_gstack;
    uint64_t    host_code_bytes;  /* ARM64 bytes actually written to the cache */
    uint32_t    indirect_unresolved;
    uint32_t    decode_refusals;
    uint32_t    worklist_pending;
    uint64_t    guest_bytes;
    uint64_t    decode_calls;     /* == blocks when resuming correctly */
    uint64_t    elapsed_ns;
} sweep_progress;

typedef struct sweep_job sweep_job;

/* Called between blocks. Return non-zero to stop now; the job stays resumable.
 * This is where the Android side hooks the idle window ending. */
typedef int (*sweep_stop_fn)(void *user);

/* Largest span of executable virtual address space a module may cover, so the
 * visited bitmap cannot be made to allocate without bound by a hostile header. */
#define SWEEP_VA_SPAN_MAX (128u * 1024u * 1024u)

/* Longest basic block followed before giving up on it. Real blocks are far
 * shorter; the cap exists so a pathological branch chain cannot run forever. */
#define SWEEP_BLOCK_MAX_BYTES 4096u

sweep_job *sweep_begin(ptc_cache *cache);
void       sweep_free(sweep_job *j);

/* Registers a module and queues its entry points: the executable's entry point,
 * and for a DLL every non-forwarded export, because starting only from DllMain
 * would leave most of a DLL's code undiscovered. pe and image are borrowed and
 * must outlive the job. Returns the number of entry points queued, or -1. */
int sweep_add_module(sweep_job *j, const char *name, uint64_t module_id,
                     const uint8_t *image, size_t len, const pe_image *pe);

/* Runs until the sweep is finished or stop() says to stop. Returns 1 when
 * finished, 0 when interrupted. Pass stop=NULL to run to completion. */
int sweep_run(sweep_job *j, sweep_stop_fn stop, void *user);

void sweep_get_progress(const sweep_job *j, sweep_progress *out);

/* The discovered blocks, for inspection and testing. */
uint32_t             sweep_block_count(const sweep_job *j);
const sweep_block   *sweep_block_at(const sweep_job *j, uint32_t i);

/* Refusal accounting. Over a real binary almost every function is refused, and
 * the ranked list of why is what turns that from a dead end into a work queue. */
uint32_t sweep_reason_count(const sweep_job *j, tr_reason r);

/* The rank-th most common refused opcode, by map and byte. Returns its count, or
 * 0 when there are not that many distinct ones. */
uint32_t sweep_top_opcode(const sweep_job *j, uint32_t rank,
                          uint8_t *out_map, uint8_t *out_opcode);

/* Why a refusal happened, in the translator's own words. sweep_reason_count says
 * which rule fired and sweep_top_opcode says which instruction it stopped at;
 * these say which sentence that instruction was refused with, which is the level
 * that separates "an import cell nobody answered" from "a call through a vtable"
 * inside one opcode's count.
 *
 * sweep_top_detail returns the rank-th most common sentence's count and, through
 * out_text, the sentence itself - a pointer owned by the translator, valid for as
 * long as the job is. Returns 0 once the ranks run out. Sentences seen after the
 * table is full are counted by sweep_detail_overflow rather than dropped silently,
 * because a histogram that stops recording without saying so reports a smaller
 * world than the one it measured. */
#define SWEEP_DETAIL_MAX 48u

/* Every import cell a translated function was made to call through, as a module id
 * and an offset within it, in the order the sweep met them. The emitted code loads the target out of the cell
 * at run time and that load is safe - the cell is inside the mapped image - but
 * nothing checks what the cell holds. A cell the loader never filled still contains
 * the file's raw value, an RVA or a name pointer, and branching to it is a fault in
 * unmapped memory. This list exists so a harness can guarantee the invariant instead
 * of hoping for it: every cell reachable from translated code holds either a known
 * host function or a trap stub.
 *
 * Not a guest VA, because a guest VA cannot be turned back into a module: a declared
 * image base is a preference, two modules may declare the same one, and then their
 * guest VA ranges coincide exactly. A module id is the one unambiguous handle on a
 * mapping, and it is what the harness that stubs these cells selects by - it has to
 * write into the same mapping the executing code will read, and that code gets its
 * base from the record's module.
 *
 * Entries repeat when several functions call the same import, which they usually do.
 * Stubbing is idempotent, so deduplicating here would cost a lookup on every resolve
 * to save a redundant store. sweep_import_cell_at returns 0 past the end. */
#define SWEEP_CELL_MAX 65536u
size_t   sweep_import_cell_count(const sweep_job *j);
int      sweep_import_cell_at(const sweep_job *j, size_t i,
                              uint64_t *out_module_id, uint64_t *out_rva);
size_t   sweep_import_cell_overflow(const sweep_job *j);
uint32_t    sweep_detail_kinds(const sweep_job *j);
uint32_t    sweep_detail_overflow(const sweep_job *j);
uint32_t    sweep_top_detail(const sweep_job *j, uint32_t rank, const char **out_text);

const char *sweep_phase_name(sweep_phase p);
const char *sweep_block_kind_name(block_kind k);

#endif /* SWEEP_H */

/* Installs the resolver every translation in the next sweep will use, or clears it
 * when both arguments are NULL. A resolver that answers with an IAT slot's RVA tagged
 * TR_ABI_HOST | TR_ABI_INDIRECT lets the sweep translate a function that calls an
 * import without any host address being known at sweep time; the slot is filled in
 * later, before the code runs. See shim.h. */
void sweep_set_resolver(tr_resolve_fn resolve, void *user);
