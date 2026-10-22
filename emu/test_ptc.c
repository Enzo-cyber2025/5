/* Tests for the persistent translation cache.
 *
 * The cases that matter most are the invalidation ones: a cache that returns a
 * hit when it should miss causes the emulator to execute machine code that no
 * longer corresponds to the guest bytes, which fails silently and corruptly. So
 * changed guest bytes, a changed module, a vanished module and a foreign host ISA
 * are each asserted to produce a miss or a refusal, not a hit.
 */
#define _POSIX_C_SOURCE 200809L

#include "ptc.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int checks, failures;

#define CHECK(cond, ...) do { \
    checks++; \
    if (!(cond)) { failures++; printf("  FAIL %s:%d: ", __FILE__, __LINE__); \
                   printf(__VA_ARGS__); printf("\n"); } \
} while (0)

static const char *TMP = "/tmp/test_ptc_cache.ptc";

static uint64_t hash_str(const char *s) { return ptc_hash_bytes(s, strlen(s)); }

/* ----------------------------------------------------------- hash / crc */

static void test_primitives(void)
{
    printf("primitives\n");
    CHECK(ptc_crc32(0, "", 0) == 0u, "crc32 of empty must be 0");
    /* The standard check value for CRC-32/ISO-HDLC. */
    CHECK(ptc_crc32(0, "123456789", 9) == 0xCBF43926u,
          "crc32(\"123456789\") = 0x%08X, expected 0xCBF43926",
          ptc_crc32(0, "123456789", 9));
    /* CRC must be incremental-equivalent. */
    uint32_t whole = ptc_crc32(0, "abcdefgh", 8);
    uint32_t split = ptc_crc32(ptc_crc32(0, "abcd", 4), "efgh", 4);
    CHECK(whole == split, "crc32 must compose: 0x%08X vs 0x%08X", whole, split);

    CHECK(hash_str("abc") == hash_str("abc"), "hash must be deterministic");
    CHECK(hash_str("abc") != hash_str("abd"), "hash must distinguish one byte");
    CHECK(ptc_hash_bytes(NULL, 0) != 0 || 1, "empty hash must not trap");
}

/* ------------------------------------------------------------- round trip */

static void test_roundtrip(void)
{
    printf("save/open round trip\n");
    unlink(TMP);
    ptc_cache *c = ptc_create(PTC_ISA_AARCH64, PTC_ISA_X86_64, 4096);
    CHECK(c != NULL, "create failed");

    uint64_t mod = 0;
    CHECK(ptc_add_module(c, "game.exe", 1000, 42, hash_str("content-a"), &mod) == 0,
          "add_module failed");
    CHECK(mod != 0, "module_id must not be 0");

    unsigned char guest[8] = {0x48, 0x89, 0xe5, 0x55, 0x48, 0x83, 0xec, 0x10};
    unsigned char host[16];
    for (int i = 0; i < 16; i++) host[i] = (unsigned char)(0xA0 + i);
    CHECK(ptc_insert(c, mod, 0x140001000ULL, guest, 8, host, 16, 0) == 0,
          "insert failed");

    uint32_t len = 0;
    const void *got = ptc_lookup(c, mod, 0x140001000ULL, guest, 8, &len);
    CHECK(got != NULL && len == 16 && memcmp(got, host, 16) == 0,
          "lookup must hit in memory");

    CHECK(ptc_save(c, TMP) == 0, "save failed");
    size_t recs_before = ptc_record_count(c);
    ptc_free(c);

    ptc_open_result why = PTC_OPEN_OK;
    c = ptc_open(TMP, PTC_ISA_AARCH64, PTC_ISA_X86_64, &why);
    CHECK(c != NULL, "open failed: reason=%d", (int)why);
    CHECK(why == PTC_OPEN_OK, "open reason must be OK, got %d", (int)why);
    if (c) {
        CHECK(ptc_module_count(c) == 1, "one module expected");
        CHECK(ptc_record_count(c) == recs_before, "record count must survive");
        CHECK(ptc_code_bytes(c) == 16, "code blob must survive, got %zu",
              ptc_code_bytes(c));
        len = 0;
        got = ptc_lookup(c, mod, 0x140001000ULL, guest, 8, &len);
        CHECK(got != NULL && len == 16 && memcmp(got, host, 16) == 0,
              "the whole point: a block translated before the restart must hit");
        CHECK(ptc_hits(c) == 1 && ptc_misses(c) == 0, "counters: %llu hits %llu misses",
              (unsigned long long)ptc_hits(c), (unsigned long long)ptc_misses(c));
        ptc_free(c);
    }
}

