#include "translate.h"

#include "a64_emit.h"
#include "x86_decode.h"

#include <stdlib.h>
#include <string.h>

#define HOST_RAX 0u      /* guest RAX -> X0 */
#define HOST_RCX 1u      /* guest RCX -> X1 */
#define HOST_SCRATCH 16u /* X16 / IP0: free for a translator to clobber */
/* The bridge's fixed cost in words: five STP pre-index pushes, six argument MOVs,
 * five LDP post-index pops. It must agree exactly with the emission, because layout
 * reserves the space before any word is written and a mismatch surfaces as
 * TRR_INTERNAL rather than as silently truncated code. */
#define ABI_BRIDGE_WORDS 16u
#define HOST_TMP2    17u /* X17 / IP1: a second short-lived scratch. Like X16 it is
                          * caller-clobbered, so it may hold a value only between
                          * being written and being consumed inside one guest
                          * instruction's emission - never across a call. */
#define HOST_RSP     14u /* guest RSP -> X14, callee-saved in the AAPCS */
#define HOST_RBP     15u /* guest RBP -> X15, likewise */
#define HOST_IMGBASE 19u /* X19: host address the guest module image is mapped at.
                          * RVA 0 lives here. Callee-saved in the AAPCS, so a host
                          * callee reached through a resolved import preserves it -
                          * IP0/IP1 (X16/X17) would not, which rules them out for
                          * a value that has to outlive every call. */

uint8_t tr_fail_opcode(const tr_func *f)
{
    /* fail_map is 0 for a one-byte opcode, 1 for 0F xx, 2 for 0F 38 xx and 3 for
     * 0F 3A xx, and op_len is 1, 2, 3, 3 to match - so the discriminating byte is
     * always the last one the decoder recorded. */
    if (!f || f->fail_from_plan || f->fail_op_len == 0 || f->fail_op_len > 3)
        return 0;
    return f->fail_op[f->fail_op_len - 1];
}

const char *tr_reason_name(tr_reason r)
{
    switch (r) {
    case TRR_OK:            return "ok";
    case TRR_UNSUPPORTED_OP:return "unsupported-opcode";
    case TRR_DECODE:        return "decoder-refused";
    case TRR_PREFIX:        return "prefix";
    case TRR_REGISTER:      return "register-unmapped";
    case TRR_IMM_RANGE:     return "immediate-too-large";
    case TRR_FLAGS:         return "flags-not-produced";
    case TRR_PARITY:        return "parity-flag";
    case TRR_XOR_TWO:       return "xor-two-operands";
    case TRR_LEAVES_FUNC:   return "branch-leaves-function";
    case TRR_NO_CODE:       return "entry-not-in-code";
    case TRR_NO_RET:        return "no-ret";
    case TRR_NEEDS_TARGET:  return "import-unresolved";
    case TRR_OVERFLOW:      return "size-limit";
    case TRR_INTERNAL:      return "internal";
    case TRR_STACK:         return "guest-stack-form";
    case TRR_GUEST_MEM:     return "memory-not-on-guest-stack";
    case TRR_BUFFER:        return "code-buffer-rejected";
    case TRR_IMG_BASE:      return "image-base-unknown";
    case TRR_ABS_ADDR:      return "absolute-addressing";
    default:                return "?";
    }
}

const char *tr_status_name(tr_status s)
{
    switch (s) {
    case TR_OK:           return "TR_OK";
    case TR_UNSUPPORTED:  return "TR_UNSUPPORTED";
    case TR_INVALID:      return "TR_INVALID";
    case TR_NEEDS_TARGET: return "TR_NEEDS_TARGET";
    case TR_OVERFLOW:     return "TR_OVERFLOW";
    default:              return "?";
    }
}

static int push(tr_output *o, uint32_t insn)
{
    if (o->n >= TR_MAX_WORDS) { o->detail = "output word buffer full"; return 0; }
    o->words[o->n++] = insn;
    return 1;
}

/* Materialises any 64-bit constant: MOVZ writes the low half and zeroes the
 * rest, then MOVK replaces each remaining non-zero 16-bit chunk. Skipping a
 * zero chunk is not just shorter, it is required - MOVK would otherwise
 * overwrite nothing, but emitting four instructions for the value 1 would hide
 * whether the chunk placement is right. */
static int emit_const(tr_output *o, unsigned rd, uint64_t v)
{
    unsigned shift;
    if (!push(o, a64_movz_x(rd, (uint16_t)(v & 0xFFFFu)))) return 0;
    for (shift = 16u; shift < 64u; shift += 16u) {
        uint16_t chunk = (uint16_t)((v >> shift) & 0xFFFFu);
        if (chunk == 0) continue;
        if (!push(o, a64_movk_x(rd, chunk, shift))) return 0;
    }
    return 1;
}

/* Maps a ModRM reg or rm field to a host register, refusing anything outside
 * the subset. REX.B and REX.R extend the field to registers 8-15, which are not
 * modelled, so their presence is a refusal rather than a silent truncation. */
static int map_reg(const x86_insn *in, unsigned field, int is_rm,
                   unsigned *host)
{
    int ext = is_rm ? in->rex_b : in->rex_r;
    if (ext) return 0;
    if (field == 0u) { *host = HOST_RAX; return 1; }
    if (field == 1u) { *host = HOST_RCX; return 1; }
    return 0;
}

/* Scans the run before emitting, for two facts the emitter cannot discover as it
 * goes: whether any instruction is a call, which decides if a frame record has to
 * be pushed, and whether the run ends on a RET at all. Emitting into a buffer and
 * patching the front afterwards would be the alternative, and it is worse - a
 * prologue that is inserted conditionally after the fact is easy to forget. */
static int run_has_call(const uint8_t *code, size_t code_len, uint64_t guest_va)
{
    size_t pos = 0;
    uint64_t va = guest_va;
    while (pos < code_len) {
        x86_insn in;
        if (x86_decode(code + pos, code_len - pos, va, &in) != X86_OK || in.len == 0)
            return 0;
        if (in.op_len == 1 && in.op[0] == 0xC3 && in.rex == 0) return 0;
        if (in.op_len == 1 && in.op[0] == 0xFF && in.reg == 2 &&
            (in.flags & X86F_CALL) != 0)
            return 1;
        pos += in.len;
        va  += in.len;
    }
    return 0;
}

tr_status tr_translate_run(const uint8_t *code, size_t code_len,
                           uint64_t guest_va, tr_resolve_fn resolve, void *user,
                           tr_output *out)
{
    size_t   pos = 0;
    uint64_t va = guest_va;
    int      needs_frame;

    if (!out) return TR_INVALID;
    memset(out, 0, sizeof(*out));
    out->detail = "ok";
    if (!code || code_len == 0) { out->detail = "no guest code"; return TR_INVALID; }

    needs_frame = run_has_call(code, code_len, guest_va);
    if (needs_frame && !push(out, a64_stp_frame_push())) return TR_OVERFLOW;

    while (pos < code_len) {
        x86_insn in;
        x86_status st = x86_decode(code + pos, code_len - pos, va, &in);

        if (st == X86_NEED_MORE) {
            out->detail = "guest code ends mid-instruction";
            return TR_INVALID;
        }
        if (st == X86_INVALID) {
            out->detail = "guest bytes are not a legal 64-bit instruction";
            return TR_INVALID;
        }
        if (st == X86_UNSUPPORTED) {
            out->detail = "decoder does not model this encoding";
            return TR_UNSUPPORTED;
        }
        if (in.len == 0) { out->detail = "decoder returned length 0"; return TR_INVALID; }

        /* ---- the subset, dispatched on what the decoder reported ---- */
        if (in.op_len == 1 && in.op[0] == 0xC3 && in.rex == 0) {
            /* Pop the frame record before returning, or X30 is still whatever the
             * last BLR left in it. */
            if (needs_frame && !push(out, a64_ldp_frame_pop())) return TR_OVERFLOW;
            if (!push(out, a64_ret())) return TR_OVERFLOW;
            out->guest_insns++;
            out->guest_bytes += in.len;
            return TR_OK;                       /* end of the run */
        }

        if (in.op_len == 1 && in.op[0] == 0xC7 && in.rex_w && in.mod == 3 &&
            in.reg == 0) {
            /* mov r64, imm32 - the decoder stores raw bits, so extending it is
             * this layer's job, exactly as the decoder's contract says. */
            unsigned rd;
            uint64_t value = (uint64_t)(int64_t)(int32_t)in.imm;
            if (!map_reg(&in, in.rm, 1, &rd)) {
                out->detail = "mov imm: destination register outside the subset";
                return TR_UNSUPPORTED;
            }
            if (!emit_const(out, rd, value)) return TR_OVERFLOW;
        } else if (in.op_len == 1 && (in.op[0] == 0x83 || in.op[0] == 0x81) &&
                   in.rex_w && in.mod == 3 && (in.reg == 0 || in.reg == 5)) {
            /* add/sub r64, imm - GRP1 /0 and /5, with imm8 (0x83) or imm32
             * (0x81). The decoder stores raw bits, so sign extension is this
             * layer's job and depends on which form it is.
             *
             * The operation comes from the opcode and the encoding from the sign
             * of the resulting effect, and the two must be decided
             * independently. Choosing the ARM64 instruction from the sign of the
             * immediate alone makes `sub rax, 5` emit an ADD, which is wrong,
             * cacheable and silent - exactly the failure this design exists to
             * prevent. */
            unsigned rd;
            int64_t  value = (in.op[0] == 0x83) ? (int64_t)(int8_t)in.imm
                                                : (int64_t)(int32_t)in.imm;
            int64_t  delta = (in.reg == 5) ? -value : value;
            if (!map_reg(&in, in.rm, 1, &rd)) {
                out->detail = "add/sub imm: register outside the subset";
                return TR_UNSUPPORTED;
            }
            /* ARM64 ADD/SUB immediate take an unsigned 12-bit field. Outside
             * +-0xFFF this needs a scratch register and a register-form add,
             * which is not in this revision; refusing beats approximating. */
            if (delta >= 0 && delta <= 0xFFF) {
                if (!push(out, a64_add_x_imm(rd, rd, (uint16_t)delta)))
                    return TR_OVERFLOW;
            } else if (delta < 0 && -delta <= 0xFFF) {
                if (!push(out, a64_sub_x_imm(rd, rd, (uint16_t)(-delta))))
                    return TR_OVERFLOW;
            } else {
                out->detail = "add/sub immediate does not fit in 12 bits";
                return TR_UNSUPPORTED;
            }
        } else if (in.op_len == 1 && in.op[0] == 0x89 && in.rex_w &&
                   in.mod == 3) {
            /* mov r/m64, r64 */
            unsigned rd, rn;
            if (!map_reg(&in, in.rm, 1, &rd) || !map_reg(&in, in.reg, 0, &rn)) {
                out->detail = "mov reg: register outside the subset";
                return TR_UNSUPPORTED;
            }
            if (!push(out, a64_mov_reg(rd, rn))) return TR_OVERFLOW;
        } else if (in.op_len == 1 && in.op[0] == 0xFF && in.reg == 2 &&
                   (in.flags & X86F_CALL) != 0) {
            /* call [rip+disp32] - an indirect call through an import slot. The
             * displacement is relative to the end of the instruction. */
            uint64_t iat_va = va + in.len + (uint64_t)(int64_t)in.disp;
            uint64_t host;

            /* Cross-check against the decoder's own RIP-relative resolution
             * when it provides one; a disagreement means one of the two is
             * wrong and translating anyway would bury it. */
            if ((in.flags & X86F_RIP_REL) != 0 && in.rip_rel_target != iat_va) {
                out->detail = "RIP-relative target disagrees with the decoder";
                return TR_INVALID;
            }
            if ((in.mod != 0 || in.rm != 5) && !(in.flags & X86F_RIP_REL)) {
                out->detail = "call target is not a RIP-relative import slot";
                return TR_UNSUPPORTED;
            }
            host = resolve ? resolve(iat_va, user) : 0;
            if (host == 0) {
                out->iat_va = iat_va;
                out->detail = "no host address known for this import slot yet";
                return TR_NEEDS_TARGET;
            }
            if (!emit_const(out, HOST_SCRATCH, host)) return TR_OVERFLOW;
            if (!push(out, a64_blr(HOST_SCRATCH))) return TR_OVERFLOW;
        } else {
            out->detail = "instruction is outside the translated subset";
            return TR_UNSUPPORTED;
        }

        out->guest_insns++;
        out->guest_bytes += in.len;
        pos += in.len;
        va  += in.len;
    }

    out->detail = "guest code ended without a RET";
    return TR_UNSUPPORTED;
}

