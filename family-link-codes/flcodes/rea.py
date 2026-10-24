"""REA - the acquisition layer: find the offline code key and save it.

REA covers every way the shared secret can be obtained in an authorised test:

``api``    fetch the Family Link app config with the parent session
           (SAPISIDHASH) and harvest the secret from the response;
``har``    read a browser HAR capture or a saved response body;
``paste``  read a pasted snippet (raw secret, DevTools "copy response",
           shared prefs dump, logcat excerpt);
``scan``   walk files/directories looking for the secret pattern;
``adb``    pull the candidate app data files from a connected device and scan
           them.

Everything except ``api`` and ``adb`` is completely offline.

The scanners are built for real reverse engineering material: UTF-16 dumps,
zip containers (APK/JAR/CRX/zip), gzip logs, LevelDB ``.ldb``/``.log`` files and
escaped or encoded strings (see ``secrets``).
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import time
import zipfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import secrets as secrets_mod

__all__ = [
    "Harvest",
    "API_KEY",
    "DEFAULT_ENDPOINTS",
    "sapisid_hash",
    "build_headers",
    "harvest_api",
    "harvest_har",
    "harvest_text",
    "harvest_files",
    "harvest_adb",
    "harvest_cookie_file",
    "read_text",
]

API_KEY = "AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw"
ORIGIN = "https://familylink.google.com"

DEFAULT_ENDPOINTS = (
    "https://familylink.googleapis.com/v1/familyLinkAppConfig",
    "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1/familyLinkAppConfig",
    "https://kidsmanagement-pa.googleapis.com/kidsmanagement/v1/familyLinkAppConfig",
    "https://familylink.google.com/?hl=en",
)

_MAX_SCAN_FILE = 8 * 1024 * 1024
_BINARY_SNIFF = 4096


@dataclass
class Harvest:
    """Result of one acquisition run."""

    candidates: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    responses: list = field(default_factory=list)

    def add(self, candidate) -> None:
        if candidate is None:
            return
        if any(candidate.secret == existing.secret for existing in self.candidates):
            return
        self.candidates.append(candidate)

    def extend(self, candidates) -> None:
        for candidate in candidates or []:
            self.add(candidate)

    def note(self, message: str) -> None:
        self.notes.append(message)

    @property
    def best(self):
        """The preferred candidate: the Android one wins over the others."""
        for candidate in self.candidates:
            if candidate.kind == "android":
                return candidate
        return self.candidates[0] if self.candidates else None

    def as_dict(self, reveal: bool = False) -> dict:
        return {
            "candidates": [c.as_dict(reveal=reveal) for c in self.candidates],
            "notes": self.notes,
            "responses": self.responses,
        }


def sapisid_hash(sapisid: str, origin: str = ORIGIN, timestamp_ms: int | None = None) -> str:
    """Build the ``SAPISIDHASH`` header value used by the Family Link APIs."""
    if not sapisid:
        raise ValueError("missing SAPISID cookie")
    if timestamp_ms is None:
        timestamp_ms = int(time.time() * 1000)
    payload = f"{timestamp_ms} {sapisid} {origin}".encode("utf-8")
    return f"{timestamp_ms}_{hashlib.sha1(payload).hexdigest()}"


def build_headers(sapisid: str = "", cookie_header: str = "", origin: str = ORIGIN) -> dict:
    """Headers accepted by the Family Link web/API endpoints."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Origin": origin,
        "Referer": origin + "/",
        "X-Goog-Api-Key": API_KEY,
    }
    if sapisid:
        headers["Authorization"] = f"SAPISIDHASH {sapisid_hash(sapisid, origin)}"
    cookies = []
    if sapisid:
        cookies.append(f"SAPISID={sapisid}")
    if cookie_header:
        cookies.append(cookie_header.strip().rstrip(";"))
    if cookies:
        headers["Cookie"] = "; ".join(cookies)
    return headers


