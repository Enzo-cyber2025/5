/* Persistent Translation Cache (PTC) - foundation of the emulator.
 *
 * Purpose: a dynamic binary translator pays for each guest basic block once.
 * This module makes that payment survive process restarts, so a block translated
 * yesterday is executed today without being translated again.
 *
 * The hard part is not storage, it is INVALIDATION. Executing stale host code
 * against changed guest bytes is a silent, unrecoverable correctness failure, so
 * every lookup is bound to three independent identities:
 *
 *   module_id  - which guest module the block came from
 *   guest_pc   - where in that module the block starts
 *   src_hash   - a hash of the block's own guest bytes
 *
 * A hit requires all three to match. Changing one byte of guest code changes
 * src_hash and the entry misses, which is what makes self-modifying code safe.
 * Replacing or updating a module changes its content hash, and every block that
 * belongs to it is dropped while other modules' blocks survive.
 *
 * A cache is also stamped with the host ISA and guest ISA it was produced for:
 * ARM64 host code must never be loaded on an x86-64 host, or executed.
 *
 * Written from scratch. No compression, serialization or hashing library is
 * used; CRC-32/ISO-HDLC and FNV-1a are implemented here.
 *
 * Little-endian only (ARM64 and x86-64 both are). Not thread-safe: the caller
 * serialises access, which the translator does anyway while emitting code.
 */
#ifndef PTC_H
#define PTC_H

#include <stddef.h>
#include <stdint.h>

#define PTC_MAGIC "PTC1"
#define PTC_FORMAT_VERSION 1u

/* Host/guest ISA stamps. Any stable enumeration works; what matters is that a
 * mismatch is detected rather than silently loading foreign machine code. */
#define PTC_ISA_UNKNOWN  0u
#define PTC_ISA_AARCH64  1u
#define PTC_ISA_X86_64   2u
#define PTC_ISA_ARM32    3u

/* Reason an existing cache file could not be used. Reported so the caller can
 * log a real cause instead of silently starting cold every time. */
typedef enum {
    PTC_OPEN_OK = 0,
    PTC_OPEN_NOT_FOUND,
    PTC_OPEN_IO_ERROR,
    PTC_OPEN_BAD_MAGIC,
    PTC_OPEN_VERSION_MISMATCH,
    PTC_OPEN_HOST_ISA_MISMATCH,
    PTC_OPEN_GUEST_ISA_MISMATCH,
    PTC_OPEN_CORRUPT,
    PTC_OPEN_TRUNCATED
} ptc_open_result;

typedef struct ptc_cache ptc_cache;

/* Per-module identity. `content_hash` is what proves the module on disk is still
 * the one the cached blocks were translated from; name/size/mtime are recorded
 * for diagnosis and as a cheap pre-check. */
typedef struct {
    uint64_t module_id;
    uint64_t size;
    uint64_t mtime;
    uint64_t content_hash;
    char    *name;          /* owned by the cache */
    int      stale;         /* set by ptc_validate_modules when identity differs */
} ptc_module;

/* ---- hashing / checksums (implemented here, no library) ---- */
uint64_t ptc_hash_bytes(const void *buf, size_t len);
uint32_t ptc_crc32(uint32_t crc, const void *buf, size_t len);

/* ---- lifecycle ---- */
ptc_cache *ptc_create(uint32_t host_isa, uint32_t guest_isa, uint32_t page_size);

/* Load a cache from disk. Returns NULL only on allocation failure; on any
 * structural problem it returns NULL and sets *why. Callers treat every non-OK
 * result the same way - start cold - but the reason is worth logging. */
ptc_cache *ptc_open(const char *path, uint32_t host_isa, uint32_t guest_isa,
                    ptc_open_result *why);

/* Write out. Atomic: a temporary file is written, fsynced, then renamed over the
 * target, so a crash mid-save cannot leave a half-written cache behind. */
int  ptc_save(ptc_cache *c, const char *path);
void ptc_free(ptc_cache *c);

/* ---- modules ---- */
/* Register a module, or find the already-registered one with the same identity.
 * out_id receives the module_id used for subsequent inserts and lookups. */
int ptc_add_module(ptc_cache *c, const char *name, uint64_t size, uint64_t mtime,
                   uint64_t content_hash, uint64_t *out_id);

/* Compare every recorded module against a caller-supplied current identity.
 * Modules whose content_hash no longer matches are marked stale and their blocks
 * are dropped. Returns the number of modules invalidated. */
typedef int (*ptc_module_probe)(const char *name, uint64_t *size, uint64_t *mtime,
                                uint64_t *content_hash, void *user);
size_t ptc_validate_modules(ptc_cache *c, ptc_module_probe probe, void *user);

/* ---- blocks ---- */
int ptc_insert(ptc_cache *c, uint64_t module_id, uint64_t guest_pc,
               const void *guest_bytes, uint32_t guest_len,
               const void *host_code, uint32_t code_len, uint32_t flags);

/* Returns a pointer to the cached host code, or NULL on miss. *out_code_len
 * receives its length. The pointer stays valid until the next insert or free. */
const void *ptc_lookup(ptc_cache *c, uint64_t module_id, uint64_t guest_pc,
                       const void *guest_bytes, uint32_t guest_len,
                       uint32_t *out_code_len);

/* ---- introspection ---- */
size_t   ptc_module_count(const ptc_cache *c);
size_t   ptc_record_count(const ptc_cache *c);
size_t   ptc_code_bytes(const ptc_cache *c);
uint64_t ptc_hits(const ptc_cache *c);
uint64_t ptc_misses(const ptc_cache *c);
const ptc_module *ptc_module_at(const ptc_cache *c, size_t i);

#endif /* PTC_H */
