#include "translate.h"

#include "a64_emit.h"
#include "x86_decode.h"

#include <stdlib.h>
#include <string.h>

#define HOST_RAX 0u      /* guest RAX -> X0 */
#define HOST_RCX 1u      /* guest RCX -> X1 */
#define HOST_SCRATCH 16u /* X16 / IP0: free for a translator to clobber */

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
    P_CMP_REG, P_CMP_IMM, P_TEST_REG, P_JCC, P_JMP, P_CALL_IAT, P_RET
} plan_op;

typedef struct {
    plan_op  op;
    uint64_t guest_va;
    uint32_t off;          /* byte offset into the guest buffer */
    uint32_t guest_len;
    unsigned rd, rn, rm;   /* host registers */
    uint64_t const_val;    /* MOV_IMM value, or the resolved host call target */
    int64_t  delta;        /* effective signed immediate for ADD/SUB/CMP imm */
    unsigned cond;         /* AArch64 condition code, for P_JCC */
    uint64_t target_va;    /* P_JCC and P_JMP */
    int      sets_flags;   /* leaves NZCV matching an x86 CMP */
    uint32_t words;        /* emitted size, fixed before layout */
    uint32_t word_at;      /* assigned by layout */
} plan;

/* Guest register -> host register. RSP and RBP are refused: using them implies a
 * guest stack model, and inventing one silently would be worse than refusing. */
