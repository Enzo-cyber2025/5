/* x86-64 length/structure decoder. See x86_decode.h for the contract. */
#include "x86_decode.h"

#include <string.h>

/* Opcode table encoding.
 *
 * Every entry is (immcode << 1) | has_modrm, except four sentinels. Spelling the
 * whole map out as data rather than deriving it from patterns costs 512 bytes and
 * buys auditability: each row can be checked against the manual independently,
 * and a mistake shows up as one wrong instruction instead of a wrong rule that
 * silently corrupts dozens.
 */
#define INV   0xFFu          /* illegal in 64-bit mode */
#define ESC0F 0xFEu          /* base map -> 0F map */
#define ESC38 0xFDu          /* 0F map -> 0F 38 map */
#define ESC3A 0xFCu          /* 0F map -> 0F 3A map */

/* immcode values, before the <<1 */
enum {
    I_NONE = 0, I_B = 1, I_W = 2, I_Z = 3,   /* imm8, imm16, imm32(16 with 66) */
    I_R = 4,                                  /* MOV r: imm64 with REX.W */
    I_ENTER = 5,                              /* imm16 + imm8 */
    I_R8 = 6, I_RZ = 7,                       /* rel8, rel32(16 with 66) */
    I_MOFFS = 8, I_GRP3 = 9                   /* moffs, imm depends on reg */
};

static const unsigned char base_map[256] = {
    /* 00 */ 0x01,0x01,0x01,0x01,0x02,0x06,INV,INV, 0x01,0x01,0x01,0x01,0x02,0x06,INV,ESC0F,
    /* 10 */ 0x01,0x01,0x01,0x01,0x02,0x06,INV,INV, 0x01,0x01,0x01,0x01,0x02,0x06,INV,INV,
    /* 20 */ 0x01,0x01,0x01,0x01,0x02,0x06,INV,INV, 0x01,0x01,0x01,0x01,0x02,0x06,INV,INV,
    /* 30 */ 0x01,0x01,0x01,0x01,0x02,0x06,INV,INV, 0x01,0x01,0x01,0x01,0x02,0x06,INV,INV,
    /* 40 */ INV,INV,INV,INV,INV,INV,INV,INV, INV,INV,INV,INV,INV,INV,INV,INV,
    /* 50 */ 0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00, 0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,
    /* 60 */ INV,INV,INV,0x01,INV,INV,INV,INV, 0x06,0x07,0x02,0x03,0x00,0x00,0x00,0x00,
    /* 70 */ 0x0C,0x0C,0x0C,0x0C,0x0C,0x0C,0x0C,0x0C, 0x0C,0x0C,0x0C,0x0C,0x0C,0x0C,0x0C,0x0C,
    /* 80 */ 0x03,0x07,INV,0x03,0x01,0x01,0x01,0x01, 0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01,
    /* 90 */ 0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00, 0x00,0x00,INV,0x00,0x00,0x00,0x00,0x00,
    /* A0 */ 0x10,0x10,0x10,0x10,0x00,0x00,0x00,0x00, 0x02,0x06,0x00,0x00,0x00,0x00,0x00,0x00,
    /* B0 */ 0x02,0x02,0x02,0x02,0x02,0x02,0x02,0x02, 0x08,0x08,0x08,0x08,0x08,0x08,0x08,0x08,
    /* C0 */ 0x03,0x03,0x04,0x00,INV,INV,0x03,0x07, 0x0A,0x00,0x04,0x00,0x00,0x02,INV,0x00,
    /* D0 */ 0x01,0x01,0x01,0x01,INV,INV,INV,0x00, 0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01,
    /* E0 */ 0x0C,0x0C,0x0C,0x0C,0x02,0x02,0x02,0x02, 0x0E,0x0E,INV,0x0C,0x00,0x00,0x00,0x00,
    /* F0 */ INV,0x00,INV,INV,0x00,0x00,0x13,0x13, 0x00,0x00,0x00,0x00,0x00,0x00,0x01,0x01
};

