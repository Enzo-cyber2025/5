/* Decoder tests: hand-assembled encodings with independently known lengths.
 *
 * Every length here was derived from the encoding rules by hand, not read back
 * from the decoder, so a table mistake shows up as a failure rather than as a
 * self-consistent wrong answer. The refusal cases matter as much as the accepted
 * ones: a decoder that guesses a length for VEX or for 0x67 would desynchronise
 * the translation stream, which is the one failure a translator cannot survive.
 */
#include "x86_decode.h"

#include <stdio.h>
#include <string.h>

static int checks, failures;

#define CHECK(cond, ...) do { \
    checks++; \
    if (!(cond)) { failures++; printf("  FAIL line %d: ", __LINE__); \
                   printf(__VA_ARGS__); printf("\n"); } \
} while (0)

typedef struct {
    const unsigned char *b;
    size_t n;
    x86_status st;
    uint8_t len;
    const char *what;
} vec;

#define V(bytes, status, length, desc) \
    { (const unsigned char *)bytes, sizeof(bytes) - 1, status, length, desc }

static void test_lengths(void)
{
    printf("instruction lengths\n");
    static const vec t[] = {
        V("\x90", X86_OK, 1, "nop"),
        V("\xC3", X86_OK, 1, "ret"),
        V("\x55", X86_OK, 1, "push rbp"),
        V("\xC9", X86_OK, 1, "leave"),
        V("\xCC", X86_OK, 1, "int3"),
        V("\x48\x89\xE5", X86_OK, 3, "mov rbp,rsp"),
        V("\x48\x83\xEC\x10", X86_OK, 4, "sub rsp,0x10"),
        V("\xE8\x00\x00\x00\x00", X86_OK, 5, "call rel32"),
        V("\x48\xB8\x01\x02\x03\x04\x05\x06\x07\x08", X86_OK, 10, "mov rax,imm64"),
        V("\xB8\x01\x00\x00\x00", X86_OK, 5, "mov eax,1"),
        V("\x66\xB8\x01\x00", X86_OK, 4, "mov ax,1 (0x66 narrows imm)"),
        V("\x0F\x05", X86_OK, 2, "syscall"),
        V("\x48\x8B\x05\x11\x22\x33\x44", X86_OK, 7, "mov rax,[rip+disp32]"),
        V("\xC2\x08\x00", X86_OK, 3, "ret imm16"),
        V("\xCA\x08\x00", X86_OK, 3, "retf imm16 (second user of the imm16 case)"),
        V("\xC8\x00\x00\x00", X86_OK, 4, "enter imm16,imm8"),
        V("\x81\xC1\x01\x00\x00\x00", X86_OK, 6, "add ecx,imm32"),
        V("\x83\xC1\x01", X86_OK, 3, "add ecx,imm8"),
        V("\xF3\x0F\x1E\xFA", X86_OK, 4, "endbr64"),
        /* 66 + 0F 1F + ModRM(44) + SIB(00) + disp8(00) = 6 bytes, the canonical
         * multi-byte NOP. mod=01 with rm=100 means SIB is present AND disp8. */
        V("\x66\x0F\x1F\x44\x00\x00", X86_OK, 6, "nop word [rax+rax]"),
        V("\x41\x54", X86_OK, 2, "push r12 (REX.B)"),
        V("\xFF\xD0", X86_OK, 2, "call rax"),
        V("\xFF\x25\x00\x00\x00\x00", X86_OK, 6, "jmp [rip+0]"),
        V("\x48\x8D\x05\x00\x00\x00\x00", X86_OK, 7, "lea rax,[rip+0]"),
        V("\xF0\x48\xFF\x01", X86_OK, 4, "lock inc [rcx]"),
        V("\xF2\x0F\x10\x00", X86_OK, 4, "movsd xmm0,[rax]"),
        V("\x66\x0F\x6F\x00", X86_OK, 4, "movdqa xmm0,[rax]"),
        V("\x48\x63\xC1", X86_OK, 3, "movsxd rax,ecx"),
        V("\x0F\xB6\xC0", X86_OK, 3, "movzx eax,al"),
        V("\x4C\x8B\x04\x25\x00\x00\x00\x00", X86_OK, 8, "mov r8,[disp32] (SIB base=5)"),
        V("\x48\x8B\x84\xC8\x78\x56\x34\x12", X86_OK, 8, "mov rax,[rax+rcx*8+disp32]"),
        V("\x0F\x84\x00\x00\x00\x00", X86_OK, 6, "je rel32"),
        V("\x74\x05", X86_OK, 2, "je rel8"),
        V("\xEB\xFE", X86_OK, 2, "jmp rel8 -2"),
        V("\xF7\xD8", X86_OK, 2, "neg eax (GRP3, no immediate)"),
        V("\xF7\xC1\x01\x00\x00\x00", X86_OK, 6, "test ecx,imm32 (GRP3 reg=0)"),
        V("\xF6\xC1\x01", X86_OK, 3, "test cl,imm8 (GRP3 reg=0, 8-bit)"),
        V("\xA1\x01\x02\x03\x04\x05\x06\x07\x08", X86_OK, 9, "mov eax,moffs64"),
        V("\x0F\x38\xF0\x00", X86_OK, 4, "0F 38 three-byte map (ModRM, no imm)"),
        V("\x66\x0F\x3A\x0F\x00\x01", X86_OK, 6, "0F 3A three-byte map (ModRM+imm8)"),
        V("\x0F\xA2", X86_OK, 2, "cpuid"),
        V("\xCD\x80", X86_OK, 2, "int 0x80"),
        V("\x0F\x1F\x00", X86_OK, 3, "nop dword [rax]"),
        V("\x40\x90", X86_OK, 2, "rex+nop"),
        V("\x0F\x0B", X86_OK, 2, "ud2"),
        /* illegal in 64-bit mode */
        V("\x06", X86_INVALID, 0, "push es (no segment registers in 64-bit)"),
        V("\x27", X86_INVALID, 0, "daa"),
        V("\x60", X86_INVALID, 0, "pushad"),
        V("\x9A\x00\x00\x00\x00\x00\x00", X86_INVALID, 0, "callf Ap"),
        V("\xD4\x0A", X86_INVALID, 0, "aam"),
        V("\x82\xC1\x01", X86_INVALID, 0, "0x82 removed in 64-bit"),
        /* legal but not modelled: must refuse, never guess */
        V("\xC4\xE2\xF1\xF7\xC0", X86_UNSUPPORTED, 0, "VEX 3-byte"),
        V("\xC5\xF8\x10\xC0", X86_UNSUPPORTED, 0, "VEX 2-byte"),
        V("\x62\xF1\x7C\x48\x58\xC1", X86_UNSUPPORTED, 0, "EVEX"),
        V("\x67\x48\x8B\x00", X86_UNSUPPORTED, 0, "0x67 address-size override"),
        /* truncated */
        V("\xE8\x00\x00", X86_NEED_MORE, 0, "call rel32 with only 2 of 4 bytes"),
        V("\x48", X86_NEED_MORE, 0, "REX with nothing after it"),
    };
    for (size_t i = 0; i < sizeof t / sizeof t[0]; i++) {
        x86_insn in;
        /* Feed a generous buffer so NEED_MORE can only come from real truncation:
         * the vector bytes are copied into a 16-byte window. */
        unsigned char buf[32];
        memset(buf, 0x90, sizeof buf);
        memcpy(buf, t[i].b, t[i].n);
        x86_status got = x86_decode(t[i].n < 15 ? buf : t[i].b, t[i].n, 0x1000, &in);
        CHECK(got == t[i].st, "%s: status %s, expected %s",
              t[i].what, x86_status_name(got), x86_status_name(t[i].st));
        CHECK(in.len == t[i].len, "%s: len %u, expected %u",
              t[i].what, in.len, t[i].len);
    }
}

