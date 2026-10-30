"""Read the protobuf side of the Family Link app, without a .proto file.

Two jobs, both dependency-free (the wire format is a few lines of varints):

* **find the schema.** A protobuf code generator embeds a serialised
  ``FileDescriptorProto`` — message names, field names, field numbers and types —
  as a constant array in the binary. The 2.105 Flutter build keeps it inside the
  Dart snapshot, so the schema of ``ParentAccessCodeData`` and
  ``FamilyLinkAppConfig`` can be recovered from the APK itself.
* **read a response.** ``GetFamilyLinkAppConfigResponse`` is protobuf on the
  wire. Once captured (a HAR body, a logcat dump, a proxy capture), this module
  decodes it into a tree and finds the field that carries the shared secret —
  by schema name when known, by shape (base32, 16..40 chars) when not.

Nothing here talks to the network and nothing prints a secret in the clear
unless the caller asks for the raw value.
"""

from __future__ import annotations

import base64
import binascii
import re
import struct
from dataclasses import dataclass, field

__all__ = [
    "ProtoError",
    "Field",
    "parse_fields",
    "FileDescriptor",
    "decode_file_descriptor",
    "scan_descriptors",
    "find_secret_fields",
    "describe",
    "looks_like_secret",
]

WIRE_VARINT = 0
WIRE_FIXED64 = 1
WIRE_LENGTH = 2
WIRE_FIXED32 = 5

#: protobuf field types we care to name
TYPE_NAMES = {
    1: "double", 2: "float", 3: "int64", 4: "uint64", 5: "int32",
    6: "fixed64", 7: "fixed32", 8: "bool", 9: "string", 10: "group",
    11: "message", 12: "bytes", 13: "uint32", 14: "enum", 15: "sfixed32",
    16: "sfixed64", 17: "sint32", 18: "sint64",
}


class ProtoError(ValueError):
    """The bytes are not valid protobuf wire format."""


@dataclass
class Field:
    """One field on the wire."""

    number: int
    wire_type: int
    value: int | bytes

    def as_text(self) -> str:
        if self.wire_type == WIRE_LENGTH:
            assert isinstance(self.value, bytes)
            if _is_printable(self.value):
                return self.value.decode("utf-8", "replace")
            return f"<{len(self.value)} bytes>"
        return str(self.value)


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    shift = 0
    result = 0
    while True:
        if pos >= len(buf):
            raise ProtoError("truncated varint")
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift > 70:
            raise ProtoError("varint too long")


def parse_fields(buf: bytes) -> list[Field]:
    """Parse a protobuf message into its fields (no schema needed)."""
    out: list[Field] = []
    pos = 0
    size = len(buf)
    while pos < size:
        key, pos = _read_varint(buf, pos)
        number = key >> 3
        wire_type = key & 0x07
        if number == 0:
            raise ProtoError("field number 0")
        if wire_type == WIRE_VARINT:
            value, pos = _read_varint(buf, pos)
        elif wire_type == WIRE_FIXED64:
            if pos + 8 > size:
                raise ProtoError("truncated fixed64")
            value = struct.unpack_from("<Q", buf, pos)[0]
            pos += 8
        elif wire_type == WIRE_LENGTH:
            length, pos = _read_varint(buf, pos)
            if pos + length > size:
                raise ProtoError("truncated length-delimited field")
            value = buf[pos : pos + length]
            pos += length
        elif wire_type == WIRE_FIXED32:
            if pos + 4 > size:
                raise ProtoError("truncated fixed32")
            value = struct.unpack_from("<I", buf, pos)[0]
            pos += 4
        else:
            raise ProtoError(f"unsupported wire type {wire_type}")
        out.append(Field(number, wire_type, value))
    return out