/* ========================================================================
 * Whole-function translation with control flow.
 * ======================================================================== */

typedef enum {
    P_MOV_IMM, P_MOV_REG, P_ZERO, P_ADD_REG, P_SUB_REG, P_ADD_IMM, P_SUB_IMM,
    P_CMP_REG, P_CMP_IMM, P_TEST_REG, P_JCC, P_JMP, P_CALL_IAT, P_RET,
    /* guest stack */
    P_PUSH_REG, P_POP_REG, P_PUSH_IMM, P_LEAVE, P_ST_LOCAL, P_LD_LOCAL,
    /* the module's own image, reached by a RIP-relative operand */
    P_LD_IMG, P_ST_IMG,
    /* a guest pointer held in a general register, bounds-checked at run time */
    P_LD_GUEST, P_ST_GUEST,
    /* lea: rd = rn + delta, with no memory touched */
    P_LEA_IMM
} plan_op;

typedef struct {
    plan_op  op;
    uint64_t guest_va;
    uint32_t off;          /* byte offset into the guest buffer */
    uint32_t guest_len;
    unsigned rd, rn, rm;   /* host registers */
    uint64_t const_val;    /* MOV_IMM value, or the resolved host call target */
    uint64_t img_size;     /* P_LD_GUEST/P_ST_GUEST: extent the RVA is checked against */
    int64_t  delta;        /* effective signed immediate for ADD/SUB/CMP imm */
    unsigned cond;         /* AArch64 condition code, for P_JCC */
    uint64_t target_va;    /* P_JCC and P_JMP */
    int      sets_flags;   /* leaves NZCV matching an x86 CMP */
    int      host_abi;     /* P_CALL_IAT: target is a real host function, so the
                            * call site emits the AAPCS bridge */
    /* Operand width: 0 for the 64-bit form, 1 for the 32-bit one. A 32-bit x86-64
     * operation zero-extends its result into the full register, and an AArch64
     * W-form zero-extends into the X register, so the two agree without any
     * masking - but only if the W form is the one emitted. */
    int      w32;
    uint32_t words;        /* emitted size, fixed before layout */
    uint32_t word_at;      /* assigned by layout */
} plan;

/* Guest register -> host register.
 *
 * RSP and RBP used to be refused here, and that refusal was the single largest
 * blocker measured on a real binary: every one of the 64 genuine code entry
 * points in a real application bundle died at its first instruction, and the two
 * .exe entries died specifically on `sub rsp, N` with reason register-unmapped.
 * They now map to X14 and X15. Both are callee-saved in the AAPCS, which is not
 * a coincidence but the reason for the choice: a function that uses the guest
 * stack saves them as a frame record, and a host callee reached through a
 * resolved import preserves them across the call without anything being emitted.
 *
 * They are NOT the host SP. See gstack.h for why: AArch64 requires 16-byte SP
 * alignment at every public interface and x86-64 only guarantees 8. */
static int map_guest_reg(unsigned field, int extended, unsigned *host)
{
    static const signed char tbl[16] = {
        /* RAX RCX RDX RBX  RSP  RBP  RSI RDI  R8..R15 */
        0, 1, 2, 3, 14, 15, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13
    };
    unsigned g = (field & 7u) | (extended ? 8u : 0u);
    if (g > 15u || tbl[g] < 0) return 0;
    *host = (unsigned)tbl[g];
    return 1;
}

/* The 14 conditions that map exactly onto AArch64 after a SUBS/ANDS. JP and JNP
 * are refused rather than dropped: AArch64 has no parity flag, so there is no
 * condition code that means the same thing, and picking one would be a guess. */
static int jcc_cond(unsigned nibble, unsigned *cond)
{
    switch (nibble) {
    case 0x4u: *cond = A64_EQ; return 1;   /* JE/JZ   */
    case 0x5u: *cond = A64_NE; return 1;   /* JNE/JNZ */
    case 0x2u: *cond = A64_LO; return 1;   /* JB/JNAE */
    case 0x3u: *cond = A64_HS; return 1;   /* JAE/JNB */
    case 0x6u: *cond = A64_LS; return 1;   /* JBE     */
    case 0x7u: *cond = A64_HI; return 1;   /* JA      */
    case 0xCu: *cond = A64_LT; return 1;   /* JL/JNGE */
    case 0xDu: *cond = A64_GE; return 1;   /* JGE/JNL */
    case 0xEu: *cond = A64_LE; return 1;   /* JLE     */
    case 0xFu: *cond = A64_GT; return 1;   /* JG      */
    case 0x8u: *cond = A64_MI; return 1;   /* JS      */
    case 0x9u: *cond = A64_PL; return 1;   /* JNS     */
    case 0x0u: *cond = A64_VS; return 1;   /* JO      */
    case 0x1u: *cond = A64_VC; return 1;   /* JNO     */
    default:   return 0;                   /* JP, JNP */
    }
}

static uint32_t const_words_w(uint64_t v, int w32)
{
    uint32_t n = 1u;
    unsigned sh, limit = w32 ? 32u : 64u;
    for (sh = 16u; sh < limit; sh += 16u)
        if ((v >> sh) & 0xFFFFu) n++;
    return n;
}

static uint32_t const_words(uint64_t v) { return const_words_w(v, 0); }

/* How many words a bounds-checked register-base access emits. It has to agree
 * exactly with the emission below, because layout reserves the space before any
 * word is written and a mismatch surfaces as TRR_INTERNAL rather than as silently
 * truncated code.
 *
 * The shape is: guest VA into X16; subtract the image base into X17; one unsigned
 * compare against the image size; branch to a trap; add the host base; access;
 * branch over the trap; the trap itself.
 *
 * That the compare is unsigned and single is the point of the design. Subtracting
 * the image base from a guest VA *below* the base wraps to a value near 2^64, which
 * is certainly >= any real image size, so one CMP + one B.HS rejects both ends of
 * the range. Written the obvious way it would need two compares and two branches. */
static uint32_t guest_mem_words(int64_t d, uint64_t base_va, uint64_t size)
{
    uint64_t mag = (d < 0) ? (uint64_t)(-(d + 1)) + 1u : (uint64_t)d;
    uint32_t va  = (d == 0 || mag <= 0xFFFu) ? 1u : const_words(mag) + 1u;
    return va + const_words(base_va) + 1u   /* SUB X17, X16, X17 */
              + const_words(size)    + 1u   /* CMP X17, X16      */
              + 1u                          /* B.HS -> trap      */
              + 1u                          /* ADD X17, X19, X17 */
              + 1u                          /* the access        */
              + 1u                          /* B -> past trap    */
              + 1u;                         /* BRK               */
}

static int pushf(tr_func *o, uint32_t insn)
{
    /* Sets the reason as well as the detail. The callers return TR_OVERFLOW
     * directly, and without this the record would keep whatever reason the
     * pre-pass-1 initialisation left in it. */
    if (o->n >= TRF_MAX_WORDS) { o->reason = TRR_OVERFLOW;
                                 o->detail = "output word buffer full"; return 0; }
    o->words[o->n++] = insn;
    return 1;
}

static int emit_const_f_w(tr_func *o, unsigned rd, uint64_t v, int w32)
{
    unsigned sh, limit = w32 ? 32u : 64u;
    if (!pushf(o, w32 ? a64_movz_w(rd, (uint16_t)(v & 0xFFFFu))
                      : a64_movz_x(rd, (uint16_t)(v & 0xFFFFu)))) return 0;
    for (sh = 16u; sh < limit; sh += 16u) {
        uint16_t chunk = (uint16_t)((v >> sh) & 0xFFFFu);
        if (chunk) {
            if (!pushf(o, w32 ? a64_movk_w(rd, chunk, sh)
                              : a64_movk_x(rd, chunk, sh))) return 0;
        }
    }
    return 1;
}

static int emit_const_f(tr_func *o, unsigned rd, uint64_t v)
{ return emit_const_f_w(o, rd, v, 0); }