/* --------------------------------------------------------- invalidation */

static void test_self_modifying_guest_code(void)
{
    printf("guest bytes changed at the same PC must miss\n");
    unlink(TMP);
    ptc_cache *c = ptc_create(PTC_ISA_AARCH64, PTC_ISA_X86_64, 4096);
    uint64_t mod = 0;
    ptc_add_module(c, "m.exe", 10, 1, hash_str("x"), &mod);
    unsigned char guest[4] = {0x90, 0x90, 0x90, 0xC3};
    unsigned char host[4] = {0xD6, 0x5F, 0x03, 0xC0};
    ptc_insert(c, mod, 0x1000, guest, 4, host, 4, 0);
    uint32_t len = 0;
    CHECK(ptc_lookup(c, mod, 0x1000, guest, 4, &len) != NULL, "baseline must hit");

    guest[0] = 0xCC;                                  /* patched under the same PC */
    CHECK(ptc_lookup(c, mod, 0x1000, guest, 4, &len) == NULL,
          "changed guest bytes must miss, not execute stale host code");

    guest[0] = 0x90;
    CHECK(ptc_lookup(c, mod, 0x1000, guest, 4, &len) != NULL, "restoring must hit");
    CHECK(ptc_lookup(c, mod, 0x2000, guest, 4, &len) == NULL, "different PC must miss");
    CHECK(ptc_lookup(c, mod + 1, 0x1000, guest, 4, &len) == NULL,
          "different module must miss");
    ptc_free(c);
}

/* Probe that reports a caller-controlled current identity for each module. */
typedef struct { const char *name; uint64_t size, mtime, chash; int present; } fake;

#define MAXFAKE 4
typedef struct { fake f[MAXFAKE]; int n; } fakeset;

/* Reports the current on-disk identity of each named module. An unknown name or
 * present=0 means "not on disk", which must invalidate that module's blocks. */
static int probe_fn(const char *name, uint64_t *size, uint64_t *mtime,
                    uint64_t *chash, void *user)
{
    fakeset *fs = (fakeset *)user;
    for (int i = 0; i < fs->n; i++) {
        if (strcmp(fs->f[i].name, name) != 0)
            continue;
        if (!fs->f[i].present)
            return 0;
        *size = fs->f[i].size;
        *mtime = fs->f[i].mtime;
        *chash = fs->f[i].chash;
        return 1;
    }
    return 0;
}

static void test_module_invalidation_is_scoped(void)
{
    printf("a changed module loses only its own blocks\n");
    unlink(TMP);
    ptc_cache *c = ptc_create(PTC_ISA_AARCH64, PTC_ISA_X86_64, 4096);
    uint64_t a = 0, b = 0;
    ptc_add_module(c, "changed.dll", 100, 7, hash_str("old"), &a);
    ptc_add_module(c, "untouched.dll", 200, 9, hash_str("same"), &b);
    unsigned char guest[4] = {1, 2, 3, 4}, host[4] = {9, 9, 9, 9};
    ptc_insert(c, a, 0x10, guest, 4, host, 4, 0);
    ptc_insert(c, b, 0x20, guest, 4, host, 4, 0);
    CHECK(ptc_record_count(c) == 2, "two blocks before validation");

    fakeset fs = { {
        { "changed.dll",   100, 7, hash_str("NEW"),  1 },   /* content changed */
        { "untouched.dll", 200, 9, hash_str("same"), 1 },   /* identity intact */
    }, 2 };
    size_t dropped = ptc_validate_modules(c, probe_fn, &fs);
    CHECK(dropped == 1, "exactly one module invalidated, got %zu", dropped);

    uint32_t len = 0;
    CHECK(ptc_lookup(c, a, 0x10, guest, 4, &len) == NULL, "changed module must miss");
    CHECK(ptc_lookup(c, b, 0x20, guest, 4, &len) != NULL,
          "untouched module must keep working - invalidation is per module");
    CHECK(ptc_record_count(c) == 1, "dead block must not be counted");

    CHECK(ptc_save(c, TMP) == 0, "save after invalidation failed");
    ptc_free(c);
    ptc_open_result why;
    c = ptc_open(TMP, PTC_ISA_AARCH64, PTC_ISA_X86_64, &why);
    CHECK(c != NULL && why == PTC_OPEN_OK, "reopen failed: %d", (int)why);
    if (c) {
        CHECK(ptc_lookup(c, a, 0x10, guest, 4, &len) == NULL,
              "invalidated block must not come back after a save");
        CHECK(ptc_lookup(c, b, 0x20, guest, 4, &len) != NULL, "survivor must persist");
        ptc_free(c);
    }
}