def _http_get(url: str, headers: dict, timeout: float) -> tuple:
    """GET a URL, returning ``(status, body_text, error)``."""
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return response.status, body.decode(charset, errors="replace"), None
    except urllib.error.HTTPError as exc:
        body = exc.read()
        return exc.code, body.decode("utf-8", errors="replace"), f"HTTP {exc.code}"
    except Exception as exc:  # network errors, TLS problems, timeouts
        return 0, "", str(exc)


def harvest_api(
    sapisid: str = "",
    cookie_header: str = "",
    endpoints=None,
    timeout: float = 20.0,
    origin: str = ORIGIN,
) -> Harvest:
    """Fetch the Family Link app config and harvest the shared secret.

    Only the account the tester is authorised to use is contacted; every
    response body stays on the machine and is parsed locally.
    """
    harvest = Harvest()
    headers = build_headers(sapisid=sapisid, cookie_header=cookie_header, origin=origin)
    for url in endpoints or DEFAULT_ENDPOINTS:
        status, body, error = _http_get(url, headers, timeout)
        harvest.responses.append({"url": url, "status": status, "error": error})
        if error:
            harvest.note(f"{url}: {error}")
            continue
        if not body:
            harvest.note(f"{url}: empty body")
            continue
        before = len(harvest.candidates)
        _scan_text(harvest, body, url)
        found = harvest.candidates[before:]
        if found:
            harvest.note(f"{url}: {len(found)} candidate(s)")
        else:
            harvest.note(f"{url}: no secret in response ({len(body)} bytes)")
    return harvest


def harvest_text(text: str, source: str = "paste") -> Harvest:
    """Harvest from a pasted blob (secret, JSON response, prefs dump...)."""
    harvest = Harvest()
    _scan_text(harvest, text, source)
    return harvest


