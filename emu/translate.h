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

/* Why a translation was refused, as a code rather than only as prose.
 *
 * A pre-translation sweep over a real binary refuses almost everything, and
 * "almost everything" is not actionable. With a reason code and the offending
 * opcode recorded, the same result becomes a ranked list of what to implement
 * next, ordered by how many functions each one unblocks. That list is the only
 * honest way to plan towards full coverage, because guessing which instruction
 * matters most is how a translator ends up implementing the wrong half.
 */
typedef enum {
    TRR_OK = 0,
    TRR_UNSUPPORTED_OP,   /* opcode outside the subset - the dominant case */
    TRR_DECODE,           /* the length decoder itself refused */
    TRR_PREFIX,           /* 66/67/F2/F3/LOCK/segment/REP changes the meaning */
    TRR_REGISTER,         /* operand uses a register with no host mapping */
    TRR_IMM_RANGE,        /* immediate does not fit an ARM64 12-bit field */
    TRR_FLAGS,            /* a branch would read flags this translator did not set */
    TRR_PARITY,           /* JP/JNP: AArch64 has no parity flag at all */
    TRR_XOR_TWO,          /* xor with two different operands, not the zero idiom */
    TRR_LEAVES_FUNC,      /* a branch targets outside the supplied buffer */
    TRR_NO_CODE,          /* the entry point is not inside executable code at all */
    TRR_NO_RET,           /* the function never reaches a RET */
    TRR_NEEDS_TARGET,     /* an import slot with no host address yet */
    TRR_OVERFLOW,         /* more instructions or words than the limits allow */
    TRR_INTERNAL,         /* the translator contradicted itself */
    TRR_COUNT
} tr_reason;

const char *tr_reason_name(tr_reason r);

typedef struct {
    uint32_t    words[TRF_MAX_WORDS];
    size_t      n;
    uint32_t    insns;             /* guest instructions translated */
    uint32_t    guest_bytes;       /* sum of their lengths */
    /* Byte range actually planned, relative to code[0]. With a whole section as
     * the buffer these are not 0 and extent: a function typically branches back
     * into shared helpers that sit before its entry point, so the low end matters.
     * They are what a cache key has to cover. */
    uint32_t    lo_off;
    uint32_t    hi_off;
    uint32_t    extent;            /* bytes from the entry to the last one planned.
                                    * Not the same as guest_bytes when branches
                                    * leave gaps, and it is the length a cache key
                                    * has to cover. */
    uint32_t    branches;          /* conditional and unconditional */
    uint32_t    backwards;         /* of those, how many jump backwards: loops */
    int         needs_frame;       /* contains a call, so X30 must be preserved */
    uint64_t    iat_va;            /* set with TR_NEEDS_TARGET */
    const char *detail;

    /* Valid only when the return status is not TR_OK: what was refused, and the
     * guest instruction that caused it. Captured from the decode rather than
     * reconstructed, so the opcode reported is the one the decoder saw, prefixes
     * and all. */
    tr_reason   reason;
    uint64_t    fail_va;
    uint8_t     fail_op[3];
    uint8_t     fail_op_len;
    uint8_t     fail_map;          /* 0=base, 1=0F, 2=0F38, 3=0F3A */
    uint8_t     fail_rex;
    uint8_t     fail_modrm;
    int         fail_has_modrm;
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

/* Same, but starting at code[start_off] while allowing branches anywhere inside
 * the whole buffer.
 *
 * This exists because bounding a function to "from its entry to the end of the
 * section" refuses almost every real one: compiled code branches backwards into
 * shared helpers that sit before the entry point, and an export is frequently a
 * thunk that jumps somewhere else entirely. Measured on a real application bundle,
 * that bound alone refused 451 of 515 functions before a single instruction was
 * even considered. Giving the translator the whole section and telling it where to
 * start separates "this code is outside the module" from "this code is outside an
 * arbitrary window I chose". */
tr_status tr_translate_function_at(const uint8_t *code, size_t code_len,
                                   uint64_t base_va, size_t start_off,
                                   tr_resolve_fn resolve, void *user,
                                   tr_func *out);

const char *tr_status_name(tr_status s);

#endif /* TRANSLATE_H */