static void test_vanished_module(void)
{
    printf("a module missing from disk loses its blocks\n");
    ptc_cache *c = ptc_create(PTC_ISA_AARCH64, PTC_ISA_X86_64, 4096);
    uint64_t m = 0;
    ptc_add_module(c, "gone.dll", 1, 1, hash_str("g"), &m);
    unsigned char guest[2] = {5, 6}, host[2] = {7, 8};
    ptc_insert(c, m, 0x40, guest, 2, host, 2, 0);
    fakeset fs = { { { "gone.dll", 0, 0, 0, 0 } }, 1 };
    CHECK(ptc_validate_modules(c, probe_fn, &fs) == 1, "absent module must invalidate");
    uint32_t len = 0;
    CHECK(ptc_lookup(c, m, 0x40, guest, 2, &len) == NULL, "must miss after removal");
    ptc_free(c);
}

/* ------------------------------------------------------------ ISA guards */

static void test_isa_and_corruption_guards(void)
{
    printf("foreign ISA and corruption must be refused\n");
    unlink(TMP);
    ptc_cache *c = ptc_create(PTC_ISA_AARCH64, PTC_ISA_X86_64, 4096);
    uint64_t m = 0;
    ptc_add_module(c, "m", 1, 1, hash_str("k"), &m);
    unsigned char guest[2] = {1, 2}, host[2] = {3, 4};
    ptc_insert(c, m, 0x99, guest, 2, host, 2, 0);
    ptc_save(c, TMP);
    ptc_free(c);

    ptc_open_result why = PTC_OPEN_OK;
    CHECK(ptc_open(TMP, PTC_ISA_X86_64, PTC_ISA_X86_64, &why) == NULL &&
              why == PTC_OPEN_HOST_ISA_MISMATCH,
          "x64 host code must not load on a different host ISA (got %d)", (int)why);
    CHECK(ptc_open(TMP, PTC_ISA_AARCH64, PTC_ISA_ARM32, &why) == NULL &&
              why == PTC_OPEN_GUEST_ISA_MISMATCH,
          "guest ISA mismatch must be refused (got %d)", (int)why);
    CHECK(ptc_open("/tmp/definitely_absent_file.ptc", PTC_ISA_AARCH64,
                   PTC_ISA_X86_64, &why) == NULL && why == PTC_OPEN_NOT_FOUND,
          "absent file must report NOT_FOUND (got %d)", (int)why);

    /* Flip one byte inside the code blob. */
    FILE *f = fopen(TMP, "r+b");
    CHECK(f != NULL, "cannot reopen for corruption test");
    if (f) { fseek(f, -1, SEEK_END); int ch = fgetc(f); fseek(f, -1, SEEK_END);
             fputc(ch ^ 0xFF, f); fclose(f); }
    CHECK(ptc_open(TMP, PTC_ISA_AARCH64, PTC_ISA_X86_64, &why) == NULL &&
              why == PTC_OPEN_CORRUPT, "corruption must be detected (got %d)", (int)why);

    /* Truncate. */
    CHECK(truncate(TMP, 8) == 0, "truncate failed");
    CHECK(ptc_open(TMP, PTC_ISA_AARCH64, PTC_ISA_X86_64, &why) == NULL &&
              why == PTC_OPEN_TRUNCATED, "truncation must be detected (got %d)", (int)why);

    /* Bad magic. The file must be at least a full header long, otherwise the
     * TRUNCATED check fires first - which is the correct precedence. */
    unlink(TMP);
    f = fopen(TMP, "wb");
    if (f) { char junk[256]; memset(junk, '.', sizeof junk);
             memcpy(junk, "NOPE", 4);
             fwrite(junk, 1, sizeof junk, f); fclose(f); }
    CHECK(ptc_open(TMP, PTC_ISA_AARCH64, PTC_ISA_X86_64, &why) == NULL &&
              why == PTC_OPEN_BAD_MAGIC, "bad magic must be detected (got %d)", (int)why);
    unlink(TMP);
}

