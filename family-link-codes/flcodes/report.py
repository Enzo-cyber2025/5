"""Saving generated codes and writing (secret-free) experiment reports."""

from __future__ import annotations

import csv
import datetime as _dt
import json
import os
from pathlib import Path

from .codes import FamilyLinkCode

__all__ = [
    "iso",
    "default_output_dir",
    "code_record",
    "save_codes",
    "harvest_report",
    "write_json",
    "secure_delete",
]


def iso(timestamp: float) -> str:
    """ISO-8601 UTC representation of an epoch value."""
    return _dt.datetime.fromtimestamp(timestamp, _dt.timezone.utc).isoformat()


def default_output_dir(base: str | os.PathLike | None = None) -> Path:
    """Return the output directory (``$FLCODES_HOME/output`` by default)."""
    if base:
        return Path(base).expanduser()
    override = os.environ.get("FLCODES_HOME")
    root = Path(override).expanduser() if override else Path.cwd() / "flcodes-out"
    return root / "output"


def code_record(
    code: FamilyLinkCode,
    label: str = "",
    seed_id: str = "",
    generated_at: float | None = None,
) -> dict:
    """Turn a generated code into a serialisable record."""
    now = generated_at if generated_at is not None else _dt.datetime.now(_dt.timezone.utc).timestamp()
    return {
        "label": label,
        "seed_id": seed_id,
        "code": code.code,
        "valid_from": code.valid_from,
        "valid_to": code.valid_to,
        "valid_from_utc": iso(code.valid_from),
        "valid_to_utc": iso(code.valid_to),
        "counter": code.counter,
        "generated_at_utc": iso(now),
    }


def save_codes(records, path: str | os.PathLike, fmt: str = "auto", append: bool = True) -> Path:
    """Write code records as CSV or JSON lines.

    ``fmt='auto'`` picks CSV for ``.csv`` and JSON lines for ``.jsonl``/``.json``.
    """
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "auto":
        fmt = "csv" if target.suffix.lower() == ".csv" else "jsonl"
    rows = list(records)
    if fmt == "csv":
        fields = [
            "label",
            "seed_id",
            "code",
            "valid_from_utc",
            "valid_to_utc",
            "valid_from",
            "valid_to",
            "counter",
            "generated_at_utc",
        ]
        exists = target.exists() and target.stat().st_size > 0
        with target.open("a" if append and exists else "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            if not (append and exists):
                writer.writeheader()
            for row in rows:
                writer.writerow(row)
        os.chmod(target, 0o600)
        return target
    if fmt in ("jsonl", "json"):
        mode = "a" if append and target.exists() and target.stat().st_size > 0 else "w"
        with target.open(mode, encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.chmod(target, 0o600)
        return target
    raise ValueError(f"unknown format: {fmt}")


def write_json(document: dict, path: str | os.PathLike) -> Path:
    """Write a JSON document with private file permissions."""
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
    os.chmod(target, 0o600)
    return target


def harvest_report(
    harvest,
    store_summary: dict | None = None,
    generated=None,
    extra: dict | None = None,
) -> dict:
    """Build the experiment report. Secrets are never included."""
    now = _dt.datetime.now(_dt.timezone.utc)
    return {
        "tool": "flcodes",
        "created_at_utc": now.isoformat(),
        "candidates": [candidate.as_dict(reveal=False) for candidate in harvest.candidates],
        "notes": list(harvest.notes),
        "responses": list(harvest.responses),
        "store": store_summary or {},
        "generated": list(generated or []),
        "extra": extra or {},
    }


def secure_delete(path: str | os.PathLike, passes: int = 1) -> bool:
    """Overwrite a file with random bytes and unlink it.

    Returns True when a file was removed. Overwriting is best effort: on
    copy-on-write or log structured filesystems the old blocks may survive,
    so the report says so instead of claiming a guaranteed wipe.
    """
    target = Path(path).expanduser()
    if not target.exists():
        return False
    size = target.stat().st_size
    with target.open("r+b", buffering=0) as handle:
        for _ in range(max(1, passes)):
            handle.seek(0)
            handle.write(os.urandom(max(1, size)))
            handle.flush()
            os.fsync(handle.fileno())
    target.unlink()
    return True
