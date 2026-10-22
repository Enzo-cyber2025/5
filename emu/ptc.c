/* Persistent Translation Cache - implementation. See ptc.h for the contract. */
/* fsync/fileno/rename are POSIX; declare them even under strict -std=c11. */
#define _POSIX_C_SOURCE 200809L

#include "ptc.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

/* ------------------------------------------------------------------ hashes */

uint64_t ptc_hash_bytes(const void *buf, size_t len)
{
    const unsigned char *p = (const unsigned char *)buf;
    uint64_t h = 1469598103934665603ULL;            /* FNV-1a 64 offset basis */
    while (len--) {
        h ^= (uint64_t)*p++;
        h *= 1099511628211ULL;                      /* FNV-1a 64 prime */
    }
    return h;
}

static uint32_t crc_tab[256];
static int crc_tab_ready;

static void crc_init(void)
{
    for (uint32_t i = 0; i < 256; i++) {
        uint32_t c = i;
        for (int k = 0; k < 8; k++)
            c = (c & 1u) ? (0xEDB88320u ^ (c >> 1)) : (c >> 1);
        crc_tab[i] = c;
    }
    crc_tab_ready = 1;
}

uint32_t ptc_crc32(uint32_t crc, const void *buf, size_t len)
{
    if (!crc_tab_ready)
        crc_init();
    const unsigned char *p = (const unsigned char *)buf;
    crc = ~crc;
    while (len--)
        crc = crc_tab[(crc ^ *p++) & 0xFFu] ^ (crc >> 8);
    return ~crc;
}

/* ------------------------------------------------------------- on-disk shape */

typedef struct {
    char     magic[4];
    uint32_t format_version;
    uint32_t host_isa;
    uint32_t guest_isa;
    uint32_t page_size;
    uint32_t n_modules;
    uint32_t n_records;
    uint32_t pad0;
    uint64_t created_unix;
    uint64_t module_off, module_len, module_crc;
    uint64_t record_off, record_len, record_crc;
    uint64_t code_off,   code_len,   code_crc;
    uint32_t header_crc;                            /* over this struct, zeroed */
    uint32_t pad1;
} __attribute__((packed)) ptc_hdr;

typedef struct {
    uint64_t module_id;
    uint64_t size;
    uint64_t mtime;
    uint64_t content_hash;
    uint32_t name_len;
} __attribute__((packed)) ptc_mod_disk;             /* name bytes follow */

typedef struct {
    uint64_t module_id;
    uint64_t guest_pc;
    uint64_t src_hash;
    uint32_t guest_len;
    uint32_t flags;
    uint32_t code_off;
    uint32_t code_len;
    uint32_t rec_crc;                               /* over the 40 bytes above */
    uint32_t pad;
} __attribute__((packed)) ptc_rec_disk;

#define REC_CRC_LEN (offsetof(ptc_rec_disk, rec_crc))

/* ------------------------------------------------------------------- memory */

typedef struct {
    uint64_t module_id, guest_pc, src_hash;
    uint32_t guest_len, flags, code_off, code_len;
    int      dead;                                  /* dropped, awaiting compaction */
} ptc_rec;

struct ptc_cache {
    uint32_t host_isa, guest_isa, page_size;
    uint64_t created_unix;

    ptc_module *mods;  size_t n_mods,  cap_mods;
    ptc_rec    *recs;  size_t n_recs,  cap_recs;
    uint8_t    *code;  size_t code_len, code_cap;

    uint32_t   *idx;   size_t idx_cap;              /* open addressing, rec#+1 */
    uint64_t hits, misses;
};

static void grow_code(struct ptc_cache *c, size_t extra);

static void *xrealloc(void *p, size_t n)
{
    void *r = realloc(p, n ? n : 1);
    if (!r) { fprintf(stderr, "ptc: out of memory (%zu bytes)\n", n); abort(); }
    return r;
}