/* Discovery marks, one BIT per guest byte rather than one byte per guest byte.
 *
 * The buffer is a whole code section, so a byte-per-entry array costs as much
 * memory as the section itself, allocated and freed on every entry point. A
 * shipped module's .text runs to hundreds of megabytes and a real bundle has
 * hundreds of exports, so that is hundreds of megabytes of churn per function.
 * The bitmap is an eighth of it and is the only reason the buffer cap could be
 * raised to a size that does not reject real modules. */
static int seen_get(const uint8_t *bm, uint32_t i)
{
    return (int)((bm[i >> 3] >> (i & 7u)) & 1u);
}

static void seen_set(uint8_t *bm, uint32_t i)
{
    bm[i >> 3] |= (uint8_t)(1u << (i & 7u));
}

/* Points the failure record at a specific planned instruction.
 *
 * Refusals raised after planning used to leave the record holding whatever the last
 * decode happened to be, so a histogram built from it named an opcode that no
 * function actually contained. fail_from_plan is set so the sweep can tell the two
 * apart instead of counting a stale opcode. */
static void blame(tr_func *out, const plan *p, uint32_t depth)
{
    out->fail_insns = depth;
    out->fail_va = p->guest_va;
    out->fail_op_len = 0;
    out->fail_map = 0;
    out->fail_from_plan = 1;
    memset(out->fail_op, 0, sizeof(out->fail_op));
}

/* What kind of addressing a memory operand uses. Four kinds, and they need four
 * different answers, so they are told apart here rather than collapsed into a
 * single "not modelled" refusal:
 *
 *   MB_RIP_REL  mod=00 rm=101 with no SIB. In 64-bit mode this is RIP-relative,
 *               NOT [RBP]. The decoder reports it with has_sib == 0 and
 *               disp_len == 4, which at a glance is indistinguishable from a real
 *               base register, so it is checked explicitly. This is the form that
 *               reaches a module's globals, and it IS translatable: the target
 *               guest VA is known from the encoding, so the RVA follows.
 *   MB_ABS      mod=00 with SIB base=101: an absolute disp32 with NO base
 *               register. It arrives with sib_base == 5, the same value RBP has.
 *               Needs a relocation, so it is refused for a different reason than
 *               a general register base - a caller cannot fix one by supplying
 *               an image base.
 *   MB_STACK    RSP or RBP relative. Modelled by the guest stack arena.
 *   MB_OTHER    a base in some other register: a guest pointer with nowhere to
 *               point. REX.B must be applied before comparing, because rm=100
 *               with REX.B is R12, not RSP, and rm=101 with REX.B is R13.
 */
typedef enum { MB_NONE = 0, MB_RIP_REL, MB_ABS, MB_STACK, MB_OTHER, MB_INDEX } mem_base_kind;

static mem_base_kind classify_mem_base(const x86_insn *in, unsigned *guest_base)
{
    unsigned b;
    if (!in->has_modrm || in->mod == 3) return MB_NONE;   /* register form */
    if (in->has_sib) {
        /* The index is checked BEFORE the absolute-base case, and the order is not
         * cosmetic. With SIB base=101 and mod=00 there is no base register, but an
         * index still applies, so `[rax*2+disp32]` reaches here too. Reporting it as
         * MB_ABS says the only thing missing is an absolute address, when what is
         * actually missing is a general guest register as well - and a work queue
         * that believes the first would implement absolute addressing and unblock
         * nothing. */
        if (in->sib_index != 4 || in->rex_x) return MB_INDEX;  /* an index register */
        if (in->sib_scale != 0) return MB_INDEX;               /* or a scale on it  */
        if (in->mod == 0 && in->sib_base == 5) return MB_ABS;
        b = (unsigned)in->sib_base | (in->rex_b ? 8u : 0u);
    } else {
        if (in->mod == 0 && in->rm == 5) return MB_RIP_REL;
        b = (unsigned)in->rm | (in->rex_b ? 8u : 0u);
    }
    *guest_base = b;                       /* set for MB_OTHER too: the register-base
                                            * access needs to know which guest register
                                            * holds the pointer, and REX.B is already
                                            * folded into b above. */
    if (b != 4u && b != 5u) return MB_OTHER;      /* not RSP and not RBP */
    return MB_STACK;
}

/* Whether a plan uses the guest stack at all, which decides if the X14/X15 frame
 * record has to be emitted. Reading the rd/rn/rm fields is safe because a plan is
 * zero-initialised and neither X14 nor X15 is register 0. */
static int plan_uses_gstack(const plan *p)
{
    switch (p->op) {
    case P_PUSH_REG: case P_POP_REG: case P_PUSH_IMM:
    case P_LEAVE: case P_ST_LOCAL: case P_LD_LOCAL:
        return 1;
    default: break;
    }
    return p->rd == HOST_RSP || p->rd == HOST_RBP ||
           p->rn == HOST_RSP || p->rn == HOST_RBP ||
           p->rm == HOST_RSP || p->rm == HOST_RBP;
}

/* Whether the X19/X20 image-base frame record has to be emitted.
 *
 * Deliberately NOT the shape of plan_uses_gstack above. That one falls through to
 * a register-field test, which is right for it because any operation touching X14
 * or X15 needs the record. Here the same fall-through would be a bug: a plain
 * `push rax` has rd == HOST_RSP, so it would demand the image-base record without
 * ever using X19, and the function would push and pop a register the caller never
 * set up. Only the two image accesses read X19, so only they count. */
static int plan_uses_imgbase(const plan *p)
{
    return p->op == P_LD_IMG || p->op == P_ST_IMG
        || p->op == P_LD_GUEST || p->op == P_ST_GUEST;
}

/* Plans a conditional jump from its condition nibble. Both encodings call this,
 * so the short and near forms cannot drift apart in which flags they read: the
 * only difference between them is where the nibble lives and how wide the
 * displacement is, and the decoder has already resolved the second. */
static tr_status plan_jcc(unsigned nibble, uint64_t va, const x86_insn *in,
                          plan *p, tr_func *out)
{
    if (!jcc_cond(nibble, &p->cond)) {
        out->reason = TRR_PARITY;
        out->detail = "JP/JNP: AArch64 has no parity flag";
        return TR_UNSUPPORTED;
    }
    p->op = P_JCC;
    p->target_va = va + in->len + (uint64_t)(int64_t)in->imm;
    p->words = 1u;
    return TR_OK;
}

/* Plans one guest instruction: decides the operation, the registers, and how many
 * ARM64 words it will emit. No emission happens here, so the layout pass has sizes
 * before any displacement is needed. */
