"""The store encryption must match RFC 8439 and be cross-checked.

A hand written ChaCha20-Poly1305 is a real risk, so it is pinned against the
RFC vectors *and* against the reference `cryptography` implementation when that
package is installed. The store format itself is tested for passphrase binding,
tampering, permissions and duplicate handling.
"""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "family-link-codes"))

from flcodes import crypto  # noqa: E402
from flcodes.store import Store, StoreError  # noqa: E402

RFC_KEY = bytes.fromhex("808182838485868788898a8b8c8d8e8f909192939495969798999a9b9c9d9e9f")
RFC_NONCE = bytes.fromhex("070000004041424344454647")
RFC_AAD = bytes.fromhex("50515253c0c1c2c3c4c5c6c7")
RFC_PLAINTEXT = (
    b"Ladies and Gentlemen of the class of '99: If I could offer you only "
    b"one tip for the future, sunscreen would be it."
)


def test_chacha20_block_matches_rfc8439_2_3_2():
    key = bytes(range(32))
    nonce = bytes.fromhex("000000090000004a00000000")
    block = crypto.chacha20_block(key, 1, nonce)
    assert block[:16].hex() == "10f1e7e4d13b5915500fdd1fa32071c4"
    assert block[16:32].hex() == "c7d1f4c733c068030422aa9ac3d46c4e"


def test_poly1305_matches_rfc8439_2_5_2():
    key = bytes.fromhex(
        "85d6be7857556d337f4452fe42d506a80103808afb0db2fd4abff6af4149f51b"
    )
    message = b"Cryptographic Forum Research Group"
    tag = crypto.poly1305_mac(message, key)
    assert tag.hex() == "a8061dc1305136c6c22b8baf0c0127a9"


def test_aead_matches_rfc8439_2_8_2():
    sealed = crypto.aead_encrypt(RFC_KEY, RFC_NONCE, RFC_PLAINTEXT, RFC_AAD)
    assert sealed[:16].hex() == "d31a8d34648e60db7b86afbc53ef7ec2"
    assert sealed[-16:].hex() == "1ae10b594f09e26a7e902ecbd0600691"
    assert crypto.aead_decrypt(RFC_KEY, RFC_NONCE, sealed, RFC_AAD) == RFC_PLAINTEXT


def test_aead_cross_checks_the_reference_library():
    reference = pytest.importorskip("cryptography.hazmat.primitives.ciphers.aead")
    aead = reference.ChaCha20Poly1305
    for size in (0, 1, 15, 16, 17, 63, 64, 65, 1000):
        key, nonce = os.urandom(32), os.urandom(12)
        plaintext, aad = os.urandom(size), os.urandom(9)
        ours = crypto.aead_encrypt(key, nonce, plaintext, aad)
        assert ours == aead(key).encrypt(nonce, plaintext, aad)
        assert crypto.aead_decrypt(key, nonce, ours, aad) == plaintext


def test_tampering_and_wrong_parameters_are_rejected():
    key, nonce = os.urandom(32), os.urandom(12)
    sealed = bytearray(crypto.aead_encrypt(key, nonce, b"segredo", b"ad"))
    sealed[0] ^= 0x01
    with pytest.raises(ValueError):
        crypto.aead_decrypt(key, nonce, bytes(sealed), b"ad")
    sealed[0] ^= 0x01
    sealed[-1] ^= 0x01
    with pytest.raises(ValueError):
        crypto.aead_decrypt(key, nonce, bytes(sealed), b"ad")
    with pytest.raises(ValueError):
        crypto.aead_decrypt(key, nonce, crypto.aead_encrypt(key, nonce, b"x", b"ad"), b"other")
    with pytest.raises(ValueError):
        crypto.aead_decrypt(key, nonce, b"short")
    with pytest.raises(ValueError):
        crypto.chacha20_block(b"short", 0, nonce)
    with pytest.raises(ValueError):
        crypto.aead_encrypt(key, b"short", b"x")


def test_kdf_binds_the_salt_and_passphrase():
    salt_a, salt_b = b"a" * 16, b"b" * 16
    key = crypto.derive_key("pass", salt_a, n=1024, dklen=32)
    assert key == crypto.derive_key("pass", salt_a, n=1024, dklen=32)
    assert key != crypto.derive_key("pass", salt_b, n=1024, dklen=32)
    assert key != crypto.derive_key("other", salt_a, n=1024, dklen=32)
    assert len(key) == 32 and len(crypto.derive_key("pass", salt_a, n=1024)) == 64


