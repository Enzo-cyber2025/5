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

/* BRK #imm16 - the software breakpoint, raising SIGTRAP. This is the controlled
 * trap for a guest pointer that fails its bounds check. The alternative is not
 * "skip the check": an unchecked host dereference of a guest value reads whatever
 * the host happens to have at that address and returns a plausible looking number
 * that is not the guest's, and nothing downstream would ever notice. A trap is
 * loud, and its immediate is a tag so a runtime can tell one kind of stop from
 * another. */
#define A64_BRK_GUEST_OOB 0x9F1Eu
uint32_t a64_brk(uint16_t imm16);

/* STP X29, X30, [SP, #-16]! and LDP X29, X30, [SP], #16 - the standard frame
 * record push and pop.
 *
 * These exist because x86-64 CALL and RET use the stack while AArch64 BLR and RET
 * use the link register. Translating one onto the other without preserving X30 is
 * wrong the moment a function both calls and returns: the BLR overwrites X30 with
 * the address of the next instruction, the callee's RET consumes it correctly, and
 * then the caller's own RET jumps back into the middle of itself and never
 * returns. That is an infinite loop, and it is invisible to inspection - it only
 * shows up when the generated code is executed.
 *
 * This is a shortcut valid for the subset, not a general answer. A general
 * translator has to model the guest stack, because guest code can push and pop the
 * return address, inspect it, and unwind through it. */
uint32_t a64_stp_frame_push(void);   /* STP X29, X30, [SP, #-16]! */
uint32_t a64_ldp_frame_pop(void);    /* LDP X29, X30, [SP], #16  */

/* ---- flag-setting forms, and the branches that consume them -------------- */

/* ADD/SUB Xd, Xn, Xm - shifted register form, no shift. These do NOT set flags,
 * which matters: x86 ADD and SUB always do, so a translation that emits these and
 * then lets a conditional branch read the result would be reading flags nobody
 * computed. The translator tracks that and refuses. */
uint32_t a64_add_reg(unsigned rd, unsigned rn, unsigned rm);
uint32_t a64_sub_reg(unsigned rd, unsigned rn, unsigned rm);

/* SUBS - the flag-setting subtract. With Rd = XZR this is CMP. After it, NZCV maps
 * exactly onto the flags an x86 CMP leaves behind:
 *   N == SF, Z == ZF, V == OF, and C == NOT CF (AArch64 C is set when there is no
 *   borrow, x86 CF is set when there is one).
 * That equivalence is what makes the condition codes below usable directly. */
uint32_t a64_subs_reg(unsigned rd, unsigned rn, unsigned rm);
uint32_t a64_subs_imm(unsigned rd, unsigned rn, uint16_t imm12);

/* ADDS with Rd = XZR is CMN, which is how `cmp r, -k` has to be rendered: an
 * ARM64 subtract-immediate field is unsigned, so comparing against a negative
 * constant is a comparison of the negation, not a negative immediate. */
uint32_t a64_adds_imm(unsigned rd, unsigned rn, uint16_t imm12);

/* ANDS Xd, Xn, Xm - with Rd = XZR this is TST, the counterpart of x86 TEST. */
uint32_t a64_ands_reg(unsigned rd, unsigned rn, unsigned rm);

/* Register alias for "discard the result, keep the flags". */
#define A64_XZR 31u

/* AArch64 condition codes, bits 3:0 of B.cond. */
#define A64_EQ 0u   /* Z==1                -> x86 JE/JZ   */
#define A64_NE 1u   /* Z==0                -> x86 JNE/JNZ */
#define A64_HS 2u   /* C==1 (no borrow)    -> x86 JAE/JNB */
#define A64_LO 3u   /* C==0 (borrow)       -> x86 JB/JNAE */
#define A64_MI 4u   /* N==1                -> x86 JS      */
#define A64_PL 5u   /* N==0                -> x86 JNS     */
#define A64_VS 6u   /* V==1                -> x86 JO      */
#define A64_VC 7u   /* V==0                -> x86 JNO     */
#define A64_HI 8u   /* C==1 && Z==0        -> x86 JA      */
#define A64_LS 9u   /* C==0 || Z==1        -> x86 JBE     */
#define A64_GE 10u  /* N==V                -> x86 JGE/JNL */
#define A64_LT 11u  /* N!=V                -> x86 JL/JNGE */
#define A64_GT 12u  /* Z==0 && N==V        -> x86 JG      */
#define A64_LE 13u  /* Z==1 || N!=V        -> x86 JLE     */