def parse_fields_prefix(buf: bytes) -> list[Field]:
    """Parse as many fields as the bytes allow.

    A ``FileDescriptorProto`` is embedded in a much larger binary, so the window
    handed to the decoder almost always ends in unrelated bytes. Stopping at the
    first invalid field is what makes that usable.
    """
    out: list[Field] = []
    pos = 0
    size = len(buf)
    while pos < size:
        try:
            key, after_key = _read_varint(buf, pos)
            number = key >> 3
            wire_type = key & 0x07
            if number == 0:
                break
            if wire_type == WIRE_VARINT:
                value, pos = _read_varint(buf, after_key)
            elif wire_type == WIRE_FIXED64:
                if after_key + 8 > size:
                    break
                value = struct.unpack_from("<Q", buf, after_key)[0]
                pos = after_key + 8
            elif wire_type == WIRE_LENGTH:
                length, after_len = _read_varint(buf, after_key)
                if after_len + length > size:
                    break
                value = buf[after_len : after_len + length]
                pos = after_len + length
            elif wire_type == WIRE_FIXED32:
                if after_key + 4 > size:
                    break
                value = struct.unpack_from("<I", buf, after_key)[0]
                pos = after_key + 4
            else:
                break
        except ProtoError:
            break
        out.append(Field(number, wire_type, value))
    return out


def _is_printable(blob: bytes) -> bool:
    if not blob:
        return False
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return all(32 <= ord(char) < 127 or char in "\t\n\r" for char in text)


def looks_like_secret(text: str) -> bool:
    """The shape of the parent-access-code secret we have seen on device.

    A Google shared secret is base32-ish, mixed case, and landed between 16 and
    40 characters on every device sampled. This is a filter, not a proof: the
    caller must still confirm the code it produces against the app.
    """
    if not 16 <= len(text) <= 40:
        return False
    if not re.fullmatch(r"[A-Za-z0-9_\-=/+]+", text):
        return False
    has_upper = any(char.isupper() for char in text)
    has_digit = any(char.isdigit() for char in text)
    return has_upper and has_digit


@dataclass
class FileDescriptor:
    """A decoded ``FileDescriptorProto``, reduced to what we need."""

    name: str = ""
    package: str = ""
    messages: list[dict] = field(default_factory=list)
    enums: list[str] = field(default_factory=list)
    services: list[dict] = field(default_factory=list)

    @property
    def full_names(self) -> list[str]:
        prefix = f"{self.package}." if self.package else ""
        return [prefix + message["name"] for message in self.messages]


def _message_from_bytes(blob: bytes) -> dict | None:
    fields = parse_fields_prefix(blob)
    if not fields:
        return None
    message: dict = {"name": "", "fields": [], "nested": []}
    for item in fields:
        if item.number == 1 and item.wire_type == WIRE_LENGTH:
            message["name"] = item.value.decode("utf-8", "replace") if isinstance(item.value, bytes) else ""
        elif item.number == 2 and item.wire_type == WIRE_LENGTH and isinstance(item.value, bytes):
            entry = {"name": "", "number": 0, "type": "", "label": ""}
            labels = {1: "optional", 2: "required", 3: "repeated"}
            for sub in parse_fields_prefix(item.value):
                value = sub.value
                if sub.number == 1 and isinstance(value, bytes):
                    entry["name"] = value.decode("utf-8", "replace")
                elif sub.number == 3 and not isinstance(value, bytes):
                    entry["number"] = int(value)
                elif sub.number == 4 and not isinstance(value, bytes):
                    entry["label"] = labels.get(int(value), "")
                elif sub.number == 5 and not isinstance(value, bytes):
                    entry["type"] = TYPE_NAMES.get(int(value), str(value))
                elif sub.number == 6 and isinstance(value, bytes):
                    entry["type"] = value.decode("utf-8", "replace")
            if entry["name"]:
                message["fields"].append(entry)
        elif item.number == 3 and item.wire_type == WIRE_LENGTH and isinstance(item.value, bytes):
            nested = _message_from_bytes(item.value)
            if nested:
                message["nested"].append(nested)
    return message if message["name"] else None


