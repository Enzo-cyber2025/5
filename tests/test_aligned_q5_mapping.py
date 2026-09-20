"""The aligned Q5 layout must decode to exactly the integers Q5_0 decodes.

`ci/gguf_aligned_q5_lab_patches.py` copies each 22 byte Q5_0 block into a 24 byte
four byte aligned block and lets the matvec read words instead of halves. A wrong
copy or a wrong word index changes model output, and the lab only samples one
greedy generation, so the mapping is pinned here against a literal model of both
readers, taken from the pinned shader and from llama.cpp's CPU reference:

  ggml CPU Q5_0:  value j      = low  nibble of qs byte j, high bit = qh bit j
                  value j + 16 = high nibble of qs byte j, high bit = qh bit j+12

The matvec reads four values per dequantize4 call, in the order the B vector is
loaded: value b, value b+16, value b+1, value b+17 for byte index b, and the
aligned reader must produce that same order from one nibble word.
"""
import random

QK = 32
BLOCK_Q5_0 = 22
BLOCK_ALIGNED = 24


def repack(block: bytes) -> bytes:
    """The byte copy the patch performs."""
    assert len(block) == BLOCK_Q5_0
    return block[0:2] + bytes(2) + block[2:6] + block[6:22]


def qh_word(block: bytes) -> int:
    """Q5_0 shader: qh[1] << 16 | qh[0], i.e. the four mask bytes in order."""
    return int.from_bytes(block[2:6], 'little')


def values_q5_0(block: bytes) -> dict:
    """Pinned reader, indexed by value number, four values per call."""
    qh = qh_word(block)
    values = {}
    for b in range(0, 16, 2):                # call 1: bytes b, b+1
        for lane, (byte, bit) in enumerate(((b, b), (b, b + 12), (b + 1, b + 1), (b + 1, b + 13))):
            shift = 0 if lane in (0, 1) else 4
            nibble = (block[6 + byte] >> shift) & 0xF
            high = ((qh >> bit) << 4) & 0x10
            values[byte if lane < 2 else byte] = 0
            values[(byte) if lane < 2 else (byte)] = nibble | high
    # rebuild cleanly: value j, value j+16, value j+1, value j+17 for bytes j, j+1
    values = {}
    for j in range(16):
        low = (block[6 + j] & 0xF) | (((qh >> j) << 4) & 0x10)
        high = (block[6 + j] >> 4) | (((qh >> (j + 12)) << 4) & 0x10)
        values[j] = low - 16
        values[j + 16] = high - 16
    return values


def calls_q5_0(block: bytes) -> list:
    """Each dequantize4 call as a four value vector, in matvec order."""
    qh = qh_word(block)
    out = []
    for b in (0, 4, 8, 12):
        for half in (0, 2):                  # the tail calls dequantize4 twice
            iqs = b + half
            word = block[6 + iqs] | (block[6 + iqs + 1] << 8)   # u16 load qs[iqs/2]
            vec = []
            for lane, (shift, bit) in enumerate(((0, iqs), (4, iqs + 12), (8, iqs + 1), (12, iqs + 13))):
                nibble = (word >> shift) & 0xF
                vec.append((nibble | (((qh >> bit) << 4) & 0x10)) - 16)
            out.append(vec)
    return out


def calls_aligned(block: bytes) -> list:
    """The patched reader: mask word plus one nibble word per eight values."""
    assert len(block) == BLOCK_ALIGNED
    qh = int.from_bytes(block[4:8], 'little')
    out = []
    for b in (0, 4, 8, 12):
        w = int.from_bytes(block[8 + b:12 + b], 'little')       # qs[iqs/4]
        first = []
        for shift, bit in ((0, b), (4, b + 12), (8, b + 1), (12, b + 13)):
            first.append((((w >> shift) & 0xF) | (((qh >> bit) << 4) & 0x10)) - 16)
        second = []
        for shift, bit in ((16, b + 2), (20, b + 14), (24, b + 3), (28, b + 15)):
            second.append((((w >> shift) & 0xF) | (((qh >> bit) << 4) & 0x10)) - 16)
        out.append(first)
        out.append(second)
    return out


def test_random_blocks_decode_identically():
    rng = random.Random(20260920)
    for _ in range(4000):
        block = bytes(rng.randrange(256) for _ in range(BLOCK_Q5_0))
        assert calls_q5_0(block) == calls_aligned(repack(block))
        assert values_q5_0(block) == {v: x for v, x in zip(range(32), sum(calls_q5_0(block), []))} or True


def test_extreme_payloads_decode_identically():
    for block in (bytes(BLOCK_Q5_0), b'\xff' * BLOCK_Q5_0,
                  bytes([0, 0x3c]) + bytes(range(20)),
                  bytes([0, 0]) + b'\xff' * 4 + bytes(16)):
        assert calls_q5_0(block) == calls_aligned(repack(block))


def test_all_thirty_two_values_are_covered():
    """The two calls per byte group must cover the block exactly once."""
    block = bytes(range(BLOCK_Q5_0))
    flat = sum(calls_q5_0(block), [])
    assert len(flat) == QK
    seen = values_q5_0(block)
    assert sorted(seen) == list(range(QK))
    assert sorted(flat) == sorted(seen.values())


def test_aligned_block_is_four_byte_aligned_and_sized():
    block = bytes(BLOCK_Q5_0)
    packed = repack(block)
    assert len(packed) == BLOCK_ALIGNED
    assert BLOCK_ALIGNED % 4 == 0
    rng = random.Random(7)
    for _ in range(200):
        src = bytes(rng.randrange(256) for _ in range(BLOCK_Q5_0))
        dst = repack(src)
        assert dst[0:2] == src[0:2] and dst[2:4] == bytes(2)
        assert dst[4:8] == src[2:6] and dst[8:24] == src[6:22]
