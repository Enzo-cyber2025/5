"""Correct token-budget completion in the pinned JNI, never override errors.

Only EOG used to set success; exhausting n_predict incorrectly returned false.
Offsets below are original file offsets (x86_64 VA = offset + 0x1000;
ARM64 VA = offset + 0x10000).
No cancellation, prompt failure, or decode failure becomes success.
"""
import hashlib
import struct

HASHES = {
    62: 'd2d8893c41e064596cf41a1896a00a9f849809d1c213261879a5b8826913c8b9',
    183: '6061ec5ccb50b7e0965577fb6da6cc6f63cfc6f06ba2a070056d571a6587610c',
}


def rel32(source, target, opcode):
    return bytes.fromhex(opcode) + struct.pack('<i', target - source - 6)


def arm_branch(source, target, conditional=False):
    delta = (target - source) // 4
    return struct.pack('<I', (0x54000000 | ((delta & 0x7ffff) << 5)) if conditional
                       else (0x14000000 | (delta & 0x3ffffff)))


# Separate the single-token budget check from the decode status check.
SINGLE = (b'\x85\xc0' + rel32(0x3e61, 0x3fa7, '0f85') + bytes.fromhex('448b65b4 4183fc01')
          + rel32(0x3e6f, 0x3d83, '0f84') + b'\x90' * 13)
PATCHES = {
    62: [
        (0x2e5f, bytes.fromhex('85c0 0f95c0 448b65b4 4183fc01 0f94c1 08c1 41bf00000000 b900000000 0f852a010000'), SINGLE),
        # DL records budget exhaustion. Keep the native result in R15B;
        # decode errors must reset it even if they occur on the final token.
        (0x2f8d, bytes.fromhex('4531ff'), bytes.fromhex('4189d7')),
        (0x2f92, bytes.fromhex('7516'), bytes.fromhex('7513')),
        (0x2f94, bytes.fromhex('b900000000'), bytes.fromhex('410fb6cf90')),
    ],
    183: [
        # Decode success is already checked before both budget branches.
        (0x2f80, bytes.fromhex('40f5ff54'), arm_branch(0x12f80, 0x12ea4, True)),
        (0x3094, bytes.fromhex('65ffff17'), arm_branch(0x13094, 0x12ea4)),
    ],
}


def patch_generation(data):
    if data[:6] != b'\x7fELF\x02\x01':
        raise ValueError('Expected original little-endian ELF64 JNI')
    machine = struct.unpack_from('<H', data, 18)[0]
    if machine not in HASHES or hashlib.sha256(data).hexdigest() != HASHES[machine]:
        raise ValueError('Generation repair requires the pinned original JNI')
    output = bytearray(data)
    for offset, old, new in PATCHES[machine]:
        if len(old) != len(new) or data[offset:offset + len(old)] != old:
            raise ValueError(f'Unexpected native completion code at {offset:x}')
        output[offset:offset + len(old)] = new
    return bytes(output)
