"""Write the observation file an investigator would take from the parent app.

The codes are produced by an *independent* RFC 4226 implementation written here
with hashlib only - deliberately not by flcodes - so the comparison in
``flcodes verify`` is not self-referential.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import pathlib
import sys

SECRET = "AItest-only-REA-demo-key.abcdefghij"  # FAKE, demo only
START = 1_792_684_800  # 2026-10-22T16:00:00Z
TTL = 600  # the config says 600 s, not one hour


def totp_bucket(secret: str, timestamp: int, validity: int = TTL) -> str:
    """Chromium's Authenticator::Generate: bucket start / 60 s, HMAC-SHA1, 6 digits."""
    bucket = (timestamp // validity) * validity
    counter = bucket // 60
    digest = hmac.new(secret.encode(), counter.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = int.from_bytes(digest[offset:offset + 4], "big") & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def build(path: pathlib.Path, buckets: int = 3) -> pathlib.Path:
    rows = []
    for index in range(buckets):
        moment = START + index * TTL + 120
        rows.append({"timestamp": moment, "code": totp_bucket(SECRET, moment), "note": "oraculo Chromium/RFC 4226"})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "code", "note"])
        writer.writeheader()
        writer.writerows(rows)
    return path


if __name__ == "__main__":
    target = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "observations.csv")
    build(target)
    print(target.read_text())
