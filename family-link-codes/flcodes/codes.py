"""Family Link parent access code generation.

The "parent access code" that Google Family Link shows in the parent app (and
that unlocks a supervised device offline) is a time based one time password.
The authoritative implementation is Chromium's
`chrome/browser/ash/child_accounts/parent_access_code/authenticator.cc`, which
is what a Chromebook uses to validate the code:

* key          = the shared secret, used as **raw key bytes** (not base32);
* hash         = HMAC-SHA1 over the big endian 64 bit counter;
* bucket       = ``timestamp // code_validity`` (code validity comes from the
                 config as ``access_code_ttl``, between 60 s and 3600 s);
* counter      = the bucket start divided by the 1 minute granularity, so a code
                 never changes inside its bucket;
* truncation   = RFC 4226 dynamic truncation, result mod 1e6, zero padded to 6.

So the code does **not** always last an hour: it lasts ``access_code_ttl``
seconds (600 s in Chromium's own test data, which was generated with the Family
Link Android app). The bucket boundaries are epoch based, so they land on
multiples of the TTL; use ``offset_minutes`` only for half hour timezones.

``CODE_VALIDITY_SECONDS`` (the fallback used when no config is available) is
3600 s, because that is what recent reports of the live app show; Chromium's own
fallback is 600 s (``kDefaultCodeValidity``), and the five access codes the
Android app itself generated in Chromium's test data use 600 s. Neither number
is authoritative: the real value is whatever the config says, so always prefer
the ``validity`` extracted from the payload, and use :func:`discover_validity`
when comparing against a code seen in the app (a single sample cannot tell
600 s from 300 s). When in doubt, ask the app: ``flcodes verify --code ...``.
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
    "check_validity",
    "discover_validity",
    "MIN_VALIDITY_SECONDS",
    "MAX_VALIDITY_SECONDS",
    "PLAUSIBLE_VALIDITIES",
]

CODE_VALIDITY_SECONDS = 3600
CODE_GRANULARITY_SECONDS = 60
#: Range accepted by Chromium's AccessCodeConfig (60 s .. 3600 s).
MIN_VALIDITY_SECONDS = 60
MAX_VALIDITY_SECONDS = 3600
#: Values worth trying when the real TTL is unknown.
PLAUSIBLE_VALIDITIES = tuple(range(60, MAX_VALIDITY_SECONDS + 1, 60))

_BASE32_RE = re.compile(r"^[A-Z2-7]+=*$")
_OTP_AUTH_RE = re.compile(r"^otpauth://totp/[^?]*\?(.*)$", re.IGNORECASE)


@dataclass(frozen=True)
class FamilyLinkCode:
    """A generated code plus the window in which the server accepts it."""

    code: str
    valid_from: int
    valid_to: int
    counter: int
    validity: int = CODE_VALIDITY_SECONDS

    @property
    def seconds_remaining(self) -> int:
        return max(0, self.valid_to - int(_dt.datetime.now(_dt.timezone.utc).timestamp()))

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "counter": self.counter,
            "validity": self.validity,
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


def check_validity(validity: int) -> int:
    """Validate a code validity (TTL) in seconds, like Chromium does."""
    try:
        value = int(validity)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid code validity: {validity!r}") from exc
    if not MIN_VALIDITY_SECONDS <= value <= MAX_VALIDITY_SECONDS:
        raise ValueError(
            f"code validity must be between {MIN_VALIDITY_SECONDS} and "
            f"{MAX_VALIDITY_SECONDS} seconds, got {value}"
        )
    return value


def _bucket_start(timestamp: float, offset_minutes: int = 0, validity: int = CODE_VALIDITY_SECONDS) -> int:
    """Epoch second where the bucket (on a clock at ``offset_minutes``) begins."""
    shift = offset_minutes * 60
    return (int(timestamp) + shift) // validity * validity - shift


def code_window(
    timestamp: float, offset_minutes: int = 0, validity: int = CODE_VALIDITY_SECONDS
) -> tuple:
    """Return ``(valid_from, valid_to)`` epoch seconds for the given moment."""
    validity = check_validity(validity)
    start = _bucket_start(timestamp, offset_minutes, validity)
    return start, start + validity


def generate_code(
    secret: str,
    timestamp: float | None = None,
    offset_minutes: int = 0,
    encoding: str = "auto",
    validity: int = CODE_VALIDITY_SECONDS,
) -> FamilyLinkCode:
    """Generate the parent access code valid at ``timestamp`` (default: now)."""
    if timestamp is None:
        timestamp = _dt.datetime.now(_dt.timezone.utc).timestamp()
    validity = check_validity(validity)
    key = secret_key(secret, encoding=encoding)
    valid_from, valid_to = code_window(timestamp, offset_minutes, validity)
    counter = valid_from // CODE_GRANULARITY_SECONDS
    digest = hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return FamilyLinkCode(
        code=f"{truncated % 1000000:06d}",
        valid_from=valid_from,
        valid_to=valid_to,
        counter=counter,
        validity=validity,
    )


def codes_for_day(
    secret: str,
    day: _dt.date,
    tz: _dt.tzinfo | None = None,
    offset_minutes: int = 0,
    encoding: str = "auto",
    validity: int = CODE_VALIDITY_SECONDS,
) -> list:
    """Return ``[(local datetime, FamilyLinkCode), ...]`` for every bucket of ``day``."""
    validity = check_validity(validity)
    tzinfo = tz or _dt.datetime.now().astimezone().tzinfo
    start = _dt.datetime.combine(day, _dt.time(0, 0), tzinfo=tzinfo)
    end = start + _dt.timedelta(days=1)
    start_ts = start.timestamp()
    end_ts = end.timestamp()
    result = []
    cursor = _bucket_start(start_ts, offset_minutes, validity)
    while cursor < end_ts:
        code = generate_code(
            secret,
            cursor,
            offset_minutes=offset_minutes,
            encoding=encoding,
            validity=validity,
        )
        result.append((_dt.datetime.fromtimestamp(cursor, tzinfo), code))
        cursor += validity
    return result


def discover_validity(
    secret: str,
    observations,
    encoding: str = "auto",
    offset_minutes: int = 0,
    candidates=None,
) -> list:
    """Return the code validities that reproduce every ``(code, timestamp)`` pair.

    When the TTL that came from the config is wrong (or missing), this finds the
    real one from a single code read in the parent app, which is how the 600 s
    value in Chromium's own test data is reproduced.
    """
    candidates = tuple(candidates or PLAUSIBLE_VALIDITIES)
    matches = []
    for validity in candidates:
        try:
            validity = check_validity(validity)
        except ValueError:
            continue
        if all(
            generate_code(
                secret, timestamp, offset_minutes=offset_minutes, encoding=encoding,
                validity=validity,
            ).code
            == str(code).strip()
            for code, timestamp in observations
        ):
            matches.append(validity)
    return matches


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
