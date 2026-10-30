#!/usr/bin/env python3
"""Look inside a real Family Link APK for the parent-access-code config.

The published gists describe a preference called ``familyLinkAppConfig`` with
``parentAccessCode.sharedSecret``, ``accessCodeTtl`` and
``clockDriftTolerance``. This script answers, with numbers instead of a story:

  * are those names still present in the current dex, or were they obfuscated?
  * which strings mention the concept at all (access code, TOTP, drift)?
  * which protobuf/RPC names the app talks about around kidsmanagement?

    tools/dex_hunt.py /path/base.apk        # prints a report, exits 0

No key material is printed and nothing is executed from the APK.
"""
from __future__ import annotations

import pathlib
import re
import sys
import zipfile

ASCII = re.compile(rb"[ -~]{6,}")

FIELDS = (
    "parentAccessCode",
    "sharedSecret",
    "shared_secret",
    "accessCodeTtl",
    "clockDriftTolerance",
    "familyLinkAppConfig",
    "family_link_app_config",
    "googleConfig",
    "parentAccessCodeConfig",
)

ENDPOINTS = (
    "kidsmanagement",
    "families/mine",
    "parentaccess",
    "parent_access",
    "appblocking",
    "timeLimits",
)

CONCEPT = ("accesscode", "sharedsecret", "clockdrift", "totp", "parentaccess", "homesweethome")


def dex_blobs(apk: pathlib.Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    with zipfile.ZipFile(apk) as archive:
        for name in archive.namelist():
            if re.fullmatch(r"classes\d*\.dex", name):
                out[name] = archive.read(name)
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    apk = pathlib.Path(argv[1])
    if not apk.is_file():
        print(f"no such APK: {apk}")
        return 2

    blobs = dex_blobs(apk)
    print("== dex files ==")
    for name, blob in sorted(blobs.items()):
        print(f"{len(blob):>10}  {name}")
    print()

    joined = b"\n".join(blobs.values())
    print("== names the public write-ups mention ==")
    for field in FIELDS:
        print(f"{field:<28} {joined.count(field.encode())}")
    print()

    print("== endpoint surface ==")
    for endpoint in ENDPOINTS:
        print(f"{endpoint:<28} {joined.count(endpoint.encode())}")
    print()

    print("== every string that mentions the concept ==")
    hits: dict[str, int] = {}
    for blob in blobs.values():
        for raw in ASCII.findall(blob):
            text = raw.decode("ascii", "ignore")
            low = text.lower()
            if any(word in low for word in CONCEPT):
                hits[text] = hits.get(text, 0) + 1
    for text in sorted(hits):
        count = hits[text]
        print(f"{count:5d}  {text[:110]}")
    print(f"total distinct: {len(hits)}")
    print()

    print("== RPC / message names around family link ==")
    seen: set[str] = set()
    for blob in blobs.values():
        for raw in ASCII.findall(blob):
            text = raw.decode("ascii", "ignore")
            low = text.lower()
            if ("kidsmanagement" in low or "familylink" in low) and any(
                word in low for word in ("config", "proto", "request", "response", "grpc")
            ):
                seen.add(text[:110])
    for text in sorted(seen)[:40]:
        print(text)
    print(f"total: {len(seen)}")

    verdict = (
        "the names from the write-ups survive in the dex"
        if joined.count(b"parentAccessCode")
        else "the names from the write-ups are NOT in the dex: renamed or removed"
    )
    print()
    print(f"verdict: {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