/* Branches. words is a SIGNED offset in instructions, not bytes: B.cond carries a
 * 19-bit field (about +-1 MiB) and B/BL a 26-bit one (about +-128 MiB). A target
 * outside that range must be refused rather than truncated, because a truncated
 * displacement branches somewhere plausible and wrong. */
uint32_t a64_b_cond(unsigned cond, int32_t words);
uint32_t a64_b(int32_t words);
uint32_t a64_bl(int32_t words);

/* ---- load/store forms the guest stack model needs -------------------------
 *
 * Everything below is derived from the same field layout as the frame record
 * above, and the derivation is checked against these two words, which have
 * already been executed on aarch64 hardware:
 *   a64_stp_pre(29, 30, 31, -16)  == 0xA9BF7BFD   STP X29,X30,[SP,#-16]!
 *   a64_ldp_post(29, 30, 31, 16)  == 0xA8C17BFD   LDP X29,X30,[SP],#16
 * Both assertions live in the test suite, so a change to the shared derivation
 * breaks a test that names the hardware-proven constant rather than drifting.
 *
 * The guest stack pointer lives in a general register (X14), not in the host SP.
 * Two reasons, both of which would otherwise cost correctness:
 *   - AArch64 requires SP to be 16-byte aligned at every public interface, while
 *     x86-64 only ever guarantees 8. Putting the guest RSP in the host SP would
 *     make every odd-sized guest adjustment an alignment fault.
 *   - X14 and X15 are callee-saved in the AAPCS, so a host function reached
 *     through a resolved import preserves the guest stack pointer for free.
 *     A translator-scratch register like X16/X17 would not survive the call.
 */

/* STP/LDP with a signed offset scaled by 8. mode: pre-index (writeback before
 * the access) or post-index (writeback after). off must be a multiple of 8 in
 * -512..504; a64_pair_range_ok reports that so the caller can refuse instead of
 * emitting a wrapped displacement, which would address a different slot. */
int      a64_pair_range_ok(int off);
uint32_t a64_stp_pre(unsigned rt, unsigned rt2, unsigned rn, int off);
uint32_t a64_ldp_post(unsigned rt, unsigned rt2, unsigned rn, int off);

/* STR/LDR with a single register. pre-index is what `push` compiles to and
 * post-index is what `pop` compiles to; the writeback is what advances the guest
 * stack pointer, so push and pop cannot drift from the value they store.
 * off is a signed byte count in -256..255. */
int      a64_imm9_range_ok(int off);
uint32_t a64_str_pre(unsigned rt, unsigned rn, int off);
uint32_t a64_ldr_post(unsigned rt, unsigned rn, int off);

/* STUR/LDUR - unscaled offset, the form a stack local needs. The scaled unsigned
 * offset form only reaches non-negative displacements, and locals live at
 * [rbp-8], [rbp-16], ... so the signed unscaled form is the one that works. */
uint32_t a64_stur(unsigned rt, unsigned rn, int off);
uint32_t a64_ldur(unsigned rt, unsigned rn, int off);
/* The 32-bit forms. A W-form load zero-extends into the X register, which is what
 * a 32-bit x86-64 load does, so the width is the only thing to get right. */
uint32_t a64_stur_w(unsigned rt, unsigned rn, int off);
uint32_t a64_ldur_w(unsigned rt, unsigned rn, int off);

/* The guest stack frame record: saves the caller's X14 (guest RSP) and X15
 * (guest RBP). Saving them is what makes the guest stack pointer balanced at
 * return even if the guest code returned early and never undid its own
 * adjustment, and it is also what the AAPCS requires of a callee that uses
 * callee-saved registers. */
uint32_t a64_stp_gstack_push(void);   /* STP X14, X15, [SP, #-16]! */
uint32_t a64_ldp_gstack_pop(void);    /* LDP X14, X15, [SP], #16   */

