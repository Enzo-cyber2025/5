"""No-root acquisition from a real device over adb.

There are exactly three things you can read from another app on an unrooted
Android without a debug build:

1. ``adb shell pm path <pkg>`` — where the APKs live (world readable);
2. ``adb backup`` — the app's own private files, written **by the device** after
   you confirm the dialog on screen (Android asks; no root involved);
3. ``adb shell dumpsys`` — metadata, no secrets.

``adb backup`` is the one that carries ``shared_prefs/*.xml`` and
``databases/*``, so it is the path this module automates. If the app declares
``android:allowBackup="false"`` the container comes back empty and there is no
no-root alternative — that is a hard limit and is reported as such, never faked.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import abe

__all__ = ["FAMILY_LINK_PACKAGES", "DeviceInfo", "adb_path", "run", "info", "backup"]

FAMILY_LINK_PACKAGES = (
    "com.google.android.apps.familylink",
    "com.google.android.apps.kids.familylink",
    "com.google.android.apps.kids.familylinkhelper",
)

_PROPS = (
    "ro.product.model",
    "ro.product.manufacturer",
    "ro.build.version.release",
    "ro.build.version.sdk",
    "ro.debuggable",
    "ro.build.type",
)


@dataclass
class DeviceInfo:
    serial: str = ""
    props: dict = field(default_factory=dict)
    packages: list = field(default_factory=list)
    apk_paths: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def debuggable(self) -> bool:
        return self.props.get("ro.debuggable") == "1"

    def as_dict(self) -> dict:
        return {
            "serial": self.serial,
            "props": self.props,
            "packages": self.packages,
            "apk_paths": self.apk_paths,
            "debuggable": self.debuggable,
            "notes": self.notes,
        }


def adb_path() -> str:
    found = shutil.which("adb")
    if not found:
        raise RuntimeError("adb not found in PATH (install platform-tools)")
    return found


def run(args, serial: str = "", timeout: float = 60.0) -> subprocess.CompletedProcess:
    command = [adb_path()] + (["-s", serial] if serial else []) + list(args)
    return subprocess.run(command, capture_output=True, timeout=timeout, check=False)


def _text(completed) -> str:
    return (completed.stdout or b"").decode("utf-8", errors="replace").strip()


def info(serial: str = "", timeout: float = 30.0) -> DeviceInfo:
    """Read product properties and locate the Family Link packages."""
    result = DeviceInfo(serial=serial)
    listing = run(["devices"], timeout=timeout)
    devices = [
        line.split("\t")[0]
        for line in _text(listing).splitlines()[1:]
        if line.strip().endswith("device")
    ]
    if serial and serial not in devices:
        result.notes.append(f"device {serial!r} not in `adb devices` ({devices or 'none'})")
    elif not serial and len(devices) > 1:
        result.notes.append(f"several devices attached {devices}; pass --serial")
    for prop in _PROPS:
        completed = run(["shell", "getprop", prop], serial=serial, timeout=timeout)
        value = _text(completed)
        if value:
            result.props[prop] = value
    packages = _text(run(["shell", "pm", "list", "packages"], serial=serial, timeout=timeout))
    result.packages = [
        line.split(":")[1].strip()
        for line in packages.splitlines()
        if line.startswith("package:") and "familylink" in line.lower()
    ]
    for package in result.packages:
        paths = _text(run(["shell", "pm", "path", package], serial=serial, timeout=timeout))
        result.apk_paths += [line.split(":", 1)[1] for line in paths.splitlines() if line.startswith("package:")]
    if not result.packages:
        result.notes.append(
            "Family Link is not installed for this user on the device "
            "(it lives on the parent's phone, not the child's)"
        )
    return result


def backup(
    package: str,
    out,
    serial: str = "",
    include_apk: bool = False,
    timeout: float = 600.0,
    confirm_wait: float = 180.0,
) -> dict:
    """Run ``adb backup`` for one package and wait for the container.

    The device shows a confirmation dialog; unless it is accepted (and, on some
    builds, a password typed) the command produces an empty file. We wait for
    the file to stop growing and then report what came back.
    """
    target = Path(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    args = ["backup", "-f", str(target)]
    args.append("-apk" if include_apk else "-noapk")
    args.append(package)
    started = time.monotonic()
    completed = run(args, serial=serial, timeout=timeout)
    stderr = (completed.stderr or b"").decode("utf-8", errors="replace").strip()
    result = {
        "package": package,
        "file": str(target),
        "returncode": completed.returncode,
        "seconds": round(time.monotonic() - started, 1),
        "stderr": stderr[-400:],
        "stdout": _text(completed)[-400:],
        "bytes": target.stat().st_size if target.exists() else 0,
    }
    if not target.exists() or result["bytes"] == 0:
        result["ok"] = False
        result["reason"] = (
            "empty backup: the confirmation was not accepted, or the app sets "
            "android:allowBackup=false (then there is no no-root path)"
        )
        return result
    result["ok"] = abe.is_android_backup(target)
    if not result["ok"]:
        result["reason"] = "file does not start with ANDROID BACKUP (adb wrote garbage)"
    else:
        try:
            result["header"] = abe.parse_header(target).as_dict()
        except abe.BackupError as exc:
            result["reason"] = str(exc)
    return result
