#include "translate.h"

#include "a64_emit.h"
#include "x86_decode.h"

#include <string.h>

#define HOST_RAX 0u      /* guest RAX -> X0 */
#define HOST_RCX 1u      /* guest RCX -> X1 */
#define HOST_SCRATCH 16u /* X16 / IP0: free for a translator to clobber */

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

tr_status tr_translate_run(const uint8_t *code, size_t code_len,
                           uint64_t guest_va, tr_resolve_fn resolve, void *user,
                           tr_output *out)
{
    size_t   pos = 0;
    uint64_t va = guest_va;

    if (!out) return TR_INVALID;
    memset(out, 0, sizeof(*out));
    out->detail = "ok";
    if (!code || code_len == 0) { out->detail = "no guest code"; return TR_INVALID; }

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
