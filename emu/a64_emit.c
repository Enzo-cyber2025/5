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

/* Shifted-register data processing: sf=1, then opc, then 01011 for ADD/SUB or
 * 01010 for the logical group, shift=00, N, Rm, imm6=0, Rn, Rd.
 *   ADD  op=0 S=0 -> 0x8B000000      SUB  op=1 S=0 -> 0xCB000000
 *   SUBS op=1 S=1 -> 0xEB000000      ANDS opc=11   -> 0xEA000000
 */
static uint32_t dp_reg(uint32_t base, unsigned rd, unsigned rn, unsigned rm)
{
    return base | ((uint32_t)(rm & 31u) << 16) | ((uint32_t)(rn & 31u) << 5) |
           (uint32_t)(rd & 31u);
}

uint32_t a64_add_reg(unsigned rd, unsigned rn, unsigned rm)
{ return dp_reg(0x8B000000u, rd, rn, rm); }

uint32_t a64_sub_reg(unsigned rd, unsigned rn, unsigned rm)
{ return dp_reg(0xCB000000u, rd, rn, rm); }

uint32_t a64_subs_reg(unsigned rd, unsigned rn, unsigned rm)
{ return dp_reg(0xEB000000u, rd, rn, rm); }

uint32_t a64_ands_reg(unsigned rd, unsigned rn, unsigned rm)
{ return dp_reg(0xEA000000u, rd, rn, rm); }

uint32_t a64_subs_imm(unsigned rd, unsigned rn, uint16_t imm12)
{
    /* sf=1 op=1 S=1 shift=00 -> 0xF1000000 */
    return 0xF1000000u | ((uint32_t)imm12 << 10) |
           ((uint32_t)(rn & 31u) << 5) | (uint32_t)(rd & 31u);
}

uint32_t a64_adds_imm(unsigned rd, unsigned rn, uint16_t imm12)
{
    /* sf=1 op=0 S=1 shift=00 -> 0xB1000000 */
    return 0xB1000000u | ((uint32_t)imm12 << 10) |
           ((uint32_t)(rn & 31u) << 5) | (uint32_t)(rd & 31u);
}

int a64_cond_range_ok(int32_t words)
{
    return words >= -262144 && words <= 262143;   /* signed 19 bits */
}

int a64_b_range_ok(int32_t words)
{
    return words >= -33554432 && words <= 33554431;   /* signed 26 bits */
}

uint32_t a64_b_cond(unsigned cond, int32_t words)
{
    /* 0101 0100 imm19 0 cond -> 0x54000000 */
    return 0x54000000u | (((uint32_t)words & 0x7FFFFu) << 5) | (cond & 0xFu);
}

uint32_t a64_b(int32_t words)
{
    return 0x14000000u | ((uint32_t)words & 0x3FFFFFFu);
}

uint32_t a64_bl(int32_t words)
{
    return 0x94000000u | ((uint32_t)words & 0x3FFFFFFu);
}

int a64_emit(uint32_t *buf, size_t cap, size_t *len, uint32_t insn)
{
    if (!buf || !len || *len + 1u > cap) return 0;
    buf[(*len)++] = insn;
    return 1;
}
