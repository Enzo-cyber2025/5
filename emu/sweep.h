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

const char *sweep_phase_name(sweep_phase p);
const char *sweep_block_kind_name(block_kind k);

#endif /* SWEEP_H */