static const unsigned char map_0f[256] = {
    /* 00 */ 0x01,0x01,0x01,0x01,INV,0x00,0x00,0x00, 0x00,0x00,INV,0x00,INV,0x01,0x00,0x03,
    /* 10 */ 0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01, 0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01,
    /* 20 */ 0x01,0x01,0x01,0x01,0x01,INV,INV,INV, 0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01,
    /* 30 */ 0x00,0x00,0x00,0x00,0x00,0x00,INV,0x00, ESC38,INV,ESC3A,INV,INV,INV,INV,INV,
    /* 40 */ 0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01, 0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01,
    /* 50 */ 0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01, 0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01,
    /* 60 */ 0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01, 0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01,
    /* 70 */ 0x03,0x03,0x03,0x03,0x01,0x01,0x01,0x00, 0x01,0x01,INV,INV,0x01,0x01,0x01,0x01,
    /* 80 */ 0x0E,0x0E,0x0E,0x0E,0x0E,0x0E,0x0E,0x0E, 0x0E,0x0E,0x0E,0x0E,0x0E,0x0E,0x0E,0x0E,
    /* 90 */ 0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01, 0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01,
    /* A0 */ 0x00,0x00,0x00,0x01,0x03,0x01,INV,INV, 0x00,0x00,0x00,0x01,0x03,0x01,0x01,0x01,
    /* B0 */ 0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01, 0x01,0x01,0x03,0x01,0x01,0x01,0x01,0x01,
    /* C0 */ 0x01,0x01,0x03,0x01,0x03,0x03,0x03,0x01, 0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,
    /* D0 */ 0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01, 0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01,
    /* E0 */ 0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01, 0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01,
    /* F0 */ 0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01, 0x01,0x01,0x01,0x01,0x01,0x01,0x01,INV
};

const char *x86_status_name(x86_status s)
{
    switch (s) {
    case X86_OK:          return "OK";
    case X86_INVALID:     return "INVALID";
    case X86_UNSUPPORTED: return "UNSUPPORTED";
    case X86_NEED_MORE:   return "NEED_MORE";
    }
    return "?";
}

/* Cursor: every fetch is bounds-checked, and the first short read is latched so
 * a later fetch cannot silently read past the end. */
typedef struct {
    const uint8_t *p;
    size_t n, pos;
    int short_read;
} cur;

static uint8_t c8(cur *c)
{
    if (c->pos >= c->n) { c->short_read = 1; return 0; }
    return c->p[c->pos++];
}

static uint16_t c16(cur *c) { uint16_t a = c8(c); return (uint16_t)(a | ((uint16_t)c8(c) << 8)); }
static uint32_t c32(cur *c)
{
    uint32_t a = c8(c); a |= (uint32_t)c8(c) << 8;
    a |= (uint32_t)c8(c) << 16; a |= (uint32_t)c8(c) << 24;
    return a;
}
static uint64_t c64(cur *c)
{
    uint64_t lo = c32(c), hi = c32(c);
    return lo | (hi << 32);
}

static void fail(x86_insn *o, x86_status s)
{
    o->status = s;
    o->len = 0;
}

/* Control-flow and privilege classification. A translator splits blocks on
 * anything that leaves the block, so getting these bits right matters more than
 * getting mnemonics right. */
