"""Android Backup (``adb backup``) parser — the no-root acquisition path.

``adb backup`` is the only documented way to read another app's private files on
an unrooted device: the device itself (not adb) writes the container, so no root
is needed — just USB debugging plus the on-device confirmation dialog.

The container is not a zip. Its layout (``com.android.server.backup``,
``BackupManagerService``) is:

    ANDROID BACKUP\\n
    <version>\\n            1..5
    <compressed>\\n         0 or 1
    <encryption>\\n         "none" or "AES-256"
    [only when encrypted]
      <user salt hex>\\n   PBKDF2 salt for the user password
      <ck salt hex>\\n     PBKDF2 salt for the master-key checksum
      <rounds>\\n
      <user IV hex>\\n
      <master key blob hex>\\n
    <payload>              AES-256-CBC, then zlib, then a tar stream

Everything here is stdlib only (``hashlib.pbkdf2_hmac`` + the local AES), so the
extractor also runs on an air-gapped host. Semantics checked against
``nelenkov/android-backup-extractor`` (``AndroidBackup.java``) in the tests.
"""

from __future__ import annotations

import hashlib
import io
import struct
import tarfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from . import aes

__all__ = [
    "MAGIC",
    "ABEHeader",
    "ExtractResult",
    "is_android_backup",
    "parse_header",
    "decrypt_master_key",
    "extract",
    "list_apps",
]

MAGIC = b"ANDROID BACKUP\n"
_ALGORITHMS = ("none", "AES-256")
_MAX_HEADER_LINE = 4096


class BackupError(RuntimeError):
    """The file is not a valid Android backup, or the password is wrong."""


@dataclass
class ABEHeader:
    version: int
    compressed: bool
    encryption: str
    payload_offset: int
    user_salt: bytes = b""
    checksum_salt: bytes = b""
    rounds: int = 0
    user_iv: bytes = b""
    master_key_blob: bytes = b""

    @property
    def encrypted(self) -> bool:
        return self.encryption == "AES-256"

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "compressed": self.compressed,
            "encryption": self.encryption,
            "encrypted": self.encrypted,
            "rounds": self.rounds,
            "payload_offset": self.payload_offset,
        }


@dataclass
class ExtractResult:
    header: ABEHeader
    members: list = field(default_factory=list)
    apps: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    tar_bytes: int = 0

    def as_dict(self) -> dict:
        return {
            "header": self.header.as_dict(),
            "members": len(self.members),
            "apps": self.apps,
            "tar_bytes": self.tar_bytes,
            "notes": self.notes,
        }


def is_android_backup(path) -> bool:
    """True when the file starts with the ``ANDROID BACKUP`` magic."""
    try:
        with open(path, "rb") as handle:
            return handle.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def _read_line(stream) -> str:
    line = stream.readline(_MAX_HEADER_LINE)
    if not line.endswith(b"\n"):
        raise BackupError("truncated backup header")
    return line[:-1].decode("ascii", errors="strict")


def parse_header(path) -> ABEHeader:
    """Parse the text header and return it with the payload offset."""
    with open(path, "rb") as stream:
        if stream.read(len(MAGIC)) != MAGIC:
            raise BackupError("not an Android backup (bad magic)")
        version = int(_read_line(stream))
        if not 1 <= version <= 5:
            raise BackupError(f"unsupported backup version {version}")
        compressed = _read_line(stream).strip() == "1"
        encryption = _read_line(stream).strip()
        if encryption not in _ALGORITHMS:
            raise BackupError(f"unsupported encryption {encryption!r}")
        header = ABEHeader(
            version=version,
            compressed=compressed,
            encryption=encryption,
            payload_offset=0,
        )
        if header.encrypted:
            header.user_salt = bytes.fromhex(_read_line(stream))
            header.checksum_salt = bytes.fromhex(_read_line(stream))
            header.rounds = int(_read_line(stream))
            header.user_iv = bytes.fromhex(_read_line(stream))
            header.master_key_blob = bytes.fromhex(_read_line(stream))
            if len(header.user_salt) != 64:
                raise BackupError("invalid user salt length")
            if len(header.user_iv) != aes.BLOCK_SIZE:
                raise BackupError("invalid user IV length")
        header.payload_offset = stream.tell()
        return header


def _password_bytes(password: str, ascii_only: bool) -> bytes:
    """Android v1 read the password as ASCII; v2+ as UTF-8."""
    if ascii_only:
        return bytes(ord(char) & 0xFF for char in password)
    return password.encode("utf-8")


