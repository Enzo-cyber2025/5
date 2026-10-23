/* x86-64 -> ARM64 translation for an explicit, deliberately small subset.
 *
 * The subset is stated rather than implied, and anything outside it is refused
 * with a reason instead of being approximated. That is the same rule the decoder
 * follows, for the same reason: a translation that is silently wrong gets cached,
 * gets executed, and nothing downstream can detect it.
 *
 * Supported in this revision:
 *   mov  r64, imm32        (sign-extended; materialised with MOVZ + MOVK)
 *   mov  r64, r64          (RAX and RCX only)
 *   add  r64, imm          (immediate must fit in 12 bits, else refused)
 *   sub  r64, imm          (likewise)
 *   call [rip+disp32]      (an indirect call through an import table)
 *   ret
 *
 * Not supported, and refused: flags and every conditional branch, memory
 * operands other than the RIP-relative import slot, the stack, every register
 * except RAX and RCX, SIMD, and every prefix that changes meaning. A real
 * application uses all of these constantly - measured on one shipped bundle, this
 * subset covers 0.05% of its basic blocks.
 *
 * Register mapping for this revision: guest RAX -> X0, guest RCX -> X1. X16
 * holds a resolved call target, which AAPCS designates IP0 and so is free for a
 * translator to clobber between the load and the branch.
 */
#ifndef TRANSLATE_H
#define TRANSLATE_H

#include <stddef.h>
#include <stdint.h>

typedef enum {
    TR_OK = 0,          /* translated; ended on RET */
    TR_UNSUPPORTED,     /* legal x86-64, outside the subset */
    TR_INVALID,         /* not a legal instruction */
    TR_NEEDS_TARGET,    /* indirect call whose host address is not known yet */
    TR_OVERFLOW         /* output buffer too small for the translation */
} tr_status;

#define TR_MAX_WORDS 64

/* Returns the host address to call for a guest import-table slot, or 0 when it
 * is not known yet. The loader supplies this: imports are resolved before code
 * runs, which is what makes the target a constant at translation time. */
typedef uint64_t (*tr_resolve_fn)(uint64_t guest_iat_va, void *user);

typedef struct {
    uint32_t    words[TR_MAX_WORDS];
    size_t      n;
    uint32_t    guest_insns;   /* guest instructions translated */
    uint32_t    guest_bytes;   /* guest bytes consumed */
    uint64_t    iat_va;        /* set when TR_NEEDS_TARGET: the slot needed */
    const char *detail;
} tr_output;

/* Translates a straight-line run of guest code starting at code[0], whose guest
 * address is guest_va, stopping after the first RET. code_len must cover at
 * least the whole run.
 *
 * Returns TR_OK only if the run ended on a RET and every instruction was
 * translated. On any other result out->n still holds the words emitted so far,
 * which must NOT be executed: a prefix of a function is not a function. */
tr_status tr_translate_run(const uint8_t *code, size_t code_len,
                           uint64_t guest_va, tr_resolve_fn resolve, void *user,
                           tr_output *out);

const char *tr_status_name(tr_status s);

#endif /* TRANSLATE_H */