def _store(tmp_path: Path, passphrase: str = "test-passphrase") -> Store:
    return Store(path=tmp_path / "store.json", passphrase=passphrase)


def test_store_roundtrip_hides_the_secret_on_disk(tmp_path):
    store = _store(tmp_path)
    secret = "AItest-only-shared-secret.abcdefghij"
    record = store.add_seed(secret, label="pai", kind="android")
    raw = store.path.read_text()
    assert secret not in raw
    assert "flcodes-store" in raw
    assert json.loads(raw)["aead"] == "chacha20-poly1305"

    reopened = _store(tmp_path)
    assert reopened.get_seed(record["id"])["secret"] == secret
    assert reopened.active_seed()["label"] == "pai"
    listed = reopened.list_seeds()
    assert "secret" not in listed[0]
    assert listed[0]["masked"].startswith("AIt")


def test_store_reloads_when_the_file_changes_on_disk(tmp_path):
    # a long running server must see keys added by another process
    reader = Store(path=tmp_path / "store.json", passphrase="pass")
    assert reader.list_seeds() == []

    writer = Store(path=tmp_path / "store.json", passphrase="pass")
    record = writer.add_seed("AItest-only-hot-reload.1", label="cli")

    assert [seed["id"] for seed in reader.list_seeds()] == [record["id"]]
    assert reader.load()["seeds"][0]["label"] == "cli"


def test_store_requires_the_right_passphrase(tmp_path):
    store = _store(tmp_path, "correct horse")
    store.add_seed("AItest-only-secret.1", label="x")
    with pytest.raises(StoreError):
        _store(tmp_path, "wrong passphrase").load()
    with pytest.raises(StoreError):
        _store(tmp_path, "").load()


def test_store_file_permissions_are_private(tmp_path):
    store = _store(tmp_path)
    store.add_seed("AItest-only-secret.2", label="x")
    mode = stat.S_IMODE(store.path.stat().st_mode)
    assert mode == 0o600


def test_store_deduplicates_and_manages_the_active_key(tmp_path):
    store = _store(tmp_path)
    first = store.add_seed("AItest-only-secret.3", label="um")
    again = store.add_seed("AItest-only-secret.3", label="outro")
    assert again["id"] == first["id"]
    assert len(store.list_seeds()) == 1

    second = store.add_seed("AItest-only-secret.4", label="dois")
    store.set_active(second["id"])
    assert store.active_seed()["id"] == second["id"]

    assert store.remove_seed(first["id"]) is True
    assert store.remove_seed(first["id"]) is False
    assert store.active_seed()["id"] == second["id"]
    assert store.remove_seed(second["id"]) is True
    assert store.active_seed() is None


def test_store_rejects_corrupt_and_unknown_containers(tmp_path):
    path = tmp_path / "store.json"
    path.write_text("not json")
    with pytest.raises(StoreError):
        Store(path=path, passphrase="x").load()
    path.write_text(json.dumps({"format": "other"}))
    with pytest.raises(StoreError):
        Store(path=path, passphrase="x").load()
    with pytest.raises(StoreError):
        Store(path=tmp_path / "missing.json", passphrase="x").add_seed("")


def test_store_export_import_roundtrip(tmp_path):
    source = _store(tmp_path / "source")
    source.path.parent.mkdir(parents=True, exist_ok=True)
    source.add_seed("AItest-only-secret.5", label="a", kind="android")
    masked = source.export(reveal=False)
    assert "AItest-only-secret.5" not in json.dumps(masked)
    full = source.export(reveal=True)

    target = _store(tmp_path / "target")
    target.path.parent.mkdir(parents=True, exist_ok=True)
    imported = target.import_seeds(full)
    assert len(imported) == 1
    assert target.get_seed(imported[0]["id"])["secret"] == "AItest-only-secret.5"

    # masked exports carry no secret and import nothing
    assert all("secret" not in entry for entry in masked["seeds"])
    empty = _store(tmp_path / "empty")
    empty.path.parent.mkdir(parents=True, exist_ok=True)
    assert empty.import_seeds(masked) == []
    assert empty.list_seeds() == []