/* ------------------------------------------------------ replace & stability */

static void test_replace_and_stable_save(void)
{
    printf("re-translation replaces; a second save is byte-stable\n");
    unlink(TMP);
    ptc_cache *c = ptc_create(PTC_ISA_AARCH64, PTC_ISA_X86_64, 4096);
    uint64_t m = 0;
    ptc_add_module(c, "m", 1, 1, hash_str("k"), &m);
    unsigned char guest[4] = {1, 2, 3, 4};
    unsigned char h1[4] = {0xAA, 0xAA, 0xAA, 0xAA}, h2[8] = {1,2,3,4,5,6,7,8};
    ptc_insert(c, m, 0x10, guest, 4, h1, 4, 0);
    ptc_insert(c, m, 0x10, guest, 4, h2, 8, 0);
    CHECK(ptc_record_count(c) == 1, "re-insert must replace, not duplicate (got %zu)",
          ptc_record_count(c));
    uint32_t len = 0;
    const void *got = ptc_lookup(c, m, 0x10, guest, 4, &len);
    CHECK(got && len == 8 && memcmp(got, h2, 8) == 0, "lookup must return the new code");

    CHECK(ptc_save(c, TMP) == 0, "first save failed");
    FILE *f = fopen(TMP, "rb");
    unsigned char first[8192]; size_t n1 = f ? fread(first, 1, sizeof first, f) : 0;
    if (f) fclose(f);
    CHECK(ptc_save(c, TMP) == 0, "second save failed");
    f = fopen(TMP, "rb");
    unsigned char second[8192]; size_t n2 = f ? fread(second, 1, sizeof second, f) : 0;
    if (f) fclose(f);
    CHECK(n1 == n2 && memcmp(first, second, n1) == 0,
          "saving twice must be idempotent (%zu vs %zu bytes)", n1, n2);
    ptc_free(c);
    unlink(TMP);
}

/* ------------------------------------------------------------- scale */

static void test_many_blocks(void)
{
    printf("index holds up over many blocks\n");
    unlink(TMP);
    ptc_cache *c = ptc_create(PTC_ISA_AARCH64, PTC_ISA_X86_64, 4096);
    uint64_t m = 0;
    ptc_add_module(c, "big", 1, 1, hash_str("k"), &m);
    const int N = 5000;
    for (int i = 0; i < N; i++) {
        unsigned char guest[8], host[12];
        memset(guest, 0, sizeof guest); memset(host, 0, sizeof host);
        memcpy(guest, &i, sizeof i); memcpy(host, &i, sizeof i);
        ptc_insert(c, m, 0x1000 + (uint64_t)i * 16, guest, 8, host, 12, 0);
    }
    CHECK(ptc_record_count(c) == (size_t)N, "expected %d records, got %zu", N,
          ptc_record_count(c));
    ptc_save(c, TMP);
    ptc_free(c);

    ptc_open_result why;
    c = ptc_open(TMP, PTC_ISA_AARCH64, PTC_ISA_X86_64, &why);
    CHECK(c != NULL, "reopen of a large cache failed: %d", (int)why);
    if (c) {
        int wrong = 0;
        for (int i = 0; i < N; i++) {
            unsigned char guest[8], host[12];
            memset(guest, 0, sizeof guest); memset(host, 0, sizeof host);
            memcpy(guest, &i, sizeof i); memcpy(host, &i, sizeof i);
            uint32_t len = 0;
            const void *got = ptc_lookup(c, m, 0x1000 + (uint64_t)i * 16, guest, 8, &len);
            if (!got || len != 12 || memcmp(got, host, 12) != 0) wrong++;
        }
        CHECK(wrong == 0, "%d of %d blocks came back wrong after reload", wrong, N);
        CHECK(ptc_hits(c) == (uint64_t)N, "expected %d hits, got %llu", N,
              (unsigned long long)ptc_hits(c));
        ptc_free(c);
    }
    unlink(TMP);
}

int main(void)
{
    printf("=== persistent translation cache ===\n");
    test_primitives();
    test_roundtrip();
    test_self_modifying_guest_code();
    test_module_invalidation_is_scoped();
    test_vanished_module();
    test_isa_and_corruption_guards();
    test_replace_and_stable_save();
    test_many_blocks();
    printf("\n%d checks, %d failure(s)\n", checks, failures);
    return failures ? 1 : 0;
}