static void test_fields(void)
{
    printf("decoded fields\n");
    x86_insn in;
    unsigned char b[32];

    /* REX decomposition */
    memset(b, 0x90, sizeof b);
    memcpy(b, "\x4C\x8B\x04\x25\x00\x00\x00\x00", 8);
    x86_decode(b, 16, 0, &in);
    CHECK(in.rex == 0x4C && in.rex_w && in.rex_r && !in.rex_x && !in.rex_b,
          "REX 0x4C must decompose to W=1 R=1 X=0 B=0");
    CHECK(in.has_sib && in.sib_base == 5 && in.sib_index == 4,
          "SIB 0x25 must give base=5 index=4(none)");

    /* RIP-relative: mod=00 rm=101 with no SIB */
    memset(b, 0x90, sizeof b);
    memcpy(b, "\x48\x8B\x05\xFB\xFF\xFF\xFF", 7);
    x86_decode(b, 16, 0x1000, &in);
    CHECK(in.flags & X86F_RIP_REL, "mov rax,[rip-5] must be RIP-relative");
    CHECK(in.rip_rel_target == 0x1000 + 7 + (uint64_t)(int64_t)-5,
          "rip target 0x%llx, expected 0x%llx",
          (unsigned long long)in.rip_rel_target,
          (unsigned long long)(0x1000 + 7 - 5));

    /* SIB with base=5 and mod=00 is disp32, NOT RIP-relative. Getting this wrong
     * silently corrupts every absolute address in position-independent code. */
    memset(b, 0x90, sizeof b);
    memcpy(b, "\x48\x8B\x04\x25\x78\x56\x34\x12", 8);
    x86_decode(b, 16, 0x1000, &in);
    CHECK(!(in.flags & X86F_RIP_REL), "SIB base=5 mod=00 must NOT be RIP-relative");
    CHECK(in.disp == 0x12345678, "disp32 must be 0x12345678, got 0x%x", in.disp);

    /* Control-flow classification drives block splitting */
    memset(b, 0x90, sizeof b);
    memcpy(b, "\xFF\xD0", 2);
    x86_decode(b, 16, 0, &in);
    CHECK((in.flags & (X86F_BRANCH | X86F_CALL | X86F_INDIRECT)) ==
              (X86F_BRANCH | X86F_CALL | X86F_INDIRECT),
          "call rax must be branch+call+indirect, flags=0x%x", in.flags);

    memset(b, 0x90, sizeof b);
    memcpy(b, "\xC3", 1);
    x86_decode(b, 16, 0, &in);
    CHECK((in.flags & (X86F_BRANCH | X86F_RET)) == (X86F_BRANCH | X86F_RET),
          "ret must be branch+ret");

    memset(b, 0x90, sizeof b);
    memcpy(b, "\x74\x05", 2);
    x86_decode(b, 16, 0, &in);
    CHECK((in.flags & (X86F_BRANCH | X86F_COND)) == (X86F_BRANCH | X86F_COND),
          "je rel8 must be branch+cond");

    memset(b, 0x90, sizeof b);
    memcpy(b, "\xE9\x00\x00\x00\x00", 5);
    x86_decode(b, 16, 0, &in);
    CHECK((in.flags & X86F_BRANCH) && !(in.flags & X86F_COND),
          "jmp rel32 must be an unconditional branch");

    /* LOCK and REP */
    memset(b, 0x90, sizeof b);
    memcpy(b, "\xF0\x48\xFF\x01", 4);
    x86_decode(b, 16, 0, &in);
    CHECK(in.flags & X86F_LOCK, "lock prefix must set X86F_LOCK");

    memset(b, 0x90, sizeof b);
    memcpy(b, "\xF3\xA4", 2);
    x86_decode(b, 16, 0, &in);
    CHECK(in.flags & X86F_REP, "rep movsb must set X86F_REP");

    /* A REX followed by a legacy prefix is ignored, not merged. */
    memset(b, 0x90, sizeof b);
    memcpy(b, "\x48\x66\x89\xC3", 4);
    x86_decode(b, 16, 0, &in);
    CHECK(in.rex == 0 && in.rex_w == 0, "REX before 0x66 must be ignored");
    CHECK(in.p66 && in.len == 4, "0x66 must still apply, len=%u", in.len);

    /* Arithmetic immediates are reported as raw bits; extension is opcode
     * specific and is the lifter's decision, not this layer's. */
    memset(b, 0x90, sizeof b);
    memcpy(b, "\x48\x83\xC0\xFF", 4);
    x86_decode(b, 16, 0, &in);
    CHECK(in.imm_len == 1 && in.imm == 0xFFu && !in.imm_signed,
          "add rax,imm8 must report raw 0xFF (imm=%llu signed=%d)",
          (unsigned long long)in.imm, (int)in.imm_signed);

    /* A relative displacement IS signed and must be extended. */
    memset(b, 0x90, sizeof b);
    memcpy(b, "\xEB\xFE", 2);
    x86_decode(b, 16, 0, &in);
    CHECK(in.imm_len == 1 && in.imm_signed && (int64_t)in.imm == -2,
          "jmp rel8 must sign-extend to -2 (imm=%lld signed=%d)",
          (long long)in.imm, (int)in.imm_signed);
    memset(b, 0x90, sizeof b);
    memcpy(b, "\xE9\xFB\xFF\xFF\xFF", 5);
    x86_decode(b, 16, 0, &in);
    CHECK(in.imm_len == 4 && in.imm_signed && (int64_t)in.imm == -5,
          "jmp rel32 must sign-extend to -5 (imm=%lld)", (long long)in.imm);

    /* GRP3 immediate depends on the reg field: TEST has one, NEG does not. */
    memset(b, 0x90, sizeof b);
    memcpy(b, "\xF7\xD8", 2);
    x86_decode(b, 16, 0, &in);
    CHECK(in.imm_len == 0, "neg eax must have no immediate, got %u", in.imm_len);
    memset(b, 0x90, sizeof b);
    memcpy(b, "\xF7\xC1\x01\x02\x03\x04", 6);
    x86_decode(b, 16, 0, &in);
    CHECK(in.imm_len == 4 && in.imm == 0x04030201u,
          "test ecx,imm32 must read the immediate, got %u", in.imm_len);

    /* mov r64, imm64 requires REX.W; without it the same opcode is imm32. */
    memset(b, 0x90, sizeof b);
    memcpy(b, "\xB8\x01\x02\x03\x04", 5);
    x86_decode(b, 16, 0, &in);
    CHECK(in.imm_len == 4 && in.len == 5, "mov eax,imm32 without REX.W");
}

