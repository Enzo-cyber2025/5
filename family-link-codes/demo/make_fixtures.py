"""Build realistic reverse engineering dumps for the flcodes demo.

Every key written here is a fake test string; nothing was taken from a real
account. The point is to exercise the REA scanners against the formats a real
investigation produces.
"""

from __future__ import annotations

import base64
import gzip
import json
import pathlib
import sys
import zipfile

SECRET = "AItest-only-REA-demo-key.abcdefghij"  # FAKE, demo only


def build(out: pathlib.Path) -> pathlib.Path:
    out.mkdir(parents=True, exist_ok=True)

    # 1) HAR shaped like the familylink.google.com config call: XSSI prefix,
    #    protobuf style array and the secret escaped as \uXXXX
    escaped = "".join("\\u%04x" % ord(char) for char in SECRET)
    # Same shape as Chromium's ParentAccessCodeConfig: the secret travels with
    # its own code validity and clock drift tolerance. The secret itself is
    # escaped, as it is inside a JSON string.
    body = ")]}'\n" + json.dumps(
        {
            "familyLinkAppConfig": {
                "parentAccessCode": {
                    "sharedSecret": escaped,
                    "accessCodeTtl": 600,
                    "clockDriftTolerance": 300,
                }
            }
        }
    )
    har = {
        "log": {
            "entries": [
                {
                    "request": {"url": "https://familylink.google.com/config?hl=pt-BR"},
                    "response": {"content": {"text": body}},
                }
            ]
        }
    }
    (out / "familylink.har").write_text(json.dumps(har), encoding="utf-8")

    # 2) Android shared prefs dump encoded as UTF-16
    prefs = (
        '<?xml version="1.0" encoding="utf-16"?><map>'
        '<string name="seed">' + SECRET.replace("demo", "pref") + "</string></map>"
    )
    (out / "prefs.xml").write_bytes(prefs.encode("utf-16"))

    # 3) APK/zip container with an internal config file
    with zipfile.ZipFile(out / "app-dump.apk", "w") as archive:
        archive.writestr(
            "assets/family_link.json",
            json.dumps({"parentAccessCode": SECRET.replace("demo", "apk1")}),
        )
        archive.writestr("classes.dex", b"\xde\xad\xbe\xef" * 32)

    # 4) LevelDB table (Chrome/ChromeOS Local Extension Settings) and a gzip log
    (out / "000005.ldb").write_bytes(
        b"\x00\x01\xff" + SECRET.replace("demo", "ldb1").encode() + b"\x00\xfe"
    )
    (out / "logcat.gz").write_bytes(
        gzip.compress(("I/fl: seed=" + SECRET.replace("demo", "gz11")).encode())
    )

    # 5) post-patch payload: the secret arrives encrypted, so it must be
    #    reported and never guessed
    (out / "post-patch.json").write_text(
        json.dumps(
            {
                "familyLinkAppConfig": {
                    "parentAccessCode": {
                        "encryptedSharedSecret": base64.b64encode(b"ciphertext").decode()
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return out


if __name__ == "__main__":
    target = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "demo-dumps")
    build(target)
    print("fixtures:", sorted(path.name for path in target.iterdir()))
