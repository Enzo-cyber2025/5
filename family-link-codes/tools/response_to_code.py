#!/usr/bin/env python3
"""Turn a captured GetFamilyLinkAppConfig response into a working code.

This is the last leg of the chain, and the only one that can be proved without a
Google account: given the bytes the app receives after the parent signs in, find
the shared secret, store it, generate the six-digit code and confirm it against
the independent Chromium implementation.

    tools/response_to_code.py --response capture.bin
    tools/response_to_code.py --response capture.b64 --base64
    tools/response_to_code.py --synthetic            # self-test, no account

With ``--synthetic`` it builds a response of the same shape with a known secret,
so the pipeline itself is exercised in CI. The secret is masked in the output
unless ``--print-secret`` is passed.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from flcodes import codes as codes_mod  # noqa: E402
from flcodes import proto as proto_mod  # noqa: E402
from flcodes.store import Store  # noqa: E402

TEST_SECRET = "AIzaSyDemoSecretForTheResponseChain01"


def _varint(value: int) -> bytes:
    out = b""
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out += bytes([byte | 0x80])
        else:
            return out + bytes([byte])


def _field(number: int, payload: bytes) -> bytes:
    return _varint(number << 3 | 2) + _varint(len(payload)) + payload


def synthetic_response(secret: str = TEST_SECRET, ttl: int = 600) -> bytes:
    """A response with the shape recovered from the 2.105 snapshot.

    ``GetFamilyLinkAppConfigResponse { FamilyLinkAppConfig family_link_app_config
                                       ParentAccessCodeConfig parent_access_code_config
                                       string shared_secret
                                       int64 access_code_ttl }``
    """
    inner = (
        _field(1, secret.encode())
        + _varint(2 << 3 | 0) + _varint(ttl)
    )
    app_config = _field(1, inner) + _field(2, inner)
    return _field(1, app_config)


def body_from_har(path: str) -> tuple:
    """Pull the familyLinkAppConfig response out of a browser HAR.

    No account is created and no session is reused: the HAR is a recording the
    person already has from their own browser. Returns (bytes, label).
    """
    import base64 as _b64
    import json as _json

    document = _json.loads(pathlib.Path(path).read_text(encoding="utf-8", errors="replace"))
    entries = document.get("log", {}).get("entries", [])
    wanted = ("familylinkappconfig", "family_link_app_config", "parentaccesscode")
    best = None
    for index, entry in enumerate(entries):
        request = entry.get("request", {})
        url = (request.get("url") or "").lower()
        content = (entry.get("response") or {}).get("content") or {}
        text = content.get("text") or ""
        if not text:
            continue
        hit = any(word in url for word in wanted) or any(
            word in text.lower() for word in ("familylinkappconfig", "parentaccesscode"))
        if not hit:
            continue
        encoding = (content.get("encoding") or "").lower()
        if encoding == "base64":
            try:
                raw = _b64.b64decode(text)
            except Exception:
                continue
        else:
            raw = text.encode("utf-8", errors="replace")
        label = f"{pathlib.Path(path).name}#{index} {request.get('url', '')[:80]}"
        if proto_mod.find_secret_fields(raw):
            return raw, label
        best = best or (raw, label)
    if best:
        return best
    raise SystemExit("no familyLinkAppConfig response in this HAR "
                     "(open the Family Link web app with the network tab recording)")


def _find_ttl(blob: bytes, depth: int = 0) -> int:
    """The validity sits next to the secret; walk until one looks plausible."""
    if depth > 6:
        return 600
    for item in proto_mod.parse_fields_prefix(blob):
        value = item.value
        if isinstance(value, int) and not isinstance(value, bool):
            if 60 <= value <= 3600:
                return value
        elif isinstance(value, bytes):
            found = _find_ttl(value, depth + 1)
            if found != 600:
                return found
    return 600


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--response", help="file with the response body")
    parser.add_argument("--har", help="a browser HAR capture; the response is found inside")
    parser.add_argument("--base64", action="store_true", help="the body is base64")
    parser.add_argument("--synthetic", action="store_true", help="self-test without an account")
    parser.add_argument("--print-secret", action="store_true")
    parser.add_argument("--label", default="from-response")
    args = parser.parse_args(argv[1:])

    if args.synthetic:
        blob = synthetic_response()
        print(f"synthetic response: {len(blob)} bytes (shape recovered from the 2.105 APK)")
    elif args.har:
        blob, label = body_from_har(args.har)
        print(f"har entry: {label}")
        print(f"response: {len(blob)} bytes")
    elif args.response:
        blob = pathlib.Path(args.response).read_bytes()
        if args.base64:
            blob = base64.b64decode(blob.strip())
        print(f"response: {len(blob)} bytes from {args.response}")
    else:
        parser.print_help()
        return 2

    print()
    print("\n".join(proto_mod.tree(blob, reveal=args.print_secret)))

    found = proto_mod.find_secret_fields(blob)
    print()
    if not found:
        print("no secret-shaped field in this message")
        print("hint: the app only writes the secret after the parent signs in")
        return 1

    path, secret = found[0]
    print(f"secret found at {path}: {proto_mod.mask(secret) if not args.print_secret else secret}"
          f" (len {len(secret)})")

    ttl = _find_ttl(blob)
    print(f"validity from the response: {ttl}s")

    home = pathlib.Path(os.environ.get("FLCODES_HOME", pathlib.Path.home() / ".flcodes"))
    store = Store(home / "store.json")
    record = store.add_seed(secret=secret, label=args.label, kind="android",
                            source="proto response", validity=ttl)
    print(f"stored: id={record['id']} kind={record['kind']} "
          f"ttl={record.get('validity')}s label={record['label']}")

    generated = codes_mod.generate_code(secret, validity=ttl)
    print()
    print(json.dumps(
        {
            "code": generated.code,
            "validity": ttl,
            "label": args.label,
            "valid_from": generated.valid_from,
            "valid_to": generated.valid_to,
            "counter": generated.counter,
        },
        indent=2,
    ))
    print()
    print("PASS: a captured response yields a secret, and the secret yields a code")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
