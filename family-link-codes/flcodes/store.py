"""Encrypted local storage for the shared secrets.

The store is a single JSON file encrypted with ChaCha20-Poly1305 (RFC 8439);
the key comes from scrypt over a passphrase. The passphrase is read from
``FLCODES_PASSPHRASE`` or asked interactively, and never written to disk.

Layout of the encrypted file::

    {"format": "flcodes-store", "version": 1,
     "kdf": {"algo": "scrypt", "n": 16384, "r": 8, "p": 1, "salt": "<b64>"},
     "aead": "chacha20-poly1305", "nonce": "<b64>", "ciphertext": "<b64>"}
"""

from __future__ import annotations

import base64
import getpass
import json
import os
import secrets as _secrets
import sys
import time
from pathlib import Path

from . import crypto

__all__ = ["Store", "StoreError", "default_store_path", "resolve_passphrase"]

FORMAT = "flcodes-store"
VERSION = 1
KDF_N = 16384
KDF_R = 8
KDF_P = 1


class StoreError(Exception):
    """Raised when the store cannot be read, written or decrypted."""


def default_store_path() -> Path:
    """Return the path of the store file (``$FLCODES_HOME`` wins)."""
    override = os.environ.get("FLCODES_HOME")
    if override:
        return Path(override).expanduser() / "store.json"
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base).expanduser() / "flcodes" / "store.json"


def resolve_passphrase(passphrase: str | None = None, confirm: bool = False) -> str:
    """Return the passphrase, asking the user only when needed."""
    if passphrase:
        return passphrase
    env = os.environ.get("FLCODES_PASSPHRASE")
    if env:
        return env
    if not sys.stdin.isatty():
        raise StoreError(
            "no passphrase: pass --passphrase, set FLCODES_PASSPHRASE "
            "or run in an interactive terminal"
        )
    value = getpass.getpass("flcodes passphrase: ")
    if not value:
        raise StoreError("empty passphrase")
    if confirm:
        again = getpass.getpass("flcodes passphrase (again): ")
        if value != again:
            raise StoreError("passphrases do not match")
    return value


