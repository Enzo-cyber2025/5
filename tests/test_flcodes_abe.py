"""Android backup (adb backup) extraction and APK static scanning.

The fixtures are real containers, built byte by byte to the format that
``com.android.server.backup`` writes, so the parser is exercised the same way it
would be on a device dump — no root, no emulator.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import zipfile
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "family-link-codes"))

from flcodes import abe, aes, apk, rea, secrets as secrets_mod  # noqa: E402

SECRET = "AItest-only-abe-secret-key"
PACKAGE = "com.google.android.apps.familylink"
PREFS = f"""<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <string name="family_link_config">{{"parentAccessCode":{{"sharedSecret":"{SECRET}",
      "accessCodeTtl":600,"clockDriftTolerance":300}}}}</string>
</map>
"""


# --------------------------------------------------------------------- helpers
def build_tar(prefix: str = "apps") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        def add(name: str, data: bytes) -> None:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 0
            archive.addfile(info, io.BytesIO(data))

        add(f"{prefix}/{PACKAGE}/_manifest", b"1\n")
        add(f"{prefix}/{PACKAGE}/f/shared_prefs/prefs.xml", PREFS.encode("utf-8"))
        add(f"{prefix}/{PACKAGE}/db/familylink.db", b"SQLite format 3\x00" + b"\x00" * 64)
        add(f"{prefix}/com.other.app/f/notes.txt", b"nothing here\n")
    return buffer.getvalue()


def build_backup(path: Path, password: str | None = None, compressed: bool = True,
                 version: int = 5, empty: bool = False) -> Path:
    payload = b"" if empty else build_tar()
    if compressed and payload:
        payload = zlib.compress(payload)
    if password:
        user_salt = os.urandom(64)
        checksum_salt = os.urandom(64)
        rounds = 10000
        user_iv = os.urandom(16)
        master_key = os.urandom(32)
        master_iv = os.urandom(16)
        header = (
            b"ANDROID BACKUP\n"
            + f"{version}\n".encode()
            + b"1\n"
            + b"AES-256\n"
            + user_salt.hex().encode() + b"\n"
            + checksum_salt.hex().encode() + b"\n"
            + f"{rounds}\n".encode()
            + user_iv.hex().encode() + b"\n"
        )
        checksum = hashlib.pbkdf2_hmac("sha1", master_key, checksum_salt, rounds, 32)
        blob = (
            bytes([len(master_iv)]) + master_iv
            + bytes([len(master_key)]) + master_key
            + bytes([len(checksum)]) + checksum
        )
        user_key = hashlib.pbkdf2_hmac("sha1", password.encode(), user_salt, rounds, 32)
        header += aes.cbc_encrypt(user_key, user_iv, aes.pad(blob)).hex().encode() + b"\n"
        payload = aes.cbc_encrypt(master_key, master_iv, aes.pad(payload))
    else:
        header = (
            b"ANDROID BACKUP\n"
            + f"{version}\n".encode()
            + (b"1\n" if compressed else b"0\n")
            + b"none\n"
        )
    path.write_bytes(header + payload)
    return path


def build_apk(path: Path) -> Path:
    """A tiny APK-shaped zip with the strings a real Family Link APK carries."""
    dex = (
        b"dex\n035\x00" + b"\x00" * 8
        + b"/data/data/com.google.android.apps.familylink/shared_prefs/familylink.xml\x00"
        + b"familyLinkAppConfig\x00sharedSecret\x00accessCodeTtl\x00"
        + b"clockDriftTolerance\x00parentAccessCode\x00"
        + b"https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1/familyLinkAppConfig\x00"
    )
    manifest = (
        b"\x03\x00\x08\x00" + b"allowBackup\x00"
        + b"com.google.android.apps.familylink\x00"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("AndroidManifest.xml", manifest)
        archive.writestr("classes.dex", dex)
        archive.writestr("lib/arm64-v8a/libfamilylink.so", b"\x7fELF" + b"\x00" * 60)
    return path


# ------------------------------------------------------------------- AES / ABE
def test_aes_matches_fips197_and_cryptography():
    vectors = [
        ("000102030405060708090a0b0c0d0e0f", "69c4e0d86a7b0430d8cdb78070b4c55a"),
        ("000102030405060708090a0b0c0d0e0f1011121314151617",
         "dda97ca4864cdfe06eaf70a0ec0d7191"),
        ("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f",
         "8ea2b7ca516745bfeafc49904b496089"),
    ]
    plain = bytes.fromhex("00112233445566778899aabbccddeeff")
    for key_hex, cipher_hex in vectors:
        round_keys = aes.expand_key(bytes.fromhex(key_hex))
        assert aes.decrypt_block(bytes.fromhex(cipher_hex), round_keys) == plain

    cryptography = pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    for size in (16, 24, 32):
        key, iv, data = os.urandom(size), os.urandom(16), os.urandom(64)
        reference = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        expected = reference.update(data) + reference.finalize()
        assert aes.cbc_encrypt(key, iv, data) == expected
        assert aes.cbc_decrypt(key, iv, expected) == data
    assert aes.unpad(aes.pad(b"abc")) == b"abc"
    with pytest.raises(ValueError):
        aes.unpad(b"abcdefghijklmnop")


def test_unencrypted_backup_is_parsed_and_extracted(tmp_path):
    container = build_backup(tmp_path / "plain.ab")
    assert abe.is_android_backup(container)
    header = abe.parse_header(container)
    assert (header.version, header.compressed, header.encrypted) == (5, True, False)

    assert abe.list_apps(container) == [PACKAGE, "com.other.app"]
    result = abe.extract(container, tmp_path / "out")
    assert len(result.members) == 4
    prefs = tmp_path / "out" / "apps" / PACKAGE / "f" / "shared_prefs" / "prefs.xml"
    assert SECRET in prefs.read_text()
    assert (tmp_path / "out" / "apps" / "com.other.app" / "f" / "notes.txt").exists()

    only = abe.extract(container, tmp_path / "one", only=PACKAGE)
    assert only.apps == [PACKAGE]
    assert all(PACKAGE in member for member in only.members)


def test_scans_the_secret_out_of_the_backup(tmp_path):
    container = build_backup(tmp_path / "plain.ab")
    abe.extract(container, tmp_path / "out")
    harvest = rea.harvest_files([tmp_path / "out"])
    assert [candidate.secret for candidate in harvest.candidates] == [SECRET]
    assert harvest.best.kind == "android"
    assert harvest.best.extra["validity"] == 600
    assert harvest.best.extra["drift"] == 300


def test_encrypted_backup_needs_the_right_password(tmp_path):
    container = build_backup(tmp_path / "secret.ab", password="hunter2")
    header = abe.parse_header(container)
    assert header.encrypted and header.rounds == 10000

    result = abe.extract(container, tmp_path / "out", password="hunter2")
    assert len(result.members) == 4
    assert SECRET in (tmp_path / "out" / "apps" / PACKAGE / "f" / "shared_prefs" / "prefs.xml").read_text()

    with pytest.raises(abe.BackupError):
        abe.extract(container, tmp_path / "bad", password="wrong")
    with pytest.raises(abe.BackupError):
        abe.extract(container, tmp_path / "nopass")


def test_empty_and_truncated_containers_are_reported(tmp_path):
    empty = build_backup(tmp_path / "empty.ab", empty=True)
    with pytest.raises(abe.BackupError) as excinfo:
        abe.extract(empty, tmp_path / "out")
    assert "allowBackup" in str(excinfo.value)

    broken = tmp_path / "broken.ab"
    broken.write_bytes(b"ANDROID BACKUP\n5\n1\nnone\n")
    with pytest.raises(abe.BackupError):
        abe.extract(broken, tmp_path / "out2")

    not_backup = tmp_path / "x.ab"
    not_backup.write_bytes(b"nope")
    assert not abe.is_android_backup(not_backup)
    with pytest.raises(abe.BackupError):
        abe.parse_header(not_backup)


def test_extraction_refuses_path_traversal(tmp_path):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        info = tarfile.TarInfo("apps/" + PACKAGE + "/../../../../tmp/evil.txt")
        info.size = 4
        archive.addfile(info, io.BytesIO(b"evil"))
        info = tarfile.TarInfo("apps/" + PACKAGE + "/f/ok.txt")
        info.size = 2
        archive.addfile(info, io.BytesIO(b"ok"))
    container = tmp_path / "evil.ab"
    container.write_bytes(b"ANDROID BACKUP\n1\n0\nnone\n" + buffer.getvalue())

    result = abe.extract(container, tmp_path / "out")
    assert any("unsafe" in note for note in result.notes)
    assert not (tmp_path / "tmp" / "evil.txt").exists()
    assert (tmp_path / "out" / "apps" / PACKAGE / "f" / "ok.txt").exists()


# ------------------------------------------------------------------------ APK
def test_apk_scan_finds_locations_and_endpoints(tmp_path):
    bundle = build_apk(tmp_path / "app.apk")
    report = apk.scan_apk(bundle)
    assert "AndroidManifest.xml" in report.scanned
    assert report.findings["config-key"]
    assert any("sharedSecret" in value for value in report.findings["config-key"])
    assert any("/data/data/com.google.android.apps.familylink" in value
               for value in report.findings["private-dir"])
    assert any(value.startswith("shared_prefs/") for value in report.findings["prefs"])
    assert report.package_guess == PACKAGE
    assert report.endpoints and report.endpoints[0]["kind"] == "app-config"
    assert "lib/arm64-v8a/libfamilylink.so" in report.native_libs
    assert report.allow_backup is not None


def test_apk_scan_rejects_non_zip(tmp_path):
    fake = tmp_path / "fake.apk"
    fake.write_bytes(b"not a zip")
    with pytest.raises(ValueError):
        apk.scan_apk(fake)


# ------------------------------------------------------------------------ CLI
def run_cli(*argv, home: Path, extra_env=None):
    env = dict(os.environ)
    env.update({"FLCODES_HOME": str(home), "FLCODES_PASSPHRASE": "test-pass"})
    env.pop("PYTHONPATH", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "flcodes", *argv],
        cwd=str(Path(__file__).resolve().parent.parent / "family-link-codes"),
        capture_output=True, text=True, env=env, timeout=120,
    )


def test_cli_abe_info_extract_and_scan(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    container = build_backup(tmp_path / "plain.ab")

    info = run_cli("abe", "info", str(container), home=home)
    assert info.returncode == 0, info.stderr
    assert "encryption=none" in info.stdout
    assert PACKAGE in info.stdout

    out = tmp_path / "extracted"
    extracted = run_cli("abe", "extract", str(container), "--out", str(out), home=home)
    assert extracted.returncode == 0, extracted.stderr
    assert "extracted 4 file(s)" in extracted.stdout

    scanned = run_cli("abe", "scan", str(container), "--save", "--label", "parent", home=home)
    assert scanned.returncode == 0, scanned.stdout + scanned.stderr
    assert "AIte" in scanned.stdout and "ttl=600s" in scanned.stdout
    keys = run_cli("keys", "list", home=home)
    assert "600s" in keys.stdout

    moment = 1_792_684_800
    generated = run_cli("gen", "--label", "parent", "--time", str(moment), "--json", home=home)
    record = json.loads(generated.stdout)
    assert record["validity"] == 600
    assert record["code"].isdigit() and len(record["code"]) == 6


def test_cli_abe_scan_encrypted_and_wrong_password(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    container = build_backup(tmp_path / "enc.ab", password="segredo")

    ok = run_cli("abe", "scan", str(container), "--password", "segredo", home=home)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "AIte" in ok.stdout

    bad = run_cli("abe", "scan", str(container), "--password", "errada", home=home)
    assert bad.returncode == 1
    assert any(word in bad.stderr for word in ("checksum", "password", "malformed"))


def test_cli_apk_scan_json(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    bundle = build_apk(tmp_path / "app.apk")
    result = run_cli("apk", "scan", str(bundle), "--json", home=home)
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    assert document["package_guess"] == PACKAGE
    assert document["findings"]["config-key"]
    human = run_cli("apk", "scan", str(bundle), home=home)
    assert "next:" in human.stdout
    assert "flcodes abe scan" in human.stdout