static tr_status plan_one(const uint8_t *code, size_t code_len, uint32_t off,
                          uint64_t base_va, uint64_t image_base_va,
                          uint64_t image_size,
                          tr_resolve_fn resolve, void *user,
                          plan *p, tr_func *out)
{
    x86_insn   in;
    x86_status st;
    uint64_t   va = base_va + off;
    int        is_grp1;

    memset(p, 0, sizeof(*p));
    p->off = off;
    p->guest_va = va;

    st = x86_decode(code + off, code_len - off, va, &in);
    out->fail_va = va;
    out->fail_op_len = (code_len - off >= 3) ? 3u : (uint8_t)(code_len - off);
    memcpy(out->fail_op, code + off, out->fail_op_len);
    out->fail_map = 0;
    if (st == X86_NEED_MORE) { out->reason = TRR_DECODE;
                               out->detail = "function ends mid-instruction";
                               return TR_INVALID; }
    if (st == X86_INVALID)   { out->reason = TRR_DECODE; out->detail = "not a legal 64-bit instruction";
                               return TR_INVALID; }
    if (st == X86_UNSUPPORTED) { out->reason = TRR_DECODE; out->detail = "decoder does not model this encoding";
                               return TR_UNSUPPORTED; }
    if (in.len == 0 || off + in.len > code_len) {
        out->reason = TRR_DECODE; out->detail = "decoder returned an unusable length";
        return TR_INVALID;
    }
    p->guest_len = in.len;
    out->fail_from_plan = 0;

    /* Record this instruction as the candidate culprit before anything below can
     * refuse it. Every refusal path then reports the opcode the decoder really
     * saw, including prefixes and the map, instead of the sweep having to guess
     * which byte stopped the translation. */
    out->fail_va = va;
    out->fail_op_len = in.op_len;
    out->fail_map = in.map;
    out->fail_rex = in.rex;
    out->fail_has_modrm = in.has_modrm;
    out->fail_modrm = in.has_modrm ? in.modrm : 0;
    memcpy(out->fail_op, in.op, sizeof(out->fail_op));

    if (in.p66 || in.p67 || in.pf2 || in.pf3 || in.lock || in.seg ||
        (in.flags & X86F_REP) != 0) {
        out->reason = TRR_PREFIX; out->detail = "a prefix that changes meaning is present";
        return TR_UNSUPPORTED;
    }
    if (in.op_len != 1 && !(in.map == 1 && in.op_len == 2)) {
        out->reason = TRR_UNSUPPORTED_OP; out->detail = "three-byte opcode maps are outside the subset";
        return TR_UNSUPPORTED;
    }

    /* ---- two-byte map: 0F 8x is the rel32 form of Jcc ----
     *
     * The condition nibble is in op[1], NOT op[0]. For every two-byte opcode the
     * decoder stores op[0] = 0x0F, the escape, and op[1] = the byte that says
     * which instruction it is. Testing op[0] against 0x80..0x8F therefore can
     * never be true, and this case was dead from the day it was written: every
     * near conditional jump fell through to the refusal below it.
     *
     * Nothing caught it, because the fall-through refusal is also correct for the
     * two-byte opcodes that really are outside the subset - which is nearly all of
     * them - so the tests passed and the behaviour looked intentional. It only
     * became visible as a cost: measured on a shipped bundle, 0F 84 alone was
     * blocking 8 functions and 0F 88 one more, ahead of every SSE instruction.
     *
     * This is the same mistake the refusal histogram made, indexing two-byte
     * opcodes by their escape byte and reporting 19 different instructions as
     * "0F 0F". Both come from assuming op[0] identifies the instruction. It
     * identifies the map; the last byte the decoder recorded identifies the
     * instruction, which is what tr_fail_opcode() exists to say. */
    if (in.map == 1) {
        if (in.op[1] >= 0x80u && in.op[1] <= 0x8Fu)
            return plan_jcc(in.op[1] & 0xFu, va, &in, p, out);
        out->reason = TRR_UNSUPPORTED_OP; out->detail = "two-byte opcode outside the subset";
        return TR_UNSUPPORTED;
    }

    is_grp1 = (in.op[0] == 0x83 || in.op[0] == 0x81);

    if (in.op[0] == 0xC3 && in.rex == 0 && in.mod == 0) {
        p->op = P_RET; p->words = 1u; return TR_OK;
    }
    if (in.op[0] == 0xC2) {
        /* RET imm16 pops arguments off the guest stack on its way out. This
         * translator's epilogue restores X14 to its entry value unconditionally,
         * which is right for a callee that does not change the caller's stack
         * pointer and wrong for one that does. Refusing is the honest outcome:
         * emitting a plain RET here would return with the caller's stack pointer
         * 8 or 16 bytes off, and the caller would then read its own locals from
         * the wrong addresses. */
        out->reason = TRR_STACK;
        out->detail = "ret imm16 pops arguments, which changes the caller's stack pointer";
        return TR_UNSUPPORTED;
    }
    if (in.op[0] == 0xEB || in.op[0] == 0xE9) {
        p->op = P_JMP;
        p->target_va = va + in.len + (uint64_t)(int64_t)in.imm;
        p->words = 1u;
        return TR_OK;
    }
    /* jcc rel8, the short form: 70-7F, nibble in the low four bits of op[0]. */
    if (in.op[0] >= 0x70u && in.op[0] <= 0x7Fu)
        return plan_jcc(in.op[0] & 0xFu, va, &in, p, out);

    if (in.op[0] == 0xFF && in.reg == 2 && (in.flags & X86F_CALL)) {
        uint64_t iat_va = va + in.len + (uint64_t)(int64_t)in.disp;
        uint64_t host;
        if ((in.flags & X86F_RIP_REL) && in.rip_rel_target != iat_va) {
            out->reason = TRR_INTERNAL; out->detail = "RIP-relative target disagrees with the decoder";
            return TR_INVALID;
        }
        if (in.mod != 0 || in.rm != 5) {
            out->reason = TRR_NEEDS_TARGET; out->detail = "call target is not a RIP-relative import slot";
            return TR_UNSUPPORTED;
        }
        host = resolve ? resolve(iat_va, user) : 0;
        if (host == 0) {
            out->iat_va = iat_va;
            out->reason = TRR_NEEDS_TARGET; out->detail = "no host address known for this import slot yet";
            return TR_NEEDS_TARGET;
        }
        p->host_abi  = (host & TR_ABI_HOST) != 0u;
        host        &= ~(uint64_t)TR_ABI_HOST;
        p->op = P_CALL_IAT;
        p->const_val = host;
        p->words = const_words(host) + 1u + (p->host_abi ? ABI_BRIDGE_WORDS : 0u);
        return TR_OK;
    }
    /* mov r32, imm32 - the shortest and one of the commonest ways to load a
     * constant. The result zero-extends into the full 64-bit register, so the W
     * form of MOVZ is exactly right and nothing has to be masked afterwards.
     *
     * REX.W turns this opcode into mov r64, imm64, a ten-byte encoding. That used
     * to be refused as outside the subset, and the refusal was wrong: the decoder
     * carries all eight immediate bytes and MOVZ+MOVK materialises any 64-bit value
     * exactly, so an exact translation was being turned away. What must still never
     * happen is truncating to 32 bits - that is a plausible wrong constant. It
     * blocked 142 functions in a real game bundle, more than any SSE instruction. */
    if ((in.op[0] & 0xF8u) == 0xB8u && !in.has_modrm) {
        if (in.rex_w) {
            if (in.imm_len != 8) {
                /* Not a refusal but an internal error: the encoding is ten bytes by
                 * definition, so a different immediate length means the decoder and
                 * this layer disagree about what was read. */
                out->reason = TRR_INTERNAL;
                out->detail = "mov r64,imm64: the decoder did not report 8 immediate bytes";
                return TR_INVALID;
            }
            if (!map_guest_reg((unsigned)(in.op[0] & 7u), in.rex_b, &p->rd)) {
                out->reason = TRR_REGISTER;
                out->detail = "mov r64,imm64: register outside the mapped set";
                return TR_UNSUPPORTED;
            }
            p->op = P_MOV_IMM;
            p->w32 = 0;
            p->const_val = in.imm;              /* all 64 bits, unmodified */
            p->words = const_words_w(p->const_val, 0);
            return TR_OK;
        }
        if (in.rex_r || in.rex_x) {
            out->reason = TRR_UNSUPPORTED_OP;
            out->detail = "mov r32, imm32 carries a REX bit that has no meaning there";
            return TR_UNSUPPORTED;
        }
        if (!map_guest_reg((unsigned)(in.op[0] & 7u), in.rex_b, &p->rd)) {
            out->reason = TRR_REGISTER;
            out->detail = "mov r32,imm32: register outside the mapped set";
            return TR_UNSUPPORTED;
        }
        p->op = P_MOV_IMM;
        p->w32 = 1;
        p->const_val = (uint64_t)(uint32_t)in.imm;   /* zero-extends, not sign- */
        p->words = const_words_w(p->const_val, 1);
        return TR_OK;
    }
    /* lea r64|r32, m - load the ADDRESS, not the contents. No memory is read, so
     * this is arithmetic on an address the instruction already encodes, and it is
     * exact in every form handled here. It blocked 266 functions in a real game
     * bundle, which is what makes it worth doing before anything that needs a
     * general guest memory model.
     *
     * Three cases, and they differ in where the address comes from:
     *   RIP-relative  the address is a guest VA fixed by the encoding, so it is a
     *                 constant. Baking a guest VA into the output is not the same
     *                 mistake as baking a host address: the guest image is never
     *                 relocated here, so its VAs are the ones in its PE header, and
     *                 ptc keys on a hash of the guest bytes so a different image
     *                 cannot reuse the translation.
     *   RBP/RSP       the base is live in X15/X14, so this is an add or subtract
     *                 against it - and it needs the guest stack arena, which the
     *                 plan picks up because rn is X14 or X15.
     *   absolute SIB  refused rather than guessed at: whether the 32-bit disp is
     *                 sign- or zero-extended into the 64-bit address is exactly the
     *                 kind of detail that produces a wrong pointer with no symptom.
     */
    if (in.op[0] == 0x8D && in.has_modrm && in.mod != 3) {
        unsigned      gbase = 0, vreg;
        mem_base_kind k = classify_mem_base(&in, &gbase);
        int           w32 = !in.rex_w;
        int64_t       d = in.disp;

        if (!map_guest_reg(in.reg, in.rex_r, &vreg)) {
            out->reason = TRR_REGISTER;
            out->detail = "lea: destination register outside the mapped set";
            return TR_UNSUPPORTED;
        }
        if (k == MB_RIP_REL) {
            p->op = P_MOV_IMM;
            p->rd = vreg;
            p->w32 = w32;
            /* A 32-bit lea truncates the address and zero-extends, which the W form
             * of MOVZ does by itself. */
            p->const_val = w32 ? (uint64_t)(uint32_t)in.rip_rel_target
                               : in.rip_rel_target;
            p->words = const_words_w(p->const_val, w32);
            return TR_OK;
        }
        if (k == MB_ABS) {
            out->reason = TRR_ABS_ADDR;
            out->detail = "lea from an absolute disp32: extending it to 64 bits is "
                          "not defined the same way by every reading of the "
                          "encoding, so it is refused rather than guessed at";
            return TR_UNSUPPORTED;
        }
        if (k == MB_INDEX) {
            out->reason = TRR_GUEST_MEM;
            out->detail = "lea with a scaled index register: needs a shift and a "
                          "second guest register";
            return TR_UNSUPPORTED;
        }
        if (k != MB_STACK) {
            out->reason = TRR_GUEST_MEM;
            out->detail = "lea from a base this translator does not model";
            return TR_UNSUPPORTED;
        }
        p->op = P_LEA_IMM;
        p->rd = vreg;
        p->rn = (gbase == 4u) ? HOST_RSP : HOST_RBP;
        p->delta = d;
        p->w32 = w32;
        /* ADD/SUB immediate carry an unsigned 12-bit field. Outside it the
         * displacement is materialised in X16 and the register form used, which is
         * exact and only costs the words it needs. */
        if ((d >= 0 && d <= 0xFFF) || (d < 0 && d >= -0xFFF))
            p->words = 1u;
        else
            p->words = const_words_w((uint64_t)(d < 0 ? -d : d), 0) + 1u;
        return TR_OK;
    }

    /* mov r/m32, imm32 with mod=3 is the same operation through a different
     * opcode; without REX.W it zero-extends, with REX.W it sign-extends. */
    if (in.op[0] == 0xC7 && in.has_modrm && in.mod == 3 && in.reg == 0) {
        if (!map_guest_reg(in.rm, in.rex_b, &p->rd)) {
            out->reason = TRR_REGISTER; out->detail = "mov imm: register outside the mapped set";
            return TR_UNSUPPORTED;
        }
        p->op = P_MOV_IMM;
        p->w32 = in.rex_w ? 0 : 1;
        /* REX.W sign-extends the 32-bit immediate to 64; without it the write is
         * 32-bit and zero-extends. Same opcode, opposite extension, and choosing
         * the wrong one is a value that looks right in a debugger's 32-bit view. */
        p->const_val = in.rex_w ? (uint64_t)(int64_t)(int32_t)in.imm
                                : (uint64_t)(uint32_t)in.imm;
        p->words = const_words_w(p->const_val, p->w32);
        return TR_OK;
    }
    if (in.op[0] == 0x89 && in.has_modrm && in.mod == 3) {
        if (!map_guest_reg(in.rm, in.rex_b, &p->rd) ||
            !map_guest_reg(in.reg, in.rex_r, &p->rn)) {
            out->reason = TRR_REGISTER; out->detail = "mov reg: register outside the mapped set";
            return TR_UNSUPPORTED;
        }
        p->op = P_MOV_REG; p->w32 = !in.rex_w; p->words = 1u; return TR_OK;
    }
    if (in.op[0] == 0x31 && in.has_modrm && in.mod == 3) {
        /* Only the zeroing idiom. A real two-operand xor needs the value AND the
         * flags it sets, and modelling half of it would be a guess. */
        unsigned a, b;
        if ((in.rm | (in.rex_b ? 8u : 0u)) != (in.reg | (in.rex_r ? 8u : 0u))) {
            out->reason = TRR_XOR_TWO; out->detail = "xor with two different operands is outside the subset";
            return TR_UNSUPPORTED;
        }
        if (!map_guest_reg(in.rm, in.rex_b, &a) || !map_guest_reg(in.reg, in.rex_r, &b)) {
            out->reason = TRR_REGISTER; out->detail = "xor: register outside the mapped set";
            return TR_UNSUPPORTED;
        }
        p->op = P_ZERO; p->rd = a; p->w32 = !in.rex_w; p->words = 1u; return TR_OK;
    }
    if (in.op[0] == 0x01 && in.has_modrm && in.mod == 3) {
        if (!map_guest_reg(in.rm, in.rex_b, &p->rd) ||
            !map_guest_reg(in.reg, in.rex_r, &p->rn)) {
            out->reason = TRR_REGISTER; out->detail = "add reg: register outside the mapped set";
            return TR_UNSUPPORTED;
        }
        p->op = P_ADD_REG; p->w32 = !in.rex_w; p->words = 1u; return TR_OK;
    }
    if (in.op[0] == 0x29 && in.has_modrm && in.mod == 3) {
        if (!map_guest_reg(in.rm, in.rex_b, &p->rd) ||
            !map_guest_reg(in.reg, in.rex_r, &p->rn)) {
            out->reason = TRR_REGISTER; out->detail = "sub reg: register outside the mapped set";
            return TR_UNSUPPORTED;
        }
        p->op = P_SUB_REG; p->w32 = !in.rex_w; p->words = 1u; return TR_OK;
    }
    if (in.op[0] == 0x39 && in.has_modrm && in.mod == 3) {
        if (!map_guest_reg(in.rm, in.rex_b, &p->rn) ||
            !map_guest_reg(in.reg, in.rex_r, &p->rm)) {
            out->reason = TRR_REGISTER; out->detail = "cmp reg: register outside the mapped set";
            return TR_UNSUPPORTED;
        }
        p->op = P_CMP_REG; p->sets_flags = 1; p->w32 = !in.rex_w; p->words = 1u; return TR_OK;
    }
    if (in.op[0] == 0x85 && in.has_modrm && in.mod == 3) {
        if (!map_guest_reg(in.rm, in.rex_b, &p->rn) ||
            !map_guest_reg(in.reg, in.rex_r, &p->rm)) {
            out->reason = TRR_REGISTER; out->detail = "test: register outside the mapped set";
            return TR_UNSUPPORTED;
        }
        p->op = P_TEST_REG; p->sets_flags = 1; p->w32 = !in.rex_w; p->words = 1u; return TR_OK;
    }
    if (is_grp1 && in.has_modrm && in.mod == 3 &&
        (in.reg == 0 || in.reg == 5 || in.reg == 7)) {
        int64_t value = (in.op[0] == 0x83) ? (int64_t)(int8_t)in.imm
                                           : (int64_t)(int32_t)in.imm;
        if (!map_guest_reg(in.rm, in.rex_b, &p->rd)) {
            out->reason = TRR_REGISTER; out->detail = "grp1: register outside the mapped set";
            return TR_UNSUPPORTED;
        }
        if (in.reg == 0) {          /* ADD */
            p->op = P_ADD_IMM; p->delta = value;
        } else if (in.reg == 5) {   /* SUB */
            p->op = P_SUB_IMM; p->delta = -value;
        } else {                    /* CMP */
            p->op = P_CMP_IMM; p->delta = value; p->sets_flags = 1;
        }
        /* The ARM64 immediate field is unsigned 12 bits, so the signed effect has
         * to fit in either direction. Outside that, a scratch register and a
         * register-form op would be needed; refusing is honest. */
        {
            /* p->delta is already the signed arithmetic effect: the opcode was
             * applied when it was planned, so a SUB stored the negated immediate.
             * Deciding the ARM64 form from the sign here is correct precisely
             * because the operation was settled earlier and independently. */
            if (p->delta > 0xFFF || p->delta < -0xFFF) {
                out->reason = TRR_IMM_RANGE; out->detail = "immediate does not fit in 12 bits";
                return TR_UNSUPPORTED;
            }
        }
        p->w32 = !in.rex_w;
        p->words = 1u;
        return TR_OK;
    }

    /* ---- guest stack ----
     *
     * push/pop are single-byte opcodes with the register in the low three bits,
     * extended by REX.B. Only REX.B is meaningful here, so a REX.R or REX.X on a
     * push is a malformed encoding and is refused rather than ignored. */
    if ((in.op[0] & 0xF8u) == 0x50u || (in.op[0] & 0xF8u) == 0x58u) {
        unsigned g;
        int is_push = (in.op[0] & 0xF8u) == 0x50u;
        if (in.rex_r || in.rex_x) {
            out->reason = TRR_UNSUPPORTED_OP;
            out->detail = "push/pop carries a REX bit that has no meaning there";
            return TR_UNSUPPORTED;
        }
        g = (unsigned)(in.op[0] & 7u) | (in.rex_b ? 8u : 0u);
        /* PUSH RSP and POP RSP are refused deliberately, and this is the one
         * place where a refusal is chosen over an encoding that would be
         * plausible. `push rsp` is ambiguous in the x86 architecture itself: the
         * value pushed is RSP after the decrement on implementations since the
         * Pentium, while STR with pre-indexed writeback stores the value from
         * before it. That is an 8-byte difference in a word that gets read back
         * later. `pop rsp` would need ARM64's Rt == Rn post-index corner case to
         * come out right. Neither is worth guessing at, and neither is common. */
        if (g == 4u) {
            out->reason = TRR_STACK;
            out->detail = is_push
                ? "push rsp: the pushed value is ambiguous between the pre- and "
                  "post-decrement stack pointer"
                : "pop rsp: would depend on an ARM64 writeback corner case";
            return TR_UNSUPPORTED;
        }
        if (!map_guest_reg(g, 0, &p->rd)) {
            out->reason = TRR_REGISTER;
            out->detail = "push/pop: register outside the mapped set";
            return TR_UNSUPPORTED;
        }
        p->op = is_push ? P_PUSH_REG : P_POP_REG;
        p->words = 1u;
        return TR_OK;
    }

    /* push imm32 / push imm8, sign-extended to 64 bits. The immediate is
     * materialised in X16 and stored with the same pre-indexed writeback, so the
     * stack pointer still advances by exactly 8. */
    if (in.op[0] == 0x68 || in.op[0] == 0x6A) {
        p->const_val = (in.op[0] == 0x6A)
                     ? (uint64_t)(int64_t)(int8_t)in.imm
                     : (uint64_t)(int64_t)(int32_t)in.imm;
        p->op = P_PUSH_IMM;
        p->words = const_words(p->const_val) + 1u;
        return TR_OK;
    }

    /* leave == mov rsp,rbp ; pop rbp */
    if (in.op[0] == 0xC9 && in.rex == 0) {
        p->op = P_LEAVE; p->words = 2u; return TR_OK;
    }

    /* mov with a memory operand: the local-variable accesses of a real frame, and
     * the RIP-relative accesses to the module's own globals.
     *
     * Both widths are accepted. `mov eax,[rbp-8]` is as much a local as
     * `mov rax,[rbp-8]` is, and refusing the 32-bit one would leave a hole in
     * exactly the code the 32-bit operand forms were added to reach. */
    if ((in.op[0] == 0x89 || in.op[0] == 0x8B) && in.has_modrm && in.mod != 3) {
        unsigned       gbase = 0, vreg;
        int64_t        d = in.disp;
        mem_base_kind  k = classify_mem_base(&in, &gbase);
        int            w32 = !in.rex_w;
        int            load = (in.op[0] == 0x8B);

        if (!map_guest_reg(in.reg, in.rex_r, &vreg)) {
            out->reason = TRR_REGISTER;
            out->detail = "memory operand: register outside the mapped set";
            return TR_UNSUPPORTED;
        }

        /* RIP-relative: the one form of "not on the guest stack" that is
         * translatable. The displacement is relative to the instruction after
         * this one, so the decoder has already computed the target guest VA, and
         * subtracting the image base turns it into an RVA.
         *
         * The RVA is materialised into X16 at run time and added by the load
         * itself - `LDR Xt, [X19, X16]` - rather than being resolved to an
         * absolute host address during translation. That distinction is the whole
         * point: an absolute address in the code would tie the translation to one
         * process's layout and break the persistent cache, and it would also need
         * a relocation. An RVA plus a base register needs neither. */
        if (k == MB_RIP_REL) {
            uint64_t tgt = in.rip_rel_target;
            if (image_base_va == 0 || image_size == 0) {
                out->reason = TRR_IMG_BASE;
                out->detail = "a RIP-relative operand is translatable, but the "
                              "module's image base was not supplied";
                return TR_UNSUPPORTED;
            }
            /* Bound it at translation time. A RIP-relative displacement can point
             * anywhere in the address space, and one landing outside the image
             * would read whatever the host has past the mapping - a plausible
             * looking value that is not the guest's. Nothing at run time would
             * notice, which is what makes this worth refusing. */
            if (tgt < image_base_va || tgt - image_base_va >= image_size) {
                out->reason = TRR_IMG_BASE;
                out->detail = "a RIP-relative operand points outside the module "
                              "image, so it is not a global this module owns";
                return TR_UNSUPPORTED;
            }
            p->op = load ? P_LD_IMG : P_ST_IMG;
            p->rd = vreg;
            p->const_val = tgt - image_base_va;   /* the RVA */
            p->w32 = w32;
            /* MOVZ/MOVK of the RVA into X16, then the register-offset access.
             * The RVA always goes into a 64-bit register because X16 supplies a
             * byte offset, and truncating it would silently reach a different
             * global once an image exceeds 4 GiB. */
            p->words = const_words_w(p->const_val, 0) + 1u;
            return TR_OK;
        }

        if (k == MB_ABS) {
            out->reason = TRR_ABS_ADDR;
            out->detail = "absolute disp32 addressing: the target is a guest "
                          "virtual address in the encoding, so it needs a "
                          "relocation rather than a base register";
            return TR_UNSUPPORTED;
        }
        /* A scaled index is refused on its own reason, and the wording matters: it
         * is not "a guest pointer with nowhere to point", which the base-register
         * case below now solves. It needs a shift and a second guest register held
         * live across the access, which is a different increment. Labelling the two
         * alike puts the wrong item on the work queue. */
        if (k == MB_INDEX) {
            out->reason = TRR_GUEST_MEM;
            out->detail = "a scaled index register: needs a shift and a second "
                          "guest register live across the access";
            return TR_UNSUPPORTED;
        }

        /* A guest pointer in a general register. Unlike the RIP-relative case above,
         * the address is not knowable during translation, so the bound cannot be
         * settled here - it has to be checked in the emitted code on every access.
         *
         * The check is against the one region this model actually maps: the module's
         * own image. A pointer into a heap, another module, or the guest stack fails
         * it and takes the trap, which is the honest outcome - there is no general
         * guest address space yet, and inventing a plausible value for one would be
         * worse than stopping. What this buys today is that an in-image pointer (a
         * global reached indirectly, a jump-table entry, a string constant passed in
         * a register) is translated exactly instead of refused. */
        if (k == MB_OTHER) {
            unsigned bhost;
            if (image_base_va == 0 || image_size == 0) {
                out->reason = TRR_IMG_BASE;
                out->detail = "a register-base operand is translatable, but the "
                              "module's image base and size were not supplied";
                return TR_UNSUPPORTED;
            }
            /* gbase already has REX.B folded in by classify_mem_base. */
            if (!map_guest_reg(gbase, 0, &bhost)) {
                out->reason = TRR_REGISTER;
                out->detail = "memory operand: base register outside the mapped set";
                return TR_UNSUPPORTED;
            }
            p->op        = load ? P_LD_GUEST : P_ST_GUEST;
            p->rd        = vreg;
            p->rn        = bhost;
            p->delta     = d;
            p->const_val = image_base_va;
            p->img_size  = image_size;
            p->w32       = w32;
            p->words     = guest_mem_words(d, image_base_va, image_size);
            return TR_OK;
        }

        /* Which displacements are legitimate depends on the base, and getting
         * this wrong is silent:
         *   - [rbp + non-negative] addresses the CALLER's frame: the saved frame
         *     pointer above it, the return address, and any incoming stack
         *     arguments. This model does not lay any of that out - the return
         *     address lives in X30 and arguments arrive in registers - so
         *     reading it would return arena garbage that looks like a value.
         *   - [rsp - n] is the SysV red zone. Windows x64 has no red zone and
         *     the arena has a PROT_NONE guard page below it, so this faults
         *     rather than corrupting, but refusing says why. */
        if (gbase == 5u && d >= 0) {
            out->reason = TRR_STACK;
            out->detail = "a non-negative RBP displacement reaches into the "
                          "caller's frame, which this model does not lay out";
            return TR_UNSUPPORTED;
        }
        if (gbase == 4u && d < 0) {
            out->reason = TRR_STACK;
            out->detail = "a negative RSP displacement is the red zone, which is "
                          "unmapped below the guest stack arena";
            return TR_UNSUPPORTED;
        }
        /* LDUR/STUR carry a signed 9-bit byte offset. Outside that a scratch
         * register and a register-offset form would be needed. */
        if (!a64_imm9_range_ok((int)d)) {
            out->reason = TRR_IMM_RANGE;
            out->detail = "stack displacement does not fit a signed 9-bit offset";
            return TR_UNSUPPORTED;
        }
        p->rd = vreg;
        p->rn = (gbase == 4u) ? HOST_RSP : HOST_RBP;
        p->delta = d;
        p->w32 = w32;
        /* 0x89 is `mov r/m, r`, a store; 0x8B is `mov r, r/m`, a load. */
        p->op = load ? P_LD_LOCAL : P_ST_LOCAL;
        p->words = 1u;
        return TR_OK;
    }

    out->reason = TRR_UNSUPPORTED_OP; out->detail = "instruction is outside the translated subset";
    return TR_UNSUPPORTED;
}

