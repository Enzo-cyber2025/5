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
HOUR = 1_792_684_800  # 2026-10-22T16:00:00Z


def totp_hour(secret: str, hour_start: int, delta_seconds: int = 300) -> str:
    """The code valid during the hour that starts at ``hour_start``."""
    counter = hour_start // 60
    digest = hmac.new(secret.encode(), counter.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = int.from_bytes(digest[offset:offset + 4], "big") & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def build(path: pathlib.Path, hours: int = 3) -> pathlib.Path:
    rows = []
    for index in range(hours):
        start = HOUR + index * 3600
        rows.append({"timestamp": start + 300, "code": totp_hour(SECRET, start), "note": "oraculo RFC 4226"})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "code", "note"])
        writer.writeheader()
        writer.writerows(rows)
    return path


if __name__ == "__main__":
    target = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "observations.csv")
    build(target)
    print(target.read_text())
