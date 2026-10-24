"""Discovery of the Family Link shared secret (the "offline code key").

The shared secret is delivered by Google inside the ``familyLinkAppConfig``
payload of the parent account. It is a short opaque string that starts with
``AI`` (the Chromebook enrolment uses a different, shorter secret; a value
starting with ``AL`` is *not* the Android one).

This module only *finds* candidates. It never contacts Google, so it works
offline on a saved payload, a HAR capture, an app data dump or a pasted
snippet.

Reverse engineering sources that are handled explicitly, because a real dump
almost never has the secret sitting in plain UTF-8:

* raw text, JSON (including the XSSI prefix) and JSON arrays (protobuf-ish
  responses such as ``["AI..."]``);
* ``\\uXXXX`` escaped strings and percent encoded strings;
* hex encoded runs;
* base64 runs inside a larger blob (also ``base64:`` prefixed values);
* UTF-16 dumps (XML prefs, Windows captures) - decoded by the file reader in
  ``rea``;
* zip containers: APK, JAR, CRX, plain ``.zip``.

If the payload carries an *encrypted* secret (the client derives the code
locally) the extractor says so instead of inventing a key.
"""

from __future__ import annotations

import base64
import html
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
    "printable",
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
_HEX_RUN_RE = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{26,}(?![0-9a-fA-F])")
_B64_RUN_RE = re.compile(r"[A-Za-z0-9+/]{32,}={0,2}")
# One or more backslashes per escape: a body inside a HAR (JSON in JSON) keeps
# the backslash escaped, so the file has \\u0041 instead of \u0041.
_UNICODE_ESCAPE_RUN_RE = re.compile(r"(?:\\+u[0-9a-fA-F]{4}|\\+x[0-9a-fA-F]{2})+")
_TTL_KEYS = (
    "access_code_ttl",
    "accessCodeTtl",
    "code_validity",
    "codeValidity",
    "validity",
    "ttl",
    "accessCodeValiditySeconds",
)
_DRIFT_KEYS = (
    "clock_drift_tolerance",
    "clockDriftTolerance",
    "clockDrift",
    "drift",
)
_ENCRYPTED_KEY_RE = re.compile(
    r"([A-Za-z_]*(?:encrypted|wrapped|sealed|cipher)[A-Za-z_]*"
    r"(?:secret|seed|key|code)[A-Za-z_]*"
    r"|(?:secret|seed|key|code)[A-Za-z_]*(?:encrypted|cipher|wrapped)[A-Za-z_]*)",
    re.IGNORECASE,
)
_MAX_DERIVED_RUNS = 400
#: How many times JSON may be nested inside JSON strings (HAR in HAR in ...).
MAX_EMBED_DEPTH = 4
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def printable(text: str, limit: int = 160) -> str:
    """Make a context snippet safe to print: control bytes become a middle dot.

    Binary dumps (LevelDB, SQLite) contain NULs around the secret; printing them
    raw turns the terminal output into garbage.
    """
    cleaned = _CONTROL_RE.sub("·", text).replace("\n", " ").replace("\r", " ").strip()
    return cleaned[:limit]