def harvest_har(path: str | os.PathLike) -> Harvest:
    """Harvest every response body stored in a browser HAR capture."""
    harvest = Harvest()
    har_path = Path(path)
    try:
        document = json.loads(har_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read HAR file: {exc}") from exc
    entries = document.get("log", {}).get("entries", [])
    for index, entry in enumerate(entries):
        request = entry.get("request", {})
        url = request.get("url", "")
        content = entry.get("response", {}).get("content", {})
        text = content.get("text") or ""
        if not text:
            continue
        source = f"{har_path.name}#{index} {url}"
        harvest.extend(secrets_mod.extract_from_payload(text, source=source))
    harvest.note(f"{har_path}: {len(entries)} entr(ies) scanned")
    return harvest


_ZIP_SUFFIXES = {".zip", ".apk", ".jar", ".crx", ".xpi", ".aar"}
_MAX_ZIP_MEMBERS = 4000


def _decode_bytes(raw: bytes) -> str:
    """Decode bytes from a dump: UTF-8, UTF-16 (any endianness) or latin-1.

    Latin-1 never fails, so LevelDB/SQLite style blobs stay scannable instead of
    being skipped just because they contain NUL bytes.
    """
    for bom, encoding in ((b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be")):
        if raw.startswith(bom):
            return raw.decode(encoding, errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    # NUL bytes every other byte: UTF-16 without a BOM (Windows/Android dumps)
    head = raw[:2048]
    if len(head) >= 4 and head.count(b"\x00") >= len(head) // 3:
        even_nuls = head[0::2].count(b"\x00")
        odd_nuls = head[1::2].count(b"\x00")
        encoding = "utf-16-be" if even_nuls > odd_nuls else "utf-16-le"
        return raw.decode(encoding, errors="replace")
    return raw.decode("latin-1", errors="replace")


def read_text(path: Path, limit: int = _MAX_SCAN_FILE) -> str | None:
    """Read a dump file as text, transparently handling gzip."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if path.suffix.lower() == ".gz" or raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw[:limit])
        except (OSError, EOFError):
            return None
    return _decode_bytes(raw[:limit])


def _scan_text(harvest: "Harvest", text: str, source: str) -> None:
    """Scan one text blob and record the encrypted-secret hint."""
    harvest.extend(secrets_mod.extract_from_payload(text, source=source))
    hint = secrets_mod.encrypted_hint(text)
    if hint:
        harvest.note(f"{source}: encrypted secret field '{hint}' (client-side only)")


def _scan_zip(harvest: "Harvest", path: Path) -> int:
    """Scan the text members of a zip container; returns the member count."""
    count = 0
    try:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if count >= _MAX_ZIP_MEMBERS or info.file_size > _MAX_SCAN_FILE:
                    continue
                if info.is_dir():
                    continue
                count += 1
                try:
                    data = archive.read(info)
                except (RuntimeError, zipfile.BadZipFile, OSError):
                    continue
                _scan_text(harvest, _decode_bytes(data), f"{path}!{info.filename}")
    except (zipfile.BadZipFile, OSError) as exc:
        harvest.note(f"{path}: bad zip ({exc})")
    return count


def harvest_files(paths, source_label: str = "file") -> Harvest:
    """Scan files and directories for the shared secret pattern."""
    harvest = Harvest()
    targets: list = []
    for entry in paths:
        path = Path(entry)
        if path.is_dir():
            for child in path.rglob("*"):
                if child.is_file():
                    targets.append(child)
        elif path.is_file():
            targets.append(path)
        else:
            harvest.note(f"{path}: not found")
    scanned = 0
    for path in targets:
        suffix = path.suffix.lower()
        if suffix in _ZIP_SUFFIXES or zipfile.is_zipfile(path):
            scanned += _scan_zip(harvest, path) or 1
            continue
        text = read_text(path)
        if text is None:
            harvest.note(f"{path}: unreadable")
            continue
        scanned += 1
        _scan_text(harvest, text, str(path))
    harvest.note(f"{scanned} source(s) scanned from {len(targets)} file(s)")
    if not targets:
        harvest.note("nothing to scan")
    return harvest


_ADB_COMMANDS = (
    ["shell", "su", "-c", "cat /data/data/com.google.android.apps.familylink/shared_prefs/*.xml"],
    ["shell", "su", "-c", "cat /data/data/com.google.android.apps.familylink/databases/*"],
    ["shell", "run-as", "com.google.android.apps.familylink", "cat", "shared_prefs"],
    ["shell", "cat", "/data/data/com.google.android.apps.familylink/shared_prefs/*.xml"],
)


def harvest_adb(serial: str = "", timeout: float = 60.0) -> Harvest:
    """Pull candidate app data from a connected device and scan it.

    Needs an unlocked, authorised device (root, ``run-as`` or an adb-enabled
    debug build). Every failure is reported instead of raising.
    """
    harvest = Harvest()
    adb = shutil.which("adb")
    if not adb:
        raise RuntimeError("adb not found in PATH")
    base = [adb]
    if serial:
        base += ["-s", serial]
    for command in _ADB_COMMANDS:
        try:
            completed = subprocess.run(
                base + command,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            harvest.note(f"adb {' '.join(command)}: {exc}")
            continue
        output = _decode_bytes(completed.stdout or b"")
        errors = (completed.stderr or b"").decode("utf-8", errors="replace")
        label = "adb " + " ".join(command)
        if completed.returncode != 0 and not output:
            harvest.note(f"{label}: exit {completed.returncode} {errors.strip()[:120]}")
            continue
        before = len(harvest.candidates)
        _scan_text(harvest, output, label)
        found = harvest.candidates[before:]
        if found:
            harvest.note(f"{label}: {len(found)} candidate(s)")
    if not harvest.candidates:
        harvest.note("no secret found through adb")
    return harvest


def harvest_cookie_file(path: str | os.PathLike) -> str:
    """Extract the SAPISID value from a cookies.txt export."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if "SAPISID" not in line:
            continue
        parts = [part.strip() for part in line.split("\t")]
        if len(parts) >= 7:
            return parts[6]
        match = re.search(r"SAPISID\s+(\S+)", line)
        if match:
            return match.group(1)
    raise ValueError("no SAPISID cookie found in the file")
