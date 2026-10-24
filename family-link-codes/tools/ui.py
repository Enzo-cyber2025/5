#!/usr/bin/env python3
"""Small UI-driver for Android devices over adb (no Appium, no root).

Used by the Play Store flow: sign in, search, install, accept dialogs. Everything
goes through ``uiautomator dump`` + ``adb shell input``, so it works on a stock
emulator image.

    python tools/ui.py dump
    python tools/ui.py find "Sign in" --click
    python tools/ui.py type "someone@example.com"
    python tools/ui.py shot /tmp/screen.png
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

SERIAL = ""
BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def adb(*args, timeout=90, binary=False):
    command = ["adb"] + (["-s", SERIAL] if SERIAL else []) + [str(a) for a in args]
    result = subprocess.run(command, capture_output=True, timeout=timeout)
    if binary:
        return result.stdout
    return result.stdout.decode("utf-8", errors="replace")


def dump_xml() -> str:
    adb("shell", "uiautomator", "dump", "/sdcard/ui.xml")
    return adb("shell", "cat", "/sdcard/ui.xml")


def nodes(xml: str):
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    return list(root.iter("node"))


def label(node) -> str:
    return " ".join(
        part for part in (
            node.get("text") or "", node.get("content-desc") or "",
            (node.get("resource-id") or "").split("/")[-1],
        ) if part
    ).strip()


def centre(node):
    match = BOUNDS.search(node.get("bounds") or "")
    if not match:
        return None
    x1, y1, x2, y2 = (int(v) for v in match.groups())
    return (x1 + x2) // 2, (y1 + y2) // 2


def find(xml: str, pattern: str, clickable_only: bool = False):
    """Return ``(node, x, y)`` for the first match, or ``None``."""
    compiled = re.compile(pattern, re.IGNORECASE)
    fallback = None
    for node in nodes(xml):
        if not label(node) or not compiled.search(label(node)):
            continue
        point = centre(node)
        if point is None:
            continue
        if node.get("clickable") == "true" or not clickable_only:
            if node.get("clickable") == "true":
                return node, point[0], point[1]
            fallback = fallback or (node, point[0], point[1])
    return fallback


def tap(x: int, y: int) -> None:
    adb("shell", "input", "tap", str(x), str(y))


def text_input(value: str) -> None:
    escaped = value.replace(" ", "%s").replace("&", "\\&").replace("'", "\\'")
    adb("shell", "input", "text", escaped)


def key(name: str) -> None:
    adb("shell", "input", "keyevent", name)


def wait_for(pattern: str, timeout: float = 60.0, interval: float = 2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = find(dump_xml(), pattern)
        if found:
            return found
        time.sleep(interval)
    return None


def screenshot(path: str) -> bool:
    data = adb("exec-out", "screencap", "-p", binary=True, timeout=120)
    if not data:
        return False
    with open(path, "wb") as handle:
        handle.write(data)
    return True


def main(argv=None) -> int:
    global SERIAL
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default="")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("dump")
    find_p = sub.add_parser("find")
    find_p.add_argument("pattern")
    find_p.add_argument("--click", action="store_true")
    find_p.add_argument("--clickable-only", action="store_true")
    type_p = sub.add_parser("type")
    type_p.add_argument("text")
    key_p = sub.add_parser("key")
    key_p.add_argument("name")
    shot_p = sub.add_parser("shot")
    shot_p.add_argument("path")
    tap_p = sub.add_parser("tap")
    tap_p.add_argument("x", type=int)
    tap_p.add_argument("y", type=int)
    wait_p = sub.add_parser("wait")
    wait_p.add_argument("pattern")
    wait_p.add_argument("--timeout", type=float, default=60)
    wait_p.add_argument("--click", action="store_true")
    args = parser.parse_args(argv)
    SERIAL = args.serial

    if args.action == "dump":
        print(dump_xml())
        return 0
    if args.action == "find":
        found = find(dump_xml(), args.pattern, args.clickable_only)
        if not found:
            return 1
        node, x, y = found
        print(f"{label(node)!r} at ({x},{y})")
        if args.click:
            tap(x, y)
        return 0
    if args.action == "type":
        text_input(args.text)
        return 0
    if args.action == "key":
        key(args.name)
        return 0
    if args.action == "tap":
        tap(args.x, args.y)
        return 0
    if args.action == "shot":
        return 0 if screenshot(args.path) else 1
    if args.action == "wait":
        found = wait_for(args.pattern, timeout=args.timeout)
        if not found:
            print(f"timeout waiting for {args.pattern!r}", file=sys.stderr)
            return 1
        node, x, y = found
        print(f"{label(node)!r} at ({x},{y})")
        if args.click:
            tap(x, y)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