static void grow_code(ptc_cache *c, size_t extra)
{
    if (c->code_len + extra <= c->code_cap)
        return;
    size_t cap = c->code_cap ? c->code_cap : 4096;
    while (cap < c->code_len + extra)
        cap *= 2;
    c->code = xrealloc(c->code, cap);
    c->code_cap = cap;
}

/* module_id is derived from the module's full identity, so a byte change in the
 * file yields a different id and old blocks stop matching on their own. */
static uint64_t module_identity(const char *name, uint64_t size, uint64_t mtime,
                                uint64_t content_hash)
{
    uint64_t h = ptc_hash_bytes(name, strlen(name));
    uint64_t parts[3] = { size, mtime, content_hash };
    for (int i = 0; i < 3; i++)
        h = ptc_hash_bytes(&parts[i], sizeof parts[i]) ^ (h * 1099511628211ULL);
    return h ? h : 1;                               /* 0 is reserved as "none" */
}

/* -------------------------------------------------------------------- index */

static size_t idx_slot(const ptc_cache *c, uint64_t module_id, uint64_t guest_pc)
{
    uint64_t k = (module_id * 1099511628211ULL) ^ (guest_pc * 0x9E3779B97F4A7C15ULL);
    return (size_t)(k & (uint64_t)(c->idx_cap - 1));
}

static void idx_rebuild(ptc_cache *c)
{
    size_t want = 16;
    while (want < (c->n_recs + 1) * 2)
        want <<= 1;
    if (want != c->idx_cap) {
        free(c->idx);
        c->idx = xrealloc(NULL, want * sizeof *c->idx);
        c->idx_cap = want;
    }
    memset(c->idx, 0, c->idx_cap * sizeof *c->idx);
    for (size_t i = 0; i < c->n_recs; i++) {
        if (c->recs[i].dead)
            continue;
        size_t s = idx_slot(c, c->recs[i].module_id, c->recs[i].guest_pc);
        while (c->idx[s])
            s = (s + 1) & (c->idx_cap - 1);
        c->idx[s] = (uint32_t)(i + 1);
    }
}

/* --------------------------------------------------------------- lifecycle */

ptc_cache *ptc_create(uint32_t host_isa, uint32_t guest_isa, uint32_t page_size)
{
    ptc_cache *c = calloc(1, sizeof *c);
    if (!c)
        return NULL;
    c->host_isa = host_isa;
    c->guest_isa = guest_isa;
    c->page_size = page_size;
    c->created_unix = (uint64_t)time(NULL);
    idx_rebuild(c);
    return c;
}

void ptc_free(ptc_cache *c)
{
    if (!c)
        return;
    for (size_t i = 0; i < c->n_mods; i++)
        free(c->mods[i].name);
    free(c->mods);
    free(c->recs);
    free(c->code);
    free(c->idx);
    free(c);
}

/* ------------------------------------------------------------------ modules */

const ptc_module *ptc_module_at(const ptc_cache *c, size_t i)
{
    return (c && i < c->n_mods) ? &c->mods[i] : NULL;
}

int ptc_add_module(ptc_cache *c, const char *name, uint64_t size, uint64_t mtime,
                   uint64_t content_hash, uint64_t *out_id)
{
    if (!c || !name)
        return -1;
    uint64_t id = module_identity(name, size, mtime, content_hash);
    for (size_t i = 0; i < c->n_mods; i++) {
        if (c->mods[i].module_id == id) {
            if (out_id) *out_id = id;
            return 0;                               /* same identity: reuse */
        }
    }
    if (c->n_mods == c->cap_mods) {
        c->cap_mods = c->cap_mods ? c->cap_mods * 2 : 8;
        c->mods = xrealloc(c->mods, c->cap_mods * sizeof *c->mods);
    }
    ptc_module *m = &c->mods[c->n_mods++];
    memset(m, 0, sizeof *m);
    m->module_id = id;
    m->size = size;
    m->mtime = mtime;
    m->content_hash = content_hash;
    m->name = xrealloc(NULL, strlen(name) + 1);
    strcpy(m->name, name);
    if (out_id) *out_id = id;
    return 0;
}