class Store:
    """Encrypted key/value store for Family Link shared secrets."""

    def __init__(self, path: str | os.PathLike | None = None, passphrase: str | None = None):
        self.path = Path(path).expanduser() if path else default_store_path()
        self._passphrase = passphrase
        self._payload: dict | None = None

    # ---------------------------------------------------------------- helpers
    @property
    def passphrase(self) -> str:
        if self._passphrase is None:
            self._passphrase = resolve_passphrase()
        return self._passphrase

    def _empty_payload(self) -> dict:
        return {"seeds": [], "active_id": None, "updated_at": int(time.time())}

    def _read_container(self) -> dict | None:
        if not self.path.exists():
            return None
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise StoreError(f"cannot read {self.path}: {exc}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise StoreError(f"corrupt store file {self.path}: {exc}") from exc

    def _write_container(self, container: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(container, indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    # ------------------------------------------------------------------- api
    def load(self) -> dict:
        """Decrypt and return the payload (empty payload when no file yet)."""
        if self._payload is not None:
            return self._payload
        container = self._read_container()
        if container is None:
            self._payload = self._empty_payload()
            return self._payload
        if container.get("format") != FORMAT:
            raise StoreError(f"unexpected store format: {container.get('format')!r}")
        kdf = container.get("kdf", {})
        salt = base64.b64decode(kdf.get("salt", ""))
        key = crypto.derive_key(
            self.passphrase,
            salt,
            n=int(kdf.get("n", KDF_N)),
            r=int(kdf.get("r", KDF_R)),
            p=int(kdf.get("p", KDF_P)),
            dklen=32,
        )
        nonce = base64.b64decode(container.get("nonce", ""))
        ciphertext = base64.b64decode(container.get("ciphertext", ""))
        try:
            plaintext = crypto.aead_decrypt(
                key, nonce, ciphertext, aad=FORMAT.encode("utf-8")
            )
        except ValueError as exc:
            raise StoreError(f"cannot decrypt store: {exc}") from exc
        try:
            self._payload = json.loads(plaintext.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StoreError(f"corrupt store payload: {exc}") from exc
        return self._payload

    def save(self) -> None:
        """Encrypt and write the payload to disk."""
        payload = self.load()
        payload["updated_at"] = int(time.time())
        salt = crypto.random_bytes(16)
        nonce = crypto.random_bytes(12)
        key = crypto.derive_key(
            self.passphrase, salt, n=KDF_N, r=KDF_R, p=KDF_P, dklen=32
        )
        ciphertext = crypto.aead_encrypt(
            key, nonce, json.dumps(payload).encode("utf-8"), aad=FORMAT.encode("utf-8")
        )
        container = {
            "format": FORMAT,
            "version": VERSION,
            "kdf": {
                "algo": "scrypt",
                "n": KDF_N,
                "r": KDF_R,
                "p": KDF_P,
                "salt": base64.b64encode(salt).decode("ascii"),
            },
            "aead": "chacha20-poly1305",
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }
        self._write_container(container)

    # --------------------------------------------------------------- secrets
    def list_seeds(self) -> list:
        """Return the stored seeds without revealing the secret."""
        payload = self.load()
        from .secrets import mask_secret

        result = []
        for seed in payload.get("seeds", []):
            entry = dict(seed)
            entry["masked"] = mask_secret(entry.get("secret", ""))
            entry.pop("secret", None)
            result.append(entry)
        return result

    def get_seed(self, seed_id: str) -> dict | None:
        """Return a stored seed including its secret."""
        for seed in self.load().get("seeds", []):
            if seed.get("id") == seed_id:
                return dict(seed)
        return None

    def active_seed(self) -> dict | None:
        """Return the seed flagged as active (the first one otherwise)."""
        payload = self.load()
        seeds = payload.get("seeds", [])
        if not seeds:
            return None
        active_id = payload.get("active_id")
        for seed in seeds:
            if seed.get("id") == active_id:
                return dict(seed)
        return dict(seeds[0])

    def add_seed(
        self,
        secret: str,
        label: str = "",
        kind: str = "unknown",
        source: str = "",
        notes: str = "",
        seed_id: str | None = None,
    ) -> dict:
        """Store a secret and return the created record."""
        payload = self.load()
        secret = (secret or "").strip()
        if not secret:
            raise StoreError("empty secret")
        for existing in payload.get("seeds", []):
            if existing.get("secret") == secret:
                return dict(existing)
        record = {
            "id": seed_id or _secrets.token_hex(6),
            "label": label or kind or "seed",
            "secret": secret,
            "kind": kind,
            "source": source,
            "notes": notes,
            "created_at": int(time.time()),
        }
        payload.setdefault("seeds", []).append(record)
        if not payload.get("active_id"):
            payload["active_id"] = record["id"]
        self.save()
        return dict(record)

    def remove_seed(self, seed_id: str) -> bool:
        """Delete a stored seed; returns True when something was removed."""
        payload = self.load()
        seeds = payload.get("seeds", [])
        remaining = [seed for seed in seeds if seed.get("id") != seed_id]
        if len(remaining) == len(seeds):
            return False
        payload["seeds"] = remaining
        if payload.get("active_id") == seed_id:
            payload["active_id"] = remaining[0]["id"] if remaining else None
        self.save()
        return True

    def set_active(self, seed_id: str) -> None:
        """Flag a seed as the active one."""
        payload = self.load()
        if not any(seed.get("id") == seed_id for seed in payload.get("seeds", [])):
            raise StoreError(f"unknown seed id: {seed_id}")
        payload["active_id"] = seed_id
        self.save()

    def export(self, reveal: bool = False) -> dict:
        """Export the store contents.

        Without ``reveal`` the ``secret`` field is dropped entirely (only the
        masked form is exported) so a masked export can never be imported back
        as if it were a usable key.
        """
        from .secrets import mask_secret

        payload = self.load()
        seeds = []
        for seed in payload.get("seeds", []):
            entry = dict(seed)
            if reveal:
                entry["secret"] = seed.get("secret", "")
            else:
                entry.pop("secret", None)
                entry["masked"] = mask_secret(seed.get("secret", ""))
            seeds.append(entry)
        return {"version": VERSION, "active_id": payload.get("active_id"), "seeds": seeds}

    def import_seeds(self, document: dict, overwrite: bool = False) -> list:
        """Import seeds exported by :meth:`export`."""
        imported = []
        for entry in document.get("seeds", []):
            secret = entry.get("secret", "")
            if not secret:
                continue
            imported.append(
                self.add_seed(
                    secret=secret,
                    label=entry.get("label", ""),
                    kind=entry.get("kind", "unknown"),
                    source=entry.get("source", "import"),
                    notes=entry.get("notes", ""),
                    seed_id=entry.get("id") if overwrite else None,
                )
            )
        return imported