static void classify(x86_insn *o)
{
    uint32_t f = 0;
    if (o->map == 0) {
        uint8_t op = o->op[0];
        if (op >= 0x70 && op <= 0x7F) f |= X86F_BRANCH | X86F_COND;
        else if (op == 0xEB)          f |= X86F_BRANCH;
        else if (op == 0xE9)          f |= X86F_BRANCH;
        else if (op == 0xE8)          f |= X86F_BRANCH | X86F_CALL;
        else if (op >= 0xE0 && op <= 0xE3) f |= X86F_BRANCH | X86F_COND;
        else if (op == 0xC3 || op == 0xCB) f |= X86F_BRANCH | X86F_RET;
        else if (op == 0xC2 || op == 0xCA) f |= X86F_BRANCH | X86F_RET;
        else if (op == 0xFF) {
            switch (o->reg) {
            case 2: f |= X86F_BRANCH | X86F_CALL | X86F_INDIRECT; break;
            case 3: f |= X86F_BRANCH | X86F_CALL | X86F_INDIRECT; break;
            case 4: f |= X86F_BRANCH | X86F_INDIRECT; break;
            case 5: f |= X86F_BRANCH | X86F_INDIRECT; break;
            default: break;
            }
        } else if (op == 0x0F) { /* handled below via map */ }
    } else if (o->map == 1) {
        uint8_t op = o->op[1];
        if (op >= 0x80 && op <= 0x8F) f |= X86F_BRANCH | X86F_COND;
        else if (op == 0x05)          f |= X86F_BRANCH;             /* syscall */
        else if (op == 0x34 || op == 0x35) f |= X86F_BRANCH;         /* sysenter/exit */
        else if (op == 0x0B)          f |= X86F_BRANCH | X86F_RET;   /* UD2 traps */
        else if (op == 0x01 || op == 0x06 || op == 0x07 || op == 0x08 ||
                 op == 0x09 || (op >= 0x30 && op <= 0x33) || op == 0x37)
            f |= X86F_PRIVILEGED;
    }
    if (o->lock) f |= X86F_LOCK;
    if (o->pf2 || o->pf3) f |= X86F_REP;
    o->flags |= f;
}

