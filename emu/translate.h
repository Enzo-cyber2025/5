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
 * Every form above also exists at 32-bit width - mov, add, sub, cmp, test, the
 * xor zeroing idiom, and GRP1 against an immediate - and the mapping is exact
 * rather than approximated. A 32-bit x86-64 operation zero-extends its result
 * into the full 64-bit register, and an AArch64 W-form zero-extends into the X
 * register: the same rule on both sides, so no mask is emitted and no upper half
 * has to be cleaned up. REX.W turns B8+r into `mov r64, imm64`, which is refused
 * rather than truncated to a plausible wrong constant.
 *
 * Supported by tr_translate_function, guest stack model (see gstack.h):
 *   push r64 | imm32 | imm8      (STR with pre-indexed writeback on X14)
 *   pop  r64                     (LDR with post-indexed writeback)
 *   leave                        (mov rsp,rbp; pop rbp)
 *   sub/add rsp, imm             (the frame adjustment a real prologue opens with)
 *   mov  rbp, rsp | rsp, rbp     (and any other reg-reg move involving them)
 *   mov  [rbp-disp], r64         (a stack local store, LDUR)
 *   mov  r64, [rbp-disp]         (a stack local load)
 *   mov  [rsp+disp], r64         (and the load form)
 *   mov  r64, [rsp+disp]
 *
 * Supported by tr_translate_function_img, the module's own image:
 *   mov  r64|r32, [rip+disp32]   (a load of one of the module's globals)
 *   mov  [rip+disp32], r64|r32   (and the store form)
 *
 * These reach a module's data, which is where almost every non-stack memory
 * operand in real code points. The emitted form materialises the RVA into X16 and
 * lets the access itself add it - `LDR Xt, [X19, X16]` - with X19 holding the host
 * address the image is mapped at, supplied by the caller on entry exactly as X14
 * holds the guest stack pointer.
 *
 * Resolving to an absolute host address at translation time instead would be
 * simpler and is deliberately not done: it would tie the translation to one
 * process's layout, break the persistent cache, and need a relocation. An RVA plus
 * a base register needs neither, so the same translated words stay valid wherever
 * the image is mapped.
 *
 * The target is bounded against image_size at translation time. A RIP-relative
 * displacement can reach anywhere in the address space, and one landing past the
 * mapping reads host memory and returns a plausible looking value that nothing at
 * run time would notice. tr_translate_function and tr_translate_function_at have no
 * image base to bound against, so they refuse these with TRR_IMG_BASE instead.
 *
 * tr_translate_run is the earlier straight-line form and is kept because the sweep
 * uses it: it stops at the first RET and refuses any branch.
 *
 * Not supported, and refused: a memory operand whose base is a general register -
 * there is still no general guest memory model, so a dereference through RAX or
 * RCX has nowhere to point. Absolute disp32 addressing is refused separately,
 * because it needs a relocation and no image base would fix it; the two used to
 * share one bucket, and a histogram that cannot tell them apart cannot say which
 * is worth doing next. Also refused: a
 * non-negative RBP displacement, because that addresses the caller's frame
 * (return address, incoming stack arguments) which this model does not lay out;
 * a negative RSP displacement, which is the SysV red zone and is unmapped below
 * the arena; `ret imm16`, which pops arguments and would leave the caller's
 * stack pointer disagreeing with the guest's; SIMD, string and REP forms; and
 * every prefix that changes meaning.
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
 * Register mapping: guest RAX,RCX,RDX,RBX -> X0..X3, RSI,RDI -> X4,X5,
 * R8..R15 -> X6..X13, guest RSP -> X14 and guest RBP -> X15. X16 (AAPCS IP0)
 * holds a resolved call target, or an immediate being pushed, and is free for a
 * translator to clobber between materialising it and using it.
 *
 * A translation that uses the guest stack saves and restores X14 and X15 as a
 * frame record. The record also makes the
 * guest stack pointer balanced at return unconditionally: whatever adjustment
 * the guest made, the epilogue puts X14 and X15 back to their entry values, so
 * an early return cannot hand a skewed stack pointer to the caller.
 *
 * ---- the two kinds of resolved call ----
 *
 * An untagged `call [rip+disp32]` emits BLR to the resolved address passing the
 * guest's register state unchanged, which is correct only when the callee is itself
 * translated guest code sharing this mapping.
 *
 * For a real host function the resolver tags the address with TR_ABI_HOST and the
 * call site emits the bridge: RCX,RDX,R8,R9 shuffled into the AAPCS positions
 * X0..X3, and the nine registers a host callee destroys but x86-64 requires
 * preserved saved and restored around the call.
 *
 * Those nine are the correction. This header used to claim X14 and X15 were
 * callee-saved in the AAPCS, so a host callee would preserve the guest stack and
 * frame pointers for free. AAPCS64 makes only X19-X28 callee-saved; X0-X18 are
 * caller-saved temporaries. So a host function destroys guest RSP (X14), RBP (X15)
 * and every x86-64 callee-saved register mapping below X19 - RBX, RSI, RDI,
 * R12-R15. The claim was load-bearing for a feature that did not exist yet, which
 * is the only reason it survived: nothing ever called a host function, so nothing
 * ever observed the guest stack pointer coming back as garbage.
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

/* 256, not the 64 this used to be. The host ABI bridge costs 16 words at every
 * call site, so a program making three import calls needs ~80 words for a body that
 * is only nine guest instructions. 64 could not hold a program that did anything,
 * and the limit is only an output buffer size. */
#define TR_MAX_WORDS 256

/* Returns the host address to call for a guest import-table slot, or 0 when it
 * is not known yet. The loader supplies this: imports are resolved before code
 * runs, which is what makes the target a constant at translation time. */
typedef uint64_t (*tr_resolve_fn)(uint64_t guest_iat_va, void *user);

/* Tag the resolver ORs into a returned address to say the target is a real host
 * function following the AAPCS, not translated guest code following the x86-64
 * convention. The translator masks it off before emitting and uses it to decide
 * whether to bridge.
 *
 * The tag is bit 63, and it was bit 0 until a test caught the reason that is wrong.
 * Bit 0 rests on code addresses being at least 4-byte aligned, which is true on
 * AArch64 - every instruction is four bytes - and FALSE on x86-64, where
 * instructions are variable length and a function may legitimately start at an odd
 * address. Measured on this host: `&abi_target` came back 0x55ec35b5a435, odd, for
 * an ordinary noinline static C function. A resolver returning that would be read
 * as "bridge this call" when the caller asked for the opposite, so the tag could
 * flip on a real address with no bug in the resolver at all.
 *
 * Bit 63 is free on both: user-space addresses are canonical and below 2^47 on
 * x86-64 and below 2^48 on AArch64 with 48-bit VA, so no function address this
 * translator can be handed ever sets it. Using a bit that is free on every host
 * rather than one that is free only on the host that happens to run the emitted
 * code is what makes the tag a property of the interface instead of an accident of
 * where the tests were compiled.
 *
 * Why a tag rather than a second callback: an untagged return keeps its exact
 * present meaning, so every existing resolver and test is unaffected, and a target
 * needing the bridge cannot be registered by accident through the old path.
 *
 * Not bridged: the fifth and later arguments, which x86-64 passes on the guest
 * stack. A shim needing them takes four or fewer parameters and supplies the rest
 * itself, which is what a wrapper is for. */
#define TR_ABI_HOST (1ULL << 63)

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

/* Largest guest buffer tr_translate_function_at will examine. The sweep hands it
 * a whole code section, because bounding a function to a window refuses almost
 * every real one; a shipped module's .text runs to hundreds of megabytes, so this
 * has to be large enough to be irrelevant in practice and small enough to reject
 * a nonsense length. */
#define TRF_MAX_CODE_BYTES (256u << 20)

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
    TRR_STACK,            /* a guest stack form this model does not lay out:
                           * the caller's frame above RBP, the red zone below
                           * RSP, or `ret imm16` */
    TRR_GUEST_MEM,        /* a memory operand whose base is not the guest stack:
                           * there is no general guest memory model, so a
                           * dereference through a general register has nowhere
                           * to point */
    TRR_BUFFER,           /* the buffer was rejected before a single instruction
                           * was decoded: too large, or a start offset past its
                           * end. Kept separate because it says the function was
                           * never examined, which is not a statement about its
                           * instructions and must not be counted as one. */
    TRR_IMG_BASE,         /* a RIP-relative access, which is translatable, but the
                           * module's image base and size were not supplied so the
                           * RVA cannot be computed or bounded */
    TRR_ABS_ADDR,         /* absolute disp32 addressing: the target is a guest
                           * virtual address baked into the instruction, so it
                           * needs a relocation, not a base register */
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
    /* Uses the guest stack, so the caller must have X14 pointing into a gs_arena
     * on entry. Distinct from needs_frame: a function can adjust its stack
     * pointer without calling anything. The arena address is deliberately not
     * part of the emitted code, so a translation stays a pure function of the
     * guest bytes and remains valid in a cache that outlives the process. */
    int         needs_gstack;
    /* Reads or writes the module's own image through a RIP-relative operand, so
     * the caller must have X19 holding the host address the image is mapped at.
     * The RVA is materialised at run time relative to X19 rather than resolved to
     * an absolute address at translation time, which is what keeps the result
     * cacheable and needs no relocation. */
    int         needs_imgbase;
    uint64_t    iat_va;            /* set with TR_NEEDS_TARGET */
    const char *detail;

    /* Valid only when the return status is not TR_OK: what was refused, and the
     * guest instruction that caused it. Captured from the decode rather than
     * reconstructed, so the opcode reported is the one the decoder saw, prefixes
     * and all. */
    tr_reason   reason;
    /* How many instructions were planned successfully before the refusal. This is
     * the field that makes the refusal mean something: 0 says the entry point's
     * very first instruction is not in the subset, while a larger number says the
     * function translated for a while and then met something - which is a
     * different problem with a different fix, and in particular raises the
     * question of whether discovery followed a branch into data that happens to
     * lie inside the same section. Without it, "refused at opcode 00" cannot be
     * told apart from "wandered into a jump table". */
    uint32_t    fail_insns;
    uint64_t    fail_va;
    uint8_t     fail_op[3];
    uint8_t     fail_op_len;
    uint8_t     fail_map;          /* 0=base, 1=0F, 2=0F38, 3=0F3A */
    int         fail_from_plan;    /* 1 when the refusal was raised after planning,
                                    * so fail_op holds no opcode and must not be
                                    * read as one */
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

/* Same as tr_translate_function_at, with the module's image base and size so that
 * RIP-relative operands can be resolved to an RVA at translation time and bounded
 * against the image.
 *
 * image_base_va is the guest virtual address that RVA 0 maps to, and image_size
 * covers the whole mapped image. Both are checked: a RIP-relative displacement can
 * point anywhere, and one that lands outside the image would read whatever the host
 * has past the mapping - a value that looks plausible and is not. Refusing at
 * translation time is cheaper than discovering that at run time.
 *
 * Passing 0 for either means "not known", and RIP-relative data access is then
 * refused with TRR_IMG_BASE rather than guessed at. */
tr_status tr_translate_function_img(const uint8_t *code, size_t code_len,
                                    uint64_t base_va, size_t start_off,
                                    uint64_t image_base_va, uint64_t image_size,
                                    tr_resolve_fn resolve, void *user,
                                    tr_func *out);

/* The byte that identifies which instruction was refused, chosen according to the
 * map rather than always read from fail_op[0].
 *
 * That distinction is the whole function. For a two-byte opcode fail_op[0] is the
 * 0x0F escape, so indexing a histogram by it collapses every SSE instruction in a
 * binary into one cell labelled "0F 0F" - which is a real encoding (3DNow!) and so
 * looks like a finding rather than a reporting bug. Measured on a shipped bundle
 * that one cell claimed to be the largest blocker in the module, ahead of anything
 * else, while actually naming 19 different instructions.
 *
 * Returns 0 when the record holds no opcode at all: either fail_from_plan is set,
 * meaning the refusal came after planning and blame() cleared fail_op, or the
 * length is zero. A caller must not count those. */
uint8_t tr_fail_opcode(const tr_func *f);

const char *tr_status_name(tr_status s);

#endif /* TRANSLATE_H */
