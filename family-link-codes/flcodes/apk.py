"""Unpack an APK and point at where the app keeps the code secret.

This is the static half of REA: no device, no root, no decompiler. The APK is a
zip; the interesting material is the string pools of the DEX files, the binary
resource table, the binary ``AndroidManifest.xml`` and any bundled assets. A
plain printable-string pass over those is enough to recover:

* the **private directory** the app writes to (``/data/data/<pkg>`` and, on the
  parent device, the shared-prefs/database file names);
* the **config field names** that carry the key (``sharedSecret``,
  ``accessCodeTtl``, ``clockDriftTolerance``);
* the **endpoints** the config comes from (delegated to ``endpoints``);
* whether ``android:allowBackup`` is enabled, which decides if
  ``adb backup`` — the no-root extraction — can work at all.

Limits are reported, not hidden: obfuscated (string-encrypted) payloads will not
show up as plain text, and DEX string pools are scanned, not decompiled.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import endpoints as endpoints_mod

__all__ = ["ApkReport", "scan_apk", "STRING_PATTERNS", "ordered_findings", "interesting_endpoints"]

_MAX_MEMBER = 48 * 1024 * 1024
_PRINTABLE = re.compile(rb"[\x20-\x7e]{6,}")

#: (label, regex, why it matters)
STRING_PATTERNS = (
    ("private-dir", re.compile(r"/data/(?:data|user/\d+)/[A-Za-z0-9_.]+(?:/[A-Za-z0-9_.\-/]*)?"),
     "private directories the app can read (no root needed for its own files)"),
    ("prefs", re.compile(r"(?:shared_prefs|databases|files|no_backup)/[A-Za-z0-9_.\-]+"),
     "file names inside the private directory"),
    ("config-key", re.compile(r"(?:sharedSecret|shared_secret|accessCodeTtl|access_code_ttl|"
                              r"clockDriftTolerance|clock_drift_tolerance|parentAccessCode)"),
     "field names that carry the key and its TTL"),
    ("backup-flag", re.compile(r"allowBackup|fullBackupContent|dataExtractionRules"),
     "whether adb backup (the no-root path) is allowed"),
    ("endpoint-hint", re.compile(r"kidsmanagement|familylink\.googleapis\.com|"
                                 r"clients6\.google\.com|familyLinkAppConfig"),
     "network paths that deliver the config"),
    ("url", re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]{6,300}"),
     "full URLs hard-coded in the app (config endpoints included)"),
    ("root-hint", re.compile(r"(?:^|/)(?:su|magisk)(?:$|/)|Superuser|RootBeer"),
     "root detection the app performs"),
)

_PACKAGE_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+){2,}$")

#: Display order: what points at the secret first, generic noise last.
_KIND_ORDER = (
    "config-key",
    "private-dir",
    "prefs",
    "backup-flag",
    "endpoint-hint",
    "root-hint",
    "url",
)


def _ordered(findings: dict) -> list:
    return [(label, findings[label]) for label in _KIND_ORDER if findings.get(label)]


@dataclass
class ApkReport:
    path: str
    package: str = ""
    package_guess: str = ""
    entries: int = 0
    scanned: list = field(default_factory=list)
    findings: dict = field(default_factory=dict)      # label -> [str]
    endpoints: list = field(default_factory=list)
    native_libs: list = field(default_factory=list)
    allow_backup: bool | None = None
    notes: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "package": self.package,
            "package_guess": self.package_guess,
            "entries": self.entries,
            "scanned": self.scanned,
            "findings": dict(_ordered(self.findings)),
            "endpoints": self.endpoints,
            "native_libs": self.native_libs,
            "allow_backup": self.allow_backup,
            "notes": self.notes,
        }


def _strings(blob: bytes):
    for match in _PRINTABLE.finditer(blob):
        yield match.group().decode("utf-8", errors="replace")


def _binary_xml_strings(blob: bytes):
    """Pull the UTF-8/UTF-16 pool out of a binary XML manifest."""
    for chunk in re.findall(rb"(?:[\x20-\x7e]\x00){4,}", blob):
        yield chunk.decode("utf-16-le", errors="replace")
    yield from _strings(blob)


def _add(findings: dict, label: str, values) -> None:
    bucket = findings.setdefault(label, [])
    for value in values:
        if value and value not in bucket and len(bucket) < 60:
            bucket.append(value)


def ordered_findings(report: "ApkReport") -> list:
    """Findings in importance order (secret locations first, URLs last)."""
    return _ordered(report.findings)


def interesting_endpoints(report: "ApkReport") -> list:
    """Only the endpoints that can carry the config (no ad/analytics noise)."""
    return [entry for entry in report.endpoints if entry.get("kind") in ("app-config", "session-check", "web-app")]


def scan_apk(path, max_members: int = 64) -> ApkReport:
    """Scan the APK and return the locations/report (never executes the app)."""
    target = Path(path)
    report = ApkReport(path=str(target))
    if not target.is_file():
        raise FileNotFoundError(target)
    if not zipfile.is_zipfile(target):
        raise ValueError(f"{target} is not a zip/APK")

    package_votes: dict = {}
    with zipfile.ZipFile(target) as archive:
        infos = archive.infolist()
        report.entries = len(infos)
        for info in infos:
            if info.filename.startswith("lib/") and info.filename.endswith(".so"):
                report.native_libs.append(info.filename)
        interesting = [
            info for info in infos
            if info.file_size <= _MAX_MEMBER
            and (
                info.filename.endswith((".dex", ".xml", ".arsc", ".json", ".js", ".properties", ".so"))
                or info.filename == "AndroidManifest.xml"
            )
        ]
        interesting.sort(key=lambda info: -info.file_size)
        for info in interesting[:max_members]:
            try:
                blob = archive.read(info)
            except (KeyError, OSError, zipfile.BadZipFile) as exc:
                report.notes.append(f"{info.filename}: {exc}")
                continue
            report.scanned.append(info.filename)
            iterator = _binary_xml_strings(blob) if info.filename.endswith(".xml") else _strings(blob)
            for text in iterator:
                for label, pattern, _why in STRING_PATTERNS:
                    for match in pattern.findall(text):
                        _add(report.findings, label, [match])
                if info.filename == "AndroidManifest.xml":
                    if text in ("true", "false"):
                        continue
                    if _PACKAGE_RE.match(text) and not text.startswith("android."):
                        package_votes[text] = package_votes.get(text, 0) + 1
            if info.filename.endswith(".xml") or info.filename.endswith(".dex"):
                flat = blob
                if b"allowBackup" in flat:
                    report.allow_backup = b'allowBackup\x00' in flat or b"allowBackup" in flat
                    if b"false" in flat and b"allowBackup" in flat:
                        report.notes.append(
                            "manifest mentions allowBackup; check the value on the device with "
                            "`adb shell dumpsys package <pkg> | grep -i backup`"
                        )

    candidates = [name for name in report.findings.get("private-dir", [])
                  if name.count(".") >= 1]
    for candidate in candidates:
        parts = [p for p in candidate.split("/") if p]
        if len(parts) >= 3:
            package = parts[2]
            package_votes[package] = package_votes.get(package, 0) + 2
    if package_votes:
        report.package_guess = max(package_votes, key=package_votes.get)

    hints = list(report.findings.get("url", []))
    hints += [hint for hint in report.findings.get("endpoint-hint", []) if hint.startswith("http")]
    for hint in hints:
        for endpoint in endpoints_mod.discover(hint, source=target.name):
            entry = endpoint.as_dict()
            if entry not in report.endpoints:
                report.endpoints.append(entry)
    if not report.endpoints and report.findings.get("endpoint-hint"):
        report.notes.append(
            "the app references the config endpoint family but no full URL was found "
            "(paths are often assembled at runtime); see `flcodes paths list`"
        )

    if not report.findings.get("config-key"):
        report.notes.append(
            "no config field names in plain text: the strings are probably obfuscated or "
            "encrypted; use a dynamic capture (HAR/logcat) instead"
        )
    return report
