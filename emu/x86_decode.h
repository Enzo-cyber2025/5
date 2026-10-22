/* x86-64 instruction decoder - length and structure, written from scratch.
 *
 * Why length comes first: in a dynamic binary translator a wrong instruction
 * length desynchronises the entire decode stream, and every block translated
 * afterwards is silently wrong. Nothing downstream can detect it. So the
 * decoder's first duty is to be exactly right about "how many bytes", and its
 * second duty is to refuse rather than guess.
 *
 * Design rule: this decoder never estimates. An encoding it does not model
 * returns X86_UNSUPPORTED, and a byte sequence that is not a legal 64-bit
 * instruction returns X86_INVALID. A caller that receives either must fall back
 * to a single-step interpreter or abort the block; it must not advance PC by a
 * guessed amount.
 *
 * Scope of this revision: legacy (non-VEX, non-EVEX) encoding, 64-bit mode.
 * Full coverage of prefixes, REX, the one- and two-byte opcode maps, the 0F 38
 * and 0F 3A three-byte maps (both fully length-decodable: 38 is always
 * ModRM/no-immediate, 3A is always ModRM/imm8), ModRM, SIB, displacement and
 * immediate sizing, and RIP-relative addressing.
 *
 * Deliberately refused rather than approximated:
 *   - VEX (C4/C5) and EVEX (62): needs its own prefix model, not a patch here.
 *   - 0x67 address-size override: 32-bit addressing changes the rm==6 and
 *     SIB-base==5 displacement rules. Returning a length that assumes 64-bit
 *     addressing would be a guess, so it reports UNSUPPORTED.
 * Mnemonic and operand lifting covers a core subset; a NULL mnemonic with
 * X86_OK means "length is trustworthy, semantics not lifted yet", which is a
 * real and useful state for a translator that only needs block boundaries.
 */
#ifndef X86_DECODE_H
#define X86_DECODE_H

#include <stddef.h>
#include <stdint.h>

typedef enum {
    X86_OK = 0,          /* length and structure are valid */
    X86_INVALID,         /* not a legal instruction in 64-bit mode */
    X86_UNSUPPORTED,     /* legal, but this decoder does not model it yet */
    X86_NEED_MORE        /* buffer ended mid-instruction; feed more bytes */
} x86_status;

/* Instruction classes that the translator has to treat specially. */
#define X86F_BRANCH     (1u << 0)   /* changes control flow */
#define X86F_COND       (1u << 1)   /* branch is conditional */
#define X86F_INDIRECT   (1u << 2)   /* target is not a constant in the encoding */
#define X86F_RET        (1u << 3)
#define X86F_CALL       (1u << 4)
#define X86F_RIP_REL    (1u << 5)   /* has a RIP-relative memory operand */
#define X86F_LOCK       (1u << 6)
#define X86F_REP        (1u << 7)
#define X86F_PRIVILEGED (1u << 8)

typedef struct {
    x86_status status;
    uint8_t    len;             /* total bytes consumed; 0 unless X86_OK */

    /* prefixes */
    uint8_t    rex;             /* REX byte, 0 if absent */
    uint8_t    rex_w, rex_r, rex_x, rex_b;
    int        p66, p67, pf2, pf3, lock, seg;

    /* opcode */
    uint8_t    op[3];           /* opcode bytes, after prefixes */
    uint8_t    op_len;          /* 1, 2 or 3 */
    uint8_t    map;             /* 0=base, 1=0F, 2=0F38, 3=0F3A */

    /* ModRM / SIB / displacement */
    int        has_modrm;
    uint8_t    modrm, mod, reg, rm;
    int        has_sib;
    uint8_t    sib, sib_scale, sib_index, sib_base;
    uint8_t    disp_len;        /* 0, 1, 2 or 4 */
    int32_t    disp;
    uint64_t   rip_rel_target;  /* valid when flags & X86F_RIP_REL */

    /* immediate */
    uint8_t    imm_len;         /* 0, 1, 2, 4 or 8 */
    uint64_t   imm;
    /* Set only for rel8/rel32, which are inherently signed displacements and are
     * stored sign-extended in imm. For every other immediate, imm holds the raw
     * bits: whether the instruction extends them is opcode-specific (GRP1 /3 does,
     * MOV r8,imm8 does not) and belongs to the lifter, not the length decoder. */
    int8_t     imm_signed;

    /* semantics */
    const char *mnemonic;       /* NULL when not lifted yet */
    uint32_t   flags;
} x86_insn;

/* Decode at most one instruction from buf[0..buflen).
 *
 * buflen should be at least 15 (the architectural maximum instruction length);
 * anything shorter risks X86_NEED_MORE on a valid instruction. pc is the guest
 * address of buf[0] and is used only to resolve RIP-relative operands.
 *
 * out is fully written on every return, including failures, so callers never see
 * a stale len from a previous decode.
 */
x86_status x86_decode(const uint8_t *buf, size_t buflen, uint64_t pc, x86_insn *out);

const char *x86_status_name(x86_status s);

#endif /* X86_DECODE_H */
