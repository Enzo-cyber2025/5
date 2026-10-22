"""Pure-stdlib AES (decrypt side) for Android backups.

The tool has to work on an air-gapped host with nothing but CPython, and
``adb backup`` containers are ``AES/CBC/PKCS5Padding``. Only decryption is
needed, so this module implements just that (plus a tiny encrypt helper used by
the tests).

Checked against the FIPS-197 known answers and against ``cryptography`` in
``tests/test_flcodes_abe.py``.
"""

from __future__ import annotations

__all__ = [
    "BLOCK_SIZE",
    "expand_key",
    "decrypt_block",
    "cbc_decrypt",
    "cbc_encrypt",
    "unpad",
    "pad",
]

BLOCK_SIZE = 16

_SBOX = (
    0x63, 0x7C, 0x77, 0x7B, 0xF2, 0x6B, 0x6F, 0xC5, 0x30, 0x01, 0x67, 0x2B, 0xFE, 0xD7, 0xAB, 0x76,
    0xCA, 0x82, 0xC9, 0x7D, 0xFA, 0x59, 0x47, 0xF0, 0xAD, 0xD4, 0xA2, 0xAF, 0x9C, 0xA4, 0x72, 0xC0,
    0xB7, 0xFD, 0x93, 0x26, 0x36, 0x3F, 0xF7, 0xCC, 0x34, 0xA5, 0xE5, 0xF1, 0x71, 0xD8, 0x31, 0x15,
    0x04, 0xC7, 0x23, 0xC3, 0x18, 0x96, 0x05, 0x9A, 0x07, 0x12, 0x80, 0xE2, 0xEB, 0x27, 0xB2, 0x75,
    0x09, 0x83, 0x2C, 0x1A, 0x1B, 0x6E, 0x5A, 0xA0, 0x52, 0x3B, 0xD6, 0xB3, 0x29, 0xE3, 0x2F, 0x84,
    0x53, 0xD1, 0x00, 0xED, 0x20, 0xFC, 0xB1, 0x5B, 0x6A, 0xCB, 0xBE, 0x39, 0x4A, 0x4C, 0x58, 0xCF,
    0xD0, 0xEF, 0xAA, 0xFB, 0x43, 0x4D, 0x33, 0x85, 0x45, 0xF9, 0x02, 0x7F, 0x50, 0x3C, 0x9F, 0xA8,
    0x51, 0xA3, 0x40, 0x8F, 0x92, 0x9D, 0x38, 0xF5, 0xBC, 0xB6, 0xDA, 0x21, 0x10, 0xFF, 0xF3, 0xD2,
    0xCD, 0x0C, 0x13, 0xEC, 0x5F, 0x97, 0x44, 0x17, 0xC4, 0xA7, 0x7E, 0x3D, 0x64, 0x5D, 0x19, 0x73,
    0x60, 0x81, 0x4F, 0xDC, 0x22, 0x2A, 0x90, 0x88, 0x46, 0xEE, 0xB8, 0x14, 0xDE, 0x5E, 0x0B, 0xDB,
    0xE0, 0x32, 0x3A, 0x0A, 0x49, 0x06, 0x24, 0x5C, 0xC2, 0xD3, 0xAC, 0x62, 0x91, 0x95, 0xE4, 0x79,
    0xE7, 0xC8, 0x37, 0x6D, 0x8D, 0xD5, 0x4E, 0xA9, 0x6C, 0x56, 0xF4, 0xEA, 0x65, 0x7A, 0xAE, 0x08,
    0xBA, 0x78, 0x25, 0x2E, 0x1C, 0xA6, 0xB4, 0xC6, 0xE8, 0xDD, 0x74, 0x1F, 0x4B, 0xBD, 0x8B, 0x8A,
    0x70, 0x3E, 0xB5, 0x66, 0x48, 0x03, 0xF6, 0x0E, 0x61, 0x35, 0x57, 0xB9, 0x86, 0xC1, 0x1D, 0x9E,
    0xE1, 0xF8, 0x98, 0x11, 0x69, 0xD9, 0x8E, 0x94, 0x9B, 0x1E, 0x87, 0xE9, 0xCE, 0x55, 0x28, 0xDF,
    0x8C, 0xA1, 0x89, 0x0D, 0xBF, 0xE6, 0x42, 0x68, 0x41, 0x99, 0x2D, 0x0F, 0xB0, 0x54, 0xBB, 0x16,
)

_INV_SBOX = [0] * 256
for _index, _value in enumerate(_SBOX):
    _INV_SBOX[_value] = _index
_INV_SBOX = tuple(_INV_SBOX)


def _xtime(value: int) -> int:
    value <<= 1
    if value & 0x100:
        value ^= 0x11B
    return value & 0xFF


def _mul(a: int, b: int) -> int:
    result = 0
    while b:
        if b & 1:
            result ^= a
        a = _xtime(a)
        b >>= 1
    return result


# multiplication by the fixed inverse-MixColumns coefficients
_MUL9 = tuple(_mul(value, 9) for value in range(256))
_MUL11 = tuple(_mul(value, 11) for value in range(256))
_MUL13 = tuple(_mul(value, 13) for value in range(256))
_MUL14 = tuple(_mul(value, 14) for value in range(256))


def _rot_word(word: list) -> list:
    return word[1:] + word[:1]


def _sub_word(word: list) -> list:
    return [_SBOX[byte] for byte in word]


_RCON = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36)


