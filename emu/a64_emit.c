#include "a64_emit.h"

uint32_t a64_movz_x(unsigned rd, uint16_t imm16)
{
    /* sf=1 opc=10 hw=00 -> 0xD2800000, imm16 at bits 20:5, Rd at 4:0 */
    return 0xD2800000u | ((uint32_t)imm16 << 5) | (uint32_t)(rd & 31u);
}

uint32_t a64_add_x_imm(unsigned rd, unsigned rn, uint16_t imm12)
{
    /* sf=1 op=0 S=0 shift=00 -> 0x91000000, imm12 at 21:10, Rn 9:5, Rd 4:0 */
    return 0x91000000u | ((uint32_t)imm12 << 10) |
           ((uint32_t)(rn & 31u) << 5) | (uint32_t)(rd & 31u);
}

uint32_t a64_ret(void)
{
    /* RET X30: 0xD65F03C0 */
    return 0xD65F03C0u;
}

uint32_t a64_movk_x(unsigned rd, uint16_t imm16, unsigned shift)
{
    /* sf=1 opc=11 -> 0xF2800000, hw (shift/16) at bits 22:21 */
    unsigned hw = (shift / 16u) & 3u;
    return 0xF2800000u | (hw << 21) | ((uint32_t)imm16 << 5) |
           (uint32_t)(rd & 31u);
}

uint32_t a64_mov_reg(unsigned rd, unsigned rm)
{
    /* ORR (shifted register): sf=1 opc=010 shift=00 N=0 Rm imm6=0 Rn=ZR Rd,
     * which is the canonical encoding of MOV Xd, Xm. */
    return 0xAA0003E0u | ((uint32_t)(rm & 31u) << 16) | (uint32_t)(rd & 31u);
}

uint32_t a64_sub_x_imm(unsigned rd, unsigned rn, uint16_t imm12)
{
    /* sf=1 op=1 S=0 shift=00 -> 0xD1000000 */
    return 0xD1000000u | ((uint32_t)imm12 << 10) |
           ((uint32_t)(rn & 31u) << 5) | (uint32_t)(rd & 31u);
}

uint32_t a64_blr(unsigned rn)
{
    /* BLR Rn: 0xD63F0000 | Rn<<5 */
    return 0xD63F0000u | ((uint32_t)(rn & 31u) << 5);
}

/* Derived from the STP/LDP pre- and post-indexed forms, then decomposed field by
 * field to check: opc=10 (64-bit), 101, V=0, L, imm7 as a signed multiple of 8,
 * Rt2, Rn, Rt.
 *   STP X29,X30,[SP,#-16]! : L=0, imm7 = -2 (0b1111110), Rt2=30, Rn=31, Rt=29
 *   LDP X29,X30,[SP],#16   : L=1, imm7 = +2,               Rt2=30, Rn=31, Rt=29
 * Both words are asserted in the test suite against these values. */
uint32_t a64_stp_frame_push(void) { return 0xA9BF7BFDu; }
uint32_t a64_ldp_frame_pop(void)  { return 0xA8C17BFDu; }

int a64_emit(uint32_t *buf, size_t cap, size_t *len, uint32_t insn)
{
    if (!buf || !len || *len + 1u > cap) return 0;
    buf[(*len)++] = insn;
    return 1;
}
