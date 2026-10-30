/* MAP_ANONYMOUS lives behind __USE_MISC in glibc, which -std=c11 turns off. On
 * glibc 2.36 it is hidden and this file does not compile; on the aarch64 runner's
 * 2.39 it is exposed and it does, so the failure only ever appeared on one host.
 * Asking for the default feature set removes the dependency. */
#ifndef _DEFAULT_SOURCE
#define _DEFAULT_SOURCE 1
#endif

/* Execute machine code this program wrote itself.
 *
 * This is the verification method for the ARM64 emitter, established before the
 * emitter exists: an encoder cannot be validated by inspection alone, because a
 * wrong encoding still looks like a plausible word. What settles it is emitting
 * into an executable page and running it. That needs a real ARM64 host or a
 * user-mode emulator, which is why this test exists and is guarded by ISA.
 *
 * The encodings here are hand-derived from the ARMv8-A encoding tables and
 * pinned by assertion, so this file doubles as the seed of the emitter's encoder
 * and as a record of where each constant came from.
 *
 * On a non-ARM64 host the test reports a skip rather than passing silently: CI
 * greps for the "EXECUTED ON aarch64" line and fails without it, so a job that
 * quietly ran nothing cannot look green.
 */
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include "a64_emit.h"
#include <stdlib.h>

#if defined(__aarch64__)
#include <sys/mman.h>
#include <unistd.h>
#endif

static int checks, failures;

#define CHECK(cond, ...) do { \
    checks++; \
    if (!(cond)) { failures++; printf("  FAIL line %d: ", __LINE__); \
                   printf(__VA_ARGS__); printf("\n"); } \
} while (0)

/* ---------------------------------------------------------------- encodings
 * MOVZ (64-bit):  sf=1 opc=10 100101 hw imm16 Rd
 *                 -> 0xD2800000 | (imm16 << 5) | Rd
 * ADD  (imm, 64): sf=1 op=0 S=0 100010 sh imm12 Rn Rd
 *                 -> 0x91000000 | (imm12 << 10) | (Rn << 5) | Rd
 * RET:            1101011 0010 11111 000000 Rn(=30)
 *                 -> 0xD65F03C0
 */
static uint32_t enc_movz_x(uint8_t rd, uint16_t imm)
{
    return 0xD2800000u | ((uint32_t)imm << 5) | rd;
}

static uint32_t enc_add_x_imm(uint8_t rd, uint8_t rn, uint16_t imm)
{
    return 0x91000000u | ((uint32_t)imm << 10) | ((uint32_t)rn << 5) | rd;
}

static uint32_t enc_ret(void) { return 0xD65F03C0u; }

static void test_encodings_are_what_the_manual_says(void)
{
    printf("hand-derived encodings\n");
    CHECK(enc_movz_x(0, 42) == 0xD2800540u, "movz x0,#42 = 0x%08X, expected 0xD2800540",
          enc_movz_x(0, 42));
    CHECK(enc_movz_x(0, 1) == 0xD2800020u, "movz x0,#1 = 0x%08X", enc_movz_x(0, 1));
    CHECK(enc_movz_x(1, 0) == 0xD2800001u, "movz x1,#0 = 0x%08X", enc_movz_x(1, 0));
    CHECK(enc_add_x_imm(0, 0, 2) == 0x91000800u, "add x0,x0,#2 = 0x%08X, expected 0x91000800",
          enc_add_x_imm(0, 0, 2));
    CHECK(enc_add_x_imm(2, 1, 0x10) == 0x91004022u,
          "add x2,x1,#0x10 = 0x%08X, expected 0x91004022", enc_add_x_imm(2, 1, 0x10));
    CHECK(enc_ret() == 0xD65F03C0u, "ret = 0x%08X", enc_ret());

    /* BRK #imm16 is 1101_0100_001 | imm16<<5 | 00000, so BRK #0 is 0xD4200000 and
     * the guest-out-of-bounds tag 0x9F1E shifts to 0x13E3C0, giving 0xD433E3C0.
     * Pinned against those literals rather than against a local enc_brk(): the
     * emitter is the thing under test here, and a helper that shares its expression
     * would only prove the function agrees with itself. */
    CHECK(a64_brk(0) == 0xD4200000u, "brk #0 = 0x%08X, expected 0xD4200000",
          a64_brk(0));
    CHECK(a64_brk(A64_BRK_GUEST_OOB) == 0xD433E3C0u,
          "brk #0x9F1E = 0x%08X, expected 0xD433E3C0", a64_brk(A64_BRK_GUEST_OOB));
}

#if defined(__aarch64__)

/* Run a sequence of ARM64 words as a function returning uint64_t in x0. */
static int run_code(const uint32_t *words, size_t n, uint64_t *out, const char **why)
{
    size_t bytes = n * sizeof words[0];
    /* RWX is required because this is a JIT harness: the whole point is writing
     * code and then executing it. Where W^X policy forbids it the mmap fails and
     * the reason is reported rather than the test silently passing. */
    void *p = mmap(NULL, bytes, PROT_READ | PROT_WRITE | PROT_EXEC,
                   MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (p == MAP_FAILED) { *why = "mmap RWX refused"; return -1; }
    memcpy(p, words, bytes);
    /* Mandatory on ARM64: the store went through the D-cache, and the fetch will
     * come from the I-cache. Without cleaning D and invalidating I, execution can
     * see stale bytes and fail in a way that looks like a bad encoding. */
    __builtin___clear_cache((char *)p, (char *)p + bytes);
    uint64_t (*fn)(void) = (uint64_t (*)(void))p;
    *out = fn();
    munmap(p, bytes);
    *why = NULL;
    return 0;
}

static void test_execute_generated_code(void)
{
    printf("executing self-generated code\n");
    uint64_t r = 0;
    const char *why = NULL;

    uint32_t prog1[] = { enc_movz_x(0, 42), enc_ret() };
    CHECK(run_code(prog1, 2, &r, &why) == 0, "could not run prog1: %s", why ? why : "?");
    CHECK(r == 42, "movz x0,#42; ret returned %llu, expected 42", (unsigned long long)r);

    uint32_t prog2[] = { enc_movz_x(0, 1), enc_add_x_imm(0, 0, 2), enc_ret() };
    CHECK(run_code(prog2, 3, &r, &why) == 0, "could not run prog2: %s", why ? why : "?");
    CHECK(r == 3, "1 + 2 returned %llu, expected 3", (unsigned long long)r);

    /* A second execution of a fresh page must not be polluted by the first: each
     * generated block needs its own cache maintenance. */
    uint32_t prog3[] = { enc_movz_x(0, 7), enc_add_x_imm(0, 0, 0), enc_ret() };
    CHECK(run_code(prog3, 3, &r, &why) == 0, "could not run prog3: %s", why ? why : "?");
    CHECK(r == 7, "movz x0,#7; add x0,x0,#0; ret returned %llu, expected 7",
          (unsigned long long)r);

    printf("EXECUTED ON aarch64\n");
}

#else  /* !__aarch64__ */

static void test_execute_generated_code(void)
{
    printf("executing self-generated code\n");
    printf("  SKIP: host is not aarch64 - encodings were checked, nothing was run\n");
    printf("SKIPPED NOT aarch64\n");
}

#endif

int main(void)
{
    printf("=== arm64 emit-and-execute harness ===\n");
#if defined(__aarch64__)
    printf("host: aarch64\n");
#else
    printf("host: not aarch64\n");
#endif
    test_encodings_are_what_the_manual_says();
    test_execute_generated_code();
    printf("\n%d checks, %d failure(s)\n", checks, failures);
    return failures ? 1 : 0;
}
