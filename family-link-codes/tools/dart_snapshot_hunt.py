#!/usr/bin/env python3
"""Take the Flutter side of the real Family Link APK apart.

The 2.104 build is Flutter (``.flutter.standalone.HomeActivity``), so the code
that matters is not in ``classes*.dex``: it is the Dart AOT snapshot inside
``libapp.so``. Flutter's release builds keep the ELF ``.dart.*`` sections, and —
unless the app was built with ``--obfuscate`` — the snapshot keeps its own symbol
and string tables.

This script answers, with numbers:

  * is ``libapp.so`` really a Dart AOT snapshot (ELF sections, version)?
  * do the names from the public write-ups live here instead of in the dex?
  * which strings around the parent-access-code concept survive?
  * does the snapshot carry symbol names such as ``ParentAccessCode``?

    tools/dart_snapshot_hunt.py /path/base.apk [--json out.json]

No key material is printed and nothing from the APK is executed.
"""
from __future__ import annotations

import json
import re
import struct
import sys
import zipfile

PRINTABLE = re.compile(rb"[ -~]{5,}")

CONCEPT = (
    "parentaccesscode",
    "parent_access_code",
    "accesscode",
    "sharedsecret",
    "shared_secret",
    "clockdrift",
    "totp",
    "hmac",
    "base32",
    "familylinkappconfig",
    "family_link_app_config",
    "kidsmanagement",
)

SYMBOL_HINTS = (
    "ParentAccessCode",
    "AccessCode",
    "SharedSecret",
    "FamilyLinkAppConfig",
    "Totp",
    "TOTP",
    "Hmac",
    "HMAC",
)


def dart_shared_objects(apk: str) -> dict[str, bytes]:
    """The Flutter native libraries, wherever the bundle keeps them."""
    out: dict[str, bytes] = {}
    with zipfile.ZipFile(apk) as archive:
        for name in archive.namelist():
            if not name.startswith("lib/"):
                continue
            base = name.rsplit("/", 1)[-1]
            if base in ("libapp.so", "libflutter.so", "libdartjni.so"):
                out[name] = archive.read(name)
    return out


def elf_sections(blob: bytes) -> list[tuple[str, int, int]]:
    """(name, offset, size) for every section, for 64-bit little-endian ELF."""
    if blob[:4] != b"\x7fELF":
        return []
    if blob[4] != 2 or blob[5] != 1:  # 64-bit, little endian
        return []
    (e_shoff,) = struct.unpack_from("<Q", blob, 0x28)
    (e_shentsize,) = struct.unpack_from("<H", blob, 0x3A)
    (e_shnum,) = struct.unpack_from("<H", blob, 0x3C)
    (e_shstrndx,) = struct.unpack_from("<H", blob, 0x3E)
    if not e_shoff or not e_shnum:
        return []
    headers = []
    for index in range(e_shnum):
        pos = e_shoff + index * e_shentsize
        name_off, sh_type, _flags, _addr, off, size = struct.unpack_from("<IIQQQQ", blob, pos)
        headers.append((name_off, sh_type, off, size))
    if e_shstrndx >= len(headers):
        return []
    _name_off, _type, str_off, str_size = headers[e_shstrndx]
    names = blob[str_off : str_off + str_size]
    sections = []
    for name_off, _type, off, size in headers:
        end = names.find(b"\x00", name_off)
        label = names[name_off:end].decode("ascii", "ignore") if end != -1 else ""
        sections.append((label, off, size))
    return sections


def strings_of(blob: bytes) -> list[str]:
    return [m.decode("ascii", "ignore") for m in PRINTABLE.findall(blob)]


def hunt(apk: str, extra: list[str] | None = None) -> dict:
    """Scan the base APK and any extra APKs (the ABI split often holds the libs)."""
    report: dict = {"apk": apk, "sources": [apk], "libraries": [], "concept": {},
                    "symbols": {}, "notes": []}
    libs = dart_shared_objects(apk)
    for other in extra or []:
        report["sources"].append(other)
        for name, blob in dart_shared_objects(other).items():
            libs.setdefault(name, blob)
    if not libs:
        report["notes"].append("no lib/*.so in the base APK (they are probably in the ABI split)")
        return report

    interested: list[str] = []
    for name, blob in sorted(libs.items()):
        entry = {"name": name, "bytes": len(blob)}
        sections = elf_sections(blob)
        dart_sections = [(s, o, z) for (s, o, z) in sections if s.startswith(".dart")]
        entry["elf"] = bool(sections)
        entry["dart_sections"] = [{"name": s, "size": z} for (s, _o, z) in dart_sections]
        entry["is_dart_snapshot"] = bool(dart_sections)
        report["libraries"].append(entry)
        if dart_sections or name.endswith("libapp.so"):
            interested.append(name)

    blob_all = b"".join(libs[n] for n in interested)
    text_all = "\n".join(strings_of(blob_all)).lower()
    for key in CONCEPT:
        report["concept"][key] = text_all.count(key)

    upper_all = "\n".join(strings_of(blob_all))
    for hint in SYMBOL_HINTS:
        # symbol names are case sensitive: count exact occurrences
        report["symbols"][hint] = upper_all.count(hint)

    # strings that carry the concept, with their exact spelling
    hits: dict[str, int] = {}
    for line in strings_of(blob_all):
        low = line.lower()
        if any(word in low for word in ("parentaccesscode", "sharedsecret", "clockdrift",
                                        "familylinkappconfig", "parent_access_code")):
            hits[line[:120]] = hits.get(line[:120], 0) + 1
    report["strings"] = dict(sorted(hits.items(), key=lambda kv: -kv[1])[:60])
    return report


def render(report: dict) -> str:
    out = [f"apk: {report['apk']}"]
    for source in report.get("sources", [])[1:]:
        out.append(f"also: {source}")
    if not report["libraries"]:
        out.extend(f"note: {n}" for n in report["notes"])
        return "\n".join(out)
    out.append("== native libraries in the APK ==")
    for lib in report["libraries"]:
        tag = "Dart AOT" if lib["is_dart_snapshot"] else "ELF"
        out.append(f"{lib['bytes']:>10}  {lib['name']}  ({tag})")
        for section in lib["dart_sections"]:
            out.append(f"{section['size']:>10}    {section['name']}")
    out.append("")
    out.append("== concept, case-insensitive, inside libapp.so ==")
    for key, count in report["concept"].items():
        out.append(f"{key:<24} {count}")
    out.append("")
    out.append("== symbol names (case sensitive) ==")
    for key, count in report["symbols"].items():
        out.append(f"{key:<24} {count}")
    out.append("")
    out.append("== strings that carry the concept ==")
    for text, count in report["strings"].items():
        out.append(f"{count:>4}  {text}")
    if not report["strings"]:
        out.append("(none: the Dart snapshot keeps no readable name for this)")
    sections = sum(1 for lib in report["libraries"] if lib["is_dart_snapshot"])
    out.append("")
    out.append(f"verdict: {sections} Dart AOT snapshot(s) found"
               + ("; the concept is named inside it"
                  if sum(report["concept"].values()) else
                  "; the concept is not named in the snapshot"))
    return "\n".join(out)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    extra = [a for a in argv[2:] if a.endswith(".apk") and a != "--json"]
    try:
        report = hunt(argv[1], extra)
    except Exception as error:  # noqa: BLE001 - a bad APK must not fail CI
        print(f"could not analyse {argv[1]}: {error}")
        return 1
    print(render(report))
    if "--json" in argv:
        target = argv[argv.index("--json") + 1]
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
