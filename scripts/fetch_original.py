#!/usr/bin/env python3
"""Fetch the pinned, original APK from this user's repository using configured gh."""
import hashlib
from pathlib import Path
import subprocess

DEST = Path(".cache/gguf/GGUF-Chat.apk")
SHA256 = "02f97871a28936b4374001e0df7352461821181957a5f740207fa5eea4117281"
ENDPOINT = "repos/Enzo-cyber2025/5/contents/GGUF-Chat.apk?ref=90b737409db091ca8c4d75a33b9d5d27748dbacb"
RAW_URL = "https://raw.githubusercontent.com/Enzo-cyber2025/5/90b737409db091ca8c4d75a33b9d5d27748dbacb/GGUF-Chat.apk"


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
        # Some gh versions try to transform a binary raw+json response as text
        # ("transform: short source buffer"). Prefer an actual binary HTTP download.
        # The public source is commit-pinned and checked before it can replace DEST.
        errors = []
        for transport in ("curl", "gh"):
            temp.unlink(missing_ok=True)
            try:
                if transport == "curl":
                    subprocess.run(["curl", "--fail", "--location", "--retry", "3",
                                    "--connect-timeout", "30", "--max-time", "300",
                                    RAW_URL, "--output", str(temp)], check=True)
                else:
                    # Fallback for environments where raw.githubusercontent.com is blocked.
                    with temp.open("wb") as f:
                        subprocess.run(["gh", "api", "-H", "Accept: application/vnd.github.raw", ENDPOINT],
                                       stdout=f, check=True)
                if not matches(temp):
                    raise ValueError("Download incompleto ou APK diferente; SHA-256 não confere.")
                temp.replace(DEST)
                break
            except (OSError, subprocess.CalledProcessError, ValueError) as exc:
                errors.append(f"{transport}: {exc}")
        else:
            raise RuntimeError("Falha ao obter APK original: " + "; ".join(errors))
    finally:
        temp.unlink(missing_ok=True)
    print(f"Original verificado: {DEST}")


if __name__ == "__main__":
    main()
