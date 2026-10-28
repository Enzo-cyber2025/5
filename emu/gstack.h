/* The guest stack arena.
 *
 * Why this exists separately from the translator. A guest function that begins
 * with `sub rsp, 0x28` - which is most of them - needs somewhere for that space
 * to be. Translating the adjustment without providing the memory produces code
 * that stores into whatever the register happened to hold, and the failure is
 * silent: it corrupts something else and gets cached. So the arena is a real,
 * separately allocated region, and the translator is entitled to assume X14
 * points into it.
 *
 * Why the guest stack pointer lives in a register rather than in the host SP.
 * AArch64 requires SP to be 16-byte aligned at every public interface; x86-64
 * only guarantees 8. Sharing the host SP would turn every odd-sized guest
 * adjustment into an alignment fault, and would also mean guest code and host
 * code interleaving in one region with no way to tell them apart afterwards.
 * X14 and X15 are callee-saved in the AAPCS, which gives a second benefit for
 * free: a host function reached through a resolved import preserves the guest
 * stack pointer across the call without the translator emitting anything.
 *
 * Why guard pages instead of bounds checks in the emitted code. A check costs
 * instructions on every push, and a loop that pushes on each iteration defeats
 * any bound computed once. PROT_NONE pages on both sides cost nothing at run
 * time and make a runaway guest stack fault immediately and precisely, at the
 * instruction that escaped, instead of quietly overwriting host memory. That is
 * the difference between a bug that is diagnosed and a bug that is discovered
 * much later in an unrelated component.
 *
 * The arena address is NOT baked into translated code. The caller passes it in
 * X14 at entry, which keeps a translation a pure function of the guest bytes
 * and therefore cacheable across processes and runs - persisting translated
 * output is a requirement, and embedding a per-process address would have made
 * every cache hit invalid on the next launch.
 */
#ifndef GSTACK_H
#define GSTACK_H

#include <stddef.h>
#include <stdint.h>

typedef struct {
    void    *map_base;     /* whole mapping, guards included: what munmap takes */
    size_t   map_size;
    char    *usable;       /* first writable byte */
    size_t   usable_size;  /* writable bytes, a whole number of pages */
    uint64_t top;          /* initial guest RSP: the high end, 16-byte aligned */
    int      guards;       /* 1 when PROT_NONE pages bound the usable region */
} gs_arena;

/* Allocates an arena of at least `bytes` writable bytes, rounded up to a page,
 * bounded by PROT_NONE guards. Returns 1 on success and fills *a; returns 0 on
 * failure, in which case gs_last_error says why and *a is zeroed.
 *
 * Failure is reported rather than papered over: if the arena cannot be had, the
 * right outcome is that stack-using code is not run at all, not that it is run
 * against an unguarded region. */
int gs_alloc(size_t bytes, gs_arena *a);

void gs_free(gs_arena *a);

const char *gs_last_error(void);

/* Is addr inside the writable region? Used by tests to state the containment
 * property directly rather than inferring it from the absence of a crash. */
int gs_contains(const gs_arena *a, uint64_t addr);

/* Bytes of the arena currently below the guest stack pointer, i.e. how much a
 * function has taken. Lets a test assert that a translated function left the
 * stack exactly as balanced as it found it. */
size_t gs_used(const gs_arena *a, uint64_t guest_rsp);

#endif /* GSTACK_H */