size_t ptc_validate_modules(ptc_cache *c, ptc_module_probe probe, void *user)
{
    if (!c || !probe)
        return 0;
    size_t invalidated = 0;
    for (size_t i = 0; i < c->n_mods; i++) {
        ptc_module *m = &c->mods[i];
        uint64_t size = 0, mtime = 0, chash = 0;
        if (!probe(m->name, &size, &mtime, &chash, user)) {
            m->stale = 1;                           /* gone from disk: drop it */
        } else if (m->size != size || m->mtime != mtime ||
                   m->content_hash != chash) {
            m->stale = 1;                           /* changed: drop its blocks */
        }
        if (!m->stale)
            continue;
        invalidated++;
        for (size_t r = 0; r < c->n_recs; r++)
            if (c->recs[r].module_id == m->module_id)
                c->recs[r].dead = 1;
    }
    if (invalidated)
        idx_rebuild(c);
    return invalidated;
}

/* ------------------------------------------------------------------- blocks */

int ptc_insert(ptc_cache *c, uint64_t module_id, uint64_t guest_pc,
               const void *guest_bytes, uint32_t guest_len,
               const void *host_code, uint32_t code_len, uint32_t flags)
{
    if (!c || !guest_bytes || !host_code || !guest_len)
        return -1;
    uint64_t src_hash = ptc_hash_bytes(guest_bytes, guest_len);

    /* Re-translating the same block replaces the old entry rather than leaving a
     * duplicate that would grow the file forever. */
    for (size_t i = 0; i < c->n_recs; i++) {
        ptc_rec *r = &c->recs[i];
        if (!r->dead && r->module_id == module_id && r->guest_pc == guest_pc) {
            r->src_hash = src_hash;
            r->guest_len = guest_len;
            r->flags = flags;
            grow_code(c, code_len);
            r->code_off = (uint32_t)c->code_len;
            r->code_len = code_len;
            memcpy(c->code + r->code_off, host_code, code_len);
            c->code_len += code_len;
            idx_rebuild(c);
            return 0;
        }
    }

    if (c->n_recs == c->cap_recs) {
        c->cap_recs = c->cap_recs ? c->cap_recs * 2 : 64;
        c->recs = xrealloc(c->recs, c->cap_recs * sizeof *c->recs);
    }
    ptc_rec *r = &c->recs[c->n_recs++];
    memset(r, 0, sizeof *r);
    r->module_id = module_id;
    r->guest_pc = guest_pc;
    r->src_hash = src_hash;
    r->guest_len = guest_len;
    r->flags = flags;
    grow_code(c, code_len);
    r->code_off = (uint32_t)c->code_len;
    r->code_len = code_len;
    memcpy(c->code + r->code_off, host_code, code_len);
    c->code_len += code_len;
    idx_rebuild(c);
    return 0;
}

const void *ptc_lookup(ptc_cache *c, uint64_t module_id, uint64_t guest_pc,
                       const void *guest_bytes, uint32_t guest_len,
                       uint32_t *out_code_len)
{
    if (!c || !guest_bytes || !c->idx_cap) {
        if (c) c->misses++;
        return NULL;
    }
    uint64_t src_hash = ptc_hash_bytes(guest_bytes, guest_len);
    size_t s = idx_slot(c, module_id, guest_pc);
    while (c->idx[s]) {
        const ptc_rec *r = &c->recs[c->idx[s] - 1];
        if (r->module_id == module_id && r->guest_pc == guest_pc) {
            /* All three identities must agree. src_hash is what catches guest
             * code that changed under a stable address. */
            if (!r->dead && r->guest_len == guest_len && r->src_hash == src_hash) {
                c->hits++;
                if (out_code_len) *out_code_len = r->code_len;
                return c->code + r->code_off;
            }
            c->misses++;
            return NULL;
        }
        s = (s + 1) & (c->idx_cap - 1);
    }
    c->misses++;
    return NULL;
}

/* --------------------------------------------------------------------- save */

