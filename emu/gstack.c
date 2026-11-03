/* MAP_ANONYMOUS lives behind __USE_MISC in glibc, which -std=c11 turns off by
 * defining __STRICT_ANSI__. Whether the mmap flag is visible therefore depends on
 * which glibc a build happens to use: it is exposed on the aarch64 runner's 2.39
 * and hidden on 2.36, so the same source compiled here and failed there. Asking
 * for the default feature set explicitly removes that dependency instead of
 * leaving it to be rediscovered on the next toolchain. */
#ifndef _DEFAULT_SOURCE
#define _DEFAULT_SOURCE 1
#endif

#include "gstack.h"

#include <stdio.h>
#include <string.h>
#include <unistd.h>

#include <sys/mman.h>

static char errbuf[160];

const char *gs_last_error(void) { return errbuf; }

static size_t page_size(void)
{
    long p = sysconf(_SC_PAGESIZE);
    return (p > 0) ? (size_t)p : 4096u;
}

int gs_alloc(size_t bytes, gs_arena *a)
{
    size_t pg, usable, total;
    unsigned char *p;

    if (!a) { snprintf(errbuf, sizeof errbuf, "no arena struct supplied"); return 0; }
    memset(a, 0, sizeof *a);
    if (bytes == 0) { snprintf(errbuf, sizeof errbuf, "arena size is zero"); return 0; }

    pg = page_size();
    usable = ((bytes + pg - 1u) / pg) * pg;
    if (usable < bytes) {
        snprintf(errbuf, sizeof errbuf, "arena size %zu overflowed when rounded", bytes);
        return 0;
    }
    /* One guard page on each side. The low guard is the one that matters: a
     * stack grows down, so a runaway guest function walks off the bottom. The
     * high guard catches a pop or a positive displacement past the top, which
     * would otherwise read whatever the allocator put there next. */
    total = pg + usable + pg;
    if (total <= usable) {
        snprintf(errbuf, sizeof errbuf, "arena mapping size overflowed");
        return 0;
    }

    p = (unsigned char *)mmap(NULL, total, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (p == MAP_FAILED) {
        snprintf(errbuf, sizeof errbuf, "mmap of %zu bytes failed", total);
        return 0;
    }
    if (mprotect(p + pg, usable, PROT_READ | PROT_WRITE) != 0) {
        snprintf(errbuf, sizeof errbuf, "mprotect of the usable region failed");
        munmap(p, total);
        return 0;
    }

    a->map_base    = p;
    a->map_size    = total;
    a->usable      = (char *)(p + pg);
    a->usable_size = usable;
    /* GS_TOP_HEADROOM below the high end of the usable region, and that is a
     * correctness fix rather than a nicety. This value is the initial guest RSP, and
     * on real x86-64 at function entry [rsp] holds the return address the caller
     * pushed - so it is readable. Setting the initial RSP to one-past-the-last-usable
     * byte, as this did, put it in the high guard page instead, and every function
     * that executed a `pop`, a `leave`, or any load at [rsp+d] faulted on its first
     * such instruction. Measured on a real game module: 86 records died that way, all
     * of them reported as faults ABOVE the stack, which is what finally separated it
     * from the runaway-stack-pointer explanation the same number had been given.
     *
     * A `push` never noticed, because it pre-decrements and so wrote below the top.
     * That is why 185 other records in the same run returned normally and this looked
     * like an occasional crash rather than a wrong definition.
     *
     * Still 16-byte aligned: usable_end is page aligned, so subtracting a multiple of
     * 16 preserves it, and the mask states the invariant instead of relying on it. */
    a->top         = ((uint64_t)(uintptr_t)(p + pg + usable) - GS_TOP_HEADROOM)
                     & ~(uint64_t)15u;
    a->guards      = 1;
    errbuf[0] = '\0';
    return 1;
}

void gs_free(gs_arena *a)
{
    if (!a || !a->map_base) return;
    munmap(a->map_base, a->map_size);
    memset(a, 0, sizeof *a);
}

int gs_contains(const gs_arena *a, uint64_t addr)
{
    uint64_t lo, hi;
    if (!a || !a->usable) return 0;
    lo = (uint64_t)(uintptr_t)a->usable;
    hi = lo + (uint64_t)a->usable_size;
    return addr >= lo && addr < hi;
}

size_t gs_used(const gs_arena *a, uint64_t guest_rsp)
{
    if (!a || !a->usable) return 0;
    if (guest_rsp > a->top) return 0;          /* above the top: nothing taken */
    return (size_t)(a->top - guest_rsp);
}
