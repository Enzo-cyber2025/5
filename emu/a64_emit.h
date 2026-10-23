/* ARM64 encoder seed - the smallest set of instructions whose encodings have
 * been executed rather than merely written down.
 *
 * Every constant here is hand-derived from the ARMv8-A encoding tables and
 * pinned by an assertion in test_emit_exec.c against a known-good word, and the
 * emitted code has been executed on a native aarch64 runner and under QEMU. An
 * encoder cannot be validated by inspection: a wrong encoding still looks like a
 * plausible 32-bit word.
 *
 * This is deliberately tiny. It exists so that the sweep, the harness and the
 * future lifter all emit through one place instead of each re-deriving the same
 * three encodings, and so that growing it is a matter of adding pinned
 * functions here rather of scattering magic numbers.
 */
#ifndef A64_EMIT_H
#define A64_EMIT_H

#include <stddef.h>
#include <stdint.h>

/* MOVZ Xd, #imm16 - zeroing move, the only safe way to materialise a constant
 * without knowing what was in the register before. */
uint32_t a64_movz_x(unsigned rd, uint16_t imm16);

/* ADD Xd, Xn, #imm12 - 64-bit immediate add, no shift. */
uint32_t a64_add_x_imm(unsigned rd, unsigned rn, uint16_t imm12);

/* RET - return to the address in X30. */
uint32_t a64_ret(void);

/* MOVK Xd, #imm16, LSL #shift - keep, replacing 16 bits. Together with MOVZ
 * this materialises any 64-bit constant in at most four instructions, which is
 * how a translator loads a resolved host address without a literal pool.
 * shift must be 0, 16, 32 or 48. */
uint32_t a64_movk_x(unsigned rd, uint16_t imm16, unsigned shift);

/* MOV Xd, Xm - the register form, which ARM64 encodes as ORR Xd, Xm, XZR. */
uint32_t a64_mov_reg(unsigned rd, unsigned rm);

/* SUB Xd, Xn, #imm12 - needed because a negative ADD immediate has no encoding. */
uint32_t a64_sub_x_imm(unsigned rd, unsigned rn, uint16_t imm12);

/* BLR Xn - call the address in a register, the shape an indirect call through
 * an import table takes once the address is resolved. */
uint32_t a64_blr(unsigned rn);

/* Appends one instruction to a buffer. Returns 0 if it would not fit, and
 * writes nothing in that case: a partially appended instruction would be
 * executed as garbage rather than refused. */
int a64_emit(uint32_t *buf, size_t cap, size_t *len, uint32_t insn);

#endif /* A64_EMIT_H */