static const char *mnemonic(const x86_insn *o)
{
    static const char *const arith[8] = {
        "add", "or", "adc", "sbb", "and", "sub", "xor", "cmp"
    };
    static const char *const jcc8[16] = {
        "jo","jno","jb","jae","je","jne","jbe","ja","js","jns","jp","jnp","jl","jge","jle","jg"
    };
    if (o->map == 0) {
        uint8_t op = o->op[0];
        if (op < 0x40 && (op & 7) <= 5) return arith[op >> 3];
        if (op >= 0x50 && op <= 0x57) return "push";
        if (op >= 0x58 && op <= 0x5F) return "pop";
        if (op >= 0x70 && op <= 0x7F) return jcc8[op & 0xF];
        if (op >= 0x88 && op <= 0x8B) return "mov";
        if (op == 0x8D) return "lea";
        if (op == 0x84 || op == 0x85) return "test";
        if (op == 0x86 || op == 0x87) return "xchg";
        if (op == 0x90) return o->rex_b ? "xchg" : "nop";
        if (op >= 0x91 && op <= 0x97) return "xchg";
        if (op == 0x98) return "cdqe";
        if (op == 0x99) return "cqo";
        if (op >= 0xB0 && op <= 0xBF) return "mov";
        if (op == 0xC6 || op == 0xC7) return "mov";
        if (op == 0xC3) return "ret";
        if (op == 0xC2) return "ret";
        if (op == 0xC9) return "leave";
        if (op == 0xCC) return "int3";
        if (op == 0xCD) return "int";
        if (op == 0xE8) return "call";
        if (op == 0xE9) return "jmp";
        if (op == 0xEB) return "jmp";
        if (op == 0xF4) return "hlt";
        if (op == 0x63) return "movsxd";
        if (op == 0x69 || op == 0x6B) return "imul";
        if (op == 0x80 || op == 0x81 || op == 0x83) {
            static const char *const g1[8] = {"add","or","adc","sbb","and","sub","xor","cmp"};
            return g1[o->reg & 7];
        }
        if (op == 0xC0 || op == 0xC1 || op == 0xD0 || op == 0xD1 ||
            op == 0xD2 || op == 0xD3) {
            static const char *const g2[8] =
                {"rol","ror","rcl","rcr","shl","shr","shl","sar"};
            return g2[o->reg & 7];
        }
        if (op == 0xF6 || op == 0xF7) {
            static const char *const g3[8] =
                {"test","test","not","neg","mul","imul","div","idiv"};
            return g3[o->reg & 7];
        }
        if (op == 0xFE) return o->reg == 0 ? "inc" : "dec";
        if (op == 0xFF) {
            static const char *const g5[8] =
                {"inc","dec","call","callf","jmp","jmpf","push",NULL};
            return g5[o->reg & 7];
        }
        return NULL;
    }
    if (o->map == 1) {
        uint8_t op = o->op[1];
        static const char *const jcc32[16] = {
            "jo","jno","jb","jae","je","jne","jbe","ja","js","jns","jp","jnp","jl","jge","jle","jg"
        };
        static const char *const setcc[16] = {
            "seto","setno","setb","setae","sete","setne","setbe","seta",
            "sets","setns","setp","setnp","setl","setge","setle","setg"
        };
        static const char *const cmov[16] = {
            "cmovo","cmovno","cmovb","cmovae","cmove","cmovne","cmovbe","cmova",
            "cmovs","cmovns","cmovp","cmovnp","cmovl","cmovge","cmovle","cmovg"
        };
        if (op >= 0x80 && op <= 0x8F) return jcc32[op & 0xF];
        if (op >= 0x90 && op <= 0x9F) return setcc[op & 0xF];
        if (op >= 0x40 && op <= 0x4F) return cmov[op & 0xF];
        if (op == 0x05) return "syscall";
        if (op == 0x0B) return "ud2";
        if (op == 0x1E) return "nop";          /* endbr64 lives in this group */
        if (op == 0x1F) return "nop";
        if (op == 0xA2) return "cpuid";
        if (op == 0x31) return "rdtsc";
        if (op == 0xAF) return "imul";
        if (op == 0xB6 || op == 0xB7) return "movzx";
        if (op == 0xBE || op == 0xBF) return "movsx";
        if (op == 0xBC) return "bsf";
        if (op == 0xBD) return "bsr";
        if (op == 0xB8) return "popcnt";
        if (op == 0xC0 || op == 0xC1) return "xadd";
        if (op == 0xC8 || op == 0xC9) return "bswap";
        if (op >= 0xCA && op <= 0xCF) return "bswap";
        if (op == 0x77) return "emms";
        if (op == 0xA4 || op == 0xAC) return op == 0xA4 ? "shld" : "shrd";
        if (op == 0xA5 || op == 0xAD) return op == 0xA5 ? "shld" : "shrd";
        if (op == 0xA3) return "bt";
        if (op == 0xAB) return "bts";
        if (op == 0xB3) return "btr";
        if (op == 0xBB) return "btc";
        if (op == 0xBA) {
            static const char *const g8[8] =
                {NULL,NULL,NULL,NULL,"bt","bts","btr","btc"};
            return g8[o->reg & 7];
        }
        return NULL;                            /* length known, semantics not lifted */
    }
    if (o->map == 2) return NULL;               /* 0F 38: lengths only for now */
    return NULL;                                /* 0F 3A */
}

