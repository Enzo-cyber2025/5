#!/usr/bin/env python3
"""Fetch the pinned, original APK from this user's repository using configured gh."""
import hashlib
from pathlib import Path
import subprocess

DEST = Path(".cache/gguf/GGUF-Chat.apk")
SHA256 = "02f97871a28936b4374001e0df7352461821181957a5f740207fa5eea4117281"
ENDPOINT = "repos/Enzo-cyber2025/5/contents/GGUF-Chat.apk?ref=90b737409db091ca8c4d75a33b9d5d27748dbacb"


def matches(path):
    if not path.is_file():
        return False
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest() == SHA256


def main():
    if matches(DEST):
        print(f"Original já verificado: {DEST}")
        return
    DEST.parent.mkdir(parents=True, exist_ok=True)
    temp = DEST.with_suffix(".part")
    try:
        with temp.open("wb") as f:
            subprocess.run(["gh", "api", "-H", "Accept: application/vnd.github.raw+json", ENDPOINT],
                           stdout=f, check=True)
        if not matches(temp):
            raise ValueError("Download incompleto ou APK diferente; SHA-256 não confere.")
        temp.replace(DEST)
    finally:
        temp.unlink(missing_ok=True)
    print(f"Original verificado: {DEST}")


if __name__ == "__main__":
    main()