int ptc_save(ptc_cache *c, const char *path)
{
    if (!c || !path)
        return -1;

    /* Drop dead records and the code they pointed at, so an invalidated module
     * does not leave its machine code in the file forever. */
    size_t live = 0;
    for (size_t i = 0; i < c->n_recs; i++)
        if (!c->recs[i].dead)
            live++;

    uint8_t *code = NULL;
    size_t code_len = 0, code_cap = 0;
    uint32_t *remap = xrealloc(NULL, (c->n_recs ? c->n_recs : 1) * sizeof *remap);
    for (size_t i = 0; i < c->n_recs; i++) {
        if (c->recs[i].dead) { remap[i] = 0xFFFFFFFFu; continue; }
        remap[i] = (uint32_t)code_len;
        if (code_len + c->recs[i].code_len > code_cap) {
            code_cap = code_cap ? code_cap * 2 : 4096;
            while (code_cap < code_len + c->recs[i].code_len) code_cap *= 2;
            code = xrealloc(code, code_cap);
        }
        memcpy(code + code_len, c->code + c->recs[i].code_off, c->recs[i].code_len);
        code_len += c->recs[i].code_len;
    }

    size_t mod_len = 0;
    for (size_t i = 0; i < c->n_mods; i++)
        mod_len += sizeof(ptc_mod_disk) + strlen(c->mods[i].name);
    size_t rec_len = live * sizeof(ptc_rec_disk);

    size_t total = sizeof(ptc_hdr) + mod_len + rec_len + code_len;
    uint8_t *img = calloc(1, total);
    if (!img) { free(code); free(remap); return -1; }

    ptc_hdr h;
    memset(&h, 0, sizeof h);
    memcpy(h.magic, PTC_MAGIC, 4);
    h.format_version = PTC_FORMAT_VERSION;
    h.host_isa = c->host_isa;
    h.guest_isa = c->guest_isa;
    h.page_size = c->page_size;
    h.n_modules = (uint32_t)c->n_mods;
    h.n_records = (uint32_t)live;
    h.created_unix = c->created_unix;
    h.module_off = sizeof(ptc_hdr);
    h.module_len = mod_len;
    h.record_off = h.module_off + mod_len;
    h.record_len = rec_len;
    h.code_off = h.record_off + rec_len;
    h.code_len = code_len;
    size_t p = h.module_off;
    for (size_t i = 0; i < c->n_mods; i++) {
        ptc_mod_disk md;
        memset(&md, 0, sizeof md);
        md.module_id = c->mods[i].module_id;
        md.size = c->mods[i].size;
        md.mtime = c->mods[i].mtime;
        md.content_hash = c->mods[i].content_hash;
        md.name_len = (uint32_t)strlen(c->mods[i].name);
        memcpy(img + p, &md, sizeof md);
        p += sizeof md;
        memcpy(img + p, c->mods[i].name, md.name_len);
        p += md.name_len;
    }
    h.module_crc = ptc_crc32(0, img + h.module_off, mod_len);

    p = h.record_off;
    for (size_t i = 0; i < c->n_recs; i++) {
        if (c->recs[i].dead)
            continue;
        ptc_rec_disk rd;
        memset(&rd, 0, sizeof rd);
        rd.module_id = c->recs[i].module_id;
        rd.guest_pc = c->recs[i].guest_pc;
        rd.src_hash = c->recs[i].src_hash;
        rd.guest_len = c->recs[i].guest_len;
        rd.flags = c->recs[i].flags;
        rd.code_off = remap[i];
        rd.code_len = c->recs[i].code_len;
        rd.rec_crc = ptc_crc32(0, &rd, REC_CRC_LEN);
        memcpy(img + p, &rd, sizeof rd);
        p += sizeof rd;
    }
    h.record_crc = ptc_crc32(0, img + h.record_off, rec_len);

    if (code_len)
        memcpy(img + h.code_off, code, code_len);
    h.code_crc = ptc_crc32(0, img + h.code_off, code_len);

    h.header_crc = ptc_crc32(0, &h, offsetof(ptc_hdr, header_crc));
    memcpy(img, &h, sizeof h);

    /* Atomic replace: write, fsync, rename. A crash cannot leave a truncated
     * cache that a later open would mistake for a valid one. */
    char tmp[4096];
    if (snprintf(tmp, sizeof tmp, "%s.tmp.%ld", path, (long)getpid()) >= (int)sizeof tmp) {
        free(img); free(code); free(remap);
        return -1;
    }
    FILE *f = fopen(tmp, "wb");
    if (!f) { free(img); free(code); free(remap); return -1; }
    int ok = (fwrite(img, 1, total, f) == total);
    if (ok) ok = (fflush(f) == 0);
    if (ok) ok = (fsync(fileno(f)) == 0);
    if (fclose(f) != 0) ok = 0;
    if (ok) ok = (rename(tmp, path) == 0);
    if (!ok) unlink(tmp);

    free(img);
    if (!ok) {
        free(code);
        free(remap);
        return -1;
    }

    /* Adopt the compacted image so a second save is byte-stable and the code
     * orphaned by replaced or invalidated entries does not linger in memory. */
    size_t w = 0;
    for (size_t i = 0; i < c->n_recs; i++) {
        if (c->recs[i].dead)
            continue;
        if (w != i)
            c->recs[w] = c->recs[i];
        c->recs[w].code_off = remap[i];
        w++;
    }
    c->n_recs = w;
    free(c->code);
    c->code = code;                                 /* ownership transferred */
    c->code_len = code_len;
    c->code_cap = code_cap;
    free(remap);
    idx_rebuild(c);
    return 0;
}