static void test_mnemonics(void)
{
    printf("mnemonics\n");
    x86_insn in;
    unsigned char b[32];
    struct { const char *bytes; size_t n; const char *want; } m[] = {
        {"\x90", 1, "nop"},
        {"\xC3", 1, "ret"},
        {"\x55", 1, "push"},
        {"\x48\x89\xE5", 3, "mov"},
        {"\x48\x83\xEC\x10", 4, "sub"},
        {"\x48\x01\xC8", 3, "add"},
        {"\xE8\x00\x00\x00\x00", 5, "call"},
        {"\xE9\x00\x00\x00\x00", 5, "jmp"},
        {"\x48\x8D\x05\x00\x00\x00\x00", 7, "lea"},
        {"\x0F\x05", 2, "syscall"},
        {"\x0F\x84\x00\x00\x00\x00", 6, "je"},
        {"\x74\x05", 2, "je"},
        {"\xF7\xD8", 2, "neg"},
        {"\xF7\xC1\x01\x00\x00\x00", 6, "test"},
        {"\x0F\xA2", 2, "cpuid"},
        {"\xC9", 1, "leave"},
        {"\xCC", 1, "int3"},
        {"\x48\x63\xC1", 3, "movsxd"},
        {"\x0F\xB6\xC0", 3, "movzx"},
        {"\x0F\xAF\xC1", 3, "imul"},
        {"\xFF\xC0", 2, "inc"},
        {"\x48\xC7\xC0\x00\x00\x00\x00", 7, "mov"},
        {"\x48\x8B\x05\x00\x00\x00\x00", 7, "mov"},
    };
    for (size_t i = 0; i < sizeof m / sizeof m[0]; i++) {
        memset(b, 0x90, sizeof b);
        memcpy(b, m[i].bytes, m[i].n);
        x86_status st = x86_decode(b, 16, 0, &in);
        CHECK(st == X86_OK, "mnemonic case %zu must decode, got %s", i,
              x86_status_name(st));
        CHECK(in.mnemonic && strcmp(in.mnemonic, m[i].want) == 0,
              "case %zu: mnemonic '%s', expected '%s'", i,
              in.mnemonic ? in.mnemonic : "(null)", m[i].want);
    }
}