/* ---- 32-bit (W) forms ----------------------------------------------------
 *
 * Every one of these is the corresponding 64-bit encoding with bit 31 - the sf
 * field - cleared, and they are generated from one shared derivation below so
 * that the two cannot drift apart.
 *
 * They matter because x86-64 code is full of 32-bit register operations, and the
 * semantics line up exactly: a 32-bit operation in x86-64 zero-extends its result
 * into the full 64-bit register, and a W-form operation in AArch64 zero-extends
 * into the X register too. So `mov eax, 5` is `MOVZ W0, #5` with no masking to
 * emit and no upper-half hazard, and the flag mapping after a 32-bit SUBS is the
 * same exact correspondence as after a 64-bit one.
 *
 * Getting this wrong is invisible in the encoding and wrong in the value: a
 * translation that emitted the X form for a 32-bit guest operation would
 * sign-extend or leave the upper half stale, and the function would return a
 * number that is right in its low 32 bits and wrong as a 64-bit value.
 */
uint32_t a64_movz_w(unsigned rd, uint16_t imm16);
uint32_t a64_movk_w(unsigned rd, uint16_t imm16, unsigned shift);
uint32_t a64_mov_reg_w(unsigned rd, unsigned rm);
uint32_t a64_add_reg_w(unsigned rd, unsigned rn, unsigned rm);
uint32_t a64_sub_reg_w(unsigned rd, unsigned rn, unsigned rm);
uint32_t a64_subs_reg_w(unsigned rd, unsigned rn, unsigned rm);
uint32_t a64_ands_reg_w(unsigned rd, unsigned rn, unsigned rm);
uint32_t a64_add_w_imm(unsigned rd, unsigned rn, uint16_t imm12);
uint32_t a64_sub_w_imm(unsigned rd, unsigned rn, uint16_t imm12);
uint32_t a64_subs_w_imm(unsigned rd, unsigned rn, uint16_t imm12);
uint32_t a64_adds_w_imm(unsigned rd, unsigned rn, uint16_t imm12);

/* ---- access relative to a base register ----------------------------------
 *
 * LDR/STR with a register offset, unsigned (option=011, S=0). This is how a
 * RIP-relative access to the module's own image is emitted once the displacement
 * is known: the RVA is materialised in a scratch register and added by the load
 * itself, so no absolute address ever enters the code.
 *
 * The base is X19, which holds the host address the guest module's image is
 * mapped at - the address RVA 0 lives at - and which the caller supplies on entry
 * exactly as it supplies the guest stack pointer in X14. Like X14 it is
 * callee-saved, so a host callee preserves it, and like X14 keeping it out of the
 * emitted words is what lets a translation be cached across processes.
 *
 * Derivation, checked against four independently known words:
 *   size[31:30] 111[29:27] V=0[26] 00[25:24] opc[23:22] 1[21] Rm[20:16]
 *   option[15:13] S[12] 10[11:10] Rn[9:5] Rt[4:0]
 *   STR opc=00, LDR opc=01; size=11 for X, 10 for W.
 *   ldr x0,[x1,x2] = 0xF8626820   str x0,[x1,x2] = 0xF8226820
 *   ldr w0,[x1,x2] = 0xB8626820   str w0,[x1,x2] = 0xB8226820
 * The W forms zero-extend into the X register, which is what a 32-bit x86-64 load
 * does too, so the width choice is the only thing that has to be right.
 */
uint32_t a64_ldr_reg(unsigned rt, unsigned rn, unsigned rm);
uint32_t a64_str_reg(unsigned rt, unsigned rn, unsigned rm);
uint32_t a64_ldr_reg_w(unsigned rt, unsigned rn, unsigned rm);
uint32_t a64_str_reg_w(unsigned rt, unsigned rn, unsigned rm);

/* The image-base frame record. X19 holds the mapped image base; X20 is saved only
 * because STP and LDP move two registers, and reserving it keeps the pair from
 * having to borrow a register that a later revision needs. */
uint32_t a64_stp_imgbase_push(void);   /* STP X19, X20, [SP, #-16]! */
uint32_t a64_ldp_imgbase_pop(void);    /* LDP X19, X20, [SP], #16   */

/* Non-zero when words fits the branch's field, so the caller can refuse. */
int a64_cond_range_ok(int32_t words);
int a64_b_range_ok(int32_t words);

/* Appends one instruction to a buffer. Returns 0 if it would not fit, and
 * writes nothing in that case: a partially appended instruction would be
 * executed as garbage rather than refused. */
int a64_emit(uint32_t *buf, size_t cap, size_t *len, uint32_t insn);

#endif /* A64_EMIT_H */
