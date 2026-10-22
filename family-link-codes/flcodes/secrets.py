"""Discovery of the Family Link shared secret (the "offline code key").

The shared secret is delivered by Google inside the ``familyLinkAppConfig``
payload of the parent account. It is a short opaque string that starts with
``AI`` (the Chromebook enrolment uses a different, shorter secret; a value
starting with ``AL`` is *not* the Android one).

This module only *finds* candidates. It never contacts Google, so it works
offline on a saved payload, a HAR capture, an app data dump or a pasted
snippet.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Iterable

from .codes import normalize_secret

__all__ = [
    "SeedCandidate",
    "normalize_secret",
    "ANDROID_PREFIX",
    "CHROMEBOOK_PREFIX",
    "classify_secret",
    "mask_secret",
    "looks_like_secret",
    "extract_from_text",
    "extract_from_json",
    "extract_from_payload",
    "parse_json_payload",
]

ANDROID_PREFIX = "AI"
CHROMEBOOK_PREFIX = "AL"

# A shared secret starts with "AI" (Android) or "AL" (Chromebook) and is
# followed by base64url-ish random characters.
_SECRET_RE = re.compile(r"A[IL][A-Za-z0-9_\-.]{10,}")
_SECRET_CHARS_RE = re.compile(r"^A[IL][A-Za-z0-9_\-.]{10,}$")
_OTP_AUTH_RE = re.compile(r"otpauth://totp/[^\s\"'<>]+", re.IGNORECASE)
_BASE32_SECRET_RE = re.compile(r"(?<![A-Z2-7=])[A-Z2-7]{16,}={0,6}(?![A-Za-z0-7])")
_JSON_KEY_RE = re.compile(
    r"(shared|secret|seed|totp|otp|passcode|accesscode|parentcode)", re.IGNORECASE
)


@dataclass
class SeedCandidate:
    """A secret found by one of the REA collectors."""

    secret: str
    kind: str = "unknown"
    source: str = ""
    context: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def masked(self) -> str:
        return mask_secret(self.secret)

    def as_dict(self, reveal: bool = False) -> dict:
        data = {
            "kind": self.kind,
            "source": self.source,
            "context": self.context,
            "masked": self.masked,
        }
        if reveal:
            data["secret"] = self.secret
        return data


def mask_secret(secret: str, keep: int = 4) -> str:
    """Mask a secret for display: ``AIab…`` plus the length."""
    if not secret:
        return ""
    if len(secret) <= keep * 2:
        return secret[0] + "*" * max(0, len(secret) - 1)
    return f"{secret[:keep]}…{secret[-2:]} (len {len(secret)})"


def classify_secret(secret: str) -> str:
    """Classify a secret as ``android``, ``chromebook`` or ``unknown``."""
    value = (secret or "").strip()
    if value.startswith(ANDROID_PREFIX):
        return "android"
    if value.startswith(CHROMEBOOK_PREFIX):
        return "chromebook"
    return "unknown"


def looks_like_secret(value: str) -> bool:
    """Return True when ``value`` plausibly is a Family Link shared secret.

    Random material is required beyond the prefix: at least one lower case
    letter and at least one digit, upper case letter or separator. That keeps
    ordinary words such as ``ALLOWEDLIST`` from being stored as a key.
    """
    if not value or not isinstance(value, str):
        return False
    candidate = value.strip()
    if len(candidate) < 13 or len(candidate) > 512:
        return False
    if not _SECRET_CHARS_RE.match(candidate):
        return False
    body = candidate[2:]
    has_lower = any(char.islower() for char in body)
    has_marker = any(
        char.isdigit() or char.isupper() or char in "-_." for char in body
    )
    return has_lower and has_marker


def _decode_maybe_base64(value: str) -> str | None:
    """Decode a base64 blob that may hide a plaintext secret."""
    text = value.strip()
    if len(text) < 16 or len(text) % 4 != 0:
        return None
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        return None
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return decoded if looks_like_secret(decoded) else None


def _candidate_from_value(value: str, source: str, context: str) -> SeedCandidate | None:
    text = urllib.parse.unquote(value).strip().strip("\"'")
    if looks_like_secret(text):
        return SeedCandidate(secret=text, kind=classify_secret(text), source=source, context=context)
    decoded = _decode_maybe_base64(text)
    if decoded:
        return SeedCandidate(
            secret=decoded,
            kind=classify_secret(decoded),
            source=source,
            context=f"{context} (base64)",
        )
    return None


def extract_from_text(text: str, source: str = "text") -> list:
    """Find every secret-looking token in a blob of text."""
    if not text:
        return []
    found: list = []
    seen: set = set()

    def add(candidate: SeedCandidate | None) -> None:
        if candidate is None or candidate.secret in seen:
            return
        seen.add(candidate.secret)
        found.append(candidate)

    for match in _SECRET_RE.finditer(text):
        secret = match.group(0)
        if not looks_like_secret(secret):
            continue
        start = max(0, match.start() - 40)
        add(
            SeedCandidate(
                secret=secret,
                kind=classify_secret(secret),
                source=source,
                context=text[start : match.end() + 20].replace("\n", " "),
            )
        )

    for match in _OTP_AUTH_RE.finditer(text):
        uri = match.group(0)
        params = urllib.parse.parse_qs(urllib.parse.urlparse(uri).query)
        secret = params.get("secret", [""])[0].strip()
        if secret:
            add(
                SeedCandidate(
                    secret=secret,
                    kind="otpauth",
                    source=source,
                    context=uri[:120],
                    extra={"uri": uri},
                )
            )

    return found


def extract_from_json(payload: Any, source: str = "json", path: str = "$") -> list:
    """Walk a decoded JSON document and collect secret candidates."""
    found: list = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            child_path = f"{path}.{key}"
            if isinstance(value, str):
                candidate = _candidate_from_value(value, source, child_path)
                if candidate is not None:
                    if _JSON_KEY_RE.search(str(key)):
                        candidate.kind = classify_secret(candidate.secret)
                        candidate.context = f"{child_path} (key match)"
                    found.append(candidate)
                elif _JSON_KEY_RE.search(str(key)) and value:
                    nested = _candidate_from_value(str(value), source, child_path)
                    if nested is not None:
                        found.append(nested)
            else:
                found.extend(extract_from_json(value, source, child_path))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            found.extend(extract_from_json(value, source, f"{path}[{index}]"))
    elif isinstance(payload, str):
        found.extend(extract_from_text(payload, source))
    return found


def parse_json_payload(text: str) -> Any:
    """Best effort JSON parsing of a captured response.

    Handles the XSSI prefix (``)]}'``) that Google APIs prepend, trailing
    garbage and a payload embedded in a larger blob.
    """
    if not text:
        raise ValueError("empty payload")
    candidate = text.strip()
    if candidate.startswith(")]}'"):
        candidate = candidate.split("\n", 1)[-1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for index, char in enumerate(candidate):
        if char not in "{[":
            continue
        try:
            value, _ = decoder.raw_decode(candidate[index:])
        except json.JSONDecodeError:
            continue
        return value
    raise ValueError("payload is not JSON")


def extract_from_payload(text: str, source: str = "payload") -> list:
    """Extract candidates from a raw response body (JSON or plain text)."""
    found: list = []
    try:
        payload = parse_json_payload(text)
    except ValueError:
        payload = None
    if payload is not None:
        found.extend(extract_from_json(payload, source))
    found.extend(extract_from_text(text, source))
    unique: list = []
    seen: set = set()
    for candidate in found:
        if candidate.secret in seen:
            continue
        seen.add(candidate.secret)
        unique.append(candidate)
    return unique


def dedupe(candidates: Iterable) -> list:
    """Keep the first candidate for each distinct secret."""
    seen: set = set()
    result = []
    for candidate in candidates:
        if candidate.secret in seen:
            continue
        seen.add(candidate.secret)
        result.append(candidate)
    return result
