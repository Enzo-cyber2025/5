"""Pure-stdlib ChaCha20-Poly1305 (RFC 8439) and scrypt key derivation.

The tool has to run on an air-gapped host with nothing but CPython, so no
third-party crypto dependency is allowed. ChaCha20-Poly1305 is implemented from
the RFC text; the AEAD is used as encrypt-then-MAC with the scrypt-derived key
split in half (one half for the cipher, one for the MAC key of the whole
container), which keeps a single file format and one passphrase.

The implementation is cross-checked against the reference ``cryptography``
implementation and the RFC 8439 known-answer vectors (see tests/).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import struct

__all__ = [
    "chacha20_block",
    "chacha20_xor",
    "poly1305_mac",
    "aead_encrypt",
    "aead_decrypt",
    "derive_key",
    "random_bytes",
]

_MASK32 = 0xFFFFFFFF
_SIGMA = b"expand 32-byte k"
_NONCE_SIZE = 12
_TAG_SIZE = 16


def random_bytes(size: int) -> bytes:
    """Return ``size`` cryptographically secure random bytes."""
    return os.urandom(size)


def _rotl(value: int, count: int) -> int:
    return ((value << count) & _MASK32) | (value >> (32 - count))


def _quarter_round(state: list, a: int, b: int, c: int, d: int) -> None:
    state[a] = (state[a] + state[b]) & _MASK32
    state[d] = _rotl(state[d] ^ state[a], 16)
    state[c] = (state[c] + state[d]) & _MASK32
    state[b] = _rotl(state[b] ^ state[c], 12)
    state[a] = (state[a] + state[b]) & _MASK32
    state[d] = _rotl(state[d] ^ state[a], 8)
    state[c] = (state[c] + state[d]) & _MASK32
    state[b] = _rotl(state[b] ^ state[c], 7)


def chacha20_block(key: bytes, counter: int, nonce: bytes) -> bytes:
    """Return one 64-byte ChaCha20 keystream block."""
    if len(key) != 32:
        raise ValueError("chacha20 key must be 32 bytes")
    if len(nonce) != _NONCE_SIZE:
        raise ValueError("chacha20 nonce must be 12 bytes")
    state = (
        list(struct.unpack("<4I", _SIGMA))
        + list(struct.unpack("<8I", key))
        + [counter & _MASK32]
        + list(struct.unpack("<3I", nonce))
    )
    working = state[:]
    for _ in range(10):
        _quarter_round(working, 0, 4, 8, 12)
        _quarter_round(working, 1, 5, 9, 13)
        _quarter_round(working, 2, 6, 10, 14)
        _quarter_round(working, 3, 7, 11, 15)
        _quarter_round(working, 0, 5, 10, 15)
        _quarter_round(working, 1, 6, 11, 12)
        _quarter_round(working, 2, 7, 8, 13)
        _quarter_round(working, 3, 4, 9, 14)
    out = [(working[i] + state[i]) & _MASK32 for i in range(16)]
    return struct.pack("<16I", *out)


def chacha20_xor(key: bytes, nonce: bytes, data: bytes, counter: int = 1) -> bytes:
    """Encrypt/decrypt ``data`` with ChaCha20 (RFC 8439 counter starts at 1)."""
    out = bytearray()
    for index in range(0, len(data), 64):
        block = chacha20_block(key, counter + index // 64, nonce)
        chunk = data[index : index + 64]
        out.extend(a ^ b for a, b in zip(chunk, block))
    return bytes(out)


def poly1305_mac(message: bytes, key: bytes) -> bytes:
    """Return the 16-byte Poly1305 tag of ``message`` under ``key``."""
    if len(key) != 32:
        raise ValueError("poly1305 key must be 32 bytes")
    r_bytes = bytearray(key[:16])
    r_bytes[3] &= 15
    r_bytes[7] &= 15
    r_bytes[11] &= 15
    r_bytes[15] &= 15
    r_bytes[4] &= 252
    r_bytes[8] &= 252
    r_bytes[12] &= 252
    r = int.from_bytes(bytes(r_bytes), "little")
    s = int.from_bytes(key[16:32], "little")

    prime = (1 << 130) - 5
    acc = 0
    for index in range(0, len(message), 16):
        block = message[index : index + 16]
        # The trailing 0x01 byte is the Poly1305 "high bit" marker (2^128).
        number = int.from_bytes(block + b"\x01", "little")
        acc = ((acc + number) * r) % prime
    acc = (acc + s) % (1 << 128)
    return acc.to_bytes(16, "little")


def _pad16(data: bytes) -> bytes:
    return b"\x00" * ((16 - len(data) % 16) % 16)


def aead_encrypt(key: bytes, nonce: bytes, plaintext: bytes, aad: bytes = b"") -> bytes:
    """Return ``ciphertext || tag`` for the RFC 8439 AEAD."""
    if len(key) != 32:
        raise ValueError("aead key must be 32 bytes")
    if len(nonce) != _NONCE_SIZE:
        raise ValueError("aead nonce must be 12 bytes")
    one_time_key = chacha20_block(key, 0, nonce)[:32]
    ciphertext = chacha20_xor(key, nonce, plaintext, counter=1)
    mac_data = (
        aad
        + _pad16(aad)
        + ciphertext
        + _pad16(ciphertext)
        + struct.pack("<Q", len(aad))
        + struct.pack("<Q", len(ciphertext))
    )
    return ciphertext + poly1305_mac(mac_data, one_time_key)


def aead_decrypt(key: bytes, nonce: bytes, data: bytes, aad: bytes = b"") -> bytes:
    """Verify and decrypt ``ciphertext || tag``; raise ValueError on tampering."""
    if len(data) < _TAG_SIZE:
        raise ValueError("ciphertext too short")
    ciphertext, tag = data[:-_TAG_SIZE], data[-_TAG_SIZE:]
    one_time_key = chacha20_block(key, 0, nonce)[:32]
    mac_data = (
        aad
        + _pad16(aad)
        + ciphertext
        + _pad16(ciphertext)
        + struct.pack("<Q", len(aad))
        + struct.pack("<Q", len(ciphertext))
    )
    expected = poly1305_mac(mac_data, one_time_key)
    if not hmac.compare_digest(expected, tag):
        raise ValueError("authentication failed: wrong passphrase or tampered file")
    return chacha20_xor(key, nonce, ciphertext, counter=1)


def derive_key(
    passphrase: str,
    salt: bytes,
    n: int = 16384,
    r: int = 8,
    p: int = 1,
    dklen: int = 64,
) -> bytes:
    """Derive ``dklen`` bytes from ``passphrase`` with scrypt (RFC 7914).

    ``dklen`` is 64 so the caller can split the result into an encryption key
    and an independent MAC key.
    """
    return hashlib.scrypt(
        passphrase.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=dklen,
        maxmem=256 * 1024 * 1024,
    )