static void test_stream_and_limits(void)
{
    printf("stream decode and the 15-byte cap\n");
    /* A realistic prologue decoded as a stream: every length must line up, or the
     * whole block boundary analysis downstream is wrong. */
    static const unsigned char prog[] = {
        0x55,                                     /* push rbp            */
        0x48, 0x89, 0xE5,                         /* mov rbp,rsp         */
        0x48, 0x83, 0xEC, 0x20,                   /* sub rsp,0x20        */
        0x48, 0x8B, 0x05, 0x11, 0x22, 0x33, 0x44, /* mov rax,[rip+x]     */
        0x48, 0x89, 0x45, 0xF8,                   /* mov [rbp-8],rax     */
        0xE8, 0x00, 0x00, 0x00, 0x00,             /* call rel32          */
        0xC9,                                     /* leave               */
        0xC3                                      /* ret                 */
    };
    size_t off = 0;
    int count = 0;
    while (off < sizeof prog) {
        x86_insn in;
        x86_status st = x86_decode(prog + off, sizeof prog - off, 0x4000 + off, &in);
        CHECK(st == X86_OK, "prologue insn %d at +%zu must decode, got %s",
              count, off, x86_status_name(st));
        if (st != X86_OK || in.len == 0) break;
        off += in.len;
        count++;
    }
    CHECK(count == 8, "expected 8 instructions in the prologue, got %d", count);
    CHECK(off == sizeof prog, "stream must consume exactly all %zu bytes, consumed %zu",
          sizeof prog, off);

    /* Prefix spam must hit the 15-byte cap rather than run off the buffer. */
    unsigned char spam[40];
    memset(spam, 0x66, sizeof spam);
    x86_insn in;
    x86_status st = x86_decode(spam, sizeof spam, 0, &in);
    CHECK(st == X86_INVALID, "endless 0x66 prefixes must be INVALID, got %s",
          x86_status_name(st));
    CHECK(in.len == 0, "a failed decode must report len 0, got %u", in.len);
}

static void test_output_is_always_initialised(void)
{
    printf("out is written even on failure\n");
    /* A caller that reuses an x86_insn must never see a stale len from a previous
     * successful decode. */
    x86_insn in;
    unsigned char b[32];
    memset(b, 0x90, sizeof b);
    memcpy(b, "\x48\x89\xE5", 3);
    x86_decode(b, 16, 0, &in);
    CHECK(in.len == 3, "setup: expected len 3");
    memcpy(b, "\x06", 1);                         /* invalid in 64-bit */
    x86_decode(b, 16, 0, &in);
    CHECK(in.len == 0 && in.mnemonic == NULL && in.flags == 0,
          "failure must clear len, mnemonic and flags");
}

int main(void)
{
    printf("=== x86-64 decoder ===\n");
    test_lengths();
    test_fields();
    test_mnemonics();
    test_stream_and_limits();
    test_output_is_always_initialised();
    printf("\n%d checks, %d failure(s)\n", checks, failures);
    return failures ? 1 : 0;
}
