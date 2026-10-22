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

int a64_emit(uint32_t *buf, size_t cap, size_t *len, uint32_t insn)
{
    if (!buf || !len || *len + 1u > cap) return 0;
    buf[(*len)++] = insn;
    return 1;
}