def decode_file_descriptor(blob: bytes) -> FileDescriptor | None:
    """Decode a serialised ``FileDescriptorProto``. ``None`` when it is not one."""
    fields = parse_fields_prefix(blob)
    if not fields:
        return None
    descriptor = FileDescriptor()
    for item in fields:
        value = item.value
        if item.number == 1 and item.wire_type == WIRE_LENGTH and isinstance(value, bytes):
            descriptor.name = value.decode("utf-8", "replace")
        elif item.number == 2 and item.wire_type == WIRE_LENGTH and isinstance(value, bytes):
            descriptor.package = value.decode("utf-8", "replace")
        elif item.number == 4 and item.wire_type == WIRE_LENGTH and isinstance(value, bytes):
            message = _message_from_bytes(value)
            if message:
                descriptor.messages.append(message)
        elif item.number == 5 and item.wire_type == WIRE_LENGTH and isinstance(value, bytes):
            for sub in _safe_fields(value):
                if sub.number == 1 and isinstance(sub.value, bytes):
                    descriptor.enums.append(sub.value.decode("utf-8", "replace"))
        elif item.number == 6 and item.wire_type == WIRE_LENGTH and isinstance(value, bytes):
            service = {"name": "", "methods": []}
            for sub in _safe_fields(value):
                if sub.number == 1 and isinstance(sub.value, bytes):
                    service["name"] = sub.value.decode("utf-8", "replace")
                elif sub.number == 2 and isinstance(sub.value, bytes):
                    method = {}
                    for deeper in _safe_fields(sub.value):
                        if deeper.number == 1 and isinstance(deeper.value, bytes):
                            method["name"] = deeper.value.decode("utf-8", "replace")
                        elif deeper.number == 2 and isinstance(deeper.value, bytes):
                            method["input"] = deeper.value.decode("utf-8", "replace")
                        elif deeper.number == 3 and isinstance(deeper.value, bytes):
                            method["output"] = deeper.value.decode("utf-8", "replace")
                    if method:
                        service["methods"].append(method)
            if service["name"]:
                descriptor.services.append(service)
    if not descriptor.name and not descriptor.messages:
        return None
    return descriptor


def _safe_fields(blob: bytes) -> list[Field]:
    return parse_fields_prefix(blob)


#: how far past the start of a candidate the parser is allowed to read
_MAX_DESCRIPTOR = 512 * 1024


def scan_descriptors(
    blob: bytes,
    needles: tuple[str, ...] = ("parent_access_code", "familylink", "kidsmanagement"),
    budget: int = 4_000_000,
) -> list[FileDescriptor]:
    """Find every embedded ``FileDescriptorProto`` that mentions the concept.

    Scanning a 47 MB shared object byte by byte is too slow, so the search starts
    from the ``.proto`` literals instead: the file name is the first field of a
    descriptor, which puts the start a few dozen bytes before it.
    """
    found: list[FileDescriptor] = []
    seen: set[tuple[str, str]] = set()
    cursor = 0
    examined = 0
    while examined < budget:
        hit = blob.find(b".proto", cursor)
        if hit == -1:
            break
        cursor = hit + 6
        # the name field is `0x0A <len> <name>`; the name is short
        for start in range(max(0, hit - 160), hit):
            if blob[start] != 0x0A:
                continue
            try:
                length, after = _read_varint(blob, start + 1)
            except ProtoError:
                continue
            if not 4 <= length <= 200:
                continue
            if start + 1 + (after - start - 1) + length != hit + 6:
                continue
            window = blob[start : start + _MAX_DESCRIPTOR]
            descriptor = decode_file_descriptor(window)
            if descriptor is None or not descriptor.name.endswith(".proto"):
                continue
            lowered = (descriptor.name + " " + descriptor.package).lower()
            if not any(needle in lowered for needle in needles) and not any(
                needle in _message_text(descriptor).lower() for needle in needles
            ):
                continue
            key = (descriptor.name, descriptor.package)
            if key in seen:
                continue
            seen.add(key)
            found.append(descriptor)
            break
        examined = cursor
    return found


def scan_apk(path: str, extras: list[str] | None = None,
             needles: tuple[str, ...] = ("parent_access_code", "familylink", "kidsmanagement"),
             ) -> list[FileDescriptor]:
    """Scan the shared objects of an APK (and of extra APKs) for descriptors."""
    import zipfile

    results: list[FileDescriptor] = []
    seen: set[tuple[str, str]] = set()
    for candidate in [path, *(extras or [])]:
        try:
            archive = zipfile.ZipFile(candidate)
        except (OSError, zipfile.BadZipFile):
            continue
        with archive:
            for name in archive.namelist():
                if not name.endswith(".so"):
                    continue
                info = archive.getinfo(name)
                if info.file_size > 96 * 1024 * 1024:
                    continue
                for descriptor in scan_descriptors(archive.read(name), needles):
                    key = (descriptor.name, descriptor.package)
                    if key in seen:
                        continue
                    seen.add(key)
                    results.append(descriptor)
    return results


