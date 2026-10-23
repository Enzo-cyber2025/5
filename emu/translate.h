/* x86-64 -> ARM64 translation for an explicit, deliberately small subset.
 *
 * The subset is stated rather than implied, and anything outside it is refused
 * with a reason instead of being approximated. That is the same rule the decoder
 * follows, for the same reason: a translation that is silently wrong gets cached,
 * gets executed, and nothing downstream can detect it.
 *
 * Supported by tr_translate_function, which handles control flow:
 *   mov  r64, imm32        (sign-extended; materialised with MOVZ + MOVK)
 *   mov  r64, r64
 *   xor  r64, r64          (the zeroing idiom; a real two-operand xor is refused)
 *   add  r64, r64 | imm    (immediate must fit in 12 bits, else refused)
 *   sub  r64, r64 | imm    (likewise)
 *   cmp  r64, r64 | imm    (SUBS / CMN; leaves usable flags)
 *   test r64, r64          (TST; leaves usable flags)
 *   jcc  rel8 | rel32      (14 of the 16 conditions; JP/JNP are refused)
 *   jmp  rel8 | rel32      (within the function only)
 *   call [rip+disp32]      (an indirect call through an import table)
 *   ret
 *
 * tr_translate_run is the earlier straight-line form and is kept because the sweep
 * uses it: it stops at the first RET and refuses any branch.
 *
 * Not supported, and refused: memory operands other than the RIP-relative import
 * slot, the stack and every instruction that touches it, RSP and RBP as operands,
 * SIMD, string and REP forms, and every prefix that changes meaning.
 *
 * ---- flags ----
 *
 * x86-64 sets flags on nearly every arithmetic instruction; AArch64 sets them only
 * on the S-suffixed forms. Emitting a plain ADD where the guest had one, and then
 * letting a conditional branch read the result, would read flags nobody computed.
 * So the translator tracks which instruction last left usable flags, and a
 * conditional branch is accepted only when the instruction immediately before it,
 * contiguous in the guest stream, is a CMP or TEST that this translator models.
 * Two more guards follow from the same reasoning: a branch whose target is the
 * conditional branch itself is refused, because then the flags would come from
 * wherever the branch came from; and an ADD or SUB that the guest would have set
 * flags on emits the non-flag-setting form, which is correct only because nothing
 * downstream is allowed to read them.
 *
 * Where a CMP does precede the branch, the mapping is exact rather than
 * approximated. After SUBS, AArch64 N is x86 SF, Z is ZF, V is OF, and C is the
 * negation of CF - AArch64 sets C when there is no borrow, x86 sets CF when there
 * is one. That is why the condition codes below can be used directly, and why
 * CMP-with-a-negative-immediate has to become CMN instead of a negative SUBS.
 *
 * Register mapping: guest RAX,RCX,RDX,RBX -> X0..X3, RSI,RDI -> X4,X5, and
 * R8..R15 -> X6..X13. RSP and RBP are refused because using them implies a stack
 * model that does not exist. X16 (AAPCS IP0) holds a resolved call target and is
 * free for a translator to clobber between the load and the branch.
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

/* ---- whole-function translation, with control flow ---- */

#define TRF_MAX_INSN   512u
#define TRF_MAX_WORDS  2048u

typedef struct {
    uint32_t    words[TRF_MAX_WORDS];
    size_t      n;
    uint32_t    insns;             /* guest instructions translated */
    uint32_t    guest_bytes;
    uint32_t    branches;          /* conditional and unconditional */
    uint32_t    backwards;         /* of those, how many jump backwards: loops */
    int         needs_frame;       /* contains a call, so X30 must be preserved */
    uint64_t    iat_va;            /* set with TR_NEEDS_TARGET */
    const char *detail;
} tr_func;

/* Translates a whole function starting at code[0], whose guest address is
 * guest_va, following direct branches wherever they lead inside the buffer.
 *
 * Three passes, because a branch displacement cannot be known until every
 * instruction's emitted size is: plan and count, lay out addresses, then emit.
 * Instruction sizes in ARM64 words do not depend on branch targets, so the layout
 * needs no fixpoint iteration.
 *
 * Returns TR_OK only if every reachable instruction translated and every branch
 * resolved inside the buffer. On any other result out->n may hold partial words,
 * which must not be executed. */
tr_status tr_translate_function(const uint8_t *code, size_t code_len,
                                uint64_t guest_va, tr_resolve_fn resolve,
                                void *user, tr_func *out);

const char *tr_status_name(tr_status s);

#endif /* TRANSLATE_H */