tr_status tr_translate_function(const uint8_t *code, size_t code_len,
                                uint64_t guest_va, tr_resolve_fn resolve,
                                void *user, tr_func *out)
{
    return tr_translate_function_at(code, code_len, guest_va, 0u, resolve, user,
                                    out);
}

tr_status tr_translate_function_at(const uint8_t *code, size_t code_len,
                                   uint64_t base_va, size_t start_off,
                                   tr_resolve_fn resolve, void *user,
                                   tr_func *out)
{
    /* No image base, so RIP-relative data access is refused with TRR_IMG_BASE
     * rather than guessed at. Callers that have loaded a module should use
     * tr_translate_function_img and get it. */
    return tr_translate_function_img(code, code_len, base_va, start_off, 0, 0,
                                     resolve, user, out);
}

tr_status tr_translate_function_img(const uint8_t *code, size_t code_len,
                                    uint64_t base_va, size_t start_off,
                                    uint64_t image_base_va, uint64_t image_size,
                                    tr_resolve_fn resolve, void *user,
                                    tr_func *out)
{
    uint64_t guest_va = base_va;   /* address of code[0]; entry is start_off in */
    plan     plans[TRF_MAX_INSN];
    uint8_t *seen = NULL;
    uint32_t stack[TRF_MAX_INSN];
    size_t   sp = 0, nplans = 0, i, j;
    uint32_t cursor;
    uint32_t entry_words;      /* frame record words at entry and before each RET */
    int      order_changed = 1;

    if (!out) return TR_INVALID;
    memset(out, 0, sizeof(*out));
    out->reason = TRR_UNSUPPORTED_OP; out->detail = "ok";
    if (!code || code_len == 0 || code_len > TRF_MAX_CODE_BYTES) {
        /* This used to report TRR_UNSUPPORTED_OP, the value the record is
         * initialised to before pass 1, which made it indistinguishable in a
         * histogram from a function whose first instruction really was outside
         * the subset. Measured on a shipped bundle that mislabelling was the
         * second largest refusal bucket: 62 code entry points, every one reported
         * as an unsupported opcode with no opcode attributable, all of them in
         * fact rejected here because the module's code section was larger than
         * the old 1 MiB cap and was never examined at all. A function this
         * translator never looked at is not a function it found unsupported. */
        out->reason = TRR_BUFFER;
        out->detail = !code ? "no guest code supplied"
                    : code_len == 0 ? "guest buffer is empty"
                    : "guest buffer is larger than TRF_MAX_CODE_BYTES";
        return TR_INVALID;
    }
    seen = calloc((code_len + 7u) / 8u, 1u);
    if (!seen) { out->reason = TRR_BUFFER; out->detail = "out of memory for the discovery marks";
                 return TR_INVALID; }

    /* ---- pass 1: discover and plan, following direct branches ---- */
    if (start_off >= code_len) {
        out->reason = TRR_BUFFER;   /* likewise: nothing was examined */
        out->detail = "start offset is past the end of the buffer";
        free(seen);
        return TR_INVALID;
    }
    stack[sp++] = (uint32_t)start_off;
    seen_set(seen, (uint32_t)start_off);
    while (sp) {
        uint32_t off = stack[--sp];
        plan p;
        tr_status st = plan_one(code, code_len, off, guest_va, image_base_va,
                                image_size, resolve, user, &p, out);
        if (st != TR_OK) {
            /* nplans is how many instructions made it through, so it is exactly the
             * depth at which this one failed. Zero means the entry point's first
             * instruction is not in the subset; larger means the function translated
             * for a while and then met something, which is a different problem. */
            out->fail_insns = (uint32_t)nplans;
            free(seen);
            return st;
        }
        if (nplans >= TRF_MAX_INSN) {
            out->reason = TRR_OVERFLOW; out->detail = "more instructions than TRF_MAX_INSN";
            free(seen);
            return TR_OVERFLOW;
        }
        plans[nplans++] = p;

        /* Successors. This is the part that decides whether a whole function is
         * discovered or only its first instruction: every instruction that is not
         * an unconditional terminator also falls through, and a conditional branch
         * falls through AND branches. Getting this wrong does not fail loudly - it
         * produces a translation of a prefix that looks complete. */
        if (p.op == P_RET) {
            /* ends this path */
        } else if (p.op == P_JMP) {
            uint64_t t = p.target_va;
            if (t < guest_va || t - guest_va >= code_len) {
                out->reason = TRR_LEAVES_FUNC; out->detail = "unconditional branch leaves the function";
                blame(out, &p, (uint32_t)nplans);
                free(seen); return TR_UNSUPPORTED;
            }
            if (!seen_get(seen, (uint32_t)(t - guest_va))) {
                if (sp >= TRF_MAX_INSN) {
                    out->reason = TRR_OVERFLOW; out->detail = "worklist overflow"; free(seen); return TR_OVERFLOW;
                }
                seen_set(seen, (uint32_t)(t - guest_va));
                stack[sp++] = (uint32_t)(t - guest_va);
            }
        } else {
            uint32_t next = off + p.guest_len;
            if (p.op == P_JCC) {
                uint64_t t = p.target_va;
                if (t < guest_va || t - guest_va >= code_len) {
                    out->reason = TRR_LEAVES_FUNC; out->detail = "conditional branch leaves the function";
                blame(out, &p, (uint32_t)nplans);
                    free(seen); return TR_UNSUPPORTED;
                }
                if (!seen_get(seen, (uint32_t)(t - guest_va))) {
                    if (sp >= TRF_MAX_INSN) {
                        out->reason = TRR_OVERFLOW; out->detail = "worklist overflow"; free(seen); return TR_OVERFLOW;
                    }
                    seen_set(seen, (uint32_t)(t - guest_va));
                    stack[sp++] = (uint32_t)(t - guest_va);
                }
            }
            if (next >= code_len) {
                /* A function whose last instruction is not a RET has no return, so
                 * translating it would emit code that runs off the end. */
                out->reason = TRR_NO_RET; out->detail = "function ends without a RET";
                blame(out, &p, (uint32_t)nplans);
                free(seen);
                return TR_UNSUPPORTED;
            }
            if (!seen_get(seen, next)) {
                if (sp >= TRF_MAX_INSN) {
                    out->reason = TRR_OVERFLOW; out->detail = "worklist overflow"; free(seen); return TR_OVERFLOW;
                }
                seen_set(seen, next);
                stack[sp++] = next;
            }
        }
    }
    free(seen);

    /* ---- sort by guest address so layout and adjacency are both in order ---- */
    while (order_changed) {
        order_changed = 0;
        for (i = 1; i < nplans; i++) {
            if (plans[i - 1].off > plans[i].off) {
                plan t = plans[i - 1];
                plans[i - 1] = plans[i];
                plans[i] = t;
                order_changed = 1;
            }
        }
    }

    /* ---- flag liveness: a conditional branch may only read flags that this
     * translator actually produced, immediately before it ---- */
    for (i = 0; i < nplans; i++) {
        if (plans[i].op != P_JCC) continue;
        if (i == 0 || !plans[i - 1].sets_flags ||
            plans[i - 1].off + plans[i - 1].guest_len != plans[i].off) {
            out->reason = TRR_FLAGS;
            out->detail = "a conditional branch would read flags this translator "
                          "did not produce: it must be preceded immediately by a "
                          "modelled CMP or TEST";
            blame(out, &plans[i], (uint32_t)i);
            return TR_UNSUPPORTED;
        }
        for (j = 0; j < nplans; j++) {
            if ((plans[j].op == P_JCC || plans[j].op == P_JMP) &&
                plans[j].target_va == plans[i].guest_va) {
                out->reason = TRR_FLAGS;
                out->detail = "a branch targets a conditional branch, so the flags "
                              "it reads would come from elsewhere";
                blame(out, &plans[j], (uint32_t)i);
                return TR_UNSUPPORTED;
            }
        }
    }

    out->lo_off = plans[0].off;
    out->hi_off = plans[0].off + plans[0].guest_len;
    for (i = 0; i < nplans; i++) {
        uint32_t end = plans[i].off + plans[i].guest_len;
        if (plans[i].op == P_CALL_IAT) out->needs_frame = 1;
        if (plan_uses_gstack(&plans[i]))  out->needs_gstack = 1;
        if (plan_uses_imgbase(&plans[i])) out->needs_imgbase = 1;
        if (end > out->extent) out->extent = end;
        if (plans[i].off < out->lo_off) out->lo_off = plans[i].off;
        if (end > out->hi_off) out->hi_off = end;
    }

    /* ---- pass 2: layout. Sizes are already fixed, so one pass is enough. ---- */
    /* Two independent frame records may be needed, and both are one word: the
     * X29/X30 pair for a translation that calls something, and the X14/X15 pair
     * for one that uses the guest stack. Each RET has to undo both. */
    /* Push order is frame, guest stack, image base; each RET pops them in the
     * reverse. The order has to match at both ends or a return restores a
     * register from the wrong slot, which is not caught by anything except the
     * value it produces. */
    entry_words = (out->needs_frame ? 1u : 0u) + (out->needs_gstack ? 1u : 0u) +
                  (out->needs_imgbase ? 1u : 0u);
    cursor = entry_words;
    for (i = 0; i < nplans; i++) {
        plans[i].word_at = cursor;
        cursor += plans[i].words;
        if (plans[i].op == P_RET) cursor += entry_words;
    }
    if (cursor + entry_words > TRF_MAX_WORDS) {
        out->reason = TRR_OVERFLOW; out->detail = "translation exceeds TRF_MAX_WORDS";
        return TR_OVERFLOW;
    }

    /* ---- pass 3: emit ---- */
    /* Push order is X29/X30 first, then X14/X15, so the guest stack record ends
     * up at [SP] and is popped first at every RET. Reversing that order here
     * without reversing it below would restore the caller's link register with
     * the guest stack pointer, and the code would return to an address that came
     * off the guest stack - a jump somewhere plausible and wrong. */
    if (out->needs_frame && !pushf(out, a64_stp_frame_push())) return TR_OVERFLOW;
    if (out->needs_gstack && !pushf(out, a64_stp_gstack_push())) return TR_OVERFLOW;
    if (out->needs_imgbase && !pushf(out, a64_stp_imgbase_push())) return TR_OVERFLOW;

    for (i = 0; i < nplans; i++) {
        const plan *p = &plans[i];
        out->insns++;
        out->guest_bytes += p->guest_len;

        switch (p->op) {
        case P_MOV_IMM:
            if (!emit_const_f_w(out, p->rd, p->const_val, p->w32)) return TR_OVERFLOW;
            break;
        case P_MOV_REG:
            if (!pushf(out, p->w32 ? a64_mov_reg_w(p->rd, p->rn)
                                   : a64_mov_reg(p->rd, p->rn))) return TR_OVERFLOW;
            break;
        case P_ZERO:
            if (!pushf(out, p->w32 ? a64_movz_w(p->rd, 0)
                                   : a64_movz_x(p->rd, 0))) return TR_OVERFLOW;
            break;
        case P_ADD_REG:
            if (!pushf(out, p->w32 ? a64_add_reg_w(p->rd, p->rd, p->rn)
                                   : a64_add_reg(p->rd, p->rd, p->rn))) return TR_OVERFLOW;
            break;
        case P_SUB_REG:
            if (!pushf(out, p->w32 ? a64_sub_reg_w(p->rd, p->rd, p->rn)
                                   : a64_sub_reg(p->rd, p->rd, p->rn))) return TR_OVERFLOW;
            break;
        case P_ADD_IMM:
        case P_SUB_IMM:
            if (p->delta >= 0) {
                if (!pushf(out, p->w32 ? a64_add_w_imm(p->rd, p->rd, (uint16_t)p->delta)
                                       : a64_add_x_imm(p->rd, p->rd, (uint16_t)p->delta)))
                    return TR_OVERFLOW;
            } else {
                if (!pushf(out, p->w32 ? a64_sub_w_imm(p->rd, p->rd, (uint16_t)(-p->delta))
                                       : a64_sub_x_imm(p->rd, p->rd, (uint16_t)(-p->delta))))
                    return TR_OVERFLOW;
            }
            break;
        case P_CMP_REG:
            if (!pushf(out, p->w32 ? a64_subs_reg_w(A64_XZR, p->rn, p->rm)
                                   : a64_subs_reg(A64_XZR, p->rn, p->rm))) return TR_OVERFLOW;
            break;
        case P_CMP_IMM:
            /* cmp r, k is SUBS XZR, r, k. A negative k has no subtract-immediate
             * encoding, so it becomes CMN, which is ADDS XZR, r, -k: the same
             * comparison, and the flags come out identical. */
            if (p->delta >= 0) {
                if (!pushf(out, p->w32 ? a64_subs_w_imm(A64_XZR, p->rd, (uint16_t)p->delta)
                                       : a64_subs_imm(A64_XZR, p->rd, (uint16_t)p->delta)))
                    return TR_OVERFLOW;
            } else {
                if (!pushf(out, p->w32 ? a64_adds_w_imm(A64_XZR, p->rd, (uint16_t)(-p->delta))
                                       : a64_adds_imm(A64_XZR, p->rd, (uint16_t)(-p->delta))))
                    return TR_OVERFLOW;
            }
            break;
        case P_TEST_REG:
            if (!pushf(out, p->w32 ? a64_ands_reg_w(A64_XZR, p->rn, p->rm)
                                   : a64_ands_reg(A64_XZR, p->rn, p->rm))) return TR_OVERFLOW;
            break;
        case P_JCC:
        case P_JMP: {
            uint32_t tgt_word = 0;
            int found = 0;
            for (j = 0; j < nplans; j++) {
                if (plans[j].guest_va == p->target_va) { tgt_word = plans[j].word_at; found = 1; break; }
            }
            if (!found) { out->reason = TRR_INTERNAL; out->detail = "branch target was not planned"; return TR_INVALID; }
            {
                int32_t delta = (int32_t)tgt_word - (int32_t)p->word_at;
                if (p->op == P_JCC) {
                    out->branches++;
                    if (delta < 0) out->backwards++;
                    if (!a64_cond_range_ok(delta)) {
                        out->reason = TRR_OVERFLOW; out->detail = "conditional branch displacement exceeds 19 bits";
                        return TR_OVERFLOW;
                    }
                    if (!pushf(out, a64_b_cond(p->cond, delta))) return TR_OVERFLOW;
                } else {
                    out->branches++;
                    if (delta < 0) out->backwards++;
                    if (!a64_b_range_ok(delta)) {
                        out->reason = TRR_OVERFLOW; out->detail = "branch displacement exceeds 26 bits";
                        return TR_OVERFLOW;
                    }
                    if (!pushf(out, a64_b(delta))) return TR_OVERFLOW;
                }
            }
            break;
        }
        case P_PUSH_REG:
            /* STR with pre-indexed writeback: the store and the 8-byte advance of
             * the guest stack pointer are one instruction, so they cannot drift
             * apart the way a separate SUB followed by a scaled store could. */
            if (!a64_imm9_range_ok(-8)) return TR_OVERFLOW;
            if (!pushf(out, a64_str_pre(p->rd, HOST_RSP, -8))) return TR_OVERFLOW;
            break;
        case P_POP_REG:
            if (!pushf(out, a64_ldr_post(p->rd, HOST_RSP, 8))) return TR_OVERFLOW;
            break;
        case P_PUSH_IMM:
            /* The immediate has to be materialised somewhere before it can be
             * stored. X16 is used and is safe: it is only ever live between being
             * written and being consumed by the instruction immediately after,
             * both here and at a resolved call. */
            if (!emit_const_f(out, HOST_SCRATCH, p->const_val)) return TR_OVERFLOW;
            if (!pushf(out, a64_str_pre(HOST_SCRATCH, HOST_RSP, -8))) return TR_OVERFLOW;
            break;
        case P_LEAVE:
            /* mov rsp,rbp then pop rbp. The second instruction reads the memory
             * the first just pointed at, which is exactly the x86 semantics. */
            if (!pushf(out, a64_mov_reg(HOST_RSP, HOST_RBP))) return TR_OVERFLOW;
            if (!pushf(out, a64_ldr_post(HOST_RBP, HOST_RSP, 8))) return TR_OVERFLOW;
            break;
        case P_LEA_IMM: {
            int64_t d = p->delta;
            int neg = d < 0;
            uint64_t mag = (uint64_t)(neg ? -d : d);
            if (mag <= 0xFFFu) {
                uint32_t w;
                if (neg) w = p->w32 ? a64_sub_w_imm(p->rd, p->rn, (uint16_t)mag)
                                    : a64_sub_x_imm(p->rd, p->rn, (uint16_t)mag);
                else     w = p->w32 ? a64_add_w_imm(p->rd, p->rn, (uint16_t)mag)
                                    : a64_add_x_imm(p->rd, p->rn, (uint16_t)mag);
                if (!pushf(out, w)) return TR_OVERFLOW;
                break;
            }
            /* Too large for the immediate field: put the magnitude in X16 and use
             * the register form. X16 is safe here for the same reason it is safe at
             * a push of an immediate - it is live only between being written and
             * being consumed by the instruction right after it. */
            if (!emit_const_f(out, HOST_SCRATCH, mag)) return TR_OVERFLOW;
            if (!pushf(out, neg
                    ? (p->w32 ? a64_sub_reg_w(p->rd, p->rn, HOST_SCRATCH)
                              : a64_sub_reg(p->rd, p->rn, HOST_SCRATCH))
                    : (p->w32 ? a64_add_reg_w(p->rd, p->rn, HOST_SCRATCH)
                              : a64_add_reg(p->rd, p->rn, HOST_SCRATCH))))
                return TR_OVERFLOW;
            break;
        }

        case P_LD_IMG:
        case P_ST_IMG: {
            /* X16 = the RVA, then X19 + X16 does the addressing. No absolute
             * address is written into the code, so this translation is valid in
             * any process that maps the same image, wherever it maps it - which
             * is what keeps it in the persistent cache. */
            uint32_t acc = (p->op == P_LD_IMG)
                ? (p->w32 ? a64_ldr_reg_w(p->rd, HOST_IMGBASE, HOST_SCRATCH)
                          : a64_ldr_reg(p->rd, HOST_IMGBASE, HOST_SCRATCH))
                : (p->w32 ? a64_str_reg_w(p->rd, HOST_IMGBASE, HOST_SCRATCH)
                          : a64_str_reg(p->rd, HOST_IMGBASE, HOST_SCRATCH));
            if (!emit_const_f(out, HOST_SCRATCH, p->const_val)) return TR_OVERFLOW;
            if (!pushf(out, acc)) return TR_OVERFLOW;
            break;
        }

        case P_LD_GUEST:
        case P_ST_GUEST: {
            /* A guest pointer in a general register, dereferenced against the one
             * region this model maps. Word for word this must match
             * guest_mem_words(); the branch displacements below are literals that
             * are only correct for that exact sequence, so the two are deliberately
             * written next to each other in shape.
             *
             * No absolute host address appears anywhere in it. The image base and
             * size are *guest* constants - the same kind of value the RIP-relative
             * case already bakes in - and the host base arrives in X19 at run time,
             * so the emitted words stay valid in any process that maps the image
             * anywhere. That is what keeps this in the persistent cache. */
            uint64_t mag = (p->delta < 0) ? (uint64_t)(-(p->delta + 1)) + 1u
                                          : (uint64_t)p->delta;
            uint32_t access;

            /* 1. the guest virtual address into X16. */
            if (p->delta == 0) {
                if (!pushf(out, a64_mov_reg(HOST_SCRATCH, p->rn))) return TR_OVERFLOW;
            } else if (mag <= 0xFFFu) {
                if (!pushf(out, (p->delta < 0)
                        ? a64_sub_x_imm(HOST_SCRATCH, p->rn, (uint16_t)mag)
                        : a64_add_x_imm(HOST_SCRATCH, p->rn, (uint16_t)mag)))
                    return TR_OVERFLOW;
            } else {
                /* Beyond the 12-bit immediate field: materialise the magnitude and
                 * use the register form. Truncating it instead would address a
                 * different guest location that still looks valid. */
                if (!emit_const_f(out, HOST_SCRATCH, mag)) return TR_OVERFLOW;
                if (!pushf(out, (p->delta < 0)
                        ? a64_sub_reg(HOST_SCRATCH, p->rn, HOST_SCRATCH)
                        : a64_add_reg(HOST_SCRATCH, p->rn, HOST_SCRATCH)))
                    return TR_OVERFLOW;
            }

            /* 2. X17 = guest VA - image base. A VA below the base wraps. */
            if (!emit_const_f(out, HOST_TMP2, p->const_val)) return TR_OVERFLOW;
            if (!pushf(out, a64_sub_reg(HOST_TMP2, HOST_SCRATCH, HOST_TMP2)))
                return TR_OVERFLOW;

            /* 3. one unsigned compare rejects both ends, because the wrapped value
             *    from a VA below the base is >= any real image size. */
            if (!emit_const_f(out, HOST_SCRATCH, p->img_size)) return TR_OVERFLOW;
            if (!pushf(out, a64_subs_reg(A64_XZR, HOST_TMP2, HOST_SCRATCH)))
                return TR_OVERFLOW;
            /* -> the BRK, which sits 4 words ahead: ADD, access, B, BRK. */
            if (!pushf(out, a64_b_cond(A64_HS, 4))) return TR_OVERFLOW;

            /* 4. host address, then the access itself. */
            if (!pushf(out, a64_add_reg(HOST_TMP2, HOST_IMGBASE, HOST_TMP2)))
                return TR_OVERFLOW;
            access = (p->op == P_LD_GUEST)
                ? (p->w32 ? a64_ldur_w(p->rd, HOST_TMP2, 0)
                          : a64_ldur  (p->rd, HOST_TMP2, 0))
                : (p->w32 ? a64_stur_w(p->rd, HOST_TMP2, 0)
                          : a64_stur  (p->rd, HOST_TMP2, 0));
            if (!pushf(out, access)) return TR_OVERFLOW;

            /* 5. step over the trap: BRK is 1 word ahead, the next guest
             *    instruction is 2. */
            if (!pushf(out, a64_b(2))) return TR_OVERFLOW;
            if (!pushf(out, a64_brk(A64_BRK_GUEST_OOB))) return TR_OVERFLOW;
            break;
        }

        case P_ST_LOCAL:
            /* The W form writes 4 bytes and leaves the upper half of the register
             * alone, which is exactly what a 32-bit x86-64 store does. */
            if (!pushf(out, p->w32 ? a64_stur_w(p->rd, p->rn, (int)p->delta)
                                   : a64_stur(p->rd, p->rn, (int)p->delta)))
                return TR_OVERFLOW;
            break;
        case P_LD_LOCAL:
            if (!pushf(out, p->w32 ? a64_ldur_w(p->rd, p->rn, (int)p->delta)
                                   : a64_ldur(p->rd, p->rn, (int)p->delta)))
                return TR_OVERFLOW;
            break;
        case P_CALL_IAT:
            if (p->host_abi) {
                /* Nine registers a host callee destroys and x86-64 requires
                 * preserved: RBX=X3, RSI=X4, RDI=X5, R12=X10, R13=X11, R14=X12,
                 * R15=X13, RBP=X15 and RSP=X14. Five pairs of 16 bytes keeps the
                 * host SP 16-byte aligned at the call, which AAPCS64 requires. The
                 * last pair stores X14 twice instead of inventing a single-register
                 * form: both slots hold the same value, the pop restores it, and it
                 * costs one redundant store rather than a new emitter. */
                static const unsigned sv[5][2] = {
                    { 3u, 4u }, { 5u, 15u }, { 10u, 11u }, { 12u, 13u }, { 14u, 14u }
                };
                for (unsigned k = 0; k < 5u; k++)
                    if (!pushf(out, a64_stp_pre(sv[k][0], sv[k][1], 31u, -16)))
                        return TR_OVERFLOW;
                /* Guest RCX,RDX,R8,R9 are X1,X2,X6,X7; the AAPCS wants X0..X3. Two
                 * temporaries are needed because X1 and X2 are each both a source
                 * and a destination. Both are dead before the target is loaded. */
                if (!pushf(out, a64_mov_reg(HOST_SCRATCH, 1u))) return TR_OVERFLOW;
                if (!pushf(out, a64_mov_reg(HOST_TMP2, 2u)))    return TR_OVERFLOW;
                if (!pushf(out, a64_mov_reg(0u, HOST_SCRATCH))) return TR_OVERFLOW;
                if (!pushf(out, a64_mov_reg(1u, HOST_TMP2)))    return TR_OVERFLOW;
                if (!pushf(out, a64_mov_reg(2u, 6u)))           return TR_OVERFLOW;
                if (!pushf(out, a64_mov_reg(3u, 7u)))           return TR_OVERFLOW;
                if (!emit_const_f(out, HOST_SCRATCH, p->const_val)) return TR_OVERFLOW;
                if (!pushf(out, a64_blr(HOST_SCRATCH))) return TR_OVERFLOW;
                /* The host returns in X0, which is guest RAX, so the result needs no
                 * shuffling back. Pop in reverse order of the pushes. */
                for (unsigned k = 5u; k-- > 0u;)
                    if (!pushf(out, a64_ldp_post(sv[k][0], sv[k][1], 31u, 16)))
                        return TR_OVERFLOW;
                break;
            }
            if (!emit_const_f(out, HOST_SCRATCH, p->const_val)) return TR_OVERFLOW;
            if (!pushf(out, a64_blr(HOST_SCRATCH))) return TR_OVERFLOW;
            break;
        case P_RET:
            /* Reverse of the prologue: the X14/X15 record was pushed last, so it
             * is at [SP] and comes off first. Restoring X14 here is also what
             * makes the guest stack pointer balanced at return regardless of how
             * the guest code left it, so an early return cannot hand the caller a
             * skewed stack pointer. */
            if (out->needs_imgbase && !pushf(out, a64_ldp_imgbase_pop())) return TR_OVERFLOW;
            if (out->needs_gstack && !pushf(out, a64_ldp_gstack_pop())) return TR_OVERFLOW;
            if (out->needs_frame && !pushf(out, a64_ldp_frame_pop())) return TR_OVERFLOW;
            if (!pushf(out, a64_ret())) return TR_OVERFLOW;
            break;
        default:
            out->reason = TRR_INTERNAL; out->detail = "internal: unplanned operation reached emission";
            return TR_INVALID;
        }
    }

    if (out->n != cursor) {
        /* Layout and emission disagreeing means a size was counted differently
         * from how it was emitted, which would put every later branch at the
         * wrong displacement. Detecting it here is cheap; finding it by executing
         * wrong code is not. */
        out->reason = TRR_INTERNAL; out->detail = "internal: emitted word count disagrees with the layout";
        return TR_INVALID;
    }
    /* Clear the refusal record on success. out->reason is initialised to
     * TRR_UNSUPPORTED_OP before pass 1 so that an early return always has a
     * reason to report, and leaving it there meant a translation that succeeded
     * was still labelled with the reason it did not fail for. Nothing reads
     * reason when the status is TR_OK today, which is exactly why it is worth
     * fixing: the first caller that does would build a histogram out of
     * successes counted as refusals. */
    out->reason = TRR_OK;
    out->fail_insns = 0;
    out->fail_op_len = 0;
    out->fail_from_plan = 0;
    memset(out->fail_op, 0, sizeof(out->fail_op));
    return TR_OK;
}
