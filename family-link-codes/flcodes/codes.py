"""Family Link parent access code generation.

The "parent access code" that Google Family Link shows in the parent app (and
that unlocks a supervised device offline) is a time based one time password:

* key          = the shared secret, used as **raw key bytes**;
* hash         = HMAC-SHA1;
* counter      = the number of 60 second steps since the epoch, **anchored to
                  the hour** (the counter only changes on the hour);
* truncation   = RFC 4226 dynamic truncation, result mod 1e6, zero padded.

Because the counter is anchored to the hour, one code stays valid for the
whole hour, which is the behaviour observed in the Family Link app and
documented by the public `fl_codegen_gui` reference implementation.

Hour alignment is computed on the epoch, so every timezone whose UTC offset is
a whole number of hours shares the same boundaries. `offset_minutes` shifts the
alignment for the half hour timezones (UTC+05:30, UTC+09:30, ...).
"""

from __future__ import annotations

import base64
import binascii
import datetime as _dt
import hashlib
import hmac
import re
import urllib.parse
from dataclasses import dataclass

__all__ = [
    "CODE_VALIDITY_SECONDS",
    "CODE_GRANULARITY_SECONDS",
    "FamilyLinkCode",
    "normalize_secret",
    "secret_key",
    "generate_code",
    "code_window",
    "codes_for_day",
    "parse_timestamp",
]

CODE_VALIDITY_SECONDS = 3600
CODE_GRANULARITY_SECONDS = 60

_BASE32_RE = re.compile(r"^[A-Z2-7]+=*$")
_OTP_AUTH_RE = re.compile(r"^otpauth://totp/[^?]*\?(.*)$", re.IGNORECASE)


@dataclass(frozen=True)
class FamilyLinkCode:
    """A generated code plus the window in which the server accepts it."""

    code: str
    valid_from: int
    valid_to: int
    counter: int

    @property
    def seconds_remaining(self) -> int:
        return max(0, self.valid_to - int(_dt.datetime.now(_dt.timezone.utc).timestamp()))

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "counter": self.counter,
        }


def normalize_secret(raw: str) -> str:
    """Clean a secret pasted from the Family Link web/app payload.

    Accepts the raw secret, a quoted string, an ``otpauth://totp/`` URI or a
    ``secret=`` query parameter. The returned value keeps the original
    characters: Family Link uses the raw string bytes as the HMAC key.
    """
    if raw is None:
        return ""
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    match = _OTP_AUTH_RE.match(value)
    if match:
        params = urllib.parse.parse_qs(match.group(1))
        secret = params.get("secret", [""])[0]
        return secret.strip()
    if value.lower().startswith("secret="):
        value = value.split("=", 1)[1]
        return urllib.parse.unquote(value).strip()
    return value.strip()


def _looks_base32(value: str) -> bool:
    if not value or len(value) % 8 != 0:
        return False
    if not _BASE32_RE.match(value):
        return False
    # A Family Link shared secret starts with "AI"; never treat it as base32.
    return not value.startswith("AI")


def secret_key(secret: str, encoding: str = "auto") -> bytes:
    """Return the HMAC key bytes for ``secret``.

    ``encoding``:

    ``raw``     the secret string bytes are the key (Family Link behaviour);
    ``base32``  the secret is base32 and is decoded first (otpauth style);
    ``auto``    base32 only when the value is unambiguously base32.
    """
    value = normalize_secret(secret)
    if not value:
        raise ValueError("empty secret")
    if encoding == "raw":
        return value.encode("utf-8")
    if encoding == "base32":
        padded = value + "=" * (-len(value) % 8)
        try:
            return base64.b32decode(padded, casefold=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"invalid base32 secret: {exc}") from exc
    if encoding != "auto":
        raise ValueError(f"unknown encoding: {encoding}")
    if _looks_base32(value):
        padded = value + "=" * (-len(value) % 8)
        try:
            return base64.b32decode(padded, casefold=True)
        except (binascii.Error, ValueError):
            return value.encode("utf-8")
    return value.encode("utf-8")


def _hour_start(timestamp: float, offset_minutes: int = 0) -> int:
    """Epoch second where the hour (on a clock at ``offset_minutes``) begins."""
    shift = offset_minutes * 60
    return (int(timestamp) + shift) // CODE_VALIDITY_SECONDS * CODE_VALIDITY_SECONDS - shift


def code_window(timestamp: float, offset_minutes: int = 0) -> tuple:
    """Return ``(valid_from, valid_to)`` epoch seconds for the given moment."""
    start = _hour_start(timestamp, offset_minutes)
    return start, start + CODE_VALIDITY_SECONDS


def generate_code(
    secret: str,
    timestamp: float | None = None,
    offset_minutes: int = 0,
    encoding: str = "auto",
) -> FamilyLinkCode:
    """Generate the parent access code valid at ``timestamp`` (default: now)."""
    if timestamp is None:
        timestamp = _dt.datetime.now(_dt.timezone.utc).timestamp()
    key = secret_key(secret, encoding=encoding)
    valid_from, valid_to = code_window(timestamp, offset_minutes)
    counter = valid_from // CODE_GRANULARITY_SECONDS
    digest = hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return FamilyLinkCode(
        code=f"{truncated % 1000000:06d}",
        valid_from=valid_from,
        valid_to=valid_to,
        counter=counter,
    )


def codes_for_day(
    secret: str,
    day: _dt.date,
    tz: _dt.tzinfo | None = None,
    offset_minutes: int = 0,
    encoding: str = "auto",
) -> list:
    """Return ``[(local datetime, FamilyLinkCode), ...]`` for every hour of ``day``."""
    tzinfo = tz or _dt.datetime.now().astimezone().tzinfo
    start = _dt.datetime.combine(day, _dt.time(0, 0), tzinfo=tzinfo)
    end = start + _dt.timedelta(days=1)
    start_ts = start.timestamp()
    end_ts = end.timestamp()
    result = []
    cursor = (int(start_ts) // CODE_VALIDITY_SECONDS) * CODE_VALIDITY_SECONDS
    while cursor < end_ts:
        code = generate_code(secret, cursor, offset_minutes=offset_minutes, encoding=encoding)
        result.append((_dt.datetime.fromtimestamp(cursor, tzinfo), code))
        cursor += CODE_VALIDITY_SECONDS
    return result


def parse_timestamp(value: str) -> float:
    """Parse an epoch value or an ISO-8601 timestamp into epoch seconds."""
    text = value.strip()
    if not text:
        raise ValueError("empty timestamp")
    try:
        return float(text)
    except ValueError:
        pass
    normalised = text.replace("Z", "+00:00")
    try:
        parsed = _dt.datetime.fromisoformat(normalised)
    except ValueError as exc:
        raise ValueError(f"cannot parse timestamp: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.timestamp()
