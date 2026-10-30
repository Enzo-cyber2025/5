#!/usr/bin/env python3
"""Tap "Back up my data" on the Android full-backup confirmation dialog.

``adb backup`` cannot run unattended: the device shows a confirmation dialog
(``com.android.backupconfirm``) and nobody can press it in CI. This helper
dumps the current UI with ``uiautomator``, finds the accept button by text,
resource-id or position, and taps it with ``adb shell input tap``.

    python tools/accept_backup_dialog.py            # one attempt
    python tools/accept_backup_dialog.py --retries 20 --interval 2

Exit code 0 when a tap was sent, 1 when no dialog was found.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ACCEPT_TEXTS = (
    "back up my data", "back up", "backup", "aceitar", "fazer backup",
    "allow", "permitir", "ok", "continue", "continuar",
)
ACCEPT_IDS = (
    "button_ok", "button_accept", "button_allow", "button_positive", "ok",
    "confirm", "backup", "allow_button",
)
_DEVICE = ""
_BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def adb(*args, timeout=60):
    command = ["adb"] + (["-s", _DEVICE] if _DEVICE else []) + list(args)
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout)


def dump_ui() -> str:
    adb("shell", "uiautomator", "dump", "/sdcard/window_dump.xml")
    return adb("shell", "cat", "/sdcard/window_dump.xml").stdout or ""


def _centre(bounds: str):
    match = _BOUNDS.search(bounds or "")
    if not match:
        return None
    x1, y1, x2, y2 = (int(value) for value in match.groups())
    return (x1 + x2) // 2, (y1 + y2) // 2


def find_button(xml: str):
    """Return ``(x, y, reason)`` for the accept button, or ``None``."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    candidates = []
    for node in root.iter("node"):
        text = (node.get("text") or "").strip()
        resource_id = (node.get("resource-id") or "").split("/")[-1].lower()
        label = text.lower()
        score = 0
        if label in ACCEPT_TEXTS:
            score = 3
        elif any(word in label for word in ACCEPT_TEXTS) and "cancel" not in label:
            score = 2
        if resource_id in ACCEPT_IDS:
            score = max(score, 3)
        if score and node.get("clickable") == "true":
            centre = _centre(node.get("bounds", ""))
            if centre:
                candidates.append((score, centre, text or resource_id))
    if not candidates:
        return None
    candidates.sort(key=lambda item: -item[0])
    score, (x, y), label = candidates[0]
    return x, y, f"{label!r} (score {score})"


def main(argv=None) -> int:
    global _DEVICE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default="")
    parser.add_argument("--retries", type=int, default=10)
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args(argv)
    _DEVICE = args.serial

    for attempt in range(1, args.retries + 1):
        xml = dump_ui()
        found = find_button(xml)
        if found:
            x, y, reason = found
            print(f"attempt {attempt}: tapping {reason} at ({x},{y})", flush=True)
            adb("shell", "input", "tap", str(x), str(y))
            return 0
        # fallback: the accept button is usually focused; ENTER activates it
        print(f"attempt {attempt}: no dialog node, sending ENTER", flush=True)
        adb("shell", "input", "keyevent", "66")
        time.sleep(args.interval)
    return 1


if __name__ == "__main__":
    sys.exit(main())