/* --------------------------------------------------------------------- open */

ptc_cache *ptc_open(const char *path, uint32_t host_isa, uint32_t guest_isa,
                    ptc_open_result *why)
{
    ptc_open_result r = PTC_OPEN_OK;
    ptc_cache *c = NULL;

    FILE *f = fopen(path, "rb");
    if (!f) { r = (errno == ENOENT) ? PTC_OPEN_NOT_FOUND : PTC_OPEN_IO_ERROR; goto done; }
    if (fseek(f, 0, SEEK_END) != 0) { r = PTC_OPEN_IO_ERROR; goto done; }
    long fsz = ftell(f);
    if (fsz < 0) { r = PTC_OPEN_IO_ERROR; goto done; }
    rewind(f);
    if ((size_t)fsz < sizeof(ptc_hdr)) { r = PTC_OPEN_TRUNCATED; goto done; }

    uint8_t *img = xrealloc(NULL, (size_t)fsz);
    if (fread(img, 1, (size_t)fsz, f) != (size_t)fsz) { free(img); r = PTC_OPEN_IO_ERROR; goto done; }
    fclose(f); f = NULL;

    ptc_hdr h;
    memcpy(&h, img, sizeof h);
    if (memcmp(h.magic, PTC_MAGIC, 4) != 0) { free(img); r = PTC_OPEN_BAD_MAGIC; goto done; }
    if (h.format_version != PTC_FORMAT_VERSION) { free(img); r = PTC_OPEN_VERSION_MISMATCH; goto done; }
    if (h.host_isa != host_isa) { free(img); r = PTC_OPEN_HOST_ISA_MISMATCH; goto done; }
    if (h.guest_isa != guest_isa) { free(img); r = PTC_OPEN_GUEST_ISA_MISMATCH; goto done; }
    uint32_t want = ptc_crc32(0, &h, offsetof(ptc_hdr, header_crc));
    if (want != h.header_crc) { free(img); r = PTC_OPEN_CORRUPT; goto done; }
    if (h.module_off + h.module_len > (uint64_t)fsz ||
        h.record_off + h.record_len > (uint64_t)fsz ||
        h.code_off + h.code_len > (uint64_t)fsz) { free(img); r = PTC_OPEN_TRUNCATED; goto done; }
    if (ptc_crc32(0, img + h.module_off, h.module_len) != h.module_crc ||
        ptc_crc32(0, img + h.record_off, h.record_len) != h.record_crc ||
        ptc_crc32(0, img + h.code_off, h.code_len) != h.code_crc) {
        free(img); r = PTC_OPEN_CORRUPT; goto done;
    }

    c = ptc_create(h.host_isa, h.guest_isa, h.page_size);
    if (!c) { free(img); r = PTC_OPEN_IO_ERROR; goto done; }
    c->created_unix = h.created_unix;

    size_t p = h.module_off;
    for (uint32_t i = 0; i < h.n_modules; i++) {
        if (p + sizeof(ptc_mod_disk) > h.module_off + h.module_len) goto corrupt;
        ptc_mod_disk md;
        memcpy(&md, img + p, sizeof md);
        p += sizeof md;
        if (p + md.name_len > h.module_off + h.module_len) goto corrupt;
        char *nm = xrealloc(NULL, md.name_len + 1);
        memcpy(nm, img + p, md.name_len);
        nm[md.name_len] = '\0';
        p += md.name_len;
        if (c->n_mods == c->cap_mods) {
            c->cap_mods = c->cap_mods ? c->cap_mods * 2 : 8;
            c->mods = xrealloc(c->mods, c->cap_mods * sizeof *c->mods);
        }
        ptc_module *m = &c->mods[c->n_mods++];
        memset(m, 0, sizeof *m);
        m->module_id = md.module_id;
        m->size = md.size;
        m->mtime = md.mtime;
        m->content_hash = md.content_hash;
        m->name = nm;
    }

    if (h.n_records && h.record_len != (uint64_t)h.n_records * sizeof(ptc_rec_disk))
        goto corrupt;
    p = h.record_off;
    for (uint32_t i = 0; i < h.n_records; i++) {
        ptc_rec_disk rd;
        memcpy(&rd, img + p, sizeof rd);
        p += sizeof rd;
        if (ptc_crc32(0, &rd, REC_CRC_LEN) != rd.rec_crc) goto corrupt;
        if ((uint64_t)rd.code_off + rd.code_len > h.code_len) goto corrupt;
        if (c->n_recs == c->cap_recs) {
            c->cap_recs = c->cap_recs ? c->cap_recs * 2 : 64;
            c->recs = xrealloc(c->recs, c->cap_recs * sizeof *c->recs);
        }
        ptc_rec *rr = &c->recs[c->n_recs++];
        memset(rr, 0, sizeof *rr);
        rr->module_id = rd.module_id;
        rr->guest_pc = rd.guest_pc;
        rr->src_hash = rd.src_hash;
        rr->guest_len = rd.guest_len;
        rr->flags = rd.flags;
        rr->code_off = rd.code_off;
        rr->code_len = rd.code_len;
    }

    c->code_len = h.code_len;
    c->code_cap = h.code_len;
    c->code = h.code_len ? xrealloc(NULL, h.code_len) : NULL;
    if (h.code_len) memcpy(c->code, img + h.code_off, h.code_len);
    free(img);
    idx_rebuild(c);
done:
    if (f) fclose(f);
    if (why) *why = r;
    return c;

corrupt:
    free(img);
    ptc_free(c);
    c = NULL;
    r = PTC_OPEN_CORRUPT;
    goto done;
}

/* ------------------------------------------------------------ introspection */

size_t ptc_module_count(const ptc_cache *c) { return c ? c->n_mods : 0; }
size_t ptc_code_bytes(const ptc_cache *c)   { return c ? c->code_len : 0; }
uint64_t ptc_hits(const ptc_cache *c)       { return c ? c->hits : 0; }
uint64_t ptc_misses(const ptc_cache *c)     { return c ? c->misses : 0; }

size_t ptc_record_count(const ptc_cache *c)
{
    if (!c) return 0;
    size_t n = 0;
    for (size_t i = 0; i < c->n_recs; i++)
        if (!c->recs[i].dead) n++;
    return n;
}
