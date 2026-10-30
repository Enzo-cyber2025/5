"""Endpoint discovery: which URLs does the Family Link client actually call?

Hardcoding a URL is a guess. This module lists the known candidates with their
provenance, and - more useful - discovers the real paths from a capture: a HAR,
a saved page, a DevTools copy, an Android logcat or a network dump. The
discovered paths can then be fed to ``flcodes rea api``.

Nothing here contacts Google by itself; ``check`` only runs when asked.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import rea

__all__ = [
    "KNOWN_ENDPOINTS",
    "Endpoint",
    "known_endpoints",
    "discover",
    "check",
]

#: Candidate endpoints, with where the knowledge comes from.
KNOWN_ENDPOINTS = (
    {
        "url": "https://familylink.googleapis.com/v1/familyLinkAppConfig",
        "kind": "app-config",
        "why": "documented in the public Family Link TOTP write-up (DevTools filter "
        "'familyLinkAppConfig', the response used to carry the shared secret)",
    },
    {
        "url": "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1/familyLinkAppConfig",
        "kind": "app-config",
        "why": "confirmed in the 2.105 APK: the Dart snapshot carries the literal "
        "'kidsmanagement/v1/familyLinkAppConfig' plus GetFamilyLinkAppConfig(Request|Response); "
        "same API host family as the endpoints used by the web dashboard",
    },
    {
        "url": "https://kidsmanagement-pa.googleapis.com/kidsmanagement/v1/familyLinkAppConfig",
        "kind": "app-config",
        "why": "alternative API host",
    },
    {
        "url": "https://familylink.google.com/",
        "kind": "web-app",
        "why": "web dashboard: the HTML and its JS bundles embed the config path",
    },
    {
        "url": "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1/families/mine/members",
        "kind": "session-check",
        "why": "returns the family members when the SAPISID session is valid; "
        "use it to confirm the cookie before hunting the config",
    },
    {
        "url": "file:///var/lib/whitelist/preferences",
        "kind": "chromeos-policy",
        "why": "ChromeOS stores ParentAccessCodeConfig (shared_secret, "
        "access_code_ttl, clock_drift_tolerance) in Local State; scan it offline",
    },
    {
        "url": "file:///home/chronos/Local State",
        "kind": "chromeos-policy",
        "why": "same policy for the logged in user on ChromeOS",
    },
)

_URL_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]{6,400}")
_PATH_RE = re.compile(r"/(?:kidsmanagement|v1|v2)/[A-Za-z0-9._~:/%?&=-]{2,160}")
_CONFIG_HINTS = ("appconfig", "parentaccess", "accesscode", "totp", "sharedsecret", "config")
_NOISE_HOSTS = ("google-analytics", "doubleclick", "gstatic", "fonts.", "youtube", ".png", ".jpg")


@dataclass
class Endpoint:
    """One path that looks able to deliver the app config."""

    url: str
    kind: str = "unknown"
    score: int = 0
    source: str = ""
    why: str = ""

    def as_dict(self) -> dict:
        return {
            "url": self.url,
            "kind": self.kind,
            "score": self.score,
            "source": self.source,
            "why": self.why,
        }


def known_endpoints() -> list:
    """The curated candidate list, best first."""
    return [Endpoint(**entry) for entry in KNOWN_ENDPOINTS]


def _score(url: str) -> int:
    lowered = url.lower()
    score = 0
    if any(host in lowered for host in _NOISE_HOSTS) and not lowered.endswith(".js"):
        return -100
    if "familylink" in lowered:
        score += 3
    if "kidsmanagement" in lowered:
        score += 3
    if any(hint in lowered for hint in _CONFIG_HINTS):
        score += 4
    if "appconfig" in lowered:
        score += 6
    if lowered.endswith(".js"):
        score += 1
    if "googleapis.com" in lowered:
        score += 1
    return score


def discover(text: str, source: str = "capture") -> list:
    """Find candidate endpoints in a capture (HAR, HTML, logcat, JS bundle).

    Returns endpoints ordered by how likely they are to hand out the config.
    """
    if not text:
        return []
    found: dict = {}

    for match in _URL_RE.finditer(text):
        url = match.group(0).rstrip('\\",;)}]')
        score = _score(url)
        if score <= 0:
            continue
        found.setdefault(url, Endpoint(url=url, kind=_kind(url), score=score, source=source))

    # API paths seen *without* their host (logcat, protobuf dumps). Only paths
    # that are not already part of a full URL are considered, and the host is
    # taken from a known endpoint that serves the same path prefix - inventing
    # combinations such as familylink.googleapis.com/kidsmanagement/... would
    # produce endpoints that do not exist.
    masked = text
    for match in _URL_RE.finditer(text):
        masked = masked[: match.start()] + " " * (match.end() - match.start()) + masked[match.end():]
    for match in _PATH_RE.finditer(masked):
        path = match.group(0).rstrip('\\",;)}]')
        score = _score(path)
        if score <= 0:
            continue
        prefix = "/" + path.strip("/").split("/")[0]
        host = next(
            (
                urllib.parse.urlparse(entry["url"]).netloc
                for entry in KNOWN_ENDPOINTS
                if f"{prefix}/" in entry["url"]
            ),
            None,
        )
        if not host:
            continue
        url = f"https://{host}{path}"
        found.setdefault(url, Endpoint(url=url, kind=_kind(url), score=score - 1, source=source))

    ordered = sorted(found.values(), key=lambda endpoint: (-endpoint.score, endpoint.url))
    for endpoint in ordered:
        endpoint.why = _why(endpoint.url)
    return ordered


def _kind(url: str) -> str:
    lowered = url.lower()
    if "appconfig" in lowered:
        return "app-config"
    if lowered.endswith(".js") or "webpack" in lowered:
        return "js-bundle"
    if "members" in lowered:
        return "session-check"
    if "config" in lowered or "parentaccess" in lowered:
        return "config-candidate"
    return "api"


def _why(url: str) -> str:
    lowered = url.lower()
    if "appconfig" in lowered:
        return "name matches the documented app config resource"
    if lowered.endswith(".js"):
        return "JS bundle: grep it for the app config path (offline)"
    if "members" in lowered:
        return "validates the session before the config hunt"
    if "config" in lowered:
        return "path suggests configuration data"
    return "Family Link API host"


def check(url: str, sapisid: str = "", cookie: str = "", timeout: float = 20.0,
          origin: str = rea.ORIGIN) -> dict:
    """Request one endpoint and report status, size and whether it held a secret.

    Only run this against the account you are authorised to test.
    """
    if url.startswith("file://"):
        return {
            "url": url,
            "status": 0,
            "error": "local path: use `flcodes rea scan <path>` instead",
        }
    headers = rea.build_headers(sapisid=sapisid, cookie_header=cookie, origin=origin)
    status, body, error = rea._http_get(url, headers, timeout)
    result = {
        "url": url,
        "status": status,
        "bytes": len(body or ""),
        "error": error,
    }
    if body:
        candidates = rea.secrets_mod.extract_from_payload(body, source=url)
        if candidates:
            result["secrets"] = len(candidates)
            result["kinds"] = sorted({candidate.kind for candidate in candidates})
        hint = rea.secrets_mod.encrypted_hint(body)
        if hint:
            result["encrypted_hint"] = hint
        endpoints = discover(body, source=url)
        if endpoints:
            result["paths"] = [endpoint.url for endpoint in endpoints[:10]]
    return result