@dataclass
class SeedCandidate:
    """A secret found by one of the REA collectors."""

    secret: str
    kind: str = "unknown"
    source: str = ""
    context: str = ""
    extra: dict = field(default_factory=dict)
    encoding: str = "raw"

    @property
    def masked(self) -> str:
        return mask_secret(self.secret)

    def as_dict(self, reveal: bool = False) -> dict:
        data = {
            "kind": self.kind,
            "source": self.source,
            "context": self.context,
            "encoding": self.encoding,
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
    """Decode one field value and, if it hides a secret, return a candidate.

    Order matters: a JSON field can hold the secret raw, escaped (``\\u0041``,
    as the API returns it), percent encoded or base64 wrapped.
    """
    raw_value = html.unescape(value).strip().strip("\"'")
    text = urllib.parse.unquote(raw_value)
    if looks_like_secret(text):
        encoding = "raw" if text == raw_value else "percent-encoded"
        return SeedCandidate(
            secret=text,
            kind=classify_secret(text),
            source=source,
            context=context,
            encoding=encoding,
        )
    if "\\" in text:
        decoded_escapes = _decode_escaped_runs(text).strip().strip("\"'")
        if looks_like_secret(decoded_escapes):
            return SeedCandidate(
                secret=decoded_escapes,
                kind=classify_secret(decoded_escapes),
                source=source,
                context=context,
                encoding="unicode-escaped",
            )
    decoded = _decode_maybe_base64(text)
    if decoded:
        return SeedCandidate(
            secret=decoded,
            kind=classify_secret(decoded),
            source=source,
            context=context,
            encoding="base64",
        )
    return None


def _decode_escaped_runs(text: str) -> str:
    """Turn ``\\u0041``, ``\\\\u0041`` and ``\\x41`` runs back into characters.

    Any number of backslashes is accepted, so payloads that were JSON encoded
    more than once (a HAR stores the response body as a JSON string) still
    decode to the secret.
    """

    def _decode(match: re.Match) -> str:
        run = match.group(0)
        out = []
        index = 0
        while index < len(run):
            while index < len(run) and run[index] == "\\":
                index += 1
            if index >= len(run):  # pragma: no cover - trailing backslashes
                break
            marker = run[index]
            if marker == "u":
                out.append(chr(int(run[index + 1 : index + 5], 16)))
                index += 5
            elif marker == "x":
                out.append(chr(int(run[index + 1 : index + 3], 16)))
                index += 3
            else:  # pragma: no cover - the regex only matches u/x markers
                out.append(marker)
                index += 1
        return "".join(out)

    return _UNICODE_ESCAPE_RUN_RE.sub(_decode, text)


def derived_blobs(text: str) -> list:
    """Return ``[(label, decoded_text)]`` for the encodings seen in dumps."""
    blobs: list = []
    if "\\u" in text or "\\x" in text:
        blobs.append(("unicode-escaped", _decode_escaped_runs(text)))
    if "%" in text:
        decoded = urllib.parse.unquote(text)
        if decoded != text:
            blobs.append(("percent-encoded", decoded))
            twice = urllib.parse.unquote(decoded)
            if twice != decoded:  # double encoded (%2541 -> %41 -> A)
                blobs.append(("percent-encoded", twice))

    for index, match in enumerate(_HEX_RUN_RE.finditer(text)):
        if index >= _MAX_DERIVED_RUNS:
            break
        run = match.group(0)
        if len(run) % 2:
            run = run[:-1]
        try:
            decoded = bytes.fromhex(run).decode("latin-1")
        except ValueError:
            continue
        if looks_like_secret(decoded.strip()):
            blobs.append(("hex", decoded))

    for index, match in enumerate(_B64_RUN_RE.finditer(text)):
        if index >= _MAX_DERIVED_RUNS:
            break
        decoded = _decode_maybe_base64(match.group(0))
        if decoded:
            blobs.append(("base64", decoded))
    return blobs


def encrypted_hint(text: str) -> str | None:
    """Return the name of an encrypted-secret field, if the payload has one.

    After the September 2024 change the web client receives a wrapped value
    instead of the shared secret; reporting that honestly is more useful than
    returning no candidate at all.
    """
    if not text:
        return None
    match = _ENCRYPTED_KEY_RE.search(text)
    return match.group(1) if match else None


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

    for candidate in _scan_plain_text(text, source):
        add(candidate)

    for label, blob in derived_blobs(text):
        for candidate in _scan_plain_text(blob, source):
            candidate.encoding = label
            add(candidate)

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


def _scan_plain_text(text: str, source: str) -> list:
    """Literal scan: the secret pattern as it appears in the text."""
    found = []
    for match in _SECRET_RE.finditer(text):
        secret = match.group(0)
        if not looks_like_secret(secret):
            continue
        start = max(0, match.start() - 40)
        found.append(
            SeedCandidate(
                secret=secret,
                kind=classify_secret(secret),
                source=source,
                context=printable(text[start : match.end() + 20]),
            )
        )
    return found


def _config_extras(payload: dict) -> dict:
    """Pick the code validity and clock tolerance that sit next to a secret.

    Chromium's ``AccessCodeConfig`` serialises as ``shared_secret`` +
    ``access_code_ttl`` + ``clock_drift_tolerance`` (60..3600 and 0..1800 s);
    the API payloads use camelCase variants.
    """
    extras = {}
    for key in _TTL_KEYS:
        if key in payload:
            try:
                value = int(payload[key])
            except (TypeError, ValueError):
                continue
            if 60 <= value <= 3600:
                extras["validity"] = value
                break
    for key in _DRIFT_KEYS:
        if key in payload:
            try:
                value = int(payload[key])
            except (TypeError, ValueError):
                continue
            if 0 <= value <= 1800:
                extras["drift"] = value
                break
    return extras


def _looks_like_json(text: str) -> bool:
    stripped = html.unescape(text).lstrip()
    if stripped.startswith(")]}'"):
        return True
    return bool(stripped) and stripped[0] in "{[" and len(stripped) < 4 * 1024 * 1024


def extract_from_json(
    payload: Any, source: str = "json", path: str = "$", depth: int = 0
) -> list:
    # ``depth`` counts *embedded* JSON levels only; structural nesting (a HAR is
    # log > entries > n > response > content > text) must not consume it.
    """Walk a decoded JSON document and collect secret candidates.

    A capture frequently nests JSON inside a string (a HAR stores the response
    body as a JSON string), so strings that look like JSON are parsed and
    walked again. Without that, the secret is found by the text scanner but the
    ``access_code_ttl`` that travels with it is lost.
    """
    found: list = []
    if isinstance(payload, dict):
        extras = _config_extras(payload)
        for key, value in payload.items():
            child_path = f"{path}.{key}"
            if isinstance(value, str):
                candidate = _candidate_from_value(value, source, child_path)
                if candidate is not None and extras:
                    candidate.extra.update(extras)
                if candidate is not None:
                    if _JSON_KEY_RE.search(str(key)):
                        candidate.kind = classify_secret(candidate.secret)
                        candidate.context = f"{child_path} (key match)"
                    found.append(candidate)
                    continue
                if _looks_like_json(value) and depth < MAX_EMBED_DEPTH:
                    try:
                        embedded = parse_json_payload(value)
                    except ValueError:
                        embedded = None
                    if embedded is not None:
                        found.extend(
                            extract_from_json(embedded, source, child_path, depth + 1)
                        )
                        continue
                if _JSON_KEY_RE.search(str(key)) and value:
                    nested = _candidate_from_value(str(value), source, child_path)
                    if nested is not None:
                        found.append(nested)
            else:
                found.extend(extract_from_json(value, source, child_path, depth))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            found.extend(extract_from_json(value, source, f"{path}[{index}]", depth))
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
    else:
        # SharedPreferences XML escapes the JSON that holds the config:
        # {&quot;parentAccessCode&quot;:{&quot;sharedSecret&quot;:...}}. Unescape
        # first, then walk any embedded JSON so the TTL comes along too.
        unescaped = html.unescape(text)
        if _looks_like_json(unescaped.strip()):
            try:
                found.extend(extract_from_json(parse_json_payload(unescaped), source))
            except ValueError:
                pass
        else:
            for chunk in re.findall(r"\{[^{}]{20,4096}\}", unescaped):
                try:
                    found.extend(extract_from_json(parse_json_payload(chunk), source))
                except ValueError:
                    continue
    found.extend(extract_from_text(text, source))
    unique: list = []
    by_secret: dict = {}
    for candidate in found:
        existing = by_secret.get(candidate.secret)
        if existing is None:
            by_secret[candidate.secret] = candidate
            unique.append(candidate)
            continue
        # keep the first candidate but never lose config metadata found later
        for key, value in candidate.extra.items():
            existing.extra.setdefault(key, value)
    return unique


def config_validity(candidates: Iterable) -> int | None:
    """Return the first code validity found among the candidates."""
    for candidate in candidates or []:
        validity = (candidate.extra or {}).get("validity")
        if validity:
            return int(validity)
    return None


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