def expand_key(key: bytes) -> list:
    """Return the round keys as a list of 16-byte ``bytes`` objects."""
    if len(key) not in (16, 24, 32):
        raise ValueError("AES key must be 16, 24 or 32 bytes")
    round_count = len(key) // 4 + 6
    words = [list(key[index:index + 4]) for index in range(0, len(key), 4)]
    for index in range(len(key) // 4, 4 * (round_count + 1)):
        temp = list(words[index - 1])
        if index % (len(key) // 4) == 0:
            temp = _sub_word(_rot_word(temp))
            temp[0] ^= _RCON[index // (len(key) // 4) - 1]
        elif len(key) == 32 and index % 8 == 4:
            temp = _sub_word(temp)
        words.append([a ^ b for a, b in zip(words[index - (len(key) // 4)], temp)])
    return [
        bytes(sum(words[4 * round_index: 4 * round_index + 4], []))
        for round_index in range(round_count + 1)
    ]


def decrypt_block(block: bytes, round_keys: list) -> bytes:
    """Decrypt one 16-byte block (FIPS-197 §5.3, inverse cipher)."""
    if len(block) != BLOCK_SIZE:
        raise ValueError("AES block must be 16 bytes")
    state = [value ^ key for value, key in zip(block, round_keys[-1])]
    for round_index in range(len(round_keys) - 2, -1, -1):
        # inverse ShiftRows (row r shifted right by r)
        state = [
            state[0], state[13], state[10], state[7],
            state[4], state[1], state[14], state[11],
            state[8], state[5], state[2], state[15],
            state[12], state[9], state[6], state[3],
        ]
        state = [_INV_SBOX[value] for value in state]
        state = [value ^ key for value, key in zip(state, round_keys[round_index])]
        if round_index:
            mixed = []
            for column in range(4):
                a0, a1, a2, a3 = state[4 * column: 4 * column + 4]
                mixed += [
                    _MUL14[a0] ^ _MUL11[a1] ^ _MUL13[a2] ^ _MUL9[a3],
                    _MUL9[a0] ^ _MUL14[a1] ^ _MUL11[a2] ^ _MUL13[a3],
                    _MUL13[a0] ^ _MUL9[a1] ^ _MUL14[a2] ^ _MUL11[a3],
                    _MUL11[a0] ^ _MUL13[a1] ^ _MUL9[a2] ^ _MUL14[a3],
                ]
            state = mixed
    return bytes(state)


def cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    """AES-CBC decryption (the data is not unpadded)."""
    if len(iv) != BLOCK_SIZE:
        raise ValueError("AES-CBC IV must be 16 bytes")
    if len(data) % BLOCK_SIZE:
        raise ValueError("AES-CBC data must be a multiple of 16 bytes")
    round_keys = expand_key(key)
    out = bytearray()
    previous = iv
    for offset in range(0, len(data), BLOCK_SIZE):
        block = data[offset:offset + BLOCK_SIZE]
        plain = decrypt_block(block, round_keys)
        out += bytes(a ^ b for a, b in zip(plain, previous))
        previous = block
    return bytes(out)


def _encrypt_block(block: bytes, round_keys: list) -> bytes:
    """Encrypt one block (only used to build fixtures in the tests)."""
    state = [value ^ key for value, key in zip(block, round_keys[0])]
    for round_index in range(1, len(round_keys)):
        state = [_SBOX[value] for value in state]
        state = [
            state[0], state[5], state[10], state[15],
            state[4], state[9], state[14], state[3],
            state[8], state[13], state[2], state[7],
            state[12], state[1], state[6], state[11],
        ]
        if round_index != len(round_keys) - 1:
            mixed = []
            for column in range(4):
                a0, a1, a2, a3 = state[4 * column: 4 * column + 4]
                mixed += [
                    _mul(a0, 2) ^ _mul(a1, 3) ^ a2 ^ a3,
                    a0 ^ _mul(a1, 2) ^ _mul(a2, 3) ^ a3,
                    a0 ^ a1 ^ _mul(a2, 2) ^ _mul(a3, 3),
                    _mul(a0, 3) ^ a1 ^ a2 ^ _mul(a3, 2),
                ]
            state = mixed
        state = [value ^ key for value, key in zip(state, round_keys[round_index])]
    return bytes(state)


def cbc_encrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    """AES-CBC encryption (the data must already be padded)."""
    if len(iv) != BLOCK_SIZE or len(data) % BLOCK_SIZE:
        raise ValueError("AES-CBC needs a 16-byte IV and block-aligned data")
    round_keys = expand_key(key)
    out = bytearray()
    previous = iv
    for offset in range(0, len(data), BLOCK_SIZE):
        block = bytes(a ^ b for a, b in zip(data[offset:offset + BLOCK_SIZE], previous))
        previous = _encrypt_block(block, round_keys)
        out += previous
    return bytes(out)


def pad(data: bytes, block_size: int = BLOCK_SIZE) -> bytes:
    """PKCS#5/PKCS#7 padding."""
    amount = block_size - (len(data) % block_size)
    return data + bytes([amount]) * amount


def unpad(data: bytes, block_size: int = BLOCK_SIZE) -> bytes:
    """Strip PKCS#5/PKCS#7 padding, rejecting a malformed tail."""
    if not data or len(data) % block_size:
        raise ValueError("bad padded length")
    amount = data[-1]
    if not 1 <= amount <= block_size or data[-amount:] != bytes([amount]) * amount:
        raise ValueError("bad padding (wrong key or password?)")
    return data[:-amount]