static int map_guest_reg(unsigned field, int extended, unsigned *host)
{
    static const signed char tbl[16] = {
        0, 1, 2, 3, -1, -1, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13
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

static uint32_t const_words(uint64_t v)
{
    uint32_t n = 1u;
    unsigned sh;
    for (sh = 16u; sh < 64u; sh += 16u)
        if ((v >> sh) & 0xFFFFu) n++;
    return n;
}

static int pushf(tr_func *o, uint32_t insn)
{
    if (o->n >= TRF_MAX_WORDS) { o->detail = "output word buffer full"; return 0; }
    o->words[o->n++] = insn;
    return 1;
}

static int emit_const_f(tr_func *o, unsigned rd, uint64_t v)
{
    unsigned sh;
    if (!pushf(o, a64_movz_x(rd, (uint16_t)(v & 0xFFFFu)))) return 0;
    for (sh = 16u; sh < 64u; sh += 16u) {
        uint16_t chunk = (uint16_t)((v >> sh) & 0xFFFFu);
        if (chunk) { if (!pushf(o, a64_movk_x(rd, chunk, sh))) return 0; }
    }
    return 1;
}

/* Plans one guest instruction: decides the operation, the registers, and how many
 * ARM64 words it will emit. No emission happens here, so the layout pass has sizes
 * before any displacement is needed. */
static tr_status plan_one(const uint8_t *code, size_t code_len, uint32_t off,
                          uint64_t base_va, tr_resolve_fn resolve, void *user,
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

    /* ---- two-byte map: 0F 8x is the rel32 form of Jcc ---- */
    if (in.map == 1) {
        if (in.op[0] >= 0x80u && in.op[0] <= 0x8Fu) {
            if (!jcc_cond(in.op[0] & 0xFu, &p->cond)) {
                out->reason = TRR_PARITY; out->detail = "JP/JNP: AArch64 has no parity flag";
                return TR_UNSUPPORTED;
            }
            p->op = P_JCC;
            p->target_va = va + in.len + (uint64_t)(int64_t)in.imm;
            p->words = 1u;
            return TR_OK;
        }
        out->reason = TRR_UNSUPPORTED_OP; out->detail = "two-byte opcode outside the subset";
        return TR_UNSUPPORTED;
    }

    is_grp1 = (in.op[0] == 0x83 || in.op[0] == 0x81);

    if (in.op[0] == 0xC3 && in.rex == 0 && in.mod == 0) {
        p->op = P_RET; p->words = 1u; return TR_OK;
    }
    if (in.op[0] == 0xEB || in.op[0] == 0xE9) {
        p->op = P_JMP;
        p->target_va = va + in.len + (uint64_t)(int64_t)in.imm;
        p->words = 1u;
        return TR_OK;
    }
    if (in.op[0] >= 0x70u && in.op[0] <= 0x7Fu) {
        if (!jcc_cond(in.op[0] & 0xFu, &p->cond)) {
            out->reason = TRR_PARITY; out->detail = "JP/JNP: AArch64 has no parity flag";
            return TR_UNSUPPORTED;
        }
        p->op = P_JCC;
        p->target_va = va + in.len + (uint64_t)(int64_t)in.imm;
        p->words = 1u;
        return TR_OK;
    }
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
        p->op = P_CALL_IAT;
        p->const_val = host;
        p->words = const_words(host) + 1u;
        return TR_OK;
    }
    if (in.op[0] == 0xC7 && in.rex_w && in.mod == 3 && in.reg == 0) {
        if (!map_guest_reg(in.rm, in.rex_b, &p->rd)) {
            out->reason = TRR_REGISTER; out->detail = "mov imm: register outside the mapped set";
            return TR_UNSUPPORTED;
        }
        p->op = P_MOV_IMM;
        p->const_val = (uint64_t)(int64_t)(int32_t)in.imm;
        p->words = const_words(p->const_val);
        return TR_OK;
    }
    if (in.op[0] == 0x89 && in.rex_w && in.mod == 3) {
        if (!map_guest_reg(in.rm, in.rex_b, &p->rd) ||
            !map_guest_reg(in.reg, in.rex_r, &p->rn)) {
            out->reason = TRR_REGISTER; out->detail = "mov reg: register outside the mapped set";
            return TR_UNSUPPORTED;
        }
        p->op = P_MOV_REG; p->words = 1u; return TR_OK;
    }
    if (in.op[0] == 0x31 && in.rex_w && in.mod == 3) {
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
        p->op = P_ZERO; p->rd = a; p->words = 1u; return TR_OK;
    }
    if (in.op[0] == 0x01 && in.rex_w && in.mod == 3) {
        if (!map_guest_reg(in.rm, in.rex_b, &p->rd) ||
            !map_guest_reg(in.reg, in.rex_r, &p->rn)) {
            out->reason = TRR_REGISTER; out->detail = "add reg: register outside the mapped set";
            return TR_UNSUPPORTED;
        }
        p->op = P_ADD_REG; p->words = 1u; return TR_OK;
    }
    if (in.op[0] == 0x29 && in.rex_w && in.mod == 3) {
        if (!map_guest_reg(in.rm, in.rex_b, &p->rd) ||
            !map_guest_reg(in.reg, in.rex_r, &p->rn)) {
            out->reason = TRR_REGISTER; out->detail = "sub reg: register outside the mapped set";
            return TR_UNSUPPORTED;
        }
        p->op = P_SUB_REG; p->words = 1u; return TR_OK;
    }
    if (in.op[0] == 0x39 && in.rex_w && in.mod == 3) {
        if (!map_guest_reg(in.rm, in.rex_b, &p->rn) ||
            !map_guest_reg(in.reg, in.rex_r, &p->rm)) {
            out->reason = TRR_REGISTER; out->detail = "cmp reg: register outside the mapped set";
            return TR_UNSUPPORTED;
        }
        p->op = P_CMP_REG; p->sets_flags = 1; p->words = 1u; return TR_OK;
    }
    if (in.op[0] == 0x85 && in.rex_w && in.mod == 3) {
        if (!map_guest_reg(in.rm, in.rex_b, &p->rn) ||
            !map_guest_reg(in.reg, in.rex_r, &p->rm)) {
            out->reason = TRR_REGISTER; out->detail = "test: register outside the mapped set";
            return TR_UNSUPPORTED;
        }
        p->op = P_TEST_REG; p->sets_flags = 1; p->words = 1u; return TR_OK;
    }
    if (is_grp1 && in.rex_w && in.mod == 3 &&
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
    uint64_t guest_va = base_va;   /* address of code[0]; entry is start_off in */
    plan     plans[TRF_MAX_INSN];
    uint8_t *seen = NULL;
    uint32_t stack[TRF_MAX_INSN];
    size_t   sp = 0, nplans = 0, i, j;
    uint32_t cursor;
    int      order_changed = 1;

    if (!out) return TR_INVALID;
    memset(out, 0, sizeof(*out));
    out->reason = TRR_UNSUPPORTED_OP; out->detail = "ok";
    if (!code || code_len == 0 || code_len > (1u << 20)) {
        out->reason = TRR_UNSUPPORTED_OP; out->detail = "guest buffer absent or implausibly large";
        return TR_INVALID;
    }
    seen = calloc(code_len, 1u);
    if (!seen) { out->reason = TRR_UNSUPPORTED_OP; out->detail = "out of memory"; return TR_INVALID; }

    /* ---- pass 1: discover and plan, following direct branches ---- */
    if (start_off >= code_len) {
        out->detail = "start offset is past the end of the buffer";
        free(seen);
        return TR_INVALID;
    }
    stack[sp++] = (uint32_t)start_off;
    seen[start_off] = 1u;
    while (sp) {
        uint32_t off = stack[--sp];
        plan p;
        tr_status st = plan_one(code, code_len, off, guest_va, resolve, user,
                                &p, out);
        if (st != TR_OK) { free(seen); return st; }
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
                free(seen); return TR_UNSUPPORTED;
            }
            if (!seen[t - guest_va]) {
                if (sp >= TRF_MAX_INSN) {
                    out->reason = TRR_OVERFLOW; out->detail = "worklist overflow"; free(seen); return TR_OVERFLOW;
                }
                seen[t - guest_va] = 1u;
                stack[sp++] = (uint32_t)(t - guest_va);
            }
        } else {
            uint32_t next = off + p.guest_len;
            if (p.op == P_JCC) {
                uint64_t t = p.target_va;
                if (t < guest_va || t - guest_va >= code_len) {
                    out->reason = TRR_LEAVES_FUNC; out->detail = "conditional branch leaves the function";
                    free(seen); return TR_UNSUPPORTED;
                }
                if (!seen[t - guest_va]) {
                    if (sp >= TRF_MAX_INSN) {
                        out->reason = TRR_OVERFLOW; out->detail = "worklist overflow"; free(seen); return TR_OVERFLOW;
                    }
                    seen[t - guest_va] = 1u;
                    stack[sp++] = (uint32_t)(t - guest_va);
                }
            }
            if (next >= code_len) {
                /* A function whose last instruction is not a RET has no return, so
                 * translating it would emit code that runs off the end. */
                out->reason = TRR_NO_RET; out->detail = "function ends without a RET";
                free(seen);
                return TR_UNSUPPORTED;
            }
            if (!seen[next]) {
                if (sp >= TRF_MAX_INSN) {
                    out->reason = TRR_OVERFLOW; out->detail = "worklist overflow"; free(seen); return TR_OVERFLOW;
                }
                seen[next] = 1u;
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
            out->reason = TRR_FLAGS; out->detail = "a conditional branch would read flags this translator "
                          "did not produce: it must be preceded immediately by a "
                          "modelled CMP or TEST";
            return TR_UNSUPPORTED;
        }
        for (j = 0; j < nplans; j++) {
            if ((plans[j].op == P_JCC || plans[j].op == P_JMP) &&
                plans[j].target_va == plans[i].guest_va) {
                out->reason = TRR_FLAGS; out->detail = "a branch targets a conditional branch, so the flags "
                              "it reads would come from elsewhere";
                return TR_UNSUPPORTED;
            }
        }
    }

    out->lo_off = plans[0].off;
    out->hi_off = plans[0].off + plans[0].guest_len;
    for (i = 0; i < nplans; i++) {
        uint32_t end = plans[i].off + plans[i].guest_len;
        if (plans[i].op == P_CALL_IAT) out->needs_frame = 1;
        if (end > out->extent) out->extent = end;
        if (plans[i].off < out->lo_off) out->lo_off = plans[i].off;
        if (end > out->hi_off) out->hi_off = end;
    }

    /* ---- pass 2: layout. Sizes are already fixed, so one pass is enough. ---- */
    cursor = out->needs_frame ? 1u : 0u;
    for (i = 0; i < nplans; i++) {
        plans[i].word_at = cursor;
        cursor += plans[i].words;
        if (plans[i].op == P_RET && out->needs_frame) cursor += 1u;
    }
    if (cursor + (out->needs_frame ? 1u : 0u) > TRF_MAX_WORDS) {
        out->reason = TRR_OVERFLOW; out->detail = "translation exceeds TRF_MAX_WORDS";
        return TR_OVERFLOW;
    }

    /* ---- pass 3: emit ---- */
    if (out->needs_frame && !pushf(out, a64_stp_frame_push())) return TR_OVERFLOW;

    for (i = 0; i < nplans; i++) {
        const plan *p = &plans[i];
        out->insns++;
        out->guest_bytes += p->guest_len;

        switch (p->op) {
        case P_MOV_IMM:
            if (!emit_const_f(out, p->rd, p->const_val)) return TR_OVERFLOW;
            break;
        case P_MOV_REG:
            if (!pushf(out, a64_mov_reg(p->rd, p->rn))) return TR_OVERFLOW;
            break;
        case P_ZERO:
            if (!pushf(out, a64_movz_x(p->rd, 0))) return TR_OVERFLOW;
            break;
        case P_ADD_REG:
            if (!pushf(out, a64_add_reg(p->rd, p->rd, p->rn))) return TR_OVERFLOW;
            break;
        case P_SUB_REG:
            if (!pushf(out, a64_sub_reg(p->rd, p->rd, p->rn))) return TR_OVERFLOW;
            break;
        case P_ADD_IMM:
        case P_SUB_IMM:
            if (p->delta >= 0) {
                if (!pushf(out, a64_add_x_imm(p->rd, p->rd, (uint16_t)p->delta)))
                    return TR_OVERFLOW;
            } else {
                if (!pushf(out, a64_sub_x_imm(p->rd, p->rd, (uint16_t)(-p->delta))))
                    return TR_OVERFLOW;
            }
            break;
        case P_CMP_REG:
            if (!pushf(out, a64_subs_reg(A64_XZR, p->rn, p->rm))) return TR_OVERFLOW;
            break;
        case P_CMP_IMM:
            /* cmp r, k is SUBS XZR, r, k. A negative k has no subtract-immediate
             * encoding, so it becomes CMN, which is ADDS XZR, r, -k: the same
             * comparison, and the flags come out identical. */
            if (p->delta >= 0) {
                if (!pushf(out, a64_subs_imm(A64_XZR, p->rd, (uint16_t)p->delta)))
                    return TR_OVERFLOW;
            } else {
                if (!pushf(out, a64_adds_imm(A64_XZR, p->rd, (uint16_t)(-p->delta))))
                    return TR_OVERFLOW;
            }
            break;
        case P_TEST_REG:
            if (!pushf(out, a64_ands_reg(A64_XZR, p->rn, p->rm))) return TR_OVERFLOW;
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
        case P_CALL_IAT:
            if (!emit_const_f(out, HOST_SCRATCH, p->const_val)) return TR_OVERFLOW;
            if (!pushf(out, a64_blr(HOST_SCRATCH))) return TR_OVERFLOW;
            break;
        case P_RET:
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
    return TR_OK;
}