x86_status x86_decode(const uint8_t *buf, size_t buflen, uint64_t pc, x86_insn *out)
{
    if (!buf || !out)
        return X86_INVALID;
    memset(out, 0, sizeof *out);
    out->status = X86_OK;

    cur c = { buf, buflen, 0, 0 };

    /* ---- prefixes ---- */
    int rex_seen = 0;
    for (;;) {
        if (c.pos >= c.n) { fail(out, X86_NEED_MORE); return out->status; }
        uint8_t b = buf[c.pos];
        int consumed = 1;
        switch (b) {
        case 0x66:
            out->p66 = 1;
            /* A REX before 0x66 is ignored: REX must be the last prefix. */
            if (rex_seen) { out->rex = 0; out->rex_w = out->rex_r = out->rex_x = out->rex_b = 0; }
            break;
        case 0x67:
            /* 32-bit addressing changes the displacement rules; refusing beats
             * returning a length computed under the wrong rule. */
            out->p67 = 1;
            fail(out, X86_UNSUPPORTED);
            return out->status;
        case 0xF0: out->lock = 1; break;
        case 0xF2: out->pf2 = 1; break;
        case 0xF3: out->pf3 = 1; break;
        case 0x26: case 0x2E: case 0x36: case 0x3E: case 0x64: case 0x65:
            out->seg = b;
            break;
        default:
            if ((b & 0xF0) == 0x40) {           /* REX */
                out->rex = b;
                out->rex_w = (b >> 3) & 1;
                out->rex_r = (b >> 2) & 1;
                out->rex_x = (b >> 1) & 1;
                out->rex_b = (b >> 0) & 1;
                rex_seen = 1;
                break;
            }
            consumed = 0;
            break;
        }
        if (!consumed)
            break;
        c.pos++;
        if (c.pos > 14) {                       /* 15-byte cap on the whole insn */
            fail(out, X86_INVALID);
            return out->status;
        }
    }
    if (c.short_read) { fail(out, X86_NEED_MORE); return out->status; }

    /* ---- opcode ---- */
    uint8_t b0 = c8(&c);
    if (c.short_read) { fail(out, X86_NEED_MORE); return out->status; }
    unsigned char ent;
    if (b0 == 0x0F) {
        out->op[0] = 0x0F;
        uint8_t b1 = c8(&c);
        if (c.short_read) { fail(out, X86_NEED_MORE); return out->status; }
        out->op[1] = b1;
        out->op_len = 2;
        if (b1 == 0x38) {
            uint8_t b2 = c8(&c);
            if (c.short_read) { fail(out, X86_NEED_MORE); return out->status; }
            out->op[2] = b2;
            out->op_len = 3;
            out->map = 2;
            /* Every 0F 38 encoding is ModRM with no immediate. */
            ent = 0x01;
        } else if (b1 == 0x3A) {
            uint8_t b2 = c8(&c);
            if (c.short_read) { fail(out, X86_NEED_MORE); return out->status; }
            out->op[2] = b2;
            out->op_len = 3;
            out->map = 3;
            /* Every 0F 3A encoding is ModRM plus imm8. */
            ent = 0x03;
        } else {
            out->map = 1;
            ent = map_0f[b1];
        }
    } else {
        out->op[0] = b0;
        out->op_len = 1;
        out->map = 0;
        ent = base_map[b0];
    }

    /* VEX and EVEX reuse the LES/LDS/BOUND slots, so this must be tested before
     * the table: in 64-bit mode they are legal encodings this decoder does not
     * model yet (UNSUPPORTED), not illegal ones (INVALID). Conflating the two
     * would make a caller abort a block that it should have interpreted. */
    if (out->op_len == 1 && (b0 == 0xC4 || b0 == 0xC5 || b0 == 0x62)) {
        fail(out, X86_UNSUPPORTED);
        return out->status;
    }
    if (ent == INV) { fail(out, X86_INVALID); return out->status; }
    if (ent == ESC0F || ent == ESC38 || ent == ESC3A) {
        fail(out, X86_INVALID);                 /* escapes already consumed above */
        return out->status;
    }

    unsigned immcode = ent >> 1;
    out->has_modrm = ent & 1;

    /* ---- ModRM / SIB / displacement ---- */
    if (out->has_modrm) {
        out->modrm = c8(&c);
        if (c.short_read) { fail(out, X86_NEED_MORE); return out->status; }
        out->mod = (out->modrm >> 6) & 3;
        out->reg = (out->modrm >> 3) & 7;
        out->rm  = out->modrm & 7;

        if (out->mod != 3 && out->rm == 4) {
            out->has_sib = 1;
            out->sib = c8(&c);
            if (c.short_read) { fail(out, X86_NEED_MORE); return out->status; }
            out->sib_scale = (out->sib >> 6) & 3;
            out->sib_index = (out->sib >> 3) & 7;
            out->sib_base  = out->sib & 7;
        }

        if (out->mod == 0) {
            if (out->has_sib && out->sib_base == 5) {
                out->disp_len = 4;              /* disp32, no base register */
            } else if (!out->has_sib && out->rm == 5) {
                out->disp_len = 4;              /* RIP-relative in 64-bit mode */
                out->flags |= X86F_RIP_REL;
            } else {
                out->disp_len = 0;
            }
        } else if (out->mod == 1) {
            out->disp_len = 1;
        } else if (out->mod == 2) {
            out->disp_len = 4;
        } else {
            out->disp_len = 0;                  /* mod 3: register direct */
        }

        if (out->disp_len == 1) {
            uint8_t d = c8(&c);
            if (c.short_read) { fail(out, X86_NEED_MORE); return out->status; }
            out->disp = (int32_t)(int8_t)d;
        } else if (out->disp_len == 4) {
            uint32_t d = c32(&c);
            if (c.short_read) { fail(out, X86_NEED_MORE); return out->status; }
            out->disp = (int32_t)d;
        }
    }

    /* ---- immediate ---- */
    int opsz16 = out->p66;                      /* 0x66 narrows Iz from 32 to 16 */
    switch (immcode) {
    case I_NONE: out->imm_len = 0; break;
    case I_B:    out->imm_len = 1; out->imm = c8(&c); break;
    case I_W:    out->imm_len = 2; out->imm = c16(&c); break;   /* RET/RETF imm16 */
    /* Whether an arithmetic immediate is sign-extended depends on the opcode
     * (GRP1 /3 extends, MOV r8,imm8 does not, PUSH Iz does). Deciding that
     * here would duplicate per-opcode semantics in the length decoder, so this
     * layer reports raw bits and leaves extension to the lifter. Only rel8 and
     * rel32 are inherently signed displacements, and those are extended. */
    case I_Z:    out->imm_len = opsz16 ? 2 : 4;
                 out->imm = opsz16 ? c16(&c) : c32(&c);
                 break;
    case I_R:
        /* MOV r64, imm64 only when REX.W; otherwise r32/r16 immediate. */
        if (out->rex_w) { out->imm_len = 8; out->imm = c64(&c); }
        else if (opsz16) { out->imm_len = 2; out->imm = c16(&c); }
        else { out->imm_len = 4; out->imm = c32(&c); }
        break;
    case I_ENTER: out->imm_len = 3; out->imm = c16(&c) | ((uint64_t)c8(&c) << 16); break;
    case I_R8:   out->imm_len = 1; out->imm = (uint64_t)(int64_t)(int8_t)c8(&c);
                 out->imm_signed = 1; break;
    case I_RZ:   out->imm_len = opsz16 ? 2 : 4;
                 out->imm = opsz16 ? (uint64_t)(int64_t)(int16_t)c16(&c)
                                   : (uint64_t)(int64_t)(int32_t)c32(&c);
                 out->imm_signed = 1;
                 break;
    case I_MOFFS: out->imm_len = 8; out->imm = c64(&c); break;
    case I_GRP3:
        /* GRP3: only TEST (reg 0 and 1) carries an immediate. NOT/NEG/MUL/IMUL/
         * DIV/IDIV do not, and assuming one would over-read by up to 4 bytes. */
        if ((out->reg & 7) < 2) {
            if (out->op[0] == 0xF6) { out->imm_len = 1; out->imm = c8(&c); }
            else if (opsz16) { out->imm_len = 2; out->imm = c16(&c); }
            else { out->imm_len = 4; out->imm = c32(&c); }
        } else {
            out->imm_len = 0;
        }
        break;
    default:
        fail(out, X86_UNSUPPORTED);
        return out->status;
    }
    if (c.short_read) { fail(out, X86_NEED_MORE); return out->status; }

    out->len = (uint8_t)c.pos;
    if (out->len == 0 || out->len > 15) {
        fail(out, X86_INVALID);
        return out->status;
    }

    if (out->flags & X86F_RIP_REL)
        out->rip_rel_target = pc + out->len + (uint64_t)(int64_t)out->disp;

    classify(out);
    out->mnemonic = mnemonic(out);
    out->status = X86_OK;
    return X86_OK;
}
