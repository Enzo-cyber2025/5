"""Tests for flcodes.proto: the schema recovered from the binary, the wire decoder."""
from __future__ import annotations

import base64
import zipfile

import pytest

from flcodes import proto as proto_mod


def varint(value: int) -> bytes:
    out = b""
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out += bytes([byte | 0x80])
        else:
            return out + bytes([byte])


def f_str(number: int, text: str | bytes) -> bytes:
    blob = text if isinstance(text, bytes) else text.encode()
    return varint(number << 3 | 2) + varint(len(blob)) + blob


def f_int(number: int, value: int) -> bytes:
    return varint(number << 3 | 0) + varint(value)


def descriptor_blob(name="parent_access_code_data.proto",
                    package="kids.familylink.parent_access_code",
                    message="ParentAccessCodeData",
                    fields=(("shared_secret", 1, 9), ("access_code_ttl", 2, 3))) -> bytes:
    entries = b""
    for index, (field_name, number, ftype) in enumerate(fields, start=1):
        entries += f_str(2, f_str(1, field_name) + f_int(3, number) + f_int(4, 1) + f_int(5, ftype))
    body = f_str(1, message) + entries
    desc = f_str(1, name) + f_str(2, package) + f_str(4, body) + f_str(12, "proto3")
    return desc


# ------------------------------------------------------------------ wire format
def test_parses_varints_and_strings():
    blob = f_int(1, 600) + f_str(2, "hello")
    fields = proto_mod.parse_fields(blob)
    assert [(f.number, f.wire_type) for f in fields] == [(1, 0), (2, 2)]
    assert fields[0].value == 600
    assert fields[1].value == b"hello"


def test_rejects_truncated_input():
    with pytest.raises(proto_mod.ProtoError):
        proto_mod.parse_fields(b"\x0a\x40only-a-few-bytes")


def test_prefix_parser_stops_cleanly():
    blob = f_str(1, "name") + b"\x00\x00garbage"
    fields = proto_mod.parse_fields_prefix(blob)
    assert len(fields) == 1
    assert fields[0].value == b"name"


# --------------------------------------------------------------- descriptors
def test_recovers_a_descriptor_from_a_binary():
    blob = b"\x7fELF" + bytes(100) + descriptor_blob() + bytes(20)
    found = proto_mod.scan_descriptors(blob)
    assert len(found) == 1
    assert found[0].name == "parent_access_code_data.proto"
    assert found[0].package == "kids.familylink.parent_access_code"
    message = found[0].messages[0]
    assert message["name"] == "ParentAccessCodeData"
    assert [f["name"] for f in message["fields"]] == ["shared_secret", "access_code_ttl"]
    assert [f["number"] for f in message["fields"]] == [1, 2]
    assert message["fields"][0]["type"] == "string"


def test_ignores_descriptors_that_do_not_mention_the_concept():
    blob = descriptor_blob(name="unrelated.proto", package="com.example",
                           message="Whatever", fields=(("value", 1, 9),))
    assert proto_mod.scan_descriptors(blob) == []


def test_finds_descriptors_inside_an_apk():
    import pathlib
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        apk = pathlib.Path(tmp) / "app.apk"
        with zipfile.ZipFile(apk, "w") as archive:
            archive.writestr("lib/arm64-v8a/libapp.so", b"\x7fELF" + descriptor_blob() + bytes(10))
        found = proto_mod.scan_apk(str(apk))
    assert found and found[0].messages[0]["name"] == "ParentAccessCodeData"


def test_describe_is_readable():
    found = proto_mod.scan_descriptors(descriptor_blob())
    text = proto_mod.describe(found[0])
    assert "message ParentAccessCodeData:" in text
    assert "shared_secret" in text
    assert "string" in text


# ------------------------------------------------------------------- responses
def test_tree_walks_nested_messages():
    nested = f_str(1, "AIzaSyDummySecretValue12345") + f_int(2, 600)
    blob = f_str(1, nested)
    lines = proto_mod.tree(blob)
    assert any("secret-shaped" in line for line in lines)


def test_find_secret_fields_returns_the_path():
    nested = f_str(3, "AIzaSyDummySecretValue12345")
    blob = f_str(1, nested)
    found = proto_mod.find_secret_fields(blob)
    assert found == [("field 1.field 3", "AIzaSyDummySecretValue12345")]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("AIzaSyDummySecretValue12345", True),
        ("short", False),
        ("alllowercaseandlongenough123", False),
        ("A" * 60, False),
        ("has spaces and Caps1234567890", False),
    ],
)
def test_secret_shape_filter(text, expected):
    assert proto_mod.looks_like_secret(text) is expected


def test_base64_body_is_unwrapped():
    inner = f_str(1, "AIzaSyDummySecretValue12345")
    blob = base64.b64encode(inner)
    lines = proto_mod.tree(blob)
    assert any("base64" in line for line in lines)


# ------------------------------------------------------------------------ cli
def test_cli_proto_apk(tmp_path, capsys):
    from flcodes.cli import main

    apk = tmp_path / "app.apk"
    with zipfile.ZipFile(apk, "w") as archive:
        archive.writestr("lib/arm64-v8a/libapp.so", descriptor_blob())
    assert main(["proto", "apk", str(apk)]) == 0
    out = capsys.readouterr().out
    assert "ParentAccessCodeData" in out


def test_cli_proto_decode_masks_by_default(tmp_path, capsys):
    from flcodes.cli import main

    path = tmp_path / "resp.bin"
    path.write_bytes(f_str(1, f_str(1, "AIzaSyDummySecretValue12345")))
    assert main(["proto", "decode", str(path)]) == 0
    out = capsys.readouterr().out
    assert "secret-shaped field at field 1.field 1" in out
    assert "AIzaSyDummySecretValue12345" not in out


def test_cli_proto_decode_can_reveal(tmp_path, capsys):
    from flcodes.cli import main

    path = tmp_path / "resp.bin"
    path.write_bytes(f_str(1, f_str(1, "AIzaSyDummySecretValue12345")))
    assert main(["proto", "decode", str(path), "--print-secret"]) == 0
    assert "AIzaSyDummySecretValue12345" in capsys.readouterr().out


def test_cli_proto_on_a_file_without_descriptors(tmp_path, capsys):
    from flcodes.cli import main

    apk = tmp_path / "plain.apk"
    with zipfile.ZipFile(apk, "w") as archive:
        archive.writestr("classes.dex", b"nothing")
    assert main(["proto", "apk", str(apk)]) == 1
