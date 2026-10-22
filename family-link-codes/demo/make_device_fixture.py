#!/usr/bin/env python3
"""Build a realistic ``adb backup`` container, byte for byte.

Used to exercise the no-root pipeline without a phone (and by the QEMU harness,
which produces the same file *from inside* the emulator):

    python demo/make_device_fixture.py --out /tmp/flcodes-demo/device
    flcodes abe info  /tmp/flcodes-demo/device/familylink.ab
    flcodes abe scan  /tmp/flcodes-demo/device/familylink.ab --save --label parent

The secret here is fictitious; the container layout, the PBKDF2/AES header and
the tar member names are the ones the device writes.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import sys
import tarfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flcodes import aes  # noqa: E402

PACKAGE = "com.google.android.apps.familylink"
SECRET = "AItest-only-device-fixture-key"

PREFS = f"""<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <string name="family_link_app_config">{{"parentAccessCode":{{
        "sharedSecret":"{SECRET}",
        "accessCodeTtl":600,
        "clockDriftTolerance":300}}}}</string>
    <boolean name="parent_access_enabled" value="true" />
</map>
"""

MANIFEST = "1\ncom.google.android.apps.familylink\n"


def build_tar() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        def add(name: str, data: bytes) -> None:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 0
            archive.addfile(info, io.BytesIO(data))

        add(f"apps/{PACKAGE}/_manifest", MANIFEST.encode())
        add(f"apps/{PACKAGE}/f/shared_prefs/familylink_preferences.xml", PREFS.encode())
        add(f"apps/{PACKAGE}/db/familylink.db", b"SQLite format 3\x00" + os.urandom(512))
    return buffer.getvalue()


def build(password: str | None, version: int = 5) -> bytes:
    payload = zlib.compress(build_tar())
    if not password:
        return b"ANDROID BACKUP\n%d\n1\nnone\n" % version + payload

    user_salt, checksum_salt = os.urandom(64), os.urandom(64)
    rounds, user_iv = 10000, os.urandom(16)
    master_key, master_iv = os.urandom(32), os.urandom(16)
    checksum = hashlib.pbkdf2_hmac("sha1", master_key, checksum_salt, rounds, 32)
    blob = (
        bytes([len(master_iv)]) + master_iv
        + bytes([len(master_key)]) + master_key
        + bytes([len(checksum)]) + checksum
    )
    user_key = hashlib.pbkdf2_hmac("sha1", password.encode(), user_salt, rounds, 32)
    header = (
        b"ANDROID BACKUP\n"
        + b"%d\n1\nAES-256\n" % version
        + user_salt.hex().encode() + b"\n"
        + checksum_salt.hex().encode() + b"\n"
        + b"%d\n" % rounds
        + user_iv.hex().encode() + b"\n"
        + aes.cbc_encrypt(user_key, user_iv, aes.pad(blob)).hex().encode() + b"\n"
    )
    return header + aes.cbc_encrypt(master_key, master_iv, aes.pad(payload))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="/tmp/flcodes-demo/device")
    parser.add_argument("--password", help="encrypt the container (like adb backup -k)")
    args = parser.parse_args(argv)
    target = Path(args.out)
    target.mkdir(parents=True, exist_ok=True)
    path = target / "familylink.ab"
    path.write_bytes(build(args.password))
    print(f"wrote {path} ({path.stat().st_size} bytes)")
    print(f"package: {PACKAGE}")
    print(f"secret (fictitious): {SECRET}")
    print()
    print("next:")
    print(f"  flcodes abe info   {path}")
    print(f"  flcodes abe extract {path} --out {target / 'extracted'}")
    print(f"  flcodes abe scan   {path}" + (f" --password {args.password}" if args.password else "")
          + " --save --label parent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
