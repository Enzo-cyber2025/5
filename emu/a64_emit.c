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
uint32_t a64_stp_frame_push(void) { return a64_stp_pre(29u, 30u, 31u, -16); }
uint32_t a64_ldp_frame_pop(void)  { return a64_ldp_post(29u, 30u, 31u, 16); }

/* ---- the shared load/store derivation ------------------------------------
 *
 * One field layout, six instructions. Writing them as six independent constants
 * is how a wrong one survives review; writing them once and pinning the result
 * against the two words already executed on hardware means a mistake in the
 * layout breaks a named assertion instead of producing plausible garbage.
 *
 *   STP/LDP : opc[31:30]=10 (64-bit) 101[29:27] V=0[26] mode[25:23] L[22]
 *             imm7[21:15] (signed, scaled by 8) Rt2[14:10] Rn[9:5] Rt[4:0]
 *             mode 011 = pre-index, 001 = post-index
 *   STR/LDR : size=11[31:30] 111[29:27] V=0[26] 00[25:24] opc[23:22]
 *             imm9[20:12] (signed bytes) mode[11:10] Rn[9:5] Rt[4:0]
 *             STR opc=00, LDR opc=01; mode 11 = pre-index, 01 = post-index,
 *             00 = unscaled offset (STUR/LDUR)
 */
int a64_pair_range_ok(int off)
{
    return (off % 8) == 0 && off >= -512 && off <= 504;
}

int a64_imm9_range_ok(int off)
{
    return off >= -256 && off <= 255;
}

uint32_t a64_stp_pre(unsigned rt, unsigned rt2, unsigned rn, int off)
{
    uint32_t imm7 = (uint32_t)((off / 8) & 0x7F);
    return (0x80000000u | 0x28000000u)          /* opc=10, 101 */
         | (0x01800000u)                        /* V=0, mode=011 pre-index */
         | (imm7 << 15) | ((uint32_t)(rt2 & 31u) << 10)
         | ((uint32_t)(rn & 31u) << 5) | (uint32_t)(rt & 31u);
}

uint32_t a64_ldp_post(unsigned rt, unsigned rt2, unsigned rn, int off)
{
    uint32_t imm7 = (uint32_t)((off / 8) & 0x7F);
    return (0x80000000u | 0x28000000u)          /* opc=10, 101 */
         | (0x00800000u)                        /* V=0, mode=001 post-index */
         | (0x00400000u)                        /* L=1 */
         | (imm7 << 15) | ((uint32_t)(rt2 & 31u) << 10)
         | ((uint32_t)(rn & 31u) << 5) | (uint32_t)(rt & 31u);
}

uint32_t a64_str_pre(unsigned rt, unsigned rn, int off)
{
    uint32_t imm9 = (uint32_t)(off & 0x1FF);
    return 0xF8000000u                          /* size=11,111,V=0,00,STR */
         | (imm9 << 12) | (0xC00u)              /* mode=11 pre-index */
         | ((uint32_t)(rn & 31u) << 5) | (uint32_t)(rt & 31u);
}

uint32_t a64_ldr_post(unsigned rt, unsigned rn, int off)
{
    uint32_t imm9 = (uint32_t)(off & 0x1FF);
    return 0xF8400000u                          /* size=11,111,V=0,00,LDR */
         | (imm9 << 12) | (0x400u)              /* mode=01 post-index */
         | ((uint32_t)(rn & 31u) << 5) | (uint32_t)(rt & 31u);
}

uint32_t a64_stur(unsigned rt, unsigned rn, int off)
{
    uint32_t imm9 = (uint32_t)(off & 0x1FF);
    return 0xF8000000u                          /* mode=00 unscaled offset */
         | (imm9 << 12) | ((uint32_t)(rn & 31u) << 5) | (uint32_t)(rt & 31u);
}

uint32_t a64_ldur(unsigned rt, unsigned rn, int off)
{
    uint32_t imm9 = (uint32_t)(off & 0x1FF);
    return 0xF8400000u
         | (imm9 << 12) | ((uint32_t)(rn & 31u) << 5) | (uint32_t)(rt & 31u);
}

uint32_t a64_stp_gstack_push(void) { return a64_stp_pre(14u, 15u, 31u, -16); }
uint32_t a64_ldp_gstack_pop(void)  { return a64_ldp_post(14u, 15u, 31u, 16); }

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