def _checksum(master_key: bytes, salt: bytes, rounds: int, ascii_only: bool) -> bytes:
    """PBKDF2 of the master key, using Android's char->bytes conversion."""
    if ascii_only:
        password = bytes(master_key)  # low byte of every char == the byte
    else:
        password = "".join(chr(byte) for byte in master_key).encode("utf-8")
    return hashlib.pbkdf2_hmac("sha1", password, salt, rounds, 32)


def decrypt_master_key(header: ABEHeader, password: str) -> tuple:
    """Return ``(master_key, iv)`` or raise :class:`BackupError`."""
    if not header.encrypted:
        raise BackupError("backup is not encrypted")
    user_key = hashlib.pbkdf2_hmac(
        "sha1",
        _password_bytes(password, ascii_only=False),
        header.user_salt,
        header.rounds,
        32,
    )
    blob = aes.cbc_decrypt(user_key, header.user_iv, header.master_key_blob)
    offset = 0
    try:
        iv_len = blob[offset]
        offset += 1
        iv = blob[offset:offset + iv_len]
        offset += iv_len
        key_len = blob[offset]
        offset += 1
        master_key = blob[offset:offset + key_len]
        offset += key_len
        checksum_len = blob[offset]
        offset += 1
        stored = blob[offset:offset + checksum_len]
    except IndexError as exc:  # pragma: no cover - defensive
        raise BackupError("malformed master key blob") from exc
    if len(iv) != aes.BLOCK_SIZE or len(master_key) != 32 or len(stored) != 32:
        raise BackupError("malformed master key blob (wrong password?)")

    # v2+ hashes with UTF-8, v1 with ASCII; accept either, like ABE does.
    for ascii_only in ((False, True) if header.version >= 2 else (True, False)):
        candidates = {_checksum(master_key, header.checksum_salt, header.rounds, ascii_only)}
        if ascii_only:
            candidates.add(
                hashlib.pbkdf2_hmac("sha1", master_key, header.checksum_salt, header.rounds, 32)
            )
        if stored in candidates:
            return master_key, iv
    raise BackupError("master key checksum mismatch (wrong password?)")


def _payload(path, header: ABEHeader, password: str | None) -> bytes:
    data = Path(path).read_bytes()[header.payload_offset:]
    if header.encrypted:
        if not password:
            raise BackupError("backup is encrypted: pass --password")
        master_key, iv = decrypt_master_key(header, password)
        data = aes.cbc_decrypt(master_key, iv, data)
    if header.compressed:
        try:
            # CipherInputStream feeds a zlib stream; a bad key pads garbage.
            data = zlib.decompressobj().decompress(data)
        except zlib.error as exc:
            raise BackupError(f"cannot inflate payload: {exc}") from exc
    if not data:
        raise BackupError(
            "empty payload: the app refused the backup "
            "(android:allowBackup=false) or the confirmation was not accepted"
        )
    return data


def list_apps(path, password: str | None = None) -> list:
    """Return the package names present in the backup."""
    header = parse_header(path)
    data = _payload(path, header, password)
    apps = []
    for member in tarfile.open(fileobj=io.BytesIO(data), mode="r:").getmembers():
        parts = member.name.strip("./").split("/")
        if len(parts) >= 2 and parts[0] == "apps" and parts[1] not in apps:
            apps.append(parts[1])
    return apps


def extract(path, out_dir, password: str | None = None, only: str | None = None) -> ExtractResult:
    """Extract the tar payload under ``out_dir``.

    ``only`` keeps a single package (``com.google.android.apps.familylink``).
    Members are sanitised: absolute paths and ``..`` are rejected.
    """
    header = parse_header(path)
    data = _payload(path, header, password)
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    result = ExtractResult(header=header, tar_bytes=len(data))
    seen_apps = []
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        for member in archive.getmembers():
            name = member.name.replace("\\", "/").lstrip("/")
            parts = [part for part in name.split("/") if part not in ("", ".")]
            if ".." in parts or not parts:
                result.notes.append(f"skipped unsafe member {member.name!r}")
                continue
            if only and not (len(parts) >= 2 and parts[0] == "apps" and parts[1] == only):
                continue
            if len(parts) >= 2 and parts[0] == "apps" and parts[1] not in seen_apps:
                seen_apps.append(parts[1])
            target = destination.joinpath(*parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                result.notes.append(f"skipped non-regular member {member.name!r}")
                continue
            source = archive.extractfile(member)
            if source is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read())
            result.members.append(str(target.relative_to(destination)))
    result.apps = seen_apps
    if not result.members:
        result.notes.append("no regular file extracted")
    return result


def _unused_struct() -> type:  # keep the import honest for future binary parsing
    return struct.Struct(">I")
