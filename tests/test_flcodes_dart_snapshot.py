"""Tests for tools/dart_snapshot_hunt.py, the Flutter side of the APK."""
from __future__ import annotations

import importlib.util
import pathlib
import struct
import zipfile

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "family-link-codes" / "tools"


def load_module():
    spec = importlib.util.spec_from_file_location("dart_hunt", TOOLS / "dart_snapshot_hunt.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_elf(payload: bytes) -> bytes:
    """A minimal 64-bit little-endian ELF with a .dart.rodata section."""
    names = b"\x00.dart.rodata\x00.shstrtab\x00"
    shstr_off = 64 + 3 * 64
    body = payload
    ro_off = shstr_off + len(names)
    blob = bytearray(b"\x7fELF" + bytes([2, 1]) + bytes(58))
    struct.pack_into("<Q", blob, 0x28, 64)          # e_shoff
    struct.pack_into("<H", blob, 0x3A, 64)          # e_shentsize
    struct.pack_into("<H", blob, 0x3C, 3)           # e_shnum
    struct.pack_into("<H", blob, 0x3E, 2)           # e_shstrndx
    blob += bytes(64 - len(blob))
    # section 0: null
    blob += bytes(64)
    # section 1: .dart.rodata
    entry = bytearray(64)
    struct.pack_into("<IIQQQQ", entry, 0, 1, 1, 0, 0, ro_off, len(body))
    blob += entry
    # section 2: .shstrtab
    entry = bytearray(64)
    struct.pack_into("<IIQQQQ", entry, 0, 14, 3, 0, 0, shstr_off, len(names))
    blob += entry
    blob = bytes(blob) + names + body
    return blob


def build_apk(tmp_path, libs: dict[str, bytes], name="app.apk"):
    apk = tmp_path / name
    with zipfile.ZipFile(apk, "w") as archive:
        for path, blob in libs.items():
            archive.writestr(path, blob)
    return apk


def test_finds_the_dart_snapshot(tmp_path, capsys):
    module = load_module()
    apk = build_apk(tmp_path, {"lib/arm64-v8a/libapp.so": fake_elf(b"ParentAccessCode\x00hmac\x00")})

    assert module.main(["dart_snapshot_hunt", str(apk)]) == 0
    out = capsys.readouterr().out
    assert "Dart AOT" in out
    assert ".dart.rodata" in out


def test_counts_the_concept_strings(tmp_path, capsys):
    module = load_module()
    payload = b"parentAccessCode\x00sharedSecret\x00clockDriftTolerance\x00"
    apk = build_apk(tmp_path, {"lib/arm64-v8a/libapp.so": fake_elf(payload)})

    module.main(["dart_snapshot_hunt", str(apk)])
    out = capsys.readouterr().out
    rows = {line.split()[0]: int(line.split()[-1]) for line in out.splitlines()
            if line and line.split()[0] in ("parentaccesscode", "sharedsecret", "clockdrift")}
    assert rows["parentaccesscode"] >= 1
    assert rows["sharedsecret"] >= 1
    assert rows["clockdrift"] >= 1


def test_reads_libraries_from_the_abi_split_too(tmp_path, capsys):
    module = load_module()
    base = build_apk(tmp_path, {"classes.dex": b"x"}, "base.apk")
    split = build_apk(tmp_path, {"lib/arm64-v8a/libapp.so": fake_elf(b"kidsmanagement\x00")},
                      "config.arm64_v8a.apk")

    module.main(["dart_snapshot_hunt", str(base), str(split)])
    out = capsys.readouterr().out
    assert "Dart AOT" in out
    assert "kidsmanagement" in out


def test_says_so_when_there_are_no_libraries(tmp_path, capsys):
    module = load_module()
    apk = build_apk(tmp_path, {"classes.dex": b"x"})

    assert module.main(["dart_snapshot_hunt", str(apk)]) == 0
    assert "no lib/*.so" in capsys.readouterr().out


def test_reports_a_missing_file():
    module = load_module()
    assert module.main(["dart_snapshot_hunt", "/nope.apk"]) == 1


def test_elf_parser_rejects_non_elf():
    module = load_module()
    assert module.elf_sections(b"not an elf") == []


def test_json_output(tmp_path):
    module = load_module()
    apk = build_apk(tmp_path, {"lib/arm64-v8a/libapp.so": fake_elf(b"parentAccessCode\x00")})
    target = tmp_path / "out.json"

    assert module.main(["dart_snapshot_hunt", str(apk), "--json", str(target)]) == 0
    assert "libraries" in target.read_text()


def test_strings_only_lists_context(tmp_path, capsys):
    module = load_module()
    payload = (b"parentAccessCode\x00sharedSecret\x00accessCodeTtl\x00"
               b"clockDriftTolerance\x00unrelated\x00")
    apk = build_apk(tmp_path, {"lib/arm64-v8a/libapp.so": fake_elf(payload)})

    assert module.main(["dart_snapshot_hunt", str(apk), "--strings-only"]) == 0
    out = capsys.readouterr().out
    assert "neighbours" in out
    assert "parentAccessCode" in out


def test_keys_mode_lists_identifier_tokens(tmp_path, capsys):
    module = load_module()
    payload = (b"sharedSecret\x00accessCodeTtl\x00ttlSeconds\x00"
               b"Monday is a long sentence, not a key\x00")
    apk = build_apk(tmp_path, {"lib/arm64-v8a/libapp.so": fake_elf(payload)})

    assert module.main(["dart_snapshot_hunt", str(apk), "--keys"]) == 0
    out = capsys.readouterr().out.split()
    assert "sharedSecret" in out
    assert "ttlSeconds" in out
    assert not any("Monday" in token for token in out)