def _message_text(descriptor: FileDescriptor) -> str:
    parts: list[str] = []
    stack = list(descriptor.messages)
    while stack:
        message = stack.pop()
        parts.append(message.get("name", ""))
        parts.extend(entry.get("name", "") for entry in message.get("fields", []))
        stack.extend(message.get("nested", []))
    return " ".join(parts)


def describe(descriptor: FileDescriptor) -> str:
    """Human readable schema, in the order protoc would show it."""
    lines = [f"file: {descriptor.name} (package {descriptor.package or '-'})"]
    for message in descriptor.messages:
        lines.extend(_describe_message(message, indent=0))
    for service in descriptor.services:
        lines.append(f"service {service['name']}:")
        for method in service["methods"]:
            lines.append(
                f"  rpc {method.get('name', '?')}({method.get('input', '?')}) "
                f"-> {method.get('output', '?')}"
            )
    return "\n".join(lines)


def _describe_message(message: dict, indent: int) -> list[str]:
    pad = "  " * indent
    lines = [f"{pad}message {message['name']}:"]
    for entry in message.get("fields", []):
        label = entry.get("label") or ""
        lines.append(
            f"{pad}  {entry['number']:>3}  {entry['type']:<10} "
            f"{entry['name']}{'  [' + label + ']' if label else ''}"
        )
    for nested in message.get("nested", []):
        lines.extend(_describe_message(nested, indent + 1))
    return lines


def find_secret_fields(blob: bytes, depth: int = 0) -> list[tuple[str, str]]:
    """Walk a response and return ``(path, value)`` for secret-shaped strings."""
    out: list[tuple[str, str]] = []
    if depth > 6:
        return out
    try:
        fields = parse_fields(blob)
    except ProtoError:
        return out
    for item in fields:
        value = item.value
        if not isinstance(value, bytes):
            continue
        if _is_printable(value):
            text = value.decode("utf-8", "replace")
            if looks_like_secret(text):
                out.append((f"field {item.number}", text))
            continue
        for path, secret in find_secret_fields(value, depth + 1):
            out.append((f"field {item.number}.{path}", secret))
    return out


def mask(secret: str) -> str:
    """``AIzaSy…45``: enough to recognise the key, not enough to use it."""
    if len(secret) <= 10:
        return "…"
    return f"{secret[:6]}…{secret[-2:]}"


def tree(blob: bytes, depth: int = 0, max_depth: int = 4, reveal: bool = False) -> list[str]:
    """A readable dump of an unknown message, nested messages included.

    Secret-shaped strings are masked unless ``reveal`` is set: this output lands
    in CI logs and pull-request comments.
    """
    lines: list[str] = []
    pad = "  " * depth
    try:
        fields = parse_fields(blob)
    except ProtoError:
        decoded = _maybe_base64(blob)
        if decoded is not None:
            inner = tree(decoded, depth, max_depth, reveal)
            return [f"{pad}(base64, {len(decoded)} bytes decoded)"] + inner
        text = blob[:40].decode("utf-8", "replace") if _is_printable(blob[:40]) else ""
        return [f"{pad}({len(blob)} binary bytes)" + (f": {text}" if text else "")]
    for item in fields:
        value = item.value
        if isinstance(value, bytes):
            if _is_printable(value):
                text = value.decode("utf-8", "replace")
                if looks_like_secret(text):
                    shown = text if reveal else mask(text)
                    lines.append(f"{pad}{item.number} = \"{shown}\"  <- secret-shaped")
                else:
                    lines.append(f"{pad}{item.number} = \"{text}\"")
            elif depth < max_depth:
                lines.append(f"{pad}{item.number} {{")
                lines.extend(tree(value, depth + 1, max_depth, reveal))
                lines.append(f"{pad}}}")
            else:
                lines.append(f"{pad}{item.number} = <{len(value)} bytes>")
        else:
            lines.append(f"{pad}{item.number} = {value}")
    return lines


def _maybe_base64(blob: bytes) -> bytes | None:
    """Decode a base64 body (HAR captures store protobuf that way)."""
    stripped = bytes(blob).strip()
    if len(stripped) < 8:
        return None
    try:
        decoded = base64.b64decode(stripped, validate=True)
    except (binascii.Error, ValueError):
        return None
    return decoded or None
